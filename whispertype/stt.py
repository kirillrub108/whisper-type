"""Распознавание речи: faster-whisper (CTranslate2) на CPU, модель живёт в памяти."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .config import ModelConfig, VadConfig

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Стандартная лестница температур Whisper: следующая ступень берётся,
# только если декодирование не прошло пороги качества.
_TEMPERATURE_LADDER = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def normalize_audio(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """Снимает постоянную составляющую и подтягивает пик к target_peak.

    Тихая запись — частая причина ошибок распознавания: Whisper обучен
    на сигнале, занимающем весь динамический диапазон.
    """
    if audio.size == 0:
        return audio
    centred = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(centred)))
    if peak < 1e-4:  # практически тишина: усиливать нечего, вылезет только шум
        return centred.astype(np.float32, copy=False)
    return (centred * (target_peak / peak)).astype(np.float32, copy=False)


def pick_language(
    detected: str,
    all_probs: Sequence[tuple[str, float]] | None,
    candidates: Sequence[str],
) -> str | None:
    """Выбирает язык из candidates. None — определённый язык менять не нужно.

    Автоопределение Whisper на коротких фразах регулярно промахивается мимо
    нужного языка, а чужой язык превращает расшифровку в транслитерированный мусор.
    """
    if not candidates or detected in candidates:
        return None
    if all_probs:
        ranked = [(lang, prob) for lang, prob in all_probs if lang in candidates]
        if ranked:
            return max(ranked, key=lambda item: item[1])[0]
    return candidates[0]


class Transcriber:
    def __init__(self, cfg: ModelConfig, vad: VadConfig, models_dir: Path) -> None:
        self._cfg = cfg
        self._vad = vad
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
        Язык задан явно — на прогреве определять его незачем.
        """
        started = time.perf_counter()
        language = self._cfg.language or (self._cfg.languages[0] if self._cfg.languages else "en")
        segments, _info = self._decode(np.zeros(SAMPLE_RATE, dtype=np.float32), language, vad=False)
        for _ in segments:  # генератор ленивый — декодирование идёт при переборе
            pass
        log.info("прогрев модели завершён за %.1f с", time.perf_counter() - started)

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("модель не загружена")
        if self._cfg.normalize_audio:
            audio = normalize_audio(audio)
        segments, info = self._decode(audio, self._cfg.language)
        if self._cfg.language is None:
            # info готов до перебора сегментов, поэтому неверный язык
            # обходится лишним проходом только когда он действительно неверный.
            override = pick_language(info.language, info.all_language_probs, self._cfg.languages)
            if override is None:
                log.info("язык %s (p=%.2f)", info.language, info.language_probability)
            else:
                log.info(
                    "язык %s (p=%.2f) вне списка %s — переопределяю на %s",
                    info.language, info.language_probability, self._cfg.languages, override,
                )
                segments, _info = self._decode(audio, override)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def unload(self) -> None:
        self._model = None

    def _decode(self, audio: np.ndarray, language: str | None, *, vad: bool = True) -> tuple[Any, Any]:
        cfg = self._cfg
        return self._model.transcribe(
            audio,
            language=language,
            beam_size=cfg.beam_size,
            temperature=_TEMPERATURE_LADDER if cfg.temperature_fallback else 0.0,
            condition_on_previous_text=False,
            compression_ratio_threshold=cfg.compression_ratio_threshold,
            log_prob_threshold=cfg.log_prob_threshold,
            no_speech_threshold=cfg.no_speech_threshold,
            initial_prompt=cfg.initial_prompt or None,
            hotwords=cfg.hotwords or None,
            vad_filter=vad and self._vad.enabled,
            vad_parameters={
                "threshold": self._vad.threshold,
                "min_silence_duration_ms": self._vad.min_silence_duration_ms,
                "speech_pad_ms": self._vad.speech_pad_ms,
            },
        )
