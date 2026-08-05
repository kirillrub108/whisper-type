"""Экранный индикатор записи: слоёное окно в правом нижнем углу.

Окно намеренно создаётся с WS_EX_NOACTIVATE и WS_EX_TRANSPARENT: оно не
забирает фокус (иначе Ctrl+V ушёл бы в него, а не в поле пользователя)
и пропускает клики насквозь. Живёт на своём потоке с message loop.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

SPI_GETWORKAREA = 0x0030
DIB_RGB_COLORS = 0
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_APP_UPDATE = 0x8001
WM_APP_CLOSE = 0x8002

_WIDTH = 132
_HEIGHT = 38
_MARGIN = 18
_TIMER_ID = 1
_FRAME_MS = 66  # ~15 кадров/с, достаточно для плавной пульсации

_STATES: dict[str, tuple[tuple[int, int, int], str]] = {
    "recording": ((233, 74, 63), "Запись"),
    "processing": ((242, 166, 0), "Распознаю"),
}

_HINT_TEXT = "Вас не слышно"
_HINT_COLOUR = (255, 178, 76)
_HINT_GAP = 13  # отступ от «Запись» до разделителя и от разделителя до подсказки


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    )


_WNDPROC = WNDCLASSEXW._fields_[2][1]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3))


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = (
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    )


_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.RegisterClassExW.argtypes = (ctypes.POINTER(WNDCLASSEXW),)
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.UpdateLayeredWindow.restype = wintypes.BOOL
_user32.UpdateLayeredWindow.argtypes = (
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
)
_user32.SystemParametersInfoW.argtypes = (
    wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT
)
_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_user32.SetWindowPos.argtypes = (
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
)
_user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID)
_user32.KillTimer.argtypes = (wintypes.HWND, ctypes.c_size_t)
_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.DestroyWindow.argtypes = (wintypes.HWND,)
_user32.PostQuitMessage.argtypes = (ctypes.c_int,)
_user32.GetMessageW.restype = ctypes.c_int
_user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
)
_user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
# Без явных argtypes ctypes считает аргументы 32-битными и рвёт хендлы на x64.
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
_gdi32.DeleteDC.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = (wintypes.HDC,)
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = (
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
)
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("segoeui.ttf", "arial.ttf", "tahoma.ttf"):
        try:
            return ImageFont.truetype(str(fonts_dir / name), size)
        except OSError:
            continue
    # Встроенный шрифт Pillow — растровый и без кириллицы, но лучше, чем падение.
    return ImageFont.load_default()


def _work_area() -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        log.warning("SystemParametersInfoW провалился, GetLastError=%d", ctypes.get_last_error())
        return 0, 0, 1920, 1080
    return rect.left, rect.top, rect.right, rect.bottom


def _render(
    state: str,
    phase: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    unheard: bool = False,
) -> Image.Image:
    colour, label = _STATES[state]
    # Подсказка прирастает слева: плашка прижата к правому краю экрана, и сам
    # индикатор записи должен остаться на месте, а не прыгать вбок.
    offset = 0
    if unheard:
        offset = 16 + int(font.getlength(_HINT_TEXT)) + _HINT_GAP * 2 + 1
    width = offset + _WIDTH
    img = Image.new("RGBA", (width, _HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, width - 1, _HEIGHT - 1), radius=_HEIGHT // 2, fill=(28, 28, 32, 232))
    if unheard:
        draw.text((16, _HEIGHT // 2), _HINT_TEXT, font=font,
                  fill=(*_HINT_COLOUR, 255), anchor="lm")
        # Разделитель: подсказка — отдельное сообщение, а не продолжение подписи.
        line_x = offset - _HINT_GAP
        draw.line((line_x, 11, line_x, _HEIGHT - 12), fill=(255, 255, 255, 46))
    cx, cy = offset + 21, _HEIGHT // 2
    if state == "recording":
        # Пульсация показывает, что запись именно идёт, а не «залипла».
        glow = 3.0 + 2.6 * (0.5 + 0.5 * math.sin(phase))
        draw.ellipse((cx - glow - 4, cy - glow - 4, cx + glow + 4, cy + glow + 4),
                     fill=(*colour, 70))
        radius = glow
    else:
        radius = 5.0
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*colour, 255))
    draw.text((offset + 38, _HEIGHT // 2), label, font=font, fill=(238, 238, 242, 255), anchor="lm")
    return img


class Overlay(threading.Thread):
    """Показывает индикатор поверх всех окон. show()/hide() — из любого потока."""

    def __init__(self, unheard_probe: Callable[[], bool] | None = None) -> None:
        super().__init__(name="overlay", daemon=True)
        self._hwnd: int = 0
        self._state: str | None = None
        self._phase = 0.0
        self._ready = threading.Event()
        self._font = _load_font(14)
        # Спрашиваем на каждом кадре, а не ждём push извне: своего таймера на
        # 15 кадров/с хватает, чтобы подсказка появилась вовремя без ещё одного потока.
        self._unheard_probe = unheard_probe
        self._proc = _WNDPROC(self._wnd_proc)  # ссылку держим: иначе GC снесёт callback

    def show(self, state: str) -> None:
        if state not in _STATES:
            return
        self._state = state
        self._wake()

    def hide(self) -> None:
        self._state = None
        self._wake()

    def stop(self) -> None:
        self._ready.wait(timeout=2.0)
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_APP_CLOSE, 0, 0)

    def _wake(self) -> None:
        if self._ready.wait(timeout=2.0) and self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_APP_UPDATE, 0, 0)

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_APP_UPDATE:
            self._apply_state()
            return 0
        if msg == WM_TIMER:
            self._phase += 0.42
            self._paint()
            return 0
        if msg == WM_APP_CLOSE:
            _user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _apply_state(self) -> None:
        if self._state is None:
            _user32.KillTimer(self._hwnd, _TIMER_ID)
            _user32.ShowWindow(self._hwnd, SW_HIDE)
            return
        self._phase = 0.0
        self._paint()
        _user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        # Заново поднимаем поверх: другое окно могло стать topmost, пока мы были скрыты.
        _user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        _user32.SetTimer(self._hwnd, _TIMER_ID, _FRAME_MS, None)

    def _paint(self) -> None:
        state = self._state
        if state is None or not self._hwnd:
            return
        unheard = state == "recording" and self._unheard_probe is not None and self._unheard_probe()
        image = _render(state, self._phase, self._font, unheard)
        self._push_bitmap(image)

    def _push_bitmap(self, image: Image.Image) -> None:
        """Отдаёт RGBA-картинку в слоёное окно через UpdateLayeredWindow.

        Размеры берём у картинки: с подсказкой «Вас не слышно» плашка шире, а
        UpdateLayeredWindow заодно и меняет размер окна под неё.
        """
        width, height = image.size
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3].astype(np.uint16)
        # UpdateLayeredWindow ждёт BGRA с premultiplied alpha.
        rgb = (arr[:, :, :3].astype(np.uint16) * alpha[:, :, None] // 255).astype(np.uint8)
        bgra = np.dstack((rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0], arr[:, :, 3]))
        buf = np.ascontiguousarray(bgra).tobytes()

        screen_dc = _user32.GetDC(None)
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # отрицательная высота = строки сверху вниз
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        bitmap = _gdi32.CreateDIBSection(
            screen_dc, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        if not bitmap or not bits:
            log.error("CreateDIBSection провалился, GetLastError=%d", ctypes.get_last_error())
            _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(None, screen_dc)
            return
        try:
            ctypes.memmove(bits, buf, len(buf))
            old = _gdi32.SelectObject(mem_dc, bitmap)
            left, top, right, bottom = _work_area()
            pos = wintypes.POINT(right - width - _MARGIN, bottom - height - _MARGIN)
            size = wintypes.SIZE(width, height)
            src = wintypes.POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            ok = _user32.UpdateLayeredWindow(
                self._hwnd, screen_dc, ctypes.byref(pos), ctypes.byref(size),
                mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
            )
            if not ok:
                log.error("UpdateLayeredWindow провалился, GetLastError=%d", ctypes.get_last_error())
            _gdi32.SelectObject(mem_dc, old)
        finally:
            _gdi32.DeleteObject(bitmap)
            _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(None, screen_dc)

    def run(self) -> None:
        try:
            self._create_window()
        except Exception:
            log.exception("не удалось создать окно индикатора")
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        log.info("индикатор записи остановлен")

    def _create_window(self) -> None:
        instance = _kernel32.GetModuleHandleW(None)
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.lpfnWndProc = self._proc
        cls.hInstance = instance
        cls.lpszClassName = "WhisperTypeOverlay"
        if not _user32.RegisterClassExW(ctypes.byref(cls)):
            err = ctypes.get_last_error()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS — после перерегистрации класс уже есть
                raise OSError(f"RegisterClassExW провалился, GetLastError={err}")
        left, top, right, bottom = _work_area()
        hwnd = _user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "WhisperTypeOverlay", "WhisperType", WS_POPUP,
            right - _WIDTH - _MARGIN, bottom - _HEIGHT - _MARGIN, _WIDTH, _HEIGHT,
            None, None, instance, None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW провалился, GetLastError={ctypes.get_last_error()}")
        self._hwnd = hwnd
        log.info("индикатор записи создан")
