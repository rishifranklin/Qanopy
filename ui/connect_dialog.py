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

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout,
    QLineEdit, QComboBox, QSpinBox, QPushButton, QFileDialog, QHBoxLayout
)

from qanopy.core.can_session import CanConfig
from qanopy.core.session_manager import SessionCreateRequest
from qanopy.core.session_manager import SessionManager

import os

class ConnectDialog(QDialog):
    def __init__(self, parent=None, initial_dir: str = "") -> None:
        super().__init__(parent)
        self._last_dir_used = str(initial_dir) if initial_dir else ""
        self.setWindowTitle("Add CAN Session")
        self.setFixedSize(400, 300)

        self.ed_name = QLineEdit("Session-1")

        self.cmb_interface = QComboBox()
        self.cmb_interface.addItems(["pcan", "vector", "ixxat", "slcan", "gs_usb", "kvaser", "socketcan"])
        self.cmb_interface.setCurrentIndex(1)
        self.ed_channel = QLineEdit("0")

        self.sp_bitrate = QSpinBox()
        self.sp_bitrate.setRange(10000, 2000000)
        self.sp_bitrate.setValue(500000)

        self.cmb_fd = QComboBox()
        self.cmb_fd.addItems(["Classic CAN", "CAN-FD"])

        self.sp_data_bitrate = QSpinBox()
        self.sp_data_bitrate.setRange(10000, 8000000)
        self.sp_data_bitrate.setValue(2000000)

        self.ed_dbc = QLineEdit("")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_dbc)

        dbc_row = QHBoxLayout()
        dbc_row.addWidget(self.ed_dbc)
        dbc_row.addWidget(self.btn_browse)

        form = QFormLayout()
        form.addRow("Session name", self.ed_name)
        form.addRow("Interface", self.cmb_interface)
        form.addRow("Channel", self.ed_channel)
        form.addRow("Bitrate", self.sp_bitrate)
        form.addRow("Mode", self.cmb_fd)
        form.addRow("Data bitrate (FD)", self.sp_data_bitrate)
        form.addRow("Initial DBC (optional)", dbc_row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def _browse_dbc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DBC",
            self._last_dir_used,
            "DBC Files (*.dbc);;All Files (*.*)"
        )
        if not path:
            return

        # Update last dir used
        self._last_dir_used = os.path.dirname(path)

        # Continue your existing logic: set UI field / add dbc to list etc.
        self.ed_dbc.setText(path)

    def get_request(self) -> SessionCreateRequest:
        is_fd = (self.cmb_fd.currentText() == "CAN-FD")
        cfg = CanConfig(
            interface=self.cmb_interface.currentText().strip(),
            channel=self.ed_channel.text().strip(),
            bitrate=int(self.sp_bitrate.value()),
            fd=is_fd,
            data_bitrate=int(self.sp_data_bitrate.value()),
        )
        dbc_path = self.ed_dbc.text().strip() or None
        name = self.ed_name.text().strip() or f"{cfg.interface}:{cfg.channel}"
        return SessionCreateRequest(display_name=name, can_cfg=cfg, dbc_path=dbc_path)

    def get_last_dir_used(self) -> str:
        return self._last_dir_used
