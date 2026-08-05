# 08. Сборка, инсталлятор и релиз

## Локальная разработка

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python launcher.py
```

Требуется **именно Python 3.11**: более новые версии не поддерживаются PyInstaller в этой
сборке, и [build.bat](../build.bat) это явно проверяет.

Проверки перед коммитом:

```bash
python -m pytest -q
ruff check whispertype tests
mypy whispertype
```

Обратите внимание на `python -m pytest`, а **не** `pytest`. Только первый вариант добавляет
корень репозитория в `sys.path`, поэтому пакет `whispertype` находится как модуль. Прямой
вызов `pytest` падает с `ModuleNotFoundError` — на этом один раз упал CI (коммит `caa0b8e`).

---

## Сборка `.exe`

```bash
build.bat
```

Скрипт ([build.bat](../build.bat)) делает пять вещей:

1. Проверяет наличие лаунчера `py` и Python 3.11.
2. **Валидирует существующий `.venv`**, а не использует его вслепую:

   ```bat
   python -c "sys.exit(0 if version_info[:2]==(3,11) and 'WindowsApps' not in base_prefix else 1)"
   ```

   Причина: PyInstaller не умеет собирать из Python, установленного из Microsoft Store, а venv
   на чужой версии выглядит рабочим до самой сборки. Не прошёл проверку — окружение
   пересоздаётся.
3. Ставит зависимости.
4. `pyinstaller --clean --noconfirm whispertype.spec` → `dist\WhisperType\`
5. Если найден Inno Setup — компилирует инсталлятор → `dist_installer\WhisperTypeSetup.exe`.
   Не найден — сообщает, как поставить, и выходит с кодом 0 (сборка exe уже удалась).

### Требование CRLF для `.bat`

```
*.bat text eol=crlf     # .gitattributes
```

cmd.exe на LF-переводах ломает разбор блоков `if (...)` и оператора `||`, из-за чего сборка
падает на пустом месте с сообщениями вида `'ь' is not recognized` и
`|| was unexpected at this time`. Файл однажды попал в репозиторий с LF и был сломан у всех,
кто клонировал; `.gitattributes` теперь не даёт этому повториться.

### Спецификация PyInstaller

[whispertype.spec](../whispertype.spec):

| Параметр | Значение | Почему |
|---|---|---|
| entry point | `launcher.py` | вызывает `multiprocessing.freeze_support()` |
| `datas` | `collect_data_files("faster_whisper")` | ассеты, в т.ч. Silero VAD `.onnx` |
| `hiddenimports` | `pystray._win32` | бэкенд подгружается динамически, анализатор его не видит |
| `excludes` | `torch, tkinter, matplotlib, IPython, PyQt5, PySide6` | иначе в сборку попадут гигабайты ненужного |
| `console` | `False` | GUI-приложение без консольного окна |
| `upx` | `False` | UPX-упаковка резко повышает шанс срабатывания антивируса |
| режим | **`--onedir`** (`EXE` + `COLLECT`) | см. ниже |

**Почему `onedir`, а не `onefile`.** Самораспаковывающийся стаб `--onefile` ведёт себя как
упаковщики вредоносов и заметно чаще ловит эвристику антивирусов. Папку пользователь больше не
видит напрямую — она уходит внутрь инсталлятора, который остаётся привычным одним `.exe`
для скачивания.

---

## Инсталлятор

[installer.iss](../installer.iss), Inno Setup 6.

| Директива | Значение | Зачем |
|---|---|---|
| `AppId` | фиксированный GUID | по нему Windows опознаёт «то же приложение» при обновлении; **менять нельзя** |
| `DefaultDirName` | `{localappdata}\Programs\WhisperType` | пользовательский каталог |
| `PrivilegesRequired` | `lowest` | установка без прав администратора |
| `AppMutex` | `WhisperType.single-instance` | то же имя, что в [winutil.py](../whispertype/winutil.py) |
| `ArchitecturesAllowed` | `x64compatible` | только 64-битные системы |
| `Compression` | `lzma2/max` + `SolidCompression` | ~70 МБ итогового файла |
| `Languages` | русский + английский | |

**`AppMutex` — важная деталь.** Если приложение запущено, установка и удаление сначала
попросят его закрыть, а не упадут молча на заблокированных файлах.

### Автозагрузка

Инсталлятор включает её **по умолчанию** — задача `autostart` в `[Tasks]` отмечена, секция
`[Registry]` пишет `HKCU\...\Run\WhisperType`. Пользователь может снять галочку на странице
дополнительных задач или позже в меню трея.

Два требования к этой записи, нарушение любого ломает поведение молча:

1. **Формат значения должен совпадать с `autostart._command()`** — путь в кавычках
   (`"""{app}\WhisperType.exe"""` в синтаксисе Inno). Иначе `is_enabled()` не узнает свою
   запись и покажет «выключено» при включённой автозагрузке.
2. **Флаг `uninsdeletevalue`** — иначе после удаления программы в реестре останется запись,
   ведущая в никуда.

Вторая строка `[Registry]` с `Tasks: not autostart` и флагом `deletevalue` нужна для
повторной установки: без неё снятая галочка не убрала бы запись, оставшуюся от прошлого раза.

### Проверка инсталлятора при живом приложении

Если на машине разработчика запущена рабочая копия WhisperType, обычный smoke-тест
установки упрётся в `AppMutex` и остановится на диалоге. Приём, применявшийся при выпуске
релизов: скомпилировать одноразовую копию скрипта с другим `AppMutex` и
`OutputBaseFilename`, протестировать ей, затем удалить артефакты.

```bash
# тихая установка и удаление
WhisperTypeSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
"%LOCALAPPDATA%\Programs\WhisperType\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Что проверять после установки:

