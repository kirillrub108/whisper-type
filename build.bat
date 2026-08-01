@echo off
setlocal
cd /d "%~dp0"

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
