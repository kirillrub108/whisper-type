# 09. Соглашения и рецепты

## Стиль кода

Конфигурация — [pyproject.toml](../pyproject.toml):

```toml
[tool.ruff]
line-length = 105
target-version = "py311"
select = ["E", "F", "W", "I", "UP", "B"]

[tool.mypy]
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
```

### Обязательные правила

**1. `from __future__ import annotations` в каждом модуле.** Без исключений — проверьте любой
файл в `whispertype/`.

**2. Полная типизация.** Нетипизированного кода в проекте нет. Единственные два места с
`# noqa: ANN202` — генераторы пунктов меню для pystray
([tray.py:125,138](../whispertype/tray.py)), где тип возврата задаётся внешней библиотекой.

**3. Никаких TODO, закомментированного и мёртвого кода.** Проверено: маркеров
`TODO`/`FIXME`/`HACK`/`XXX` в репозитории нет ни одного.

**4. Комментарии — только там, где код неочевиден.** Это главное стилевое отличие проекта.
Комментарий объясняет **почему**, а не что:

```python
# Ссылку на callback держим в атрибуте: если её соберёт GC, хук упадёт.
self._proc = _HOOKPROC(self._ll_proc)
```

```python
# utf-8-sig, а не utf-8: Блокнот и PowerShell сохраняют файл с BOM,
# на которой json падает — и весь конфиг молча заменяется дефолтами.
```

Плотность комментариев резко разная по слоям, и это правильно: `textproc.py` почти не
комментирован (код говорит сам за себя), `inject.py` и `overlay.py` — плотно, потому что
каждый второй вызов WinAPI содержит неочевидную ловушку.

**5. Язык — русский.** Docstring'и, комментарии, сообщения логов, тексты уведомлений. Имена
идентификаторов — английские.

**6. Сообщения об ошибках WinAPI — с `GetLastError`:**

```python
log.error("SendInput отправил %d/%d, GetLastError=%d", sent, len(inputs), ctypes.get_last_error())
```

**7. Ленивое форматирование логов** (`log.info("...%s", value)`, а не f-строки) — стандартная
практика logging.

---

## Тесты

**Что покрывается:** только чистая логика без побочных эффектов.

| Файл | Тестов | Что проверяет |
|---|---:|---|
| [test_config.py](../tests/test_config.py) | 16 | загрузка, типы, диапазоны, BOM, автоподбор потоков |
| [test_stt_logic.py](../tests/test_stt_logic.py) | 19 | окно энкодера, нормализация, выбор языка |
| [test_textproc.py](../tests/test_textproc.py) | 19 | постобработка, галлюцинации, схлопывание, `menu_label` |
| [test_history.py](../tests/test_history.py) | 10 | добавление, лимит, персистентность, битые файлы |
| [test_audio_cut.py](../tests/test_audio_cut.py) | 6 | поиск точки разреза |
| [test_keys.py](../tests/test_keys.py) | 6 | разбор комбинаций хоткея |
| [test_inject_helpers.py](../tests/test_inject_helpers.py) | 6 | `utf16_units`, `batched` |
| **Итого** | **86** | |

**Что НЕ покрывается и почему:** WinAPI (хук, `SendInput`, буфер обмена, слоёное окно) и
захват звука. Их нельзя проверить без реального окружения — нужны настоящая клавиатура, окно
в фокусе и микрофон. Попытка мокать их дала бы тесты, проверяющие моки, а не код.

Практическое следствие: **изменения в `inject.py`, `hotkey.py`, `overlay.py`, `audio.py`
проверяются только руками.** Планируя правку там, закладывайте ручной прогон.

### Как писать новый тест

Тесты не используют фикстуры сложнее `tmp_path` и `monkeypatch`, `conftest.py` в проекте нет.
Образец:

```python
def test_cpu_threads_auto_leaves_cpus_free(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from whispertype import config as cfg_mod
    monkeypatch.setattr(cfg_mod.os, "cpu_count", lambda: 12)
    assert cfg_mod.resolve_cpu_threads(None) == 10
```

Запуск — **обязательно** через `python -m pytest -q` (см.
[08-build-release.md](08-build-release.md)).

---

## Рецепты

### Добавить параметр конфигурации

