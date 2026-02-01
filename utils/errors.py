"""
Copyright 2026 [Rishi Franklin]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

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
