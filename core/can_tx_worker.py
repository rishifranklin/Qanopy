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

import queue
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import can
from PyQt6.QtCore import QThread, pyqtSignal

from qanopy.core.multi_dbc_manager import MultiDbcManager


@dataclass
class TxPeriodicJob:
    job_id: str
    arbitration_id: int
    is_extended: bool
    data: bytes
    period_s: float
    next_due: float


class CanTxWorker(QThread):
    error_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)

    def __init__(self, session_name: str, bus: can.BusABC, dbcs: MultiDbcManager) -> None:
        super().__init__()
        self.session_name = session_name
        self.bus = bus
        self.dbcs = dbcs

        self._running = True
        self._cmd_q: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._jobs: Dict[str, TxPeriodicJob] = {}

    def stop(self) -> None:
        self._running = False
        try:
            self._cmd_q.put_nowait(("noop", None))
        except Exception:
            pass

    # UI commands

    def send_one_shot_raw(self, arbitration_id: int, data: bytes, is_extended: bool) -> None:
        self._cmd_q.put(("send_raw", (arbitration_id, data, is_extended)))

    def send_one_shot_dbc(self, dbc_key: str, frame_id: int, msg_name: str, signals: Dict[str, Any]) -> None:
        self._cmd_q.put(("send_dbc", (dbc_key, frame_id, msg_name, signals)))

    def start_periodic_raw(self, job_id: str, arbitration_id: int, data: bytes, is_extended: bool, period_ms: int) -> None:
        self._cmd_q.put(("start_periodic_raw", (job_id, arbitration_id, data, is_extended, period_ms)))

    def stop_periodic(self, job_id: str) -> None:
        self._cmd_q.put(("stop_periodic", job_id))

    def stop_all_periodic(self) -> None:
        self._cmd_q.put(("stop_all", None))

    # Worker LoopS

    def _do_send(self, arbitration_id: int, data: bytes, is_extended: bool) -> None:
        msg = can.Message(
            arbitration_id=int(arbitration_id),
            data=bytes(data),
            is_extended_id=bool(is_extended),
        )
        self.bus.send(msg)

    def run(self) -> None:
        self.status_signal.emit(f"[{self.session_name}] TX worker started")

        while self._running:
            now = time.monotonic()

            # send periodic jobs
            for job in list(self._jobs.values()):
                if now >= job.next_due:
                    try:
                        self._do_send(job.arbitration_id, job.data, job.is_extended)
                    except Exception as e:
                        self.error_signal.emit("TX Send Error", f"[{self.session_name}] {e}")
                    finally:
                        job.next_due = now + max(0.001, job.period_s)

            # process commands
            try:
                cmd, payload = self._cmd_q.get(timeout=0.02)
            except queue.Empty:
                continue

            try:
                if cmd == "send_raw":
                    arb_id, data, is_ext = payload
                    self._do_send(arb_id, data, is_ext)
                    self.status_signal.emit(f"[{self.session_name}] TX one-shot raw 0x{int(arb_id):X}")

                elif cmd == "send_dbc":
                    dbc_key, frame_id, msg_name, sigs = payload
                    data = self.dbcs.encode(str(dbc_key), int(frame_id), dict(sigs))
                    self._do_send(int(frame_id), data, False)
                    self.status_signal.emit(f"[{self.session_name}] TX one-shot {msg_name}")

                elif cmd == "start_periodic_raw":
                    job_id, arb_id, data, is_ext, period_ms = payload
                    period_s = max(1.0, float(period_ms)) / 1000.0
                    self._jobs[str(job_id)] = TxPeriodicJob(
                        job_id=str(job_id),
                        arbitration_id=int(arb_id),
                        is_extended=bool(is_ext),
                        data=bytes(data),
                        period_s=period_s,
                        next_due=time.monotonic(),
                    )
                    self.status_signal.emit(f"[{self.session_name}] TX periodic started job={job_id}")

                elif cmd == "stop_periodic":
                    job_id = str(payload)
                    if job_id in self._jobs:
                        self._jobs.pop(job_id, None)
                        self.status_signal.emit(f"[{self.session_name}] TX periodic stopped job={job_id}")

                elif cmd == "stop_all":
                    self._jobs.clear()
                    self.status_signal.emit(f"[{self.session_name}] TX periodic stopped (all)")

            except Exception as e:
                self.error_signal.emit("TX Worker Error", f"[{self.session_name}] {e}")

        self._jobs.clear()
        self.status_signal.emit(f"[{self.session_name}] TX worker stopped")
