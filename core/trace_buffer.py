from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from threading import Lock
from typing import Deque, Dict, List, Optional


@dataclass(frozen=True)
class TraceFrame:
    seq: int
    time_s: float
    sof_s: float
    delta_s: Optional[float]

    channel: str
    direction: str  # "Rx" / "Tx"

    arbitration_id: int
    is_extended: bool
    dlc: int
    data: bytes

    dbc_key: Optional[str]
    msg_name: Optional[str]


class TraceBuffer:
    """
    Thread-safe ring buffer for CAN trace frames.
    UI pulls frames via get_since(last_seq).
    """

    def __init__(self, max_frames: int = 20000, bitrate: int = 500000) -> None:
        self._lock = Lock()
        self._buf: Deque[TraceFrame] = deque(maxlen=max_frames)
        self._seq = 0

        self._last_time_by_id: Dict[int, float] = {}
        self._bitrate = max(1, int(bitrate))

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._last_time_by_id.clear()

    def _estimate_frame_bits(self, dlc: int, is_extended: bool) -> int:
        """
        Very rough estimate of bits on wire (ignores stuff bits).
        Enough for a 'Start of Frame' approximation.
        """
        payload_bits = max(0, min(64, int(dlc))) * 8
        base_bits = 67 if is_extended else 47  # rough typical values
        return base_bits + payload_bits

    def push(
        self,
        time_s: float,
        channel: str,
        direction: str,
        arbitration_id: int,
        is_extended: bool,
        dlc: int,
        data: bytes,
        dbc_key: Optional[str],
        msg_name: Optional[str],
    ) -> None:
        with self._lock:
            arb = int(arbitration_id)
            t = float(time_s)

            last = self._last_time_by_id.get(arb)
            delta = None if last is None else (t - last)
            self._last_time_by_id[arb] = t

            bits = self._estimate_frame_bits(dlc, is_extended)
            sof = max(0.0, t - (bits / float(self._bitrate)))

            self._seq += 1
            frame = TraceFrame(
                seq=self._seq,
                time_s=t,
                sof_s=sof,
                delta_s=delta,
                channel=str(channel),
                direction=str(direction),

                arbitration_id=arb,
                is_extended=bool(is_extended),
                dlc=int(dlc),
                data=bytes(data),

                dbc_key=dbc_key,
                msg_name=msg_name,
            )
            self._buf.append(frame)

    def get_since(self, last_seq: int) -> List[TraceFrame]:
        """
        Returns frames with seq > last_seq.
        If the ring overwrote old frames, you may miss some.
        """
        with self._lock:
            if not self._buf:
                return []

            # fast path: if last_seq is older than the oldest retained, return all.
            oldest = self._buf[0].seq
            if last_seq < oldest:
                return list(self._buf)

            # filter
            return [f for f in self._buf if f.seq > last_seq]
