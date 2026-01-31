from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import can


@dataclass(frozen=True)
class LogStat:
    enqueued: int
    written: int
    dropped: int
    running: bool
    path: str


class CanFrameLogger:
    """
    Threaded CAN logger.
    - push_frame() is non-blocking (drops on overflow instead of freezing UI/RX).
    - Writer thread writes to CSV / ASC / BLF based on file extension using python-can.

    Supported extensions (via python-can):
      - .csv  (CSVWriter)
      - .asc  (ASCWriter - Vector ASCII)
      - .blf  (BLFWriter - Vector Binary Log Format)

    Notes:
    - We stamp msg.timestamp with the provided 't' (seconds) so exported logs have consistent time base.
    """

    def __init__(self, max_queue: int = 50000, recent_max: int = 5000) -> None:
        self._q: "queue.Queue[Optional[Tuple[float, can.Message]]]" = queue.Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        self._writer = None
        self._path = ""
        self._lock = threading.Lock()

        self._enqueued = 0
        self._written = 0
        self._dropped = 0

        # Small in-memory tail for a log viewer window (if you have one)
        self._recent_max = int(recent_max)
        self._recent: List[str] = []

    # public API

    def start(self, path: str) -> None:
        """
        Start logging to a file. Format is inferred from extension.
        """
        with self._lock:
            if self.is_running():
                self.stop()

            if not path:
                raise ValueError("Log path is empty")

            ext = os.path.splitext(path)[1].lower()
            if ext not in (".csv", ".asc", ".blf"):
                raise ValueError("Unsupported log format. Use .csv, .asc, or .blf")

            # attempt to create a python-can writer (extension-based)
            try:
                self._writer = can.Logger(path)  # factory selects writer by extension
            except Exception as e:
                # provide a helpful hint for BLF if missing in their python-can version/build
                if ext == ".blf":
                    raise RuntimeError(
                        "Failed to create BLF writer. Ensure you have a recent python-can version "
                        "that includes BLFWriter support."
                    ) from e
                raise RuntimeError(f"Failed to create logger for {ext}: {e}") from e

            self._path = path
            self._enqueued = 0
            self._written = 0
            self._dropped = 0
            self._recent.clear()

            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._run, name="PyCAN-Logger", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """
        Stop logging gracefully.
        """
        with self._lock:
            if not self.is_running():
                return

            self._stop_evt.set()

            # unblock writer thread
            try:
                self._q.put_nowait(None)
            except Exception:
                pass

            th = self._thread
            self._thread = None

        if th is not None:
            th.join(timeout=2.0)

        # close writer
        with self._lock:
            wr = self._writer
            self._writer = None
            self._path = ""

        if wr is not None:
            try:
                # python-can writers typically expose stop()
                wr.stop()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._thread is not None and not self._stop_evt.is_set()

    def push_frame(self, t: float, msg: can.Message) -> None:
        """
        Non-blocking enqueue. Drops frames if queue is full (never blocks RX/UI).
        """
        with self._lock:
            if self._writer is None or self._thread is None:
                return

        # stamp timestamp used by python-can writers
        try:
            msg.timestamp = float(t)
        except Exception:
            pass

        try:
            self._q.put_nowait((float(t), msg))
            self._enqueued += 1
            self._push_recent(self._format_recent_line(t, msg))
        except queue.Full:
            self._dropped += 1
        except Exception:
            # do not throw from RX thread
            self._dropped += 1

    def get_status(self) -> LogStat:
        with self._lock:
            return LogStat(
                enqueued=int(self._enqueued),
                written=int(self._written),
                dropped=int(self._dropped),
                running=bool(self.is_running()),
                path=str(self._path),
            )

    def tail_lines(self, max_lines: int = 2000) -> List[str]:
        """
        Optional helper for Log Viewer window.
        """
        with self._lock:
            return list(self._recent[-max(1, int(max_lines)):])

    # internal usage

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is None:
                break

            _t, msg = item
            with self._lock:
                wr = self._writer

            if wr is None:
                continue

            try:
                # python-can writer interface
                wr.on_message_received(msg)
                self._written += 1
            except Exception:
                # keep logging thread alive
                self._dropped += 1

        # best-effort flush/stop
        with self._lock:
            wr = self._writer
        if wr is not None:
            try:
                wr.stop()
            except Exception:
                pass

    def _push_recent(self, line: str) -> None:
        with self._lock:
            self._recent.append(line)
            if len(self._recent) > self._recent_max:
                # trim from the front
                del self._recent[: max(1, self._recent_max // 10)]

    def _format_recent_line(self, t: float, msg: can.Message) -> str:
        try:
            arb = int(msg.arbitration_id)
            is_ext = bool(getattr(msg, "is_extended_id", False))
            dlc = int(getattr(msg, "dlc", len(msg.data)))
            data = bytes(msg.data)
            data_hex = " ".join(f"{b:02X}" for b in data)
            return f"{t:10.6f}  {'29' if is_ext else '11'}  0x{arb:X}  DLC={dlc}  {data_hex}"
        except Exception:
            return f"{t:10.6f}  <frame>"
            
    def get_recent_lines(self, max_lines: int = 2000):
        """
        Backwards-compatible API for LogMdi window.
        """
        return self.tail_lines(max_lines)

