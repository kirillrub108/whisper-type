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

# onedir, а не onefile: самораспаковывающийся стаб --onefile ведёт себя как
# упаковщики вредоносов и заметно чаще ловит эвристику антивирусов. Папку
# пользователь больше не увидит напрямую — она уходит внутрь инсталлятора
# (installer.iss), который остаётся привычным одним .exe для скачивания.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WhisperType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WhisperType",
)
