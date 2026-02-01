from __future__ import annotations

import time
import can

from PyQt6.QtCore import QThread, pyqtSignal

from qanopy.core.datastore import DataStore
from qanopy.core.logger import CanFrameLogger
from qanopy.core.filtering import CanFilterBank
from qanopy.core.multi_dbc_manager import MultiDbcManager
from qanopy.core.trace_buffer import TraceBuffer
from qanopy.utils.timebase import monotonic_seconds


class CanRxThread(QThread):
    error_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)

    def __init__(
        self,
        session_id: str,
        session_name: str,
        bus: can.BusABC,
        dbcs: MultiDbcManager,
        filters: CanFilterBank,
        datastore: DataStore,
        logger: CanFrameLogger,
        trace: TraceBuffer,
        channel_label: str,
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.session_name = session_name

        self.bus = bus
        self.dbcs = dbcs
        self.filters = filters
        self.datastore = datastore
        self.logger = logger
        self.trace = trace
        self.channel_label = channel_label

        self._running = True

    def stop(self) -> None:
        self._running = False

    def _to_float(self, v) -> float:
        # keep plotting numeric always. Bool becomes 0/1.
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        # cantools sometimes returns numpy scalar types
        try:
            return float(v)
        except Exception:
            raise ValueError(f"Non-numeric signal value: {v!r}")

    def run(self) -> None:
        self.status_signal.emit(f"[{self.session_name}] RX thread started")
        t0 = monotonic_seconds()

        while self._running:
            try:
                msg = self.bus.recv(timeout=0.1)
            except Exception as e:
                self.error_signal.emit("CAN Receive Error", f"[{self.session_name}] {e}")
                time.sleep(0.01)
                continue

            if msg is None:
                continue

            t = monotonic_seconds() - t0

            arb_id = int(msg.arbitration_id)
            is_ext = bool(getattr(msg, "is_extended_id", False))
            dlc = int(getattr(msg, "dlc", len(msg.data)))
            data = bytes(msg.data)

            # resolve DBC key (which DBC applies to this frame ID)
            dbc_key = self.dbcs.lookup_dbc_key(arb_id)

            # resolve message name if possible (for trace display)
            msg_name = None
            if dbc_key is not None:
                try:
                    db = self.dbcs.get_db(dbc_key)
                    m = db.get_message_by_frame_id(arb_id)
                    msg_name = m.name
                except Exception:
                    msg_name = None

            # TRACE: always capture incoming frames (unfiltered)
            try:
                self.trace.push(
                    time_s=t,
                    channel=self.channel_label,
                    direction="Rx",
                    arbitration_id=arb_id,
                    is_extended=is_ext,
                    dlc=dlc,
                    data=data,
                    dbc_key=dbc_key,
                    msg_name=msg_name,
                )
            except Exception:
                pass

            # Per-DBC filter (affects decode/plots; trace remains unfiltered)
            allow = True
            affects_logging = False
            if dbc_key is not None:
                flt = self.filters.get(dbc_key)
                allow = flt.allows(arb_id)
                affects_logging = flt.affects_logging()

            # Raw logging (optionally filtered)
            try:
                if (dbc_key is None) or (not affects_logging) or allow:
                    self.logger.push_frame(t, msg)
            except Exception:
                pass

            if not allow:
                continue

            if dbc_key is None:
                # Unknown frame id (no DBC match)
                continue

            # Decode NUMERIC values for plotting
            # IMPORTANT: decode_choices=False ensures enums stay numeric (e.g., 0/1/2),
            # while the plot Y-axis can still show text via choices mapping.
            try:
                db = self.dbcs.get_db(dbc_key)
                m = db.get_message_by_frame_id(arb_id)
                decoded = m.decode(data, decode_choices=False, scaling=True)
            except KeyError:
                continue
            except Exception as e:
                self.error_signal.emit(
                    "DBC Decode Error",
                    f"[{self.session_name}] ID=0x{arb_id:X}: {e}",
                )
                continue

            for sig_name, sig_val in decoded.items():
                key = f"{self.session_id}:{dbc_key}:{arb_id}:{sig_name}"
                try:
                    y = self._to_float(sig_val)
                    self.datastore.append(key, float(t), y)
                except Exception:
                    # do not crash RX thread for a bad signal
                    continue

        self.status_signal.emit(f"[{self.session_name}] RX thread stopped")
