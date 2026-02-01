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

from dataclasses import dataclass
from threading import Lock
from typing import Dict, Iterable, Set


@dataclass
class FilterSnapshot:
    enabled: bool
    mode: str               # "include" or "exclude"
    ids: Set[int]
    affects_logging: bool


class CanMessageFilter:
    """
    Thread-safe include/exclude filter by arbitration ID.
    - include: only IDs in set pass
    - exclude: IDs in set blocked
    """
    def __init__(self) -> None:
        self._lock = Lock()
        self._enabled = False
        self._mode = "exclude"
        self._ids: Set[int] = set()
        self._affects_logging = False

    def snapshot(self) -> FilterSnapshot:
        with self._lock:
            return FilterSnapshot(
                enabled=self._enabled,
                mode=self._mode,
                ids=set(self._ids),
                affects_logging=self._affects_logging,
            )

    def configure(self, enabled: bool, mode: str, ids: Iterable[int], affects_logging: bool) -> None:
        m = mode.strip().lower()
        if m not in ("include", "exclude"):
            raise ValueError("mode must be 'include' or 'exclude'")
        with self._lock:
            self._enabled = bool(enabled)
            self._mode = m
            self._ids = set(int(x) for x in ids)
            self._affects_logging = bool(affects_logging)

    def allows(self, arbitration_id: int) -> bool:
        with self._lock:
            if not self._enabled:
                return True
            in_set = int(arbitration_id) in self._ids
            if self._mode == "include":
                return in_set
            return not in_set

    def affects_logging(self) -> bool:
        with self._lock:
            return self._affects_logging


class CanFilterBank:
    """
    Holds one CanMessageFilter per dbc_key within a session.
    """
    def __init__(self) -> None:
        self._lock = Lock()
        self._filters: Dict[str, CanMessageFilter] = {}

    def ensure(self, dbc_key: str) -> CanMessageFilter:
        with self._lock:
            f = self._filters.get(dbc_key)
            if f is None:
                f = CanMessageFilter()
                self._filters[dbc_key] = f
            return f

    def get(self, dbc_key: str) -> CanMessageFilter:
        return self.ensure(dbc_key)

    def remove(self, dbc_key: str) -> None:
        with self._lock:
            self._filters.pop(dbc_key, None)
