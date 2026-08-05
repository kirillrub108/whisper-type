"""Захват звука: постоянно открытый InputStream 16 kHz mono float32.

Запись — это просто флаг «складывать блоки в буфер»; девайс не переоткрывается
на каждое нажатие. Watchdog переоткрывает поток при отключении/смене микрофона.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


SEARCH_BACK_SECONDS = 6.0
SILENCE_RMS = 0.02


def find_cut_point(
    audio: np.ndarray,
    target_samples: int,
    max_samples: int,
    silence_rms: float = SILENCE_RMS,
    frame_ms: int = 100,
) -> int:
    """Индекс среза записи на куски: самая тихая точка ближе к концу окна.

    Ищем паузу с оглядкой назад, а не среди самых свежих данных: иначе срез
    попадает в середину слова, и оно задваивается на стыке кусков. Пока паузы
    нет и есть запас до max_samples, возвращаем len(audio) — режем позже.
    """
    if len(audio) < target_samples:
        return len(audio)
    frame = max(1, frame_ms * SAMPLE_RATE // 1000)
    search_start = max(0, target_samples - int(SEARCH_BACK_SECONDS * SAMPLE_RATE))
    region = audio[search_start:]
    n_frames = len(region) // frame
    if n_frames == 0:
        return len(audio)
    frames = region[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    quietest = int(np.argmin(rms))
    if rms[quietest] > silence_rms and len(audio) < max_samples:
        return len(audio)  # подходящей паузы нет — копим дальше
    return search_start + quietest * frame + frame // 2


def is_silence(level: float, threshold: float) -> bool:
    """True, если громкость сессии ниже порога — микрофон молчал.

    threshold <= 0 полностью отключает проверку.
    """
    if threshold <= 0:
        return False
    return level < threshold


def list_input_devices() -> list[str]:
    names: list[str] = []
    try:
        for dev in sd.query_devices():
            if int(dev.get("max_input_channels", 0)) > 0:
                name = str(dev.get("name", ""))
                if name and name not in names:
                    names.append(name)
    except Exception:
        log.exception("не удалось перечислить устройства ввода")
    return names


class AudioRecorder:
    def __init__(
        self,
        device: int | str | None,
        max_seconds: int,
        on_limit: Callable[[], None],
    ) -> None:
        self._configured_device = device
        self._max_samples = max_seconds * SAMPLE_RATE
        self._on_limit = on_limit
        self._lock = threading.Lock()
        self._open_lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._total = 0
        self._level = 0.0
        self._recording = False
        self._limit_fired = False
        self._stream: sd.InputStream | None = None
        self._stopping = False
        self._watchdog: threading.Thread | None = None

    def start(self) -> None:
        self._open_stream()
        self._watchdog = threading.Thread(target=self._watch, name="audio-watchdog", daemon=True)
        self._watchdog.start()

    def begin(self) -> bool:
        """Начать запись. False — микрофон недоступен даже после переоткрытия."""
        stream = self._stream
        if stream is None or not stream.active:
            log.warning("аудиопоток неактивен, переоткрываю перед записью")
            if not self._open_stream():
                return False
        with self._lock:
            self._chunks = []
            self._total = 0
            self._level = 0.0
            self._limit_fired = False
            self._recording = True
        return True

    def end(self) -> np.ndarray:
        """Остановить запись и вернуть накопленный сигнал (float32, 16 kHz, mono)."""
        with self._lock:
            self._recording = False
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate([c.reshape(-1) for c in chunks]).astype(np.float32, copy=False)

    def peak_level(self) -> float:
        """Громкость самого громкого блока за всю текущую сессию записи.

        RMS блока, а не мгновенный пик: неисправное устройство отдаёт одиночные
        щелчки с амплитудой речи, и по пику такая сессия выглядит не тихой.
        """
        with self._lock:
            return self._level

    def pending_samples(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._chunks)

    def cut_prefix(self, target_samples: int, max_samples: int) -> np.ndarray:
        """Отрезает начало буфера по тихой точке. Пустой массив — резать ещё рано."""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            buffered = np.concatenate([c.reshape(-1) for c in self._chunks])
            cut = find_cut_point(buffered, target_samples, max_samples)
            if cut >= len(buffered):
                self._chunks = [buffered]
                return np.zeros(0, dtype=np.float32)
            self._chunks = [buffered[cut:]]
            return buffered[:cut].astype(np.float32, copy=False)

    def cancel(self) -> None:
        with self._lock:
            self._recording = False
            self._chunks = []
            self._total = 0
            self._level = 0.0

    def set_device(self, device: int | str | None) -> None:
        self._configured_device = device
        self._open_stream()

    def close(self) -> None:
        self._stopping = True
        self._close_stream()

    def _callback(self, indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        if status:
            log.debug("статус аудиопотока: %s", status)
        if not self._recording:
            return
        fire_limit = False
        with self._lock:
            if not self._recording:
                return
            self._chunks.append(indata.copy())
            self._total += frames
            block = indata.reshape(-1)
            self._level = max(self._level, float(np.sqrt(np.mean(block * block))))
            if self._total >= self._max_samples and not self._limit_fired:
                self._limit_fired = True
                fire_limit = True
        if fire_limit:
            try:
                self._on_limit()
            except Exception:
                log.exception("обработчик лимита записи упал")

    def _open_stream(self) -> bool:
        with self._open_lock:
            self._close_stream()
            candidates: list[int | str | None] = [self._configured_device]
            if self._configured_device is not None:
                candidates.append(None)  # fallback на системный дефолт
            for device in candidates:
                try:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=1,
                        dtype="float32",
                        device=device,
                        callback=self._callback,
                    )
                    stream.start()
                except Exception as exc:
                    log.warning("не удалось открыть устройство %r: %s", device, exc)
                    continue
                self._stream = stream
                log.info("аудиопоток открыт, устройство=%r", device if device is not None else "default")
                return True
            log.error("не удалось открыть ни одно устройство ввода")
            return False

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("закрытие старого аудиопотока не удалось", exc_info=True)

    def _watch(self) -> None:
        while not self._stopping:
            time.sleep(3.0)
            if self._stopping:
                break
            stream = self._stream
            if stream is None or not stream.active:
                log.warning("аудиопоток умер (смена/отключение устройства?), переоткрываю")
                self._open_stream()
