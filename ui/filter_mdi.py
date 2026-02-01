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

from typing import Set

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMdiSubWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox
)

from ..core.session_manager import SessionManager


class FilterMdiSubWindow(QMdiSubWindow):
    def __init__(self, sessions: SessionManager) -> None:
        super().__init__()
        self.setWindowTitle("Message Filter")

        self.sessions = sessions

        root = QWidget()
        self.setWidget(root)
        layout = QVBoxLayout()
        root.setLayout(layout)

        top = QHBoxLayout()
        self.cmb_session = QComboBox()
        self.cmb_dbc = QComboBox()

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["exclude", "include"])

        self.chk_enable = QCheckBox("Enable filter")
        self.chk_affects_log = QCheckBox("Filter affects logging")

        top.addWidget(QLabel("Session"))
        top.addWidget(self.cmb_session, 2)
        top.addWidget(QLabel("DBC"))
        top.addWidget(self.cmb_dbc, 2)
        top.addWidget(QLabel("Mode"))
        top.addWidget(self.cmb_mode)
        top.addWidget(self.chk_enable)
        top.addWidget(self.chk_affects_log)
        top.addStretch(1)

        self.btn_all = QPushButton("Select All")
        self.btn_none = QPushButton("Select None")
        self.btn_apply = QPushButton("Apply")
        self.btn_refresh = QPushButton("Refresh")

        top.addWidget(self.btn_all)
        top.addWidget(self.btn_none)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_apply)

        layout.addLayout(top)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Use", "Message", "Frame ID"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tbl)

        self.btn_all.clicked.connect(lambda: self._set_all_checks(True))
        self.btn_none.clicked.connect(lambda: self._set_all_checks(False))
        self.btn_apply.clicked.connect(self._apply)
        self.btn_refresh.clicked.connect(self._reload_messages)
        self.cmb_session.currentIndexChanged.connect(self._reload_dbcs)
        self.cmb_dbc.currentIndexChanged.connect(self._reload_messages)

        self._reload_sessions()

    def _reload_sessions(self) -> None:
        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        for sid, sess in self.sessions.all_sessions().items():
            self.cmb_session.addItem(sess.display_name, userData=sid)
        self.cmb_session.blockSignals(False)
        self._reload_dbcs()

    def _get_session_id(self) -> str:
        sid = self.cmb_session.currentData()
        if not sid:
            raise RuntimeError("No session selected")
        return str(sid)

    def _get_dbc_key(self) -> str:
        k = self.cmb_dbc.currentData()
        if not k:
            # raise RuntimeError("No DBC selected")
            QMessageBox.information(self, "Filter", "Selected DBC no longer exists.")
            return None
        return str(k)

    def _reload_dbcs(self) -> None:
        self.cmb_dbc.blockSignals(True)
        self.cmb_dbc.clear()

        if self.cmb_session.count() == 0:
            self.cmb_dbc.blockSignals(False)
            self._reload_messages()
            return

        sid = self._get_session_id()
        sess = self.sessions.get(sid)

        keys = sess.dbcs.list_keys()
        for k in keys:
            self.cmb_dbc.addItem(k, userData=k)

        self.cmb_dbc.blockSignals(False)
        self._reload_messages()

    def _reload_messages(self) -> None:
        self.tbl.setRowCount(0)
        if self.cmb_session.count() == 0 or self.cmb_dbc.count() == 0:
            return

        try:
            sid = self._get_session_id()
            dbc_key = self._get_dbc_key()
            sess = self.sessions.get(sid)

            if sess == None:
                QMessageBox.information(self, "Filter", "Selected DBC no longer exists.")
                return

            if not sess.dbcs.has(dbc_key):
                QMessageBox.information(self, "Filter", "Selected DBC no longer exists.")
                return

            flt = sess.filters.get(dbc_key)
            snap = flt.snapshot()

            self.chk_enable.setChecked(snap.enabled)
            self.chk_affects_log.setChecked(snap.affects_logging)
            self.cmb_mode.setCurrentText(snap.mode)

            db = sess.dbcs.get_db(dbc_key)
            self.tbl.setRowCount(len(db.messages))

            for r, msg in enumerate(db.messages):
                frame_id = int(msg.frame_id)

                chk_item = QTableWidgetItem("")
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

                in_set = frame_id in snap.ids
                chk_item.setCheckState(Qt.CheckState.Checked if in_set else Qt.CheckState.Unchecked)

                name_item = QTableWidgetItem(msg.name)
                id_item = QTableWidgetItem(f"0x{frame_id:X}")
                id_item.setData(Qt.ItemDataRole.UserRole, frame_id)

                self.tbl.setItem(r, 0, chk_item)
                self.tbl.setItem(r, 1, name_item)
                self.tbl.setItem(r, 2, id_item)

        except Exception as e:
            QMessageBox.critical(self, "Filter Error", str(e))

    def _set_all_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it:
                it.setCheckState(state)

    def _apply(self) -> None:
        sid = self._get_session_id()
        dbc_key = self._get_dbc_key()
        sess = self.sessions.get(sid)

        if sess == None:
            QMessageBox.information(self, "Filter", "Selected DBC no longer exists.")
            return

        enabled = self.chk_enable.isChecked()
        mode = self.cmb_mode.currentText().strip().lower()
        affects_logging = self.chk_affects_log.isChecked()

        ids: Set[int] = set()
        for r in range(self.tbl.rowCount()):
            chk = self.tbl.item(r, 0)
            id_item = self.tbl.item(r, 2)
            if not chk or not id_item:
                continue
            frame_id = int(id_item.data(Qt.ItemDataRole.UserRole))
            if chk.checkState() == Qt.CheckState.Checked:
                ids.add(frame_id)

        try:
            sess.filters.get(dbc_key).configure(enabled=enabled, mode=mode, ids=ids, affects_logging=affects_logging)
        except Exception as e:
            QMessageBox.critical(self, "Apply Failed", str(e))
            return

        QMessageBox.information(self, "Filter", "Filter applied to selected DBC.")
