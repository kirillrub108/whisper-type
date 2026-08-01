"""Трей-иконка: визуальные состояния, меню, уведомления (pystray + Pillow)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from . import __version__
from .config import APP_NAME, config_path, logs_dir

if TYPE_CHECKING:
    from .app import App

log = logging.getLogger(__name__)

_STATE_COLORS = {
    "loading": "#8a8a8a",
    "idle": "#4a6fa5",
    "recording": "#d93025",
    "processing": "#f2a600",
    "error": "#8c1d18",
}
_STATE_LABELS = {
    "loading": "загрузка модели…",
    "idle": "готов",
    "recording": "запись…",
    "processing": "распознавание…",
    "error": "ошибка (см. лог)",
}


def _make_image(state: str) -> Image.Image:
    color = _STATE_COLORS[state]
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=color)
    if state == "error":
        draw.rectangle((29, 16, 35, 40), fill="white")
        draw.ellipse((29, 45, 35, 51), fill="white")
    else:
        # стилизованный микрофон
        draw.rounded_rectangle((26, 13, 38, 35), radius=6, fill="white")
        draw.arc((20, 22, 44, 44), start=0, end=180, fill="white", width=3)
        draw.line((32, 44, 32, 51), fill="white", width=3)
    return img


class Tray:
    def __init__(self, app: App) -> None:
        self._app = app
        self._images = {state: _make_image(state) for state in _STATE_COLORS}
        self._icon = pystray.Icon(
            APP_NAME,
            icon=self._images["loading"],
            title=f"{APP_NAME} — {_STATE_LABELS['loading']}",
            menu=self._build_menu(),
        )

    def run(self, setup: Callable[[pystray.Icon], None]) -> None:
        self._icon.run(setup=setup)

    def stop(self) -> None:
        self._icon.stop()

    def set_state(self, state: str) -> None:
        self._icon.icon = self._images[state]
        self._icon.title = f"{APP_NAME} — {_STATE_LABELS[state]}"

    def notify(self, message: str, title: str = APP_NAME) -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            log.exception("не удалось показать уведомление")

    def _build_menu(self) -> Menu:
        app = self._app
        return Menu(
            MenuItem(f"{APP_NAME} {__version__}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "Включено",
                lambda icon, item: app.toggle_enabled(),
                checked=lambda item: app.enabled,
            ),
            MenuItem(
                "Режим",
                Menu(
                    MenuItem(
                        "Push-to-talk (зажать)",
                        lambda icon, item: app.set_mode("push_to_talk"),
                        radio=True,
                        checked=lambda item: app.mode == "push_to_talk",
                    ),
                    MenuItem(
                        "Toggle (нажать дважды)",
                        lambda icon, item: app.set_mode("toggle"),
                        radio=True,
                        checked=lambda item: app.mode == "toggle",
                    ),
                ),
            ),
            MenuItem("Микрофон", Menu(self._device_items)),
            Menu.SEPARATOR,
            MenuItem(
                "Автозагрузка",
                lambda icon, item: app.toggle_autostart(),
                checked=lambda item: app.autostart_enabled,
            ),
            MenuItem("Открыть конфиг", lambda icon, item: _open_path(config_path())),
            MenuItem("Папка логов", lambda icon, item: _open_path(logs_dir())),
            Menu.SEPARATOR,
            MenuItem("О программе", lambda icon, item: app.show_about()),
            MenuItem("Выход", lambda icon, item: app.quit()),
        )

    def _device_items(self):  # noqa: ANN202 — генератор пунктов для pystray
        from .audio import list_input_devices

        app = self._app

        def select(device: str | None) -> Callable[[pystray.Icon, MenuItem], None]:
            return lambda icon, item: app.select_device(device)

        yield MenuItem(
            "Системный по умолчанию",
            select(None),
            radio=True,
            checked=lambda item: app.current_device is None,
        )
        for name in list_input_devices():
            yield MenuItem(
                name,
                select(name),
                radio=True,
                checked=lambda item, n=name: app.current_device == n,
            )


def _open_path(path: object) -> None:
    try:
        os.startfile(str(path))  # noqa: S606 — открытие своего конфига/логов
    except OSError:
        log.exception("не удалось открыть %s", path)
