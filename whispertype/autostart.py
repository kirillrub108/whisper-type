"""Автозагрузка через HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (без прав админа)."""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

from .config import APP_NAME

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Запуск из исходников: pythonw, чтобы не висело консольное окно.
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if pythonw.exists():
        interpreter = pythonw
    launcher = Path(__file__).resolve().parent.parent / "launcher.py"
    return f'"{interpreter}" "{launcher}"'


def is_enabled() -> bool:
    """True — автозапуск включён именно для этой копии программы.

    Путь сверяется, а не просто проверяется наличие записи: запись, оставшаяся
    от переехавшей или удалённой копии, Windows выполняет молча и молча же
    проваливает, а галочка в меню показывала бы, что всё в порядке.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _value_type = winreg.QueryValueEx(key, APP_NAME)
    except OSError:
        return False
    return str(value) == _command()


def set_enabled(enabled: bool) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _command())
                log.info("автозагрузка включена: %s", _command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
                log.info("автозагрузка выключена")
        return True
    except OSError:
        log.exception("не удалось изменить автозагрузку")
        return False