1. Поле в нужный dataclass в [config.py](../whispertype/config.py) с дефолтом.
2. Запись в `_FIELD_TYPES` — иначе `_type_ok` бросит `KeyError`.
3. При наличии диапазона — проверка в `_validate` с текстом предупреждения.
4. Использование в коде.
5. Тест на тип и на границы диапазона.
6. Строка в таблицу «Все параметры» в [README.md](../README.md).

Дефолт менять безопасно: он применяется только к отсутствующим в файле полям.

### Добавить пункт в меню трея

1. Метод (или property) в `App` — вся логика живёт там, не в `Tray`.
2. `MenuItem` в `Tray._build_menu` ([tray.py:82](../whispertype/tray.py)).
3. Для чекбокса — `checked=lambda item: app.<property>`; для радиогруппы — плюс `radio=True`.
4. Если пункт меняет настройку — сохранять через `App._persist`, а не `write_config` напрямую.

Динамические подменю делаются генератором: `MenuItem("Название", Menu(self._items))`, где
`_items` — метод-генератор. pystray переоценивает его при каждом открытии.

**Текст, приходящий от пользователя, пропускать через `menu_label`** — иначе амперсанд
превратится в подчёркивание.

### Добавить состояние иконки

1. Цвет в `_STATE_COLORS` и подпись в `_STATE_LABELS` ([tray.py:23-36](../whispertype/tray.py)).
2. `_make_image` при необходимости — особая отрисовка.

Изображения создаются один раз в конструкторе `Tray`, так что новое состояние подхватится
автоматически.

### Добавить вызов WinAPI

Чек-лист в [05-winapi.md](05-winapi.md#чек-лист-при-добавлении-winapi-вызова). Коротко:
`argtypes`/`restype` обязательно, структуры явно, хендлы правильных типов, ссылки на коллбэки
хранить, ошибки логировать с `GetLastError`, асинхронные вызовы проверять опросом.

### Добавить фоновый поток

Шаблон, принятый в проекте:

```python
threading.Thread(target=self._loop, name="имя", daemon=True).start()

def _loop(self) -> None:
    while not self._shutdown.wait(интервал):
        ...
```

`daemon=True` — обязательно, иначе процесс не завершится. Ожидание через `Event.wait(timeout)`,
а не `time.sleep` — так поток мгновенно реагирует на завершение. Имя потока обязательно: оно
попадает в каждую строку лога.

### Добавить событие хоткея

1. Новая строка-событие кладётся в `App._events`.
2. Ветка в `App._handle` ([app.py:153](../whispertype/app.py)).
3. Если событие приходит из хука — обработка в `_ll_proc`, но **только `queue.put`**, без
   какой-либо работы.

---

## Чего не ломать

| Инвариант | Почему |
|---|---|
| `AppId` в `installer.iss` | Windows перестанет узнавать приложение при обновлении |
| Имя mutex'а `WhisperType.single-instance` | оно же в `AppMutex` инсталлятора — рассинхрон сломает установку поверх |
| `*.bat text eol=crlf` в `.gitattributes` | cmd.exe ломается на LF |
| `faster-whisper<2` в requirements | `adaptive_window` патчит внутреннюю `pad_or_trim`, не публичный API |
| `without_timestamps=frames is not None` | развязка приведёт к дублям текста |
| `chunk_seconds` ≤ `MAX_NARROW_SECONDS` | иначе куски проваливаются в дорогой путь |
| `sizeof(INPUT) == 40` на x64 | `SendInput` молча перестанет работать |
| Хук-коллбэк без тяжёлой работы | Windows снимет хук, клавиатура начнёт лагать |
| Версия в двух местах при релизе | `__init__.py` и `installer.iss` |

---

## Проверь себя

1. Вы добавили поле в `AudioConfig`, но забыли `_FIELD_TYPES`. Что произойдёт?
   *(Ответ: `KeyError` в `_type_ok` при загрузке конфига, где это поле присутствует.)*
2. Почему в проекте нет тестов на `inject.py` целиком, хотя это самый большой модуль?
   *(Ответ: WinAPI нельзя проверить без реального окна в фокусе; покрыты только чистые
   хелперы `utf16_units` и `batched`.)*
3. Что не так с `while True: time.sleep(1)` в фоновом потоке этого проекта?
   *(Ответ: не реагирует на `_shutdown`; принятый шаблон — `while not self._shutdown.wait(1)`.)*
