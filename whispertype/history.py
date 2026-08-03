"""История распознанных фраз: список в памяти, переживающий перезапуск."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

MAX_PHRASES = 10


class PhraseHistory:
    """Последние фразы, свежие сверху.

    Пишет worker-поток (после распознавания), читает поток трея (при открытии
    меню), поэтому доступ под замком. Файл переписывается целиком на каждую
    фразу: он крошечный, а приложение закрывают как попало — копить в памяти
    до выхода означало бы терять историю при снятии процесса.
    """

    def __init__(self, path: Path, limit: int = MAX_PHRASES) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._items: deque[str] = deque(maxlen=limit)

    def load(self) -> None:
        """Читает файл; при любой поломке молча начинает с пустой истории."""
        if not self._path.exists():
            return
        try:
            # utf-8-sig: файл могли открыть Блокнотом и пересохранить с BOM
            raw = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("не удалось прочитать %s: %s; история пуста", self._path.name, exc)
            return
        if not isinstance(raw, list):
            log.warning("%s: ожидался список фраз; история пуста", self._path.name)
            return
        with self._lock:
            self._items.extend(item for item in raw if isinstance(item, str) and item)
        log.info("история фраз загружена: %d шт.", len(self._items))

    def add(self, text: str) -> None:
        with self._lock:
            if self._items and self._items[-1] == text:
                return  # подряд одно и то же — незачем занимать место в списке
            self._items.append(text)
            self._write()

    def recent(self) -> list[str]:
        with self._lock:
            return list(reversed(self._items))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._write()

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(list(self._items), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            log.exception("не удалось сохранить историю в %s", self._path)