- `%LOCALAPPDATA%\Programs\WhisperType\WhisperType.exe` и `unins000.exe` на месте;
- в `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{AppId}_is1` версия верная;
- после удаления каталог и запись в реестре исчезли, а `%APPDATA%\WhisperType\config.json`
  и `history.json` **остались**.

---

## CI

[.github/workflows/build.yml](../.github/workflows/build.yml) — `windows-latest`, Python 3.11:

```
python -m pytest -q
ruff check whispertype tests
mypy whispertype
pyinstaller --clean --noconfirm whispertype.spec
choco install innosetup
ISCC installer.iss
upload-artifact: WhisperTypeSetup.exe
```

Триггеры: push в `master`, любой pull request, ручной запуск.

CI нужен не только для проверок: **публичный автоматический билд — одно из условий SignPath
Foundation** для бесплатной подписи кода (см. ниже).

---

## Выпуск релиза

Порядок, отработанный на версиях 1.1.0–1.1.2:

1. **Синхронизировать версию в двух местах** — их легко забыть:
   - [`whispertype/__init__.py`](../whispertype/__init__.py) → `__version__`
   - [`installer.iss`](../installer.iss) → `#define MyAppVersion`

   Первое видно в меню «О программе», второе — в «Установке и удалении программ».

2. Прогнать `python -m pytest -q`, `ruff`, `mypy`.
3. `build.bat` → получить `dist_installer\WhisperTypeSetup.exe`.
4. Smoke-тест установки/удаления (см. выше).
5. Коммит версии, `git tag -a vX.Y.Z`, push тега.
6. `gh release create vX.Y.Z dist_installer/WhisperTypeSetup.exe --title ... --notes ...`
7. Проверить, что `releases/latest` резолвится на новый тег — именно эта ссылка стоит в
   [README](../README.md).

---

## Предупреждения при скачивании

Три независимых механизма, которые часто путают:

| Механизм | Что показывает | Чем лечится |
|---|---|---|
| **Google Drive** | «файл слишком большой для проверки на вирусы» | не использовать — раздавать через GitHub Releases |
| **SmartScreen** | «неизвестный издатель» | только подпись кода (платный сертификат или SignPath) |
| **Антивирусы** | эвристика на PyInstaller-сборке | `onedir` вместо `onefile`, без UPX; подпись **не** помогает |

Важно: **подпись кода не убирает срабатывания стороннего антивируса** — она решает только
проблему SmartScreen.

### SignPath Foundation

Бесплатная подпись кода для open-source. Требования, которые репозиторий уже выполняет:

- OSI-одобренная лицензия — [LICENSE](../LICENSE), MIT;
- публичный репозиторий;
- публичный автоматизированный CI — GitHub Actions;
- отсутствие проприетарных компонентов.

Заявка подаётся вручную на signpath.org («Apply for Free Code Signing»); требуется, чтобы
страница загрузки упоминала использование SignPath Foundation. **На момент написания
документации заявка не подана и подпись не настроена.**

---

## Проверь себя

1. Почему в CI стоит `python -m pytest`, а не `pytest`?
   *(Ответ: только первый добавляет корень репозитория в `sys.path`; иначе
   `ModuleNotFoundError: No module named 'whispertype'`.)*
2. Что сломается, если поменять `AppId` в `installer.iss`?
   *(Ответ: Windows сочтёт это другим приложением — старая версия не обновится, а останется
   второй записью в списке программ.)*
3. Установщик запущен при работающей программе. Что произойдёт и почему?
   *(Ответ: `AppMutex` совпадает с mutex'ом приложения → инсталлятор попросит закрыть
   программу вместо падения на заблокированных файлах.)*
