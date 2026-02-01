from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import can

from qanopy.core.can_rx_thread import CanRxThread
from qanopy.core.dbc_manager import DbcManager
from qanopy.core.datastore import DataStore
from qanopy.core.logger import CanFrameLogger


@dataclass(frozen=True)
class CanConfig:
    interface: str
    channel: str
    bitrate: int
    fd: bool = False
    data_bitrate: int = 2000000


class CanManager:
    def __init__(
        self,
        datastore: DataStore,
        dbc_manager: DbcManager,
        logger: CanFrameLogger,
        on_error: Callable[[str, str], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.datastore = datastore
        self.dbc_manager = dbc_manager
        self.logger = logger
        self.on_error = on_error
        self.on_status = on_status

        self.bus: Optional[can.BusABC] = None
        self.rx_thread: Optional[CanRxThread] = None

    def connect(self, cfg: CanConfig) -> None:
        if self.bus is not None:
            self.disconnect()

        try:
            # python-can parameters vary by interface.
            if cfg.interface == "ixxat":
                kwargs = dict(
                    interface=cfg.interface,
                    channel=cfg.channel,
                    bitrate=cfg.bitrate,
                    include_error_frames=True
                )
                if cfg.fd:
                    kwargs["fd"] = True
                    kwargs["data_bitrate"] = cfg.data_bitrate

                self.bus = can.Bus(**kwargs)  # type: ignore[arg-type]
            elif cfg.interface == "vector":
                if cfg.fd:
                    kwargs["fd"] = True
                    kwargs["data_bitrate"] = cfg.data_bitrate
                    
                kwargs = dict(bustype='vector',
                              app_name='Qanopy',
                              channel=cfg.channel,
                              bitrate=cfg.bitrate,
                              include_error_frames=True)
            else:
                pass
                
        except Exception as e:
            raise RuntimeError(
                f"Failed to open CAN bus.\nInterface={cfg.interface} Channel={cfg.channel}\n{e}"
            )

        self.rx_thread = CanRxThread(
            bus=self.bus,
            dbc_manager=self.dbc_manager,
            datastore=self.datastore,
            logger=self.logger,
        )
        self.rx_thread.error_signal.connect(lambda title, msg: self.on_error(title, msg))
        self.rx_thread.status_signal.connect(lambda msg: self.on_status(msg))
        self.rx_thread.start()
        self.on_status("CAN connected")

    def disconnect(self) -> None:
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

        self.on_status("CAN disconnected")
