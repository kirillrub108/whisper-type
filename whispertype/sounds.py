"""Короткие звуковые сигналы через winsound (без внешних файлов)."""

from __future__ import annotations

import logging
import threading
import winsound

log = logging.getLogger(__name__)


def _beep(frequency: int, duration_ms: int) -> None:
    try:
        winsound.Beep(frequency, duration_ms)
    except RuntimeError:
        log.debug("winsound.Beep недоступен", exc_info=True)


class Sounds:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _play(self, frequency: int, duration_ms: int) -> None:
        if not self.enabled:
            return
        # Beep блокирует поток на duration_ms — играем в фоне.
        threading.Thread(
            target=_beep, args=(frequency, duration_ms), name="beep", daemon=True
        ).start()

    def record_start(self) -> None:
        self._play(880, 70)

    def record_stop(self) -> None:
        self._play(600, 70)

    def error(self) -> None:
        self._play(220, 180)
