"""Конфигурация приложения: пути, дефолты, загрузка и валидация config.json."""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "WhisperType"


# Сколько логических процессоров оставить свободными под захват звука, хук
# хоткея и трей: инференс не должен занимать машину целиком, иначе эти лёгкие,
# но чувствительные к задержкам потоки ждут своей очереди у планировщика.
RESERVED_CPUS = 2


def resolve_cpu_threads(configured: int | None) -> int:
    """Число потоков инференса; None — подобрать по числу логических процессоров.

    Замеры на Ryzen 5 7500F (6 ядер / 12 потоков, turbo, int8_float32, фраза
    5.5 с): 6 потоков — 1.37 с, 8 — 1.22 с, 10 — 1.06 с, 12 — 1.10 с. Занимать
    все логические потоки невыгодно: SMT-сосед делит с ядром одни и те же
    исполнительные блоки, а матричные умножения их и так насыщают, поэтому
    сверх физических ядер прирост даёт только частичную загрузку SMT.
    Проверено на одной машине — на других формула может быть неоптимальной,
    поэтому значение всегда можно задать явно.
    """
    if configured is not None:
        return configured
    logical = os.cpu_count() or 4
    return max(1, logical - RESERVED_CPUS)


def appdata_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME


def localappdata_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME


def config_path() -> Path:
    return appdata_dir() / "config.json"


def history_path() -> Path:
    return appdata_dir() / "history.json"


def models_dir() -> Path:
    return localappdata_dir() / "models"


def logs_dir() -> Path:
    return localappdata_dir() / "logs"


def ensure_dirs() -> None:
    for directory in (appdata_dir(), localappdata_dir(), models_dir(), logs_dir()):
        directory.mkdir(parents=True, exist_ok=True)


DEFAULT_HALLUCINATION_PATTERNS: tuple[str, ...] = (
    "субтитры сделал",
    "субтитры делал",
    "субтитры подготовил",
    "субтитры создавал",
    "редактор субтитров",
    "продолжение следует",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "ставьте лайк",
    "до новых встреч",
    "dimatorzok",
    "thank you for watching",
    "thanks for watching",
    "subtitles by",
    "amara.org",
    "переведено сообществом",
)


@dataclass
class ModelConfig:
    repo: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    compute_type: str = "int8_float32"
    # null — подобрать по числу логических процессоров (см. resolve_cpu_threads).
    cpu_threads: int | None = None
    beam_size: int = 5
    # Заданный язык экономит отдельный проход энкодера на автоопределении (вдвое быстрее).
    # null — определять автоматически по списку languages, но платить этим проходом.
    language: str | None = "ru"
    languages: list[str] = field(default_factory=lambda: ["ru", "en"])  # кандидаты при авто
    initial_prompt: str | None = None
    hotwords: str | None = None
    temperature_fallback: bool = True
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    normalize_audio: bool = True
    # Сужение окна энкодера под длину фразы — главное ускорение на CPU (turbo:
    # ~1 с вместо ~4 с на короткой записи). Работает в связке с without_timestamps
    # и нижним порогом окна 12 с (см. stt.py); редкий остаточный самоповтор
    # схлопывается текстом (collapse_duplicated) без повторного распознавания.
    adaptive_window: bool = True


@dataclass
class VadConfig:
    enabled: bool = True
    threshold: float = 0.35
    # Пауза, разделяющая сегменты. При крупном значении речь после короткой
    # паузы попадает в один сегмент, и если там сменился язык, Whisper
    # обрывает расшифровку — вторая половина записи теряется целиком.
    min_silence_duration_ms: int = 500
    speech_pad_ms: int = 400


@dataclass
class OverlayConfig:
    enabled: bool = True


@dataclass
class StreamingConfig:
    """Обработка длинной диктовки кусками прямо во время записи.

    Куски режутся начиная с chunk_seconds и только по настоящей паузе: при
    сплошной речи буфер копится до предела окна, поэтому слово не разрывается.
    Порог заметно влияет на ожидание: при 25 с запись на 20 с не режется вовсе
    и ждёт целиком (4.2 с), при 8 с ожидание падает до 1.4 с.
    """

    enabled: bool = True
    chunk_seconds: int = 8


@dataclass
class AudioConfig:
    input_device: int | str | None = None
    max_record_seconds: int = 120
    min_record_ms: int = 300


@dataclass
class HotkeyConfig:
    mode: str = "toggle"  # push_to_talk | toggle
    combo: str = "ctrl + space"
    cancel: str = "esc"


@dataclass
class InjectConfig:
    method: str = "clipboard"  # clipboard | type
    clipboard_restore_delay_ms: int = 150
    type_batch_size: int = 16
    type_batch_delay_ms: int = 5
    append_space: bool = False
    strip_final_period: bool = False


@dataclass
class Config:
    log_level: str = "INFO"
    sounds: bool = True
    model: ModelConfig = field(default_factory=ModelConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    inject: InjectConfig = field(default_factory=InjectConfig)
    hallucination_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_HALLUCINATION_PATTERNS)
    )


