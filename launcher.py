"""Точка входа: запуск из исходников и entry script для PyInstaller."""

from __future__ import annotations

import multiprocessing
import sys

from whispertype.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
