from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict, Tuple, List

import numpy as np


@dataclass
class _Series:
    t: Deque[float]
    y: Deque[float]


class DataStore:
    def __init__(self, max_points_per_signal: int = 20000) -> None: 
        self.max_points = int(max_points_per_signal)
        self._lock = Lock()
        self._data: Dict[str, _Series] = {}

    def append(self, key: str, t: float, y: float) -> None:
        with self._lock:
            s = self._data.get(key)
            if s is None:
                s = _Series(t=deque(maxlen=self.max_points), y=deque(maxlen=self.max_points))
                self._data[key] = s
            s.t.append(float(t))
            s.y.append(float(y))

    def get_series(self, key: str):
        with self._lock:
            s = self._data.get(key)
            if s is None:
                return np.array([], dtype=float), np.array([], dtype=float)
            # return numpy arrays for fast plotting/interp
            return np.fromiter(s.t, dtype=float), np.fromiter(s.y, dtype=float)
