# CLAUDE.md

> Автоматически загружается Claude Code в каждой сессии.

## Проект

WhisperType — офлайн голосовой ввод для Windows: хоткей → речь → распознанный текст вставляется
в активное поле любого приложения. Однопроцессное десктопное приложение, без сети и без БД.

**Стек:** Python 3.11 (строго), faster-whisper (CTranslate2, CPU), sounddevice, numpy,
pystray + Pillow, весь WinAPI — на голом `ctypes`. Сборка: PyInstaller `--onedir` + Inno Setup 6.

Подробная инженерная документация — в [docs/](docs/README.md).

---

## Команды

```bash
# Разработка (из .venv на Python 3.11)
python launcher.py

# Тесты — ТОЛЬКО так, см. «Осторожно»
python -m pytest -q
python -m pytest tests/test_stt_logic.py -v      # один файл
python -m pytest -q -k "window"                  # по имени

# Линт и типы
ruff check whispertype tests
mypy whispertype

# Сборка exe + инсталлятора
build.bat
```

Окружение: `py -3.11 -m venv .venv && .venv\Scripts\activate && pip install -r requirements-dev.txt`

---

## Структура

```
whispertype/
  app.py       — оркестрация, state machine записи, main(); знает про все модули
  stt.py       — распознавание + сужение окна энкодера (главная оптимизация)
  inject.py    — вставка текста: буфер обмена, SendInput, UIPI, возврат фокуса
  hotkey.py    — низкоуровневый хук WH_KEYBOARD_LL на своём потоке
  audio.py     — постоянно открытый InputStream + нарезка по паузам
  overlay.py   — слоёное окно-индикатор записи
  tray.py      — иконка и меню (pystray)
  config.py    — дефолты, пути, валидация config.json; базовый слой, ни от кого не зависит
  textproc.py  — постобработка текста (чистые функции)
  keys.py      — разбор строки хоткея в VK-коды (чистые функции)
launcher.py    — точка входа для PyInstaller (нужен freeze_support)
whispertype.spec / installer.iss / build.bat — сборка
```

---

## Архитектура

Ядро — класс `App` ([whispertype/app.py](whispertype/app.py)): владеет всеми подсистемами и
крутит state machine `idle → recording → processing`. Подсистемы друг о друге не знают —
общение только через `queue.Queue[str]` (`App._events`) со строками-событиями
`press`/`release`/`cancel`/`limit`/`hook_failed`.

**9 потоков**: main (pystray), hotkey (хук + message loop), overlay (окно + message loop),
worker (разбор очереди, распознавание), stream (нарезка во время записи), foreground (опрос
активного окна), audio-watchdog, аудио-коллбэк PortAudio, beep. Имя потока попадает в каждую
строку лога — без него разобрать лог невозможно.

Зависимости строго однонаправленные: `app.py` → подсистемы → `config.py`. `textproc.py` и
`keys.py` — чистые, без WinAPI, именно они покрыты тестами.

---

## Конвенции

- **`from __future__ import annotations` в каждом модуле.** Без исключений.
- **Полная типизация.** Нетипизированного кода нет; `# noqa: ANN202` только на генераторах
  меню pystray.
- **Никаких TODO, закомментированного и мёртвого кода.** Маркеров TODO/FIXME в репозитории 0.
- **Комментарии объясняют «почему», а не «что»**, и только там, где код неочевиден.
  `textproc.py` почти без комментариев, `inject.py`/`overlay.py` — плотно (каждый второй вызов
  WinAPI содержит ловушку).
- **Язык:** русский в docstring'ах, комментариях, логах и уведомлениях; идентификаторы английские.
- **Логи:** ленивое форматирование (`log.info("...%s", x)`), ошибки WinAPI — обязательно с
  `ctypes.get_last_error()`.
- **Тесты:** только чистая логика. WinAPI и аудио не покрываются намеренно — мокать их значит
  тестировать моки. Фикстуры не сложнее `tmp_path`/`monkeypatch`, `conftest.py` нет.
- **Фоновые потоки:** `daemon=True`, ожидание через `Event.wait(timeout)`, а не `time.sleep`,
  и обязательное `name=`.

---

## Типовые задачи

### Добавить параметр конфигурации
1. Поле в нужный dataclass в [whispertype/config.py](whispertype/config.py) с дефолтом.
2. Запись в `_FIELD_TYPES` — **иначе `KeyError` в `_type_ok`** при загрузке.
3. Диапазон — проверка в `_validate` с текстом предупреждения.
4. Тест на тип и на границы + строка в таблицу «Все параметры» в [README.md](README.md).

### Добавить пункт в меню трея
1. Метод/property в `App` — логика живёт там, не в `Tray`.
2. `MenuItem` в `Tray._build_menu` ([whispertype/tray.py](whispertype/tray.py)).
3. Настройку сохранять через `App._persist`, **не** `write_config` напрямую.
4. Пользовательский текст — через `menu_label` (экранирует `&`).

### Добавить вызов WinAPI
`argtypes`/`restype` обязательно (без них ctypes рвёт хендлы на x64), структуры объявлять явно,
ссылку на коллбэк хранить в атрибуте (иначе GC → падение), ошибку логировать с `GetLastError`,
асинхронные вызовы проверять опросом, а не по коду возврата.

---

## Осторожно

- **`pytest -q` падает с `ModuleNotFoundError`** → запускать `python -m pytest -q`: только он
  добавляет корень репозитория в `sys.path`. Уже ломало CI.
- **Хук-коллбэк (`hotkey._ll_proc`) не должен делать никакой работы** → только `queue.put`.
  Задержка → Windows снимает хук → лаги всей клавиатуры.
- **Не развязывать `without_timestamps=frames is not None`** ([whispertype/stt.py](whispertype/stt.py))
  → с таймкодами на узком окне модель дублирует текст.
- **`streaming.chunk_seconds` не выше 25 (`MAX_NARROW_SECONDS`)** → выше окно энкодера перестаёт
  сужаться, кусок идёт дорогим полным проходом, и `_finish()` виснет на `Transcriber._lock`.
  Константа продублирована литералом в `config.py:_validate` — менять в обоих местах.
- **`faster-whisper<2` в requirements не поднимать бездумно** → `adaptive_window` патчит
  внутреннюю `pad_or_trim`, не публичный API.
- **`.bat` только с CRLF** (закреплено в `.gitattributes`) → cmd.exe на LF ломает `if (...)` и `||`.
- **Читать `config.json`/`history.json` через `encoding="utf-8-sig"`** → Блокнот и PowerShell
  сохраняют с BOM, на которой `json.loads` падает.
- **Не менять `AppId` в `installer.iss`** и имя mutex'а `WhisperType.single-instance` (оно же
  `AppMutex`) → сломается обновление поверх.
- **При релизе версия правится в двух местах:** `whispertype/__init__.py` и `installer.iss`.
- **Правки в `inject.py`, `hotkey.py`, `overlay.py`, `audio.py`, `app.py` тестами не ловятся**
  (~62% кода) → проверять руками запуском.

---

## Данные на диске

`%APPDATA%\WhisperType\` — `config.json`, `history.json` (настройки пользователя).
`%LOCALAPPDATA%\WhisperType\` — `models\` (~1.6 ГБ), `logs\app.log` (5 × 2 МБ).
Переменных окружения проект не использует; вся конфигурация — в `config.json`.
