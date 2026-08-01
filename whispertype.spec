# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller --clean --noconfirm whispertype.spec
from PyInstaller.utils.hooks import collect_data_files

# Ассеты faster-whisper (Silero VAD onnx и т.п.)
datas = collect_data_files("faster_whisper")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["pystray._win32"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tkinter", "matplotlib", "IPython", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WhisperType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
