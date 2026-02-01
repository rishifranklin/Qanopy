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

from typing import Dict, Optional, Tuple, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QMdiSubWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QCheckBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from qanopy.core.session_manager import SessionManager
from qanopy.core.trace_buffer import TraceFrame


class TraceMdiSubWindow(QMdiSubWindow):
    """
    Trace Window (MDI):
      - Mode A: All Frames (append every frame)
      - Mode B: Live (one row per message ID; update existing row instead of appending)

    Expand a frame row to show decoded signals:
      - Physical/scaled value + unit
      - Raw/unscaled value
    Shows delta-time (Δt) per message ID (time since last reception of same arbitration_id)

    NEW:
      - Apply DBC filter (same filter bank used elsewhere) to Trace display
      - Show CAN/bus errors in Trace mixed with messages (red font) if TraceFrame provides error fields
    """

    COL_TIME = 0
    COL_SOF = 1
    COL_DT = 2
    COL_CHN = 3
    COL_ID = 4
    COL_NAME = 5
    COL_DIR = 6
    COL_DLC = 7
    COL_DATA = 8
    COL_VALUE = 9
    COL_UNIT = 10
    COL_RAW = 11
    COL_DBC = 12

    def __init__(self, sessions: SessionManager) -> None:
        super().__init__()
        self.setWindowTitle("Trace")

        self.sessions = sessions
        self._last_seq: int = 0
        self._paused = False

        # Live mode: one row per (ID + ext + dir)
        self._live_mode = False
        self._row_by_key: Dict[Tuple[int, bool, str], QTreeWidgetItem] = {}

        # NEW: apply DBC filters in Trace window
        self._apply_filters = True

        # Styling
        self._err_brush = QBrush(QColor(255, 0, 0))

        root = QWidget()
        self.setWidget(root)

        layout = QVBoxLayout()
        root.setLayout(layout)

        top = QHBoxLayout()
        self.cmb_session = QComboBox()

        self.chk_pause = QCheckBox("Pause")
        self.chk_live = QCheckBox("List Once (Live Update)")
        self.chk_update_expanded = QCheckBox("Auto-update expanded decode")
        self.chk_update_expanded.setChecked(True)

        # NEW: Apply filter checkbox
        self.chk_apply_filter = QCheckBox("Apply DBC Filter")
        self.chk_apply_filter.setChecked(True)

        self.btn_clear = QPushButton("Clear")
        self.btn_refresh = QPushButton("Refresh Sessions")

        top.addWidget(QLabel("Session"))
        top.addWidget(self.cmb_session, 2)
        top.addWidget(self.chk_pause)
        top.addWidget(self.chk_live)
        top.addWidget(self.chk_update_expanded)
        top.addWidget(self.chk_apply_filter)
        top.addWidget(self.btn_clear)
        top.addWidget(self.btn_refresh)
        top.addStretch(1)
        layout.addLayout(top)

        headers = [
            "Time",
            "Start of Frame",
            "Δt (ms)",
            "Chn",
            "ID",
            "Name",
            "Dir",
            "DLC",
            "Data",
            "Value",
            "Unit",
            "Raw",
            "DBC",
        ]

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(headers))
        self.tree.setHeaderLabels(headers)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setStyleSheet("QTreeWidget::item:selected { background-color: blue; color: white; }")
        self.tree.itemExpanded.connect(self._on_item_expanded)
        layout.addWidget(self.tree)

        self.chk_pause.stateChanged.connect(self._on_pause)
        self.chk_live.stateChanged.connect(self._on_live_mode_changed)
        self.chk_apply_filter.stateChanged.connect(self._on_apply_filter_changed)

        self.btn_clear.clicked.connect(self._clear)
        self.btn_refresh.clicked.connect(self._reload_sessions)
        self.cmb_session.currentIndexChanged.connect(self._on_session_changed)

        self._reload_sessions()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pump)
        self._timer.start(50)

    # UI state
    def _reload_sessions(self) -> None:
        cur = self.cmb_session.currentData()

        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        for sid, sess in self.sessions.all_sessions().items():
            self.cmb_session.addItem(sess.display_name, userData=sid)
        self.cmb_session.blockSignals(False)

        if cur is not None:
            idx = self.cmb_session.findData(cur)
            if idx >= 0:
                self.cmb_session.setCurrentIndex(idx)

        self._on_session_changed()

    def _get_selected_session_id(self) -> Optional[str]:
        sid = self.cmb_session.currentData()
        if not sid:
            return None
        return str(sid)

    def _on_pause(self) -> None:
        self._paused = self.chk_pause.isChecked()

    def _on_live_mode_changed(self) -> None:
        self._live_mode = self.chk_live.isChecked()
        # Reset view and per-row map when switching modes
        self.tree.clear()
        self._row_by_key.clear()
        self._last_seq = 0

    def _on_apply_filter_changed(self) -> None:
        self._apply_filters = self.chk_apply_filter.isChecked()
        # We do not retroactively remove existing rows; filtering applies to new incoming frames.
        # User can Clear if they want a clean filtered view.

    def _clear(self) -> None:
        self.tree.clear()
        self._row_by_key.clear()
        self._last_seq = 0

        sid = self._get_selected_session_id()
        if sid:
            try:
                self.sessions.get(sid).trace.clear()
            except Exception:
                pass

    def _on_session_changed(self) -> None:
        # reset view for new session
        self.tree.clear()
        self._row_by_key.clear()
        self._last_seq = 0

    # formatting helpers
    def _fmt_hex_bytes(self, b: bytes) -> str:
        return " ".join(f"{x:02X}" for x in b)

    def _fmt_dt_ms(self, delta_s: Optional[float]) -> str:
        if delta_s is None:
            return ""
        return f"{(delta_s * 1000.0):.3f}"

    def _apply_error_style(self, it: QTreeWidgetItem) -> None:
        for c in range(self.tree.columnCount()):
            it.setForeground(c, self._err_brush)

    def _is_error_frame(self, f: TraceFrame) -> bool:
        # Backward compatible: only true if producer sets it
        return bool(getattr(f, "is_error", False))

    def _error_text(self, f: TraceFrame) -> str:
        return str(getattr(f, "error_text", "") or "")

    # filtering

    def _trace_filter_allows(self, sess: Any, f: TraceFrame) -> bool:
        """
        Apply the session's per-DBC filter to Trace display.

        Rules:
          - Errors always pass (so you never miss bus faults)
          - If no dbc_key: pass
          - If no filter bank: pass
          - Otherwise: consult the DBC filter for this dbc_key and ask if the message id is allowed.
        """
        if self._is_error_frame(f):
            return True

        dbc_key = getattr(f, "dbc_key", None)
        if not dbc_key:
            return True

        # Find the session's filter bank (common attribute names)
        bank = None
        for attr in ("filters", "filter_bank", "filters_bank", "can_filters"):
            bank = getattr(sess, attr, None)
            if bank is not None:
                break
        if bank is None:
            return True

        # Get the per-dbc filter
        flt = None
        try:
            if hasattr(bank, "get") and callable(getattr(bank, "get")):
                flt = bank.get(str(dbc_key))
            elif isinstance(bank, dict):
                flt = bank.get(str(dbc_key))
        except Exception:
            flt = None

        if flt is None:
            return True

        arb_id = int(getattr(f, "arbitration_id", 0))

        # Common allow method names
        for fn_name in ("allows", "is_allowed", "allow", "matches", "permits"):
            fn = getattr(flt, fn_name, None)
            if callable(fn):
                try:
                    return bool(fn(arb_id))
                except Exception:
                    return True

        # Common "allowed ids" container names
        for attr in ("allowed_ids", "ids", "whitelist"):
            ids = getattr(flt, attr, None)
            if ids is not None:
                try:
                    return arb_id in set(ids)
                except Exception:
                    return True

        return True

    # pumping data
    def _pump(self) -> None:
        if self._paused:
            return

        sid = self._get_selected_session_id()
        if not sid:
            return

        sess = self.sessions.get(sid)
        if sess is None:
            return

        frames = sess.trace.get_since(self._last_seq)
        if not frames:
            return

        self.tree.setUpdatesEnabled(False)
        try:
            for f in frames:
                self._last_seq = max(self._last_seq, f.seq)

                # NEW: Apply filter to Trace display
                if self._apply_filters and (not self._trace_filter_allows(sess, f)):
                    continue

                if self._live_mode:
                    self._upsert_live_row(str(sid), f)
                else:
                    self._append_frame_row(str(sid), f)
        finally:
            self.tree.setUpdatesEnabled(True)

        # safety limits (only relevant for All Frames mode)
        if not self._live_mode:
            MAX_ROWS = 5000
            while self.tree.topLevelItemCount() > MAX_ROWS:
                self.tree.takeTopLevelItem(0)

    # All Frames mode
    def _append_frame_row(self, session_id: str, f: TraceFrame) -> None:
        it = QTreeWidgetItem()
        self._set_frame_row_text(it, f)

        it.setData(0, Qt.ItemDataRole.UserRole, ("frame", session_id, f))
        it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

        if self._is_error_frame(f):
            self._apply_error_style(it)

        self.tree.addTopLevelItem(it)

    # Live mode (one row per ID)
    def _make_live_key(self, f: TraceFrame) -> Tuple[int, bool, str]:
        # key = (arbitration_id, is_extended, direction)
        return (int(f.arbitration_id), bool(f.is_extended), str(f.direction))

    def _upsert_live_row(self, session_id: str, f: TraceFrame) -> None:
        key = self._make_live_key(f)
        existing = self._row_by_key.get(key)

        if existing is None:
            it = QTreeWidgetItem()
            self._set_frame_row_text(it, f)

            it.setData(0, Qt.ItemDataRole.UserRole, ("frame", session_id, f))
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

            if self._is_error_frame(f):
                self._apply_error_style(it)

            self._insert_sorted_by_id(it, f)
            self._row_by_key[key] = it
            return

        # Update the existing row instead of appending
        self._set_frame_row_text(existing, f)
        existing.setData(0, Qt.ItemDataRole.UserRole, ("frame", session_id, f))

        if self._is_error_frame(f):
            self._apply_error_style(existing)
        else:
            # Note: do not "un-red" here; if you want that, reset foregrounds on non-error.
            pass

        # If the row is expanded and auto-update is enabled, refresh decode
        if self.chk_update_expanded.isChecked():
            try:
                expanded = self.tree.isExpanded(self.tree.indexFromItem(existing))
            except Exception:
                expanded = False

            if existing.childCount() > 0 and expanded:
                if self._is_error_frame(f):
                    self._update_error_child(existing, f)
                else:
                    self._update_existing_children(session_id, existing, f)

    def _insert_sorted_by_id(self, it: QTreeWidgetItem, f: TraceFrame) -> None:
        # Keep top-level rows sorted by arbitration ID, then ext flag, then direction
        target_id = int(f.arbitration_id)
        target_ext = bool(f.is_extended)
        target_dir = str(f.direction)

        n = self.tree.topLevelItemCount()
        insert_at = n

        for i in range(n):
            cur = self.tree.topLevelItem(i)
            data = cur.data(0, Qt.ItemDataRole.UserRole)
            if not data or data[0] != "frame":
                continue
            _tag, _sid, cf = data

            cid = int(cf.arbitration_id)
            cext = bool(cf.is_extended)
            cdir = str(cf.direction)

            if (target_id, target_ext, target_dir) < (cid, cext, cdir):
                insert_at = i
                break

        self.tree.insertTopLevelItem(insert_at, it)

    # Row update helpers
    def _set_frame_row_text(self, it: QTreeWidgetItem, f: TraceFrame) -> None:
        dt_ms = self._fmt_dt_ms(getattr(f, "delta_s", None))

        # Errors: show like normal frames, but ID/Name/Data carry error information
        if self._is_error_frame(f):
            name = getattr(f, "msg_name", None) or "BUS_ERROR"
            dbc = getattr(f, "dbc_key", None) or ""
            info = self._error_text(f)

            it.setText(self.COL_TIME, f"{float(getattr(f, 'time_s', 0.0)):.6f}")
            it.setText(self.COL_SOF, f"{float(getattr(f, 'sof_s', 0.0)):.6f}")
            it.setText(self.COL_DT, dt_ms)
            it.setText(self.COL_CHN, str(getattr(f, "channel", "")))
            it.setText(self.COL_ID, "ERR")
            it.setText(self.COL_NAME, str(name))
            it.setText(self.COL_DIR, str(getattr(f, "direction", "Rx")))
            it.setText(self.COL_DLC, "")
            it.setText(self.COL_DATA, info)
            it.setText(self.COL_VALUE, "")
            it.setText(self.COL_UNIT, "")
            it.setText(self.COL_RAW, "")
            it.setText(self.COL_DBC, str(dbc))
            return

        name = f.msg_name if f.msg_name else "(Unknown)"
        dbc = f.dbc_key if f.dbc_key else ""

        dlc = int(f.dlc)
        data_hex = self._fmt_hex_bytes(f.data)

        it.setText(self.COL_TIME, f"{f.time_s:.6f}")
        it.setText(self.COL_SOF, f"{f.sof_s:.6f}")
        it.setText(self.COL_DT, dt_ms)
        it.setText(self.COL_CHN, f.channel)
        it.setText(self.COL_ID, f"0x{int(f.arbitration_id):X}")
        it.setText(self.COL_NAME, name)
        it.setText(self.COL_DIR, f.direction)
        it.setText(self.COL_DLC, str(dlc))
        it.setText(self.COL_DATA, data_hex)
        it.setText(self.COL_VALUE, "")
        it.setText(self.COL_UNIT, "")
        it.setText(self.COL_RAW, "")
        it.setText(self.COL_DBC, dbc)

    # Expansion decode
    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        # Lazy populate children on first expand
        if item.childCount() > 0:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "frame":
            return

        _tag, sid, frame = data
        if self._is_error_frame(frame):
            self._populate_error_child(item, frame)
        else:
            self._populate_children(str(sid), item, frame)

    def _populate_error_child(self, item: QTreeWidgetItem, frame: TraceFrame) -> None:
        txt = self._error_text(frame)
        if not txt:
            txt = "(Error)"
        child = QTreeWidgetItem(["", "", "", "", "", f"(Error) {txt}", "", "", "", "", "", "", ""])
        item.addChild(child)
        self._apply_error_style(child)

    def _update_error_child(self, item: QTreeWidgetItem, frame: TraceFrame) -> None:
        # Update existing child (if present) with latest error text
        if item.childCount() == 0:
            self._populate_error_child(item, frame)
            return
        txt = self._error_text(frame)
        if not txt:
            txt = "(Error)"
        ch = item.child(0)
        ch.setText(self.COL_NAME, f"(Error) {txt}")
        self._apply_error_style(ch)

    def _populate_children(self, session_id: str, item: QTreeWidgetItem, frame: TraceFrame) -> None:
        sess = self.sessions.get(session_id)

        if frame.dbc_key is None:
            child = QTreeWidgetItem(["", "", "", "", "", "(No DBC match)", "", "", "", "", "", "", ""])
            item.addChild(child)
            return

        try:
            db = sess.dbcs.get_db(frame.dbc_key)
            msg = db.get_message_by_frame_id(int(frame.arbitration_id))

            phys = msg.decode(frame.data, decode_choices=True, scaling=True)
            raw = msg.decode(frame.data, decode_choices=False, scaling=False)

            for sig in msg.signals:
                sname = sig.name
                unit = sig.unit or ""

                v_phys = phys.get(sname)
                v_raw = raw.get(sname)

                if isinstance(v_phys, float):
                    v_phys_str = f"{v_phys:.3f}"
                else:
                    v_phys_str = "" if v_phys is None else str(v_phys)

                raw_dec = ""
                raw_hex = ""
                if isinstance(v_raw, int):
                    raw_dec = str(v_raw)
                    raw_hex = f"0x{v_raw:X}" if v_raw >= 0 else str(v_raw)
                else:
                    raw_dec = "" if v_raw is None else str(v_raw)
                    raw_hex = raw_dec

                child = QTreeWidgetItem([
                    "", "", "", "", "",
                    sname, "", "",
                    raw_hex,
                    v_phys_str,
                    unit,
                    raw_dec,
                    frame.dbc_key,
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, ("sig", sname))
                item.addChild(child)

        except Exception as e:
            child = QTreeWidgetItem(["", "", "", "", "", f"(Decode error: {e})", "", "", "", "", "", "", ""])
            item.addChild(child)

    def _update_existing_children(self, session_id: str, item: QTreeWidgetItem, frame: TraceFrame) -> None:
        """
        Update already-populated children rows with latest decoded values.
        Used in Live mode when a row is expanded.
        """
        sess = self.sessions.get(session_id)

        if frame.dbc_key is None:
            return

        try:
            db = sess.dbcs.get_db(frame.dbc_key)
            msg = db.get_message_by_frame_id(int(frame.arbitration_id))

            phys = msg.decode(frame.data, decode_choices=True, scaling=True)
            raw = msg.decode(frame.data, decode_choices=False, scaling=False)

            # Update children in-place by sig name
            for i in range(item.childCount()):
                ch = item.child(i)
                d = ch.data(0, Qt.ItemDataRole.UserRole)
                if not d or d[0] != "sig":
                    continue
                sname = d[1]

                # find corresponding unit
                unit = ""
                for sig in msg.signals:
                    if sig.name == sname:
                        unit = sig.unit or ""
                        break

                v_phys = phys.get(sname)
                v_raw = raw.get(sname)

                if isinstance(v_phys, float):
                    v_phys_str = f"{v_phys:.3f}"
                else:
                    v_phys_str = "" if v_phys is None else str(v_phys)

                raw_dec = ""
                raw_hex = ""
                if isinstance(v_raw, int):
                    raw_dec = str(v_raw)
                    raw_hex = f"0x{v_raw:X}" if v_raw >= 0 else str(v_raw)
                else:
                    raw_dec = "" if v_raw is None else str(v_raw)
                    raw_hex = raw_dec

                ch.setText(self.COL_DATA, raw_hex)
                ch.setText(self.COL_VALUE, v_phys_str)
                ch.setText(self.COL_UNIT, unit)
                ch.setText(self.COL_RAW, raw_dec)
                ch.setText(self.COL_DBC, frame.dbc_key)

        except Exception:
            # If decode fails, keep old displayed values
            return
