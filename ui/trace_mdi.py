from __future__ import annotations

from typing import Dict, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
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

        root = QWidget()
        self.setWidget(root)

        layout = QVBoxLayout()
        root.setLayout(layout)

        top = QHBoxLayout()
        self.cmb_session = QComboBox()

        self.chk_pause = QCheckBox("Pause")
        self.chk_live = QCheckBox("List Once (Live Update)")  # NEW requirement
        self.chk_update_expanded = QCheckBox("Auto-update expanded decode")
        self.chk_update_expanded.setChecked(True)

        self.btn_clear = QPushButton("Clear")
        self.btn_refresh = QPushButton("Refresh Sessions")

        top.addWidget(QLabel("Session"))
        top.addWidget(self.cmb_session, 2)
        top.addWidget(self.chk_pause)
        top.addWidget(self.chk_live)
        top.addWidget(self.chk_update_expanded)
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
        self.tree.itemExpanded.connect(self._on_item_expanded)
        layout.addWidget(self.tree)

        self.chk_pause.stateChanged.connect(self._on_pause)
        self.chk_live.stateChanged.connect(self._on_live_mode_changed)
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

    # pumping data

    def _pump(self) -> None:
        if self._paused:
            return

        sid = self._get_selected_session_id()
        if not sid:
            return

        sess = self.sessions.get(sid)
        if sess != None:
            frames = sess.trace.get_since(self._last_seq)
            if not frames:
                return
        else:
            return

        self.tree.setUpdatesEnabled(False)
        try:
            for f in frames:
                self._last_seq = max(self._last_seq, f.seq)
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
        self.tree.addTopLevelItem(it)

    # Live mode (one row per ID)

    def _make_live_key(self, f: TraceFrame) -> Tuple[int, bool, str]:
        # key = (arbitration_id, is_extended, direction)
        # channel is session-specific anyway (user selects a session in this view)
        return (int(f.arbitration_id), bool(f.is_extended), str(f.direction))

    def _upsert_live_row(self, session_id: str, f: TraceFrame) -> None:
        key = self._make_live_key(f)
        existing = self._row_by_key.get(key)

        if existing is None:
            it = QTreeWidgetItem()
            self._set_frame_row_text(it, f)

            it.setData(0, Qt.ItemDataRole.UserRole, ("frame", session_id, f))
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

            self._insert_sorted_by_id(it, f)
            self._row_by_key[key] = it
            return

        # Update the existing row instead of appending
        self._set_frame_row_text(existing, f)
        existing.setData(0, Qt.ItemDataRole.UserRole, ("frame", session_id, f))

        # If the row is expanded and auto-update is enabled, refresh signal decode
        if self.chk_update_expanded.isChecked():
            try:
                expanded = self.tree.isExpanded(self.tree.indexFromItem(existing))
            except Exception:
                expanded = False

            if existing.childCount() > 0 and expanded:
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
            cf = cf  # type: ignore[assignment]

            cid = int(cf.arbitration_id)
            cext = bool(cf.is_extended)
            cdir = str(cf.direction)

            if (target_id, target_ext, target_dir) < (cid, cext, cdir):
                insert_at = i
                break

        self.tree.insertTopLevelItem(insert_at, it)

    # Row update helpers

    def _set_frame_row_text(self, it: QTreeWidgetItem, f: TraceFrame) -> None:
        dt_ms = self._fmt_dt_ms(f.delta_s)

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
        self._populate_children(str(sid), item, frame)

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
                    sname, "", "",          # Name column holds signal name
                    raw_hex,                # Data column shows raw hex-ish representation
                    v_phys_str,             # Value (physical/scaled)
                    unit,
                    raw_dec,                # Raw decimal/unscaled
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
        This is used in Live mode when a row is expanded.
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

                # find corresponding signal definition for unit (cheap linear scan)
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
            # If decode fails on update, keep old displayed values (don’t spam UI with errors)
            return
