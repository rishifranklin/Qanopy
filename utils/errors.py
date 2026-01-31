from __future__ import annotations

import sys
import traceback
from typing import Callable, Optional

from PyQt6.QtWidgets import QMessageBox, QWidget


def notify_error(parent: Optional[QWidget], title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def install_qt_exception_hook(on_shutdown: Callable[[], None]) -> None:
    """
    Catch unhandled exceptions, show a dialog, attempt graceful shutdown.
    """

    def _hook(exc_type, exc_value, exc_tb):
        try:
            msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            try:
                on_shutdown()
            except Exception:
                pass
            QMessageBox.critical(None, "Unhandled Exception", msg[:6000])
        finally:
            sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
