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

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton, QMessageBox, QAbstractItemView

from qanopy.core.session_manager import SessionManager


class DbcTreeWidget(QWidget):
    signal_double_clicked = pyqtSignal(str, str)  # signal_key, display_name
    merge_request = pyqtSignal(str, str, str, str)  # a_key,a_name,b_key,b_name
    session_selected = pyqtSignal(str)  # session_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Session > DBC > Node > Message > Signal"])
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setStyleSheet("QTreeWidget::item:selected { background-color: blue; color: white; }")

        self.btn_merge = QPushButton("Merge 2 Selected Signals (A-B)")
        self.btn_merge.clicked.connect(self._on_merge_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        layout.addWidget(self.btn_merge)
        self.setLayout(layout)

    def populate(self, sm: SessionManager) -> None:
        self.tree.clear()

        for sid, sess in sm.all_sessions().items():
            top = QTreeWidgetItem([sess.display_name])
            top.setData(0, Qt.ItemDataRole.UserRole, ("session", sid))

            dbc_keys = sess.dbcs.list_keys()
            if not dbc_keys:
                top.addChild(QTreeWidgetItem(["(No DBC loaded)"]))
                self.tree.addTopLevelItem(top)
                continue

            for dbc_key in dbc_keys:
                dbc_item = QTreeWidgetItem([dbc_key])
                dbc_item.setData(0, Qt.ItemDataRole.UserRole, ("dbc", sid, dbc_key))
                top.addChild(dbc_item)

                db = sess.dbcs.get_db(dbc_key)

                node_map = {n.name: QTreeWidgetItem([n.name]) for n in db.nodes}
                unspecified = QTreeWidgetItem(["UNSPECIFIED"])

                for item in node_map.values():
                    dbc_item.addChild(item)
                dbc_item.addChild(unspecified)

                for msg in db.messages:
                    parents = [unspecified] if not msg.senders else [node_map.get(s, unspecified) for s in msg.senders]

                    for parent in parents:
                        m_item = QTreeWidgetItem([f"{msg.name} (0x{msg.frame_id:X})"])
                        parent.addChild(m_item)

                        for sig in msg.signals:
                            s_item = QTreeWidgetItem([sig.name])
                            signal_key = f"{sid}:{dbc_key}:{msg.frame_id}:{sig.name}"
                            display_name = f"[{sess.display_name}] [{dbc_key}] {msg.name}.{sig.name}"
                            s_item.setData(0, Qt.ItemDataRole.UserRole, ("signal", signal_key, display_name))
                            m_item.addChild(s_item)

            self.tree.addTopLevelItem(top)

        self.tree.expandToDepth(2)

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return

        cur = items[0]
        while cur is not None:
            data = cur.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "session":
                self.session_selected.emit(data[1])
                return
            cur = cur.parent()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "signal":
            _, signal_key, display_name = data
            self.signal_double_clicked.emit(signal_key, display_name)

    def _get_selected_signals(self) -> list[tuple[str, str]]:
        out = []
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "signal":
                out.append((data[1], data[2]))
        return out

    def _on_merge_clicked(self) -> None:
        sigs = self._get_selected_signals()
        if len(sigs) != 2:
            QMessageBox.warning(self, "Merge", "Select exactly 2 signals to merge (A-B).")
            return
        (a_key, a_name), (b_key, b_name) = sigs
        self.merge_request.emit(a_key, a_name, b_key, b_name)
