from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import can
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMdiSubWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

from qanopy.core.session_manager import SessionManager


@dataclass
class _PeriodicJob:
    stop_evt: threading.Event
    thread: threading.Thread


class TxMdiSubWindow(QMdiSubWindow):
    """
    Transmit Window (MDI)

    Features:
      - Select Session -> DBC -> Message
      - Signal editors:
          * If signal has DBC choices/enums => dropdown (QComboBox)
          * Else numeric editor (QSpinBox/QDoubleSpinBox)
      - One-shot send
      - Periodic send (threaded; UI remains responsive)
    """

    def __init__(self, sessions: SessionManager) -> None:
        super().__init__()
        self.setWindowTitle("Transmit")

        self.sessions = sessions

        self._job: Optional[_PeriodicJob] = None
        self._editors: Dict[str, Tuple[Any, Any]] = {}  # sig_name -> (sig_def, editor_widget)

        root = QWidget()
        self.setWidget(root)

        layout = QVBoxLayout()
        root.setLayout(layout)

        # Top selection row
        top = QHBoxLayout()

        self.cmb_session = QComboBox()
        self.cmb_dbc = QComboBox()
        self.cmb_msg = QComboBox()

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._reload_sessions)

        top.addWidget(QLabel("Session"))
        top.addWidget(self.cmb_session, 2)
        top.addWidget(QLabel("DBC"))
        top.addWidget(self.cmb_dbc, 2)
        top.addWidget(QLabel("Message"))
        top.addWidget(self.cmb_msg, 3)
        top.addWidget(self.btn_refresh)

        layout.addLayout(top)

        # Signal table
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Signal", "Value", "Unit", "Notes"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.tbl)

        # TX controls
        bot = QHBoxLayout()

        self.sp_cycle_ms = QSpinBox()
        self.sp_cycle_ms.setRange(1, 60000)
        self.sp_cycle_ms.setValue(100)

        self.btn_send_once = QPushButton("Send Once")
        self.btn_start = QPushButton("Start Periodic")
        self.btn_stop = QPushButton("Stop")

        self.btn_send_once.clicked.connect(self._send_once)
        self.btn_start.clicked.connect(self._start_periodic)
        self.btn_stop.clicked.connect(self._stop_periodic)

        self.btn_stop.setEnabled(False)

        bot.addWidget(QLabel("Cycle (ms)"))
        bot.addWidget(self.sp_cycle_ms)
        bot.addSpacing(12)
        bot.addWidget(self.btn_send_once)
        bot.addWidget(self.btn_start)
        bot.addWidget(self.btn_stop)
        bot.addStretch(1)

        layout.addLayout(bot)

        # Wiring
        self.cmb_session.currentIndexChanged.connect(self._on_session_changed)
        self.cmb_dbc.currentIndexChanged.connect(self._on_dbc_changed)
        self.cmb_msg.currentIndexChanged.connect(self._on_msg_changed)

        self._reload_sessions()

    # loading lists

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

    def _get_session_id(self) -> Optional[str]:
        sid = self.cmb_session.currentData()
        if not sid:
            return None
        return str(sid)

    def _on_session_changed(self) -> None:
        self._stop_periodic()

        sid = self._get_session_id()
        self.cmb_dbc.blockSignals(True)
        self.cmb_dbc.clear()

        if sid:
            sess = self.sessions.get(sid)
            # assumes sess.dbcs has list_keys() or keys()
            keys = []
            for fn in ("list_keys", "keys"):
                f = getattr(sess.dbcs, fn, None)
                if callable(f):
                    keys = list(f())
                    break

            for k in keys:
                self.cmb_dbc.addItem(str(k), userData=str(k))

        self.cmb_dbc.blockSignals(False)
        self._on_dbc_changed()

    def _on_dbc_changed(self) -> None:
        self._stop_periodic()

        sid = self._get_session_id()
        dbc_key = self.cmb_dbc.currentData()
        self.cmb_msg.blockSignals(True)
        self.cmb_msg.clear()

        if sid and dbc_key:
            sess = self.sessions.get(sid)
            try:
                db = sess.dbcs.get_db(str(dbc_key))
                # cantools: db.messages list
                for m in db.messages:
                    # show name + id
                    self.cmb_msg.addItem(f"{m.name} (0x{int(m.frame_id):X})", userData=m.name)
            except Exception:
                pass

        self.cmb_msg.blockSignals(False)
        self._on_msg_changed()

    def _on_msg_changed(self) -> None:
        self._stop_periodic()
        self._populate_signal_editors()

    # signal editors

    def _populate_signal_editors(self) -> None:
        self._editors.clear()
        self.tbl.setRowCount(0)

        sid = self._get_session_id()
        dbc_key = self.cmb_dbc.currentData()
        msg_name = self.cmb_msg.currentData()
        if not (sid and dbc_key and msg_name):
            return

        sess = self.sessions.get(sid)
        try:
            db = sess.dbcs.get_db(str(dbc_key))
            msg = db.get_message_by_name(str(msg_name))
        except Exception as e:
            self._notify_error("Transmit", f"Failed to load message: {e}")
            return

        self.tbl.setRowCount(len(msg.signals))

        for r, sig in enumerate(msg.signals):
            sig_name = sig.name
            unit = sig.unit or ""

            self.tbl.setItem(r, 0, QTableWidgetItem(sig_name))
            self.tbl.setItem(r, 2, QTableWidgetItem(unit))

            notes = []
            if getattr(sig, "minimum", None) is not None:
                notes.append(f"min={sig.minimum}")
            if getattr(sig, "maximum", None) is not None:
                notes.append(f"max={sig.maximum}")
            self.tbl.setItem(r, 3, QTableWidgetItem("  ".join(notes)))

            editor = self._make_editor_for_signal(sig)
            self.tbl.setCellWidget(r, 1, editor)
            self._editors[sig_name] = (sig, editor)

        self.tbl.resizeColumnsToContents()

    def _make_editor_for_signal(self, sig) -> QWidget:
        """
        If DBC has choices -> dropdown
        Else numeric editor.
        """
        choices = getattr(sig, "choices", None)
        if choices:
            cmb = QComboBox()
            # sort by numeric value
            for val in sorted(choices.keys(), key=lambda x: int(x)):
                label = str(choices[val])
                cmb.addItem(f"{label} ({int(val)})", userData=int(val))

            # Try set default based on initial value:
            # - if sig.initial exists, use it
            init = getattr(sig, "initial", None)
            if init is not None:
                idx = cmb.findData(int(init))
                if idx >= 0:
                    cmb.setCurrentIndex(idx)

            return cmb

        # Numeric editor (prefer int if signal is clearly integer)
        is_float = bool(getattr(sig, "is_float", False))
        if not is_float:
            # cantools may not expose is_float consistently; infer from scale/offset or decimals
            scale = getattr(sig, "scale", 1.0)
            offset = getattr(sig, "offset", 0.0)
            if abs(float(scale) - round(float(scale))) > 1e-9 or abs(float(offset) - round(float(offset))) > 1e-9:
                is_float = True

        if is_float:
            sp = QDoubleSpinBox()
            sp.setDecimals(3)
            sp.setSingleStep(0.1)
            sp.setRange(-1e12, 1e12)
            if getattr(sig, "minimum", None) is not None:
                sp.setMinimum(float(sig.minimum))
            if getattr(sig, "maximum", None) is not None:
                sp.setMaximum(float(sig.maximum))
            init = getattr(sig, "initial", None)
            if init is not None:
                try:
                    sp.setValue(float(init))
                except Exception:
                    pass
            return sp

        sp = QSpinBox()
        sp.setRange(-2147483648, 2147483647)
        if getattr(sig, "minimum", None) is not None:
            sp.setMinimum(int(sig.minimum))
        if getattr(sig, "maximum", None) is not None:
            sp.setMaximum(int(sig.maximum))
        init = getattr(sig, "initial", None)
        if init is not None:
            try:
                sp.setValue(int(init))
            except Exception:
                pass
        return sp

    # build + send

    def _collect_signal_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for sig_name, (sig, w) in self._editors.items():
            choices = getattr(sig, "choices", None)
            if choices:
                # dropdown -> numeric backing value
                cmb: QComboBox = w  # type: ignore[assignment]
                v = cmb.currentData()
                if v is None:
                    # fallback parse from text
                    txt = cmb.currentText()
                    # "Label (N)" -> N
                    try:
                        v = int(txt.split("(")[-1].split(")")[0].strip())
                    except Exception:
                        v = 0
                values[sig_name] = int(v)
                continue

            if isinstance(w, QDoubleSpinBox):
                values[sig_name] = float(w.value())
            elif isinstance(w, QSpinBox):
                values[sig_name] = int(w.value())
            else:
                # unexpected editor widget type
                try:
                    values[sig_name] = float(getattr(w, "value")())
                except Exception:
                    values[sig_name] = 0

        return values

    def _build_can_message(self) -> Tuple[can.Message, str]:
        """
        Encode DBC message using current signal editors.
        Returns (python-can Message, human label).
        """
        sid = self._get_session_id()
        dbc_key = self.cmb_dbc.currentData()
        msg_name = self.cmb_msg.currentData()
        if not (sid and dbc_key and msg_name):
            raise RuntimeError("Select Session, DBC, and Message first.")

        sess = self.sessions.get(sid)
        db = sess.dbcs.get_db(str(dbc_key))
        msg = db.get_message_by_name(str(msg_name))

        values = self._collect_signal_values()

        # Encode: scaling=True uses physical values; enums are numeric anyway
        data = msg.encode(values)  # bytes

        frame_id = int(msg.frame_id)
        dlc = int(msg.length)

        # Extended inference: cantools Message has is_extended_frame sometimes
        is_ext = bool(getattr(msg, "is_extended_frame", False))
        if not is_ext:
            is_ext = frame_id > 0x7FF

        cm = can.Message(
            arbitration_id=frame_id,
            is_extended_id=is_ext,
            dlc=dlc,
            data=data,
        )
        label = f"{msg.name} (0x{frame_id:X})"
        return cm, label

    def _send_once(self) -> None:
        try:
            cm, label = self._build_can_message()
            self._tx_send(cm)
        except Exception as e:
            self._notify_error("Send Once Failed", str(e))

    def _start_periodic(self) -> None:
        if self._job is not None:
            return

        try:
            cm, label = self._build_can_message()
        except Exception as e:
            self._notify_error("Start Periodic Failed", str(e))
            return

        cycle_ms = int(self.sp_cycle_ms.value())
        stop_evt = threading.Event()

        def _worker():
            next_t = time.perf_counter()
            while not stop_evt.is_set():
                # Rebuild each cycle so changed dropdown values take effect live
                try:
                    cm2, _ = self._build_can_message()
                    self._tx_send(cm2)
                except Exception:
                    # keep thread alive; UI may be mid-change
                    pass

                next_t += (cycle_ms / 1000.0)
                dt = next_t - time.perf_counter()
                if dt > 0:
                    stop_evt.wait(dt)
                else:
                    # if we fell behind, reset
                    next_t = time.perf_counter()

        th = threading.Thread(target=_worker, name="PyCAN-TX-Periodic", daemon=True)
        self._job = _PeriodicJob(stop_evt=stop_evt, thread=th)
        th.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_send_once.setEnabled(False)

    def _stop_periodic(self) -> None:
        if self._job is None:
            return

        try:
            self._job.stop_evt.set()
            self._job.thread.join(timeout=1.0)
        except Exception:
            pass

        self._job = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_send_once.setEnabled(True)

    def _tx_send(self, cm: can.Message) -> None:
        sid = self._get_session_id()
        if not sid:
            raise RuntimeError("No session selected")

        sess = self.sessions.get(sid)

        # Prefer session TX worker if available (non-blocking), else send directly.
        tx = getattr(sess, "tx", None)
        if tx is not None:
            for fn_name in ("send_once", "enqueue_one_shot", "post_one_shot", "submit_one_shot"):
                fn = getattr(tx, fn_name, None)
                if callable(fn):
                    fn(cm)
                    return

        bus = getattr(sess, "bus", None)
        if bus is None:
            raise RuntimeError("Session has no bus handle")

        try:
            bus.send(cm)
        except Exception as e:
            raise RuntimeError(f"CAN send failed: {e}") from e

    # UI helpers

    def _notify_error(self, title: str, msg: str) -> None:
        QMessageBox.critical(self, title, msg)

    def closeEvent(self, event) -> None:
        self._stop_periodic()
        super().closeEvent(event)
