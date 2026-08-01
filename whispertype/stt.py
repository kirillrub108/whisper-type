"""Распознавание речи: faster-whisper (CTranslate2) на CPU, модель живёт в памяти."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from .config import ModelConfig

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class Transcriber:
    def __init__(self, cfg: ModelConfig, models_dir: Path) -> None:
        self._cfg = cfg
        self._models_dir = models_dir
        self._model: Any = None

    def is_cached(self) -> bool:
        """Модель уже скачана в локальный кэш (есть model.bin в snapshot'е HF)."""
        return self._models_dir.exists() and any(self._models_dir.rglob("model.bin"))

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        # Тяжёлый импорт откладываем, чтобы трей появлялся мгновенно.
        from faster_whisper import WhisperModel

        self._models_dir.mkdir(parents=True, exist_ok=True)
        offline = self.is_cached()
        log.info(
            "загрузка модели %s (compute=%s, threads=%d, offline=%s)",
            self._cfg.repo, self._cfg.compute_type, self._cfg.cpu_threads, offline,
        )
        started = time.perf_counter()
        self._model = WhisperModel(
            self._cfg.repo,
            device="cpu",
            compute_type=self._cfg.compute_type,
            cpu_threads=self._cfg.cpu_threads,
            download_root=str(self._models_dir),
            local_files_only=offline,
        )
        log.info("модель загружена за %.1f с", time.perf_counter() - started)

    def warm_up(self) -> None:
        """Прогоняет 1 с тишины, чтобы первый реальный запрос не был медленнее.

        VAD выключен намеренно: иначе тишина отсекается и encoder не прогревается.
        """
        started = time.perf_counter()
        self._transcribe_array(np.zeros(SAMPLE_RATE, dtype=np.float32), vad=False)
        log.info("прогрев модели завершён за %.1f с", time.perf_counter() - started)

    def transcribe(self, audio: np.ndarray) -> str:
        return self._transcribe_array(audio, vad=True)

    def unload(self) -> None:
        self._model = None

    def _transcribe_array(self, audio: np.ndarray, *, vad: bool) -> str:
        if self._model is None:
            raise RuntimeError("модель не загружена")
        segments, _info = self._model.transcribe(
            audio,
            language=self._cfg.language,
            beam_size=self._cfg.beam_size,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=vad,
            no_speech_threshold=self._cfg.no_speech_threshold,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
