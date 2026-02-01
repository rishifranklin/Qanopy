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

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QDockWidget,
    QMdiArea,
    QMessageBox,
    QStatusBar,
)

from qanopy.core.datastore import DataStore
from qanopy.core.session_manager import SessionManager
from qanopy.utils.errors import notify_error
from qanopy.ui.connect_dialog import ConnectDialog
from qanopy.ui.dbc_tree import DbcTreeWidget
from qanopy.ui.filter_mdi import FilterMdiSubWindow
from qanopy.ui.log_mdi import LogMdiSubWindow
from qanopy.ui.plot_mdi import PlotMdiSubWindow
from qanopy.ui.tx_mdi import TxMdiSubWindow
from qanopy.ui.trace_mdi import TraceMdiSubWindow
from qanopy.core.app_state import AppState

import os

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Qanopy")
        self.resize(1400, 900)

        self.mdi = QMdiArea()
        self.setCentralWidget(self.mdi)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.datastore = DataStore(max_points_per_signal=80000)
        self.sessions = SessionManager(
            datastore=self.datastore,
            on_error=lambda title, msg: notify_error(self, title, msg),
            on_status=lambda msg: self.status.showMessage(msg, 5000),
        )

        self.selected_session_id: Optional[str] = None

        # Tree dock
        self.dbc_tree = DbcTreeWidget()
        self.dbc_tree.signal_double_clicked.connect(self.on_signal_double_clicked)
        self.dbc_tree.merge_request.connect(self.on_merge_request)
        self.dbc_tree.session_selected.connect(self._on_session_selected)

        dock = QDockWidget("Sessions / DBC Browser", self)
        dock.setWidget(self.dbc_tree)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self._plot_window: Optional[PlotMdiSubWindow] = None

        self._build_actions()
        self._build_menu()
        self._refresh_tree()

        self.app_state = AppState()

    def _build_actions(self) -> None:
        self.act_add_session = QAction("Add Session...", self)
        self.act_add_session.triggered.connect(self.on_add_session)

        self.act_disconnect_session = QAction("Disconnect Session", self)
        self.act_disconnect_session.triggered.connect(self.on_disconnect_session)

        self.act_remove_session = QAction("Remove Session", self)
        self.act_remove_session.triggered.connect(self.on_remove_session)

        self.act_add_dbc_to_session = QAction("Add DBC to Session...", self)
        self.act_add_dbc_to_session.triggered.connect(self.on_add_dbc_to_session)

        self.act_start_logging = QAction("Start Logging for Session...", self)
        self.act_start_logging.triggered.connect(self.on_start_logging_for_session)

        self.act_stop_logging = QAction("Stop Logging for Session", self)
        self.act_stop_logging.triggered.connect(self.on_stop_logging_for_session)

        self.act_open_log_view = QAction("Open Log Viewer (Session)", self)
        self.act_open_log_view.triggered.connect(self.on_open_log_view_for_session)

        self.act_open_filter = QAction("Open Filter Window", self)
        self.act_open_filter.triggered.connect(self.on_open_filter)

        self.act_open_tx = QAction("Open Transmit Window", self)
        self.act_open_tx.triggered.connect(self.on_open_tx)

        self.act_open_trace = QAction("Open Trace Window", self)
        self.act_open_trace.triggered.connect(self.on_open_trace)

        self.act_exit = QAction("Exit", self)
        self.act_exit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        menu = self.menuBar()

        m_file = menu.addMenu("File")
        m_file.addAction(self.act_exit)

        m_session = menu.addMenu("Session")
        m_session.addAction(self.act_add_session)
        m_session.addAction(self.act_add_dbc_to_session)
        m_session.addSeparator()
        m_session.addAction(self.act_disconnect_session)
        m_session.addAction(self.act_remove_session)

        m_log = menu.addMenu("Logging")
        m_log.addAction(self.act_start_logging)
        m_log.addAction(self.act_stop_logging)
        m_log.addSeparator()
        m_log.addAction(self.act_open_log_view)

        m_tools = menu.addMenu("Tools")
        m_tools.addAction(self.act_open_filter)
        m_tools.addAction(self.act_open_tx)
        m_tools.addAction(self.act_open_trace)

    def _on_session_selected(self, session_id: str) -> None:
        self.selected_session_id = session_id

    def _refresh_tree(self) -> None:
        self.dbc_tree.populate(self.sessions)

    def on_add_session(self) -> None:
        start_dir = self.app_state.get_last_dir()

        # Pass start_dir into dialog (new arg)
        dlg = ConnectDialog(self, initial_dir=start_dir)

        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        # Persist the last directory used inside ConnectDialog (if it browsed any file)
        try:
            last_dir = dlg.get_last_dir_used()
            if last_dir:
                self.app_state.set_last_dir(last_dir)
        except Exception:
            pass

        req = dlg.get_request()
        try:
            sid = self.sessions.create_session(req)
            if sid == None:
                QMessageBox.warning(self, "Session", "Session already exists. Select a different name.")
                return

            self.sessions.connect(sid)
        except Exception as e:
            notify_error(self, "Session Add Failed", str(e))
            return

        self._refresh_tree()

    def _require_selected_session(self) -> Optional[str]:
        if not self.selected_session_id:
            QMessageBox.warning(self, "Session", "Select a session first (click its name in the tree).")
            return None
        return self.selected_session_id

    def on_add_dbc_to_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return

        start_dir = self.app_state.get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add DBC",
            start_dir,
            "DBC Files (*.dbc);;All Files (*.*)",
        )
        if not path:
            return

        self.app_state.set_last_dir_from_path(path)

        try:
            sess = self.sessions.get(sid)
            sess.add_dbc(path)
        except Exception as e:
            notify_error(self, "Add DBC Failed", str(e))
            return

        self._refresh_tree()

    def on_disconnect_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return
        try:
            self.sessions.disconnect(sid)
        except Exception as e:
            notify_error(self, "Disconnect Failed", str(e))
        self._refresh_tree()

    def on_remove_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return
        self.sessions.remove_session(sid)
        if self.selected_session_id == sid:
            self.selected_session_id = None
        self._refresh_tree()

        QMessageBox.warning(self, "Session", "Session closed. Close all open windows.")


    def _ensure_plot_window(self) -> PlotMdiSubWindow:
        if self._plot_window is None or self._plot_window.isHidden():
            self._plot_window = PlotMdiSubWindow(self.datastore, self.sessions)  # <-- changed
            self.mdi.addSubWindow(self._plot_window)
            self._plot_window.show()
        else:
            self._plot_window.setFocus()
        return self._plot_window

    def on_signal_double_clicked(self, signal_key: str, display_name: str) -> None:
        w = self._ensure_plot_window()
        w.add_signal(signal_key, display_name)

    def on_merge_request(self, a_key: str, a_name: str, b_key: str, b_name: str) -> None:
        w = self._ensure_plot_window()
        w.add_derived_difference(a_key, a_name, b_key, b_name)

    def on_start_logging_for_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return

        start_dir = self.app_state.get_last_dir()
        default_path = os.path.join(start_dir, "pycan_log.csv")

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Start Logging",
            default_path,
            "CSV (*.csv);;Vector ASCII (*.asc);;Vector BLF (*.blf);;All Files (*.*)",
        )
        if not path:
            return

        # If user omitted extension, infer from selected filter
        if "." not in os.path.basename(path):
            if "(*.asc)" in selected_filter:
                path += ".asc"
            elif "(*.blf)" in selected_filter:
                path += ".blf"
            else:
                path += ".csv"

        self.app_state.set_last_dir_from_path(path)

        try:
            self.sessions.get(sid).logger.start(path)
        except Exception as e:
            notify_error(self, "Logging Failed", str(e))

    def on_stop_logging_for_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return
        try:
            self.sessions.get(sid).logger.stop()
        except Exception as e:
            notify_error(self, "Stop Logging Failed", str(e))

    def on_open_log_view_for_session(self) -> None:
        sid = self._require_selected_session()
        if not sid:
            return
        sess = self.sessions.get(sid)
        w = LogMdiSubWindow(sess.logger)
        w.setWindowTitle(f"Log Viewer - {sess.display_name}")
        self.mdi.addSubWindow(w)
        w.show()

    def on_open_filter(self) -> None:
        # do not open window unless a session is active
        if len(self.sessions.all_sessions()) == 0:
            QMessageBox.warning(self, "Session", "No active session.")
            return None

        w = FilterMdiSubWindow(self.sessions)
        self.mdi.addSubWindow(w)
        w.show()

    def on_open_tx(self) -> None:
        w = TxMdiSubWindow(self.sessions)
        self.mdi.addSubWindow(w)
        w.show()

    def on_open_trace(self) -> None:
        w = TraceMdiSubWindow(self.sessions)
        self.mdi.addSubWindow(w)
        w.show()

    def closeEvent(self, event) -> None:
        self.safe_shutdown()
        super().closeEvent(event)

    def safe_shutdown(self) -> None:
        try:
            self.sessions.shutdown_all()
        except Exception:
            pass
