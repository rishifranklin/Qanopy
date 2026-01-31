from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import can

from qanopy.core.can_rx_thread import CanRxThread
from qanopy.core.can_tx_worker import CanTxWorker
from qanopy.core.datastore import DataStore
from qanopy.core.filtering import CanFilterBank
from qanopy.core.logger import CanFrameLogger
from qanopy.core.multi_dbc_manager import MultiDbcManager
from qanopy.core.trace_buffer import TraceBuffer


@dataclass(frozen=True)
class CanConfig:
    interface: str
    channel: str
    bitrate: int
    fd: bool = False
    data_bitrate: int = 2000000


class CanSession:
    """
    One CAN interface/channel session.
    Holds:
      - Multiple DBCs (MultiDbcManager)
      - Per-DBC filters (CanFilterBank)
      - RX thread (decoding)
      - TX worker thread (sending)
      - Per-session logger
      - Per-session trace buffer
    """

    def __init__(
        self,
        session_id: str,
        display_name: str,
        can_cfg: CanConfig,
        datastore: DataStore,
        on_error: Callable[[str, str], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.session_id = session_id
        self.display_name = display_name
        self.can_cfg = can_cfg

        self.datastore = datastore
        self.on_error = on_error
        self.on_status = on_status

        self.logger = CanFrameLogger()
        self.filters = CanFilterBank()
        self.dbcs = MultiDbcManager(on_warning=lambda m: self.on_status(f"[{self.display_name}] {m}"))

        # trace ring buffer (keeps last N frames)
        self.trace = TraceBuffer(max_frames=20000, bitrate=self.can_cfg.bitrate)

        self.bus: Optional[can.BusABC] = None
        self.rx_thread: Optional[CanRxThread] = None
        self.tx_worker: Optional[CanTxWorker] = None

    # DBC management

    def add_dbc(self, dbc_path: str) -> str:
        dbc_key = self.dbcs.add(dbc_path)
        self.filters.ensure(dbc_key)
        return dbc_key

    def remove_dbc(self, dbc_key: str) -> None:
        self.dbcs.remove(dbc_key)
        self.filters.remove(dbc_key)

    # Connection lifecycle

    def connect(self) -> None:
        if self.bus is not None:
            self.disconnect()

        cfg = self.can_cfg
        
        if cfg.interface == "ixxat":
            kwargs = dict(interface=cfg.interface, channel=cfg.channel, bitrate=cfg.bitrate)
        elif cfg.interface == "vector":
            kwargs = dict(bustype='vector', app_name='Qanopy', channel=cfg.channel, bitrate=cfg.bitrate)
        else:
            pass
            
        if cfg.fd:
            kwargs["fd"] = True
            kwargs["data_bitrate"] = cfg.data_bitrate

        try:
            self.bus = can.Bus(**kwargs)  # type: ignore[arg-type]
        except Exception as e:
            raise RuntimeError(
                f"[{self.display_name}] Failed to open CAN bus.\n"
                f"Interface={cfg.interface} Channel={cfg.channel}\n{e}"
            )

        # clear trace at connect (optional, but sane)
        try:
            self.trace.clear()
        except Exception:
            pass

        self.rx_thread = CanRxThread(
            session_id=self.session_id,
            session_name=self.display_name,
            bus=self.bus,
            dbcs=self.dbcs,
            filters=self.filters,
            datastore=self.datastore,
            logger=self.logger,
            trace=self.trace,
            channel_label=self.display_name,
        )
        self.rx_thread.error_signal.connect(lambda title, msg: self.on_error(title, msg))
        self.rx_thread.status_signal.connect(lambda msg: self.on_status(msg))
        self.rx_thread.start()

        self.tx_worker = CanTxWorker(session_name=self.display_name, bus=self.bus, dbcs=self.dbcs)
        self.tx_worker.error_signal.connect(lambda title, msg: self.on_error(title, msg))
        self.tx_worker.status_signal.connect(lambda msg: self.on_status(msg))
        self.tx_worker.start()

        self.on_status(f"[{self.display_name}] Connected")

    def disconnect(self) -> None:
        if self.tx_worker is not None:
            try:
                self.tx_worker.stop_all_periodic()
                self.tx_worker.stop()
                self.tx_worker.wait(1500)
            except Exception:
                pass
            self.tx_worker = None

        if self.rx_thread is not None:
            try:
                self.rx_thread.stop()
                self.rx_thread.wait(1500)
            except Exception:
                pass
            self.rx_thread = None

        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

        try:
            self.logger.stop()
        except Exception:
            pass

        self.on_status(f"[{self.display_name}] Disconnected")

    # TX wrappers

    def tx_one_shot_raw(self, arbitration_id: int, data: bytes, is_extended: bool = False) -> None:
        if self.tx_worker is None:
            raise RuntimeError("TX worker not running (session disconnected)")
        self.tx_worker.send_one_shot_raw(arbitration_id, data, is_extended)

    def tx_one_shot_dbc(self, dbc_key: str, frame_id: int, msg_name: str, signals: Dict[str, Any]) -> None:
        if self.tx_worker is None:
            raise RuntimeError("TX worker not running (session disconnected)")
        self.tx_worker.send_one_shot_dbc(dbc_key, frame_id, msg_name, signals)

    def tx_start_periodic_raw(self, job_id: str, arbitration_id: int, data: bytes, is_extended: bool, period_ms: int) -> None:
        if self.tx_worker is None:
            raise RuntimeError("TX worker not running (session disconnected)")
        self.tx_worker.start_periodic_raw(job_id, arbitration_id, data, is_extended, period_ms)

    def tx_stop_periodic(self, job_id: str) -> None:
        if self.tx_worker is None:
            return
        self.tx_worker.stop_periodic(job_id)
