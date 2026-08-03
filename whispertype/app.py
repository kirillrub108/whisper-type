"""Оркестрация: state machine записи, обработка событий хоткея, main()."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import types
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import __version__, autostart, inject
from .audio import SAMPLE_RATE, AudioRecorder
from .config import (
    APP_NAME,
    Config,
    config_path,
    ensure_dirs,
    history_path,
    load_config,
    logs_dir,
    models_dir,
    write_config,
)
from .history import PhraseHistory
from .hotkey import HotkeyListener
from .keys import Hotkey, parse_hotkey
from .logging_setup import setup_logging
from .overlay import Overlay
from .sounds import Sounds
from .stt import Transcriber
from .textproc import postprocess
from .tray import Tray
from .winutil import acquire_single_instance, show_message

if TYPE_CHECKING:
    import pystray

log = logging.getLogger(__name__)

_DEFAULT_COMBO = "right ctrl"
_DEFAULT_CANCEL = "esc"


class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.enabled = True
        self.ready = False
        self.state = "idle"  # idle | recording | processing
        self._events: queue.Queue[str] = queue.Queue()
        self._shutdown = threading.Event()
        self.sounds = Sounds(cfg.sounds)
        self.recorder = AudioRecorder(
            cfg.audio.input_device,
            cfg.audio.max_record_seconds,
            lambda: self._events.put("limit"),
        )
        self.transcriber = Transcriber(cfg.model, cfg.vad, models_dir())
        hotkey = self._parse_or_default(cfg.hotkey.combo, _DEFAULT_COMBO)
        cancel = self._parse_or_default(cfg.hotkey.cancel, _DEFAULT_CANCEL)
        self._hotkey_vks = hotkey.all_vks()
        self.listener = HotkeyListener(hotkey, cancel, self._events.put)
        self.overlay = Overlay() if cfg.overlay.enabled else None
        self.tray = Tray(self)
        self._worker: threading.Thread | None = None
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()
        self._stream_parts: list[str] = []
        self.history = PhraseHistory(history_path())
        self._last_window = 0

    @staticmethod
    def _parse_or_default(spec: str, default: str) -> Hotkey:
        try:
            return parse_hotkey(spec)
        except ValueError as exc:
            log.error("конфиг: %s; использован дефолт %r", exc, default)
            return parse_hotkey(default)

    # ------------------------------------------------------------ запуск/останов

    def run(self) -> None:
        self.tray.run(setup=self._setup)

    def _setup(self, icon: pystray.Icon) -> None:
        # pystray вызывает setup в отдельном потоке после создания иконки.
        icon.visible = True
        try:
            self._init()
        except Exception:
            log.exception("инициализация провалилась")
            self.tray.set_state("error")
            self.tray.notify("Не удалось запуститься — подробности в логе.")
            self.sounds.error()

    def _init(self) -> None:
        self.tray.set_state("loading")
        self.history.load()
        self.recorder.start()
        self._worker = threading.Thread(target=self._worker_loop, name="worker", daemon=True)
        self._worker.start()
        threading.Thread(target=self._track_foreground, name="foreground", daemon=True).start()
        self.listener.start()
        if self.overlay is not None:
            self.overlay.start()
        if not self.transcriber.is_cached():
            self.tray.notify(
                "Первый запуск: скачиваю модель распознавания (~1.6 ГБ). "
                "Это займёт несколько минут, прогресс — в логе."
            )
        self.transcriber.load()
        self.transcriber.warm_up()
        self.ready = True
        self.tray.set_state("idle")
        self.tray.notify(f"Готов к работе. Хоткей: {self.cfg.hotkey.combo}")

    def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        log.info("завершение работы")
        self.listener.stop()
        if self.overlay is not None:
            self.overlay.stop()
        self.recorder.close()
        self.transcriber.unload()

    def quit(self) -> None:
        self.shutdown()
        self.tray.stop()

    # ------------------------------------------------------------ события хоткея

    def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                event = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle(event)
            except Exception:
                log.exception("ошибка при обработке события %s", event)
                self.state = "idle"
                self.listener.set_recording(False)
                self.tray.set_state("error")
                self._overlay_hide()
                self.sounds.error()

    def _handle(self, event: str) -> None:
        if event == "hook_failed":
            self.tray.set_state("error")
            self.tray.notify("Не удалось установить клавиатурный хук — хоткей не работает.")
            return
        if not self.enabled:
            return
        mode = self.cfg.hotkey.mode
        if event == "press":
            if not self.ready:
                if self.state == "idle":
                    self.tray.notify("Модель ещё загружается, подождите…")
                return
            if self.state == "idle":
                self._start_recording()
            elif self.state == "recording" and mode == "toggle":
                self._finish()
        elif event == "release":
            if mode == "push_to_talk" and self.state == "recording":
                self._finish()
        elif event == "cancel":
            if self.state == "recording":
                self._cancel()
        elif event == "limit":
            if self.state == "recording":
                log.info("достигнут лимит длительности записи")
                self._finish()

    def _start_recording(self) -> None:
        if not self.recorder.begin():
            self.tray.set_state("error")
            self.tray.notify("Микрофон недоступен. Проверьте устройство в меню трея.")
            self.sounds.error()
            return
        self.state = "recording"
        self.listener.set_recording(True)
        self.tray.set_state("recording")
        self._overlay_show("recording")
        self.sounds.record_start()
        self._stream_parts = []
        if self.cfg.streaming.enabled:
            self._stream_stop.clear()
            self._stream_thread = threading.Thread(
                target=self._stream_loop, name="stream", daemon=True
            )
            self._stream_thread.start()

    def _stream_loop(self) -> None:
        """Пока идёт запись, дораспознаёт накопленное кусками.

        К моменту отпускания хоткея остаётся только хвост, поэтому ожидание
        не растёт вместе с длиной диктовки.
        """
        target = self.cfg.streaming.chunk_seconds * SAMPLE_RATE
        # 29 с — предел одного окна энкодера, дальше кусок обойдётся вдвое дороже.
        hard_max = 29 * SAMPLE_RATE
        while not self._stream_stop.wait(0.25):
            if self.recorder.pending_samples() < target:
                continue
            chunk = self.recorder.cut_prefix(target, hard_max)
            if chunk.size == 0:
                continue
            try:
                raw = self.transcriber.transcribe(chunk)
            except Exception:
                log.exception("не удалось распознать промежуточный кусок")
                continue
            # Фильтруем каждый кусок отдельно: обрывок на стыке легко порождает
            # галлюцинацию, а в общей склейке её уже не отличить от речи.
            text = postprocess(raw, self.cfg.hallucination_patterns)
            log.info("промежуточный кусок %.1f с: %r", chunk.size / SAMPLE_RATE, text[:60])
            if text:
                self._stream_parts.append(text)

    def _stop_stream(self) -> None:
        self._stream_stop.set()
        thread = self._stream_thread
        self._stream_thread = None
        if thread is not None:
            thread.join(timeout=60.0)  # ждём текущий кусок, иначе потеряем его текст

    def _cancel(self) -> None:
        self._stop_stream()
        self._stream_parts = []
        self.recorder.cancel()
        self.listener.set_recording(False)
        self.state = "idle"
        self.tray.set_state("idle")
        self._overlay_hide()
        log.info("запись отменена")

    def _finish(self) -> None:
        self.listener.set_recording(False)
        self._stop_stream()
        audio = self.recorder.end()
        parts = self._stream_parts
        self._stream_parts = []
        self.state = "processing"
        self.tray.set_state("processing")
        self._overlay_show("processing")
        self.sounds.record_stop()
        try:
            duration_ms = len(audio) / SAMPLE_RATE * 1000
            if duration_ms < self.cfg.audio.min_record_ms:
                if not parts:
                    log.info("запись слишком короткая (%.0f мс) — игнорирую", duration_ms)
                    return
                tail = ""  # хвост после последнего куска — обрывок, распознавать нечего
            else:
                started = time.perf_counter()
                tail = self.transcriber.transcribe(audio)
                log.info(
                    "распознано %.1f с аудио за %.2f с: %r",
                    duration_ms / 1000, time.perf_counter() - started, tail[:120],
                )
            raw = " ".join(part for part in (*parts, tail) if part)
            text = postprocess(
                raw,
                self.cfg.hallucination_patterns,
                append_space=self.cfg.inject.append_space,
                strip_final_period=self.cfg.inject.strip_final_period,
            )
            if not text:
                log.info("после постобработки текст пуст — ничего не вставляю")
                return
            self.history.add(text)
            self._inject(text)
        finally:
            self.state = "idle"
            self.tray.set_state("idle")
            self._overlay_hide()

    def _overlay_show(self, state: str) -> None:
        if self.overlay is not None:
            self.overlay.show(state)

    def _overlay_hide(self) -> None:
        if self.overlay is not None:
            self.overlay.hide()

    def _inject(self, text: str) -> None:
        inject.wait_keys_released(self._hotkey_vks)
        if inject.foreground_blocks_input():
            inject.write_clipboard(text)
            self.tray.notify(
                "Окно в фокусе запущено с правами администратора — автовставка невозможна. "
                "Текст скопирован в буфер, нажмите Ctrl+V вручную."
            )
            return
        if self.cfg.inject.method == "type":
            ok = inject.type_text(
                text, self.cfg.inject.type_batch_size, self.cfg.inject.type_batch_delay_ms
            )
        else:
            ok = inject.paste_via_clipboard(text, self.cfg.inject.clipboard_restore_delay_ms)
        if not ok:
            self.tray.notify("Не удалось вставить текст — подробности в логе.")
            self.sounds.error()

    # ------------------------------------------------------------ история фраз

    def _track_foreground(self) -> None:
        """Запоминает последнее чужое активное окно.

        Открытое меню трея само становится активным окном, поэтому в момент
        клика по пункту истории спросить систему «куда вставлять» уже поздно.
        """
        while not self._shutdown.wait(0.2):
            hwnd = inject.foreground_window()
            if hwnd and not inject.is_own_window(hwnd) and not inject.is_shell_window(hwnd):
                self._last_window = hwnd

    @property
    def recent_phrases(self) -> list[str]:
        """Последние фразы, свежие сверху."""
        return self.history.recent()

    def insert_phrase(self, text: str) -> None:
        """Вставляет фразу из истории в то окно, что было активным до меню."""
        target = inject.foreground_window()
        if not target or inject.is_own_window(target):
            target = self._last_window
        if not inject.focus_window(target):
            inject.write_clipboard(text)
            self.tray.notify("Не удалось вернуть фокус окну. Текст в буфере — нажмите Ctrl+V.")
            return
        self._inject(text)

    # ------------------------------------------------------------ команды из меню

    @property
    def mode(self) -> str:
        return self.cfg.hotkey.mode

    @property
    def current_device(self) -> int | str | None:
        return self.cfg.audio.input_device

    @property
    def autostart_enabled(self) -> bool:
        return autostart.is_enabled()

    def toggle_enabled(self) -> None:
        self.enabled = not self.enabled
        self.listener.set_enabled(self.enabled)
        log.info("распознавание %s", "включено" if self.enabled else "выключено")

    def _persist(self, apply: Callable[[Config], None]) -> None:
        """Меняет одно поле поверх файла на диске, а не поверх снимка из памяти.

        Снимок сделан при запуске, поэтому запись им целиком молча затирала бы
        правки, внесённые в config.json руками при работающем приложении.
        """
        apply(self.cfg)
        try:
            on_disk, _warnings = load_config()
            apply(on_disk)
            write_config(on_disk)
        except OSError:
            log.exception("не удалось сохранить конфиг")

    def set_mode(self, mode: str) -> None:
        self._persist(lambda cfg: setattr(cfg.hotkey, "mode", mode))
        log.info("режим переключён на %s", mode)

    def select_device(self, device: str | None) -> None:
        self._persist(lambda cfg: setattr(cfg.audio, "input_device", device))
        self.recorder.set_device(device)

    def toggle_autostart(self) -> None:
        autostart.set_enabled(not autostart.is_enabled())

    def show_about(self) -> None:
        self.tray.notify(
            f"{APP_NAME} {__version__} — офлайн голосовой ввод.\n"
            f"Модель: {self.cfg.model.repo} (CPU, {self.cfg.model.compute_type}).\n"
            f"Хоткей: {self.cfg.hotkey.combo} ({self.cfg.hotkey.mode})."
        )


def _install_excepthooks(app: App) -> None:
    def handle(exc_type: type[BaseException], exc: BaseException,
               tb: types.TracebackType | None) -> None:
        log.critical("необработанное исключение", exc_info=(exc_type, exc, tb))
        try:
            app.tray.set_state("error")
            app.sounds.error()
        except Exception:
            pass

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(
        args.exc_type, args.exc_value or args.exc_type(), args.exc_traceback
    )


def main() -> int:
    ensure_dirs()
    cfg, warnings = load_config(config_path())
    setup_logging(logs_dir(), cfg.log_level)
    for warning in warnings:
        log.warning("конфиг: %s", warning)
    if not acquire_single_instance(APP_NAME):
        show_message(f"{APP_NAME} уже запущен — иконка в системном трее.", APP_NAME)
        return 0
    log.info("запуск %s %s", APP_NAME, __version__)
    app = App(cfg)
    _install_excepthooks(app)
    try:
        app.run()
    finally:
        app.shutdown()
    log.info("остановлен")
    return 0
