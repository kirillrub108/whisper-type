"""Вставка текста в активное окно: буфер обмена + Ctrl+V через SendInput,
fallback — посимвольный ввод KEYEVENTF_UNICODE, детект UIPI."""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Iterable, Iterator, Sequence
from ctypes import wintypes
from typing import NamedTuple, TypeVar

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

T = TypeVar("T")

# ---------------------------------------------------------------- чистые хелперы


def utf16_units(text: str) -> list[int]:
    """UTF-16 code units; символы вне BMP дают суррогатную пару (2 unit'а)."""
    units: list[int] = []
    for ch in text:
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            units.append(int.from_bytes(data[i : i + 2], "little"))
    return units


def batched(seq: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    step = max(1, size)
    for i in range(0, len(seq), step):
        yield seq[i : i + step]


# ---------------------------------------------------------------- SendInput (x64)

ULONG_PTR = ctypes.c_size_t

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_CONTROL = 0x11
VK_V = 0x56
VK_RETURN = 0x0D

_MODIFIER_VKS: tuple[int, ...] = (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


# На x64 INPUT обязан быть 40 байт (4 type + 4 паддинг + 32 union), иначе SendInput молча ломается.
assert ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(INPUT) == 40

_user32.SendInput.restype = wintypes.UINT
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send_inputs(inputs: Sequence[INPUT]) -> bool:
    array = (INPUT * len(inputs))(*inputs)
    sent = _user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        log.error("SendInput отправил %d/%d, GetLastError=%d",
                  sent, len(inputs), ctypes.get_last_error())
        return False
    return True


def wait_keys_released(extra_vks: Iterable[int] = (), timeout: float = 1.0) -> bool:
    """Ждёт физического отпускания модификаторов и клавиш хоткея.

    Без этого Ctrl+V уйдёт в окно как Ctrl+<модификатор>+V и вставки не будет.
    """
    vks = set(_MODIFIER_VKS) | set(extra_vks)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
            return True
        time.sleep(0.01)
    log.warning("модификаторы всё ещё зажаты спустя %.1f с — вставка может не сработать", timeout)
    return False


def send_ctrl_v() -> bool:
    return _send_inputs(
        [
            _key_input(vk=VK_CONTROL),
            _key_input(vk=VK_V),
            _key_input(vk=VK_V, flags=KEYEVENTF_KEYUP),
            _key_input(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
        ]
    )


def type_text(text: str, batch_size: int, batch_delay_ms: int) -> bool:
    """Посимвольный ввод через KEYEVENTF_UNICODE (для полей, не принимающих paste)."""
    inputs: list[INPUT] = []
    for unit in utf16_units(text.replace("\r\n", "\n")):
        if unit == 0x0A:
            # Unicode-перевод строки многие поля игнорируют — шлём настоящий Enter.
            inputs.append(_key_input(vk=VK_RETURN))
            inputs.append(_key_input(vk=VK_RETURN, flags=KEYEVENTF_KEYUP))
        else:
            inputs.append(_key_input(scan=unit, flags=KEYEVENTF_UNICODE))
            inputs.append(_key_input(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    for chunk in batched(inputs, batch_size * 2):  # *2: down+up на каждый unit
        if not _send_inputs(chunk):
            return False
        time.sleep(batch_delay_ms / 1000.0)
    return True


# ---------------------------------------------------------------- буфер обмена

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_user32.OpenClipboard.restype = wintypes.BOOL
_user32.OpenClipboard.argtypes = (wintypes.HWND,)
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
_user32.IsClipboardFormatAvailable.argtypes = (wintypes.UINT,)
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.GetClipboardData.argtypes = (wintypes.UINT,)
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
_user32.CountClipboardFormats.restype = ctypes.c_int
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
_kernel32.GlobalLock.restype = wintypes.LPVOID
_kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
_kernel32.GlobalFree.restype = wintypes.HGLOBAL
_kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)


class ClipboardSnapshot(NamedTuple):
    text: str | None
    restorable: bool  # False — в буфере было нетекстовое содержимое, не трогаем


def _open_clipboard(retries: int = 10) -> bool:
    # Буфер часто занят другим процессом — ретраи с нарастающей паузой.
    for attempt in range(retries):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(0.01 * (attempt + 1))
    log.error("OpenClipboard не удался после %d попыток, GetLastError=%d",
              retries, ctypes.get_last_error())
    return False


def read_clipboard() -> ClipboardSnapshot:
    if not _open_clipboard():
        return ClipboardSnapshot(None, False)
    try:
        if _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            handle = _user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                ptr = _kernel32.GlobalLock(handle)
                if ptr:
                    try:
                        text = ctypes.wstring_at(ptr)
                    finally:
                        _kernel32.GlobalUnlock(handle)
                    return ClipboardSnapshot(text, True)
            log.warning("GetClipboardData/GlobalLock не удались, GetLastError=%d",
                        ctypes.get_last_error())
            return ClipboardSnapshot(None, False)
        if _user32.CountClipboardFormats() == 0:
            return ClipboardSnapshot(None, True)  # пустой буфер — восстановим как пустой
        return ClipboardSnapshot(None, False)
    finally:
        _user32.CloseClipboard()


def write_clipboard(text: str) -> bool:
    if not _open_clipboard():
        return False
    try:
        if not _user32.EmptyClipboard():
            log.error("EmptyClipboard не удался, GetLastError=%d", ctypes.get_last_error())
            return False
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            log.error("GlobalAlloc не удался, GetLastError=%d", ctypes.get_last_error())
            return False
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            log.error("GlobalLock не удался, GetLastError=%d", ctypes.get_last_error())
            _kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            log.error("SetClipboardData не удался, GetLastError=%d", ctypes.get_last_error())
            _kernel32.GlobalFree(handle)
            return False
        return True  # владельцем handle стала система
    finally:
        _user32.CloseClipboard()


def clear_clipboard() -> None:
    if _open_clipboard():
        try:
            _user32.EmptyClipboard()
        finally:
            _user32.CloseClipboard()


def paste_via_clipboard(text: str, restore_delay_ms: int) -> bool:
    """Сохранить буфер → положить текст → Ctrl+V → восстановить буфер."""
    snapshot = read_clipboard()
    if not write_clipboard(text):
        return False
    ok = send_ctrl_v()
    time.sleep(restore_delay_ms / 1000.0)
    if snapshot.restorable:
        if snapshot.text is not None:
            if not write_clipboard(snapshot.text):
                log.warning("не удалось восстановить прежний текст буфера обмена")
        else:
            clear_clipboard()
    else:
        log.info("в буфере было нетекстовое содержимое — восстановление пропущено")
    return ok


# ---------------------------------------------------------------- UIPI

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25  # TokenIntegrityLevel из TOKEN_INFORMATION_CLASS

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
_advapi32.GetTokenInformation.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
_advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
_advapi32.GetSidSubAuthorityCount.argtypes = (ctypes.c_void_p,)
_advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
_advapi32.GetSidSubAuthority.argtypes = (ctypes.c_void_p, wintypes.DWORD)


def _process_integrity(process_handle: int) -> int | None:
    """RID уровня целостности процесса (0x2000 medium, 0x3000 high и т.д.)."""
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        log.debug("OpenProcessToken не удался, GetLastError=%d", ctypes.get_last_error())
        return None
    try:
        size = wintypes.DWORD(0)
        _advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL, buf, size.value, ctypes.byref(size)
        ):
            log.debug("GetTokenInformation не удался, GetLastError=%d", ctypes.get_last_error())
            return None
        # buf — TOKEN_MANDATORY_LABEL, первое поле — PSID.
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not psid:
            return None
        count = _advapi32.GetSidSubAuthorityCount(psid).contents.value
        return int(_advapi32.GetSidSubAuthority(psid, count - 1).contents.value)
    finally:
        _kernel32.CloseHandle(token)


def foreground_blocks_input() -> bool:
    """True — окно в фокусе принадлежит процессу с более высоким integrity level:
    UIPI молча отбросит наш SendInput."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return False
    own_level = _process_integrity(_kernel32.GetCurrentProcess())
    process = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        # Процесс даже не открывается на чтение — почти наверняка повышенные права.
        log.info("OpenProcess(pid=%d) не удался, GetLastError=%d — считаю окно повышенным",
                 pid.value, ctypes.get_last_error())
        return True
    try:
        target_level = _process_integrity(process)
    finally:
        _kernel32.CloseHandle(process)
    if own_level is None or target_level is None:
        return False
    return target_level > own_level
