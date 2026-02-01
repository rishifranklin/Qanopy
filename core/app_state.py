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

import os
from typing import Optional

from PyQt6.QtCore import QSettings, QStandardPaths


class AppState:
    """
    Persistent application state using QSettings (Windows: registry).
    Current requirement: remember last directory used in file dialogs.
    """

    KEY_LAST_DIR = "ui/last_dir"

    def __init__(self) -> None:
        # explicit names so it’s stable regardless of QCoreApplication settings
        self._s = QSettings("Qanopy", "Qanopy")

    def get_last_dir(self) -> str:
        v = self._s.value(self.KEY_LAST_DIR, "")
        if isinstance(v, str) and v and os.path.isdir(v):
            return v

        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if isinstance(docs, str) and docs and os.path.isdir(docs):
            return docs

        return os.getcwd()

    def set_last_dir_from_path(self, path: str) -> None:
        if not path:
            return
        d = os.path.dirname(path)
        if d and os.path.isdir(d):
            self._s.setValue(self.KEY_LAST_DIR, d)

    def set_last_dir(self, directory: str) -> None:
        if directory and os.path.isdir(directory):
            self._s.setValue(self.KEY_LAST_DIR, directory)
