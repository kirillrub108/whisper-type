"""Глобальный низкоуровневый клавиатурный хук (WH_KEYBOARD_LL) на выделенном потоке.

Хук обязан возвращать управление быстро: вся реакция сводится к on_event()
(в приложении это queue.put), иначе Windows отключит хук и клавиатура начнёт лагать.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

from .keys import Hotkey

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10


class KBDLLHOOKSTRUCT(ctypes.Structure):
    # x64: четыре DWORD + ULONG_PTR (8 байт)
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_user32.GetMessageW.restype = ctypes.c_int
_user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)


class HotkeyListener(threading.Thread):
    """События: "press" (комбо собрано), "release" (комбо распалось),
    "cancel" (клавиша отмены во время записи), "hook_failed"."""

    def __init__(self, hotkey: Hotkey, cancel: Hotkey, on_event: Callable[[str], None]) -> None:
        super().__init__(name="hotkey", daemon=True)
        self._hotkey = hotkey
        self._cancel = cancel
        self._on_event = on_event
        self._pressed: set[int] = set()
        self._combo_active = False
        self._enabled = True
        self._recording = False
        self._tid = 0
        self._ready = threading.Event()
        # Ссылку на callback держим в атрибуте: если её соберёт GC, хук упадёт.
        self._proc = _HOOKPROC(self._ll_proc)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._pressed.clear()
            self._combo_active = False

    def set_recording(self, recording: bool) -> None:
        self._recording = recording

    def _emit(self, event: str) -> None:
        try:
            self._on_event(event)
        except Exception:
            log.exception("хук: обработчик события %s упал", event)

    def _ll_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code != HC_ACTION or not self._enabled:
            return _user32.CallNextHookEx(None, n_code, w_param, l_param)
        kb = KBDLLHOOKSTRUCT.from_address(l_param)
        if kb.flags & LLKHF_INJECTED:  # наши же SendInput-события (Ctrl+V и т.п.)
            return _user32.CallNextHookEx(None, n_code, w_param, l_param)
        vk = int(kb.vkCode)
        down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        repeat = down and vk in self._pressed
        if down:
            self._pressed.add(vk)
        else:
            self._pressed.discard(vk)

        if self._recording and vk in self._cancel.trigger:
            if down and not repeat:
                self._emit("cancel")
            return 1  # Esc не должен дойти до приложения в фокусе

        was_active = self._combo_active
        now_active = all(
            any(v in self._pressed for v in part) for part in self._hotkey.parts
        )
        if now_active and not was_active:
            self._combo_active = True
            self._emit("press")
        elif was_active and not now_active:
            self._combo_active = False
            self._emit("release")

        # Несущую клавишу комбо глотаем, чтобы она не пришла в активное окно.
        if vk in self._hotkey.trigger and (self._combo_active or was_active):
            return 1
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def run(self) -> None:
        self._tid = _kernel32.GetCurrentThreadId()
        hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, _kernel32.GetModuleHandleW(None), 0
        )
        if not hook:
            log.error("SetWindowsHookExW провалился, GetLastError=%d", ctypes.get_last_error())
            self._ready.set()
            self._emit("hook_failed")
            return
        self._ready.set()
        log.info("клавиатурный хук установлен")
        msg = wintypes.MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:  # WM_QUIT или ошибка
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        if not _user32.UnhookWindowsHookEx(hook):
            log.error("UnhookWindowsHookEx провалился, GetLastError=%d", ctypes.get_last_error())
        else:
            log.info("клавиатурный хук снят")

    def stop(self) -> None:
        self._ready.wait(timeout=2.0)
        if self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
