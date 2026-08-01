"""Single instance через именованный mutex и MessageBox для второго запуска."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_user32.MessageBoxW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)

ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40

# Держим handle до конца жизни процесса — иначе mutex освободится.
_mutex_handle: int | None = None


def acquire_single_instance(name: str) -> bool:
    """False — экземпляр уже запущен."""
    global _mutex_handle
    handle = _kernel32.CreateMutexW(None, False, f"Local\\{name}.single-instance")
    err = ctypes.get_last_error()
    if not handle:
        log.error("CreateMutexW не удался, GetLastError=%d — продолжаю без защиты", err)
        return True
    _mutex_handle = handle
    return err != ERROR_ALREADY_EXISTS


def show_message(text: str, title: str) -> None:
    _user32.MessageBoxW(None, text, title, MB_ICONINFORMATION)