# Допустимые JSON-типы каждого листового поля (bool проверяется отдельно,
# т.к. bool — подкласс int).
_FIELD_TYPES: dict[str, tuple[type, ...]] = {
    "log_level": (str,),
    "sounds": (bool,),
    "hallucination_patterns": (list,),
    "repo": (str,),
    "compute_type": (str,),
    "cpu_threads": (int, type(None)),
    "beam_size": (int,),
    "language": (str, type(None)),
    "languages": (list,),
    "initial_prompt": (str, type(None)),
    "hotwords": (str, type(None)),
    "temperature_fallback": (bool,),
    "compression_ratio_threshold": (int, float),
    "log_prob_threshold": (int, float),
    "no_speech_threshold": (int, float),
    "normalize_audio": (bool,),
    "adaptive_window": (bool,),
    "enabled": (bool,),
    "threshold": (int, float),
    "min_silence_duration_ms": (int,),
    "speech_pad_ms": (int,),
    "chunk_seconds": (int,),
    "input_device": (int, str, type(None)),
    "max_record_seconds": (int,),
    "min_record_ms": (int,),
    "mode": (str,),
    "combo": (str,),
    "cancel": (str,),
    "method": (str,),
    "clipboard_restore_delay_ms": (int,),
    "type_batch_size": (int,),
    "type_batch_delay_ms": (int,),
    "append_space": (bool,),
    "strip_final_period": (bool,),
}


def _type_ok(name: str, value: Any) -> bool:
    expected = _FIELD_TYPES[name]
    if isinstance(value, bool) and bool not in expected:
        return False
    return isinstance(value, expected)


def _apply(target: Any, data: dict[str, Any], prefix: str, warnings: list[str]) -> None:
    for f in dataclasses.fields(target):
        if f.name not in data:
            continue
        value = data[f.name]
        current = getattr(target, f.name)
        if dataclasses.is_dataclass(current):
            if isinstance(value, dict):
                _apply(current, value, f"{prefix}{f.name}.", warnings)
            else:
                warnings.append(f"{prefix}{f.name}: ожидался объект, получено {type(value).__name__}")
            continue
        if not _type_ok(f.name, value):
            warnings.append(
                f"{prefix}{f.name}: неверный тип {type(value).__name__}, оставлен дефолт {current!r}"
            )
            continue
        setattr(target, f.name, value)


def _validate(cfg: Config, warnings: list[str]) -> None:
    if cfg.hotkey.mode not in ("push_to_talk", "toggle"):
        warnings.append(f"hotkey.mode: неизвестный режим {cfg.hotkey.mode!r}, использован toggle")
        cfg.hotkey.mode = "toggle"
    if cfg.inject.method not in ("clipboard", "type"):
        warnings.append(f"inject.method: неизвестный метод {cfg.inject.method!r}, использован clipboard")
        cfg.inject.method = "clipboard"
    if not 1 <= cfg.model.beam_size <= 5:
        warnings.append(f"model.beam_size: {cfg.model.beam_size} вне диапазона 1–5, использован 5")
        cfg.model.beam_size = 5
    langs = [lang for lang in cfg.model.languages if isinstance(lang, str) and lang]
    if len(langs) != len(cfg.model.languages):
        warnings.append("model.languages: нестроковые элементы отброшены")
    cfg.model.languages = langs
    if not 0.0 <= cfg.vad.threshold <= 1.0:
        warnings.append(f"vad.threshold: {cfg.vad.threshold} вне диапазона 0–1, использовано 0.35")
        cfg.vad.threshold = 0.35
    if cfg.vad.speech_pad_ms < 0:
        cfg.vad.speech_pad_ms = 400
    if cfg.vad.min_silence_duration_ms < 0:
        cfg.vad.min_silence_duration_ms = 500
    # Больше 29 с бессмысленно: кусок перестанет помещаться в окно энкодера.
    if not 5 <= cfg.streaming.chunk_seconds <= 29:
        warnings.append(
            f"streaming.chunk_seconds: {cfg.streaming.chunk_seconds} вне диапазона 5–29, использовано 8"
        )
        cfg.streaming.chunk_seconds = 8
    if cfg.model.cpu_threads is not None and cfg.model.cpu_threads < 1:
        warnings.append("model.cpu_threads: значение < 1, включён автоподбор")
        cfg.model.cpu_threads = None
    if not 1 <= cfg.audio.max_record_seconds <= 600:
        warnings.append("audio.max_record_seconds: вне диапазона 1–600, использовано 120")
        cfg.audio.max_record_seconds = 120
    if cfg.audio.min_record_ms < 0:
        warnings.append("audio.min_record_ms: отрицательное значение, использовано 300")
        cfg.audio.min_record_ms = 300
    if cfg.inject.clipboard_restore_delay_ms < 0:
        cfg.inject.clipboard_restore_delay_ms = 150
    if cfg.inject.type_batch_size < 1:
        cfg.inject.type_batch_size = 16
    if cfg.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        warnings.append(f"log_level: неизвестный уровень {cfg.log_level!r}, использован INFO")
        cfg.log_level = "INFO"
    bad = [p for p in cfg.hallucination_patterns if not isinstance(p, str)]
    if bad:
        warnings.append("hallucination_patterns: нестроковые элементы отброшены")
        cfg.hallucination_patterns = [p for p in cfg.hallucination_patterns if isinstance(p, str)]


def load_config(path: Path | None = None) -> tuple[Config, list[str]]:
    """Читает конфиг; при отсутствии создаёт с дефолтами, при ошибках не падает."""
    path = path if path is not None else config_path()
    cfg = Config()
    warnings: list[str] = []
    if not path.exists():
        write_config(cfg, path)
        return cfg, warnings
    try:
        # utf-8-sig, а не utf-8: Блокнот и PowerShell сохраняют файл с BOM,
        # на которой json падает — и весь конфиг молча заменяется дефолтами.
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"не удалось прочитать {path.name}: {exc}; использованы дефолты")
        return cfg, warnings
    if not isinstance(raw, dict):
        warnings.append(f"{path.name}: корень не объект; использованы дефолты")
        return cfg, warnings
    _apply(cfg, raw, "", warnings)
    _validate(cfg, warnings)
    return cfg, warnings


def write_config(cfg: Config, path: Path | None = None) -> None:
    path = path if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataclasses.asdict(cfg), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
