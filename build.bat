@echo off
setlocal
cd /d "%~dp0"

rem Существующее окружение проверяем, а не используем вслепую: PyInstaller не
rem умеет собирать из Python, установленного из Microsoft Store, а venv на
rem чужой версии выглядит рабочим до самой сборки.
if exist .venv (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) and 'WindowsApps' not in sys.base_prefix else 1)" 2>nul
    if errorlevel 1 (
        echo Окружение .venv не на обычном Python 3.11 — пересоздаю.
        rmdir /s /q .venv || goto :error
    )
)
if not exist .venv (
    py -3.11 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

python -m pip install --upgrade pip -q || goto :error
pip install -r requirements-dev.txt -q || goto :error

pyinstaller --clean --noconfirm whispertype.spec || goto :error

echo.
echo Готово: dist\WhisperType.exe
exit /b 0

:error
echo.
echo Сборка провалилась (код %errorlevel%).
exit /b %errorlevel%
