from __future__ import annotations

import os
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cantools


class DuplicateDbcFilenameError(RuntimeError):
    pass


@dataclass(frozen=True)
class DbcEntry:
    key: str  # basename, e.g. "A.dbc"
    path: str
    db: cantools.database.Database


class MultiDbcManager:
    """
    Multiple DBCs per CAN session, keyed by basename (tree node requirement).

    - add(path): loads and stores db as DbcEntry under basename
    - rejects duplicate basenames within the same session (error handling requirement)
    - frame routing index: frame_id -> dbc_key
      If frame_id collisions occur, first loaded keeps ownership; warning emitted.
    """

    def __init__(self, on_warning=None) -> None:
        self._lock = RLock()
        self._dbcs: Dict[str, DbcEntry] = {}
        self._frame_index: Dict[int, str] = {}          # frame_id -> dbc_key
        self._collisions: Dict[int, List[str]] = {}     # frame_id -> [dbc_key...]
        self._on_warning = on_warning

    def list_keys(self) -> List[str]:
        with self._lock:
            return list(self._dbcs.keys())

    def has(self, dbc_key: str) -> bool:
        with self._lock:
            return dbc_key in self._dbcs

    def get_entry(self, dbc_key: str) -> DbcEntry:
        with self._lock:
            return self._dbcs[dbc_key]

    def get_db(self, dbc_key: str) -> cantools.database.Database:
        with self._lock:
            return self._dbcs[dbc_key].db

    def add(self, path: str) -> str:
        key = os.path.basename(path)

        with self._lock:
            if key in self._dbcs:
                raise DuplicateDbcFilenameError(
                    f"DBC filename '{key}' is already loaded for this session.\n"
                    f"Existing: {self._dbcs[key].path}\n"
                    f"New:      {path}\n\n"
                    f"Rename the DBC file (basename) or remove the existing one before adding."
                )

            db = cantools.database.load_file(path)
            entry = DbcEntry(key=key, path=path, db=db)
            self._dbcs[key] = entry

            # update route index
            for msg in db.messages:
                fid = int(msg.frame_id)

                if fid in self._frame_index:
                    existing = self._frame_index[fid]
                    self._collisions.setdefault(fid, [existing])
                    if key not in self._collisions[fid]:
                        self._collisions[fid].append(key)

                    if self._on_warning:
                        self._on_warning(
                            f"FrameID collision 0x{fid:X}: already mapped to '{existing}', also in '{key}'. "
                            f"RX decode will use '{existing}'."
                        )
                    continue

                self._frame_index[fid] = key

            return key

    def remove(self, dbc_key: str) -> None:
        with self._lock:
            if dbc_key not in self._dbcs:
                return
            self._dbcs.pop(dbc_key, None)
            self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._frame_index.clear()
        self._collisions.clear()

        for k, entry in self._dbcs.items():
            for msg in entry.db.messages:
                fid = int(msg.frame_id)
                if fid in self._frame_index:
                    existing = self._frame_index[fid]
                    self._collisions.setdefault(fid, [existing])
                    if k not in self._collisions[fid]:
                        self._collisions[fid].append(k)
                    continue
                self._frame_index[fid] = k

    def lookup_dbc_key(self, frame_id: int) -> Optional[str]:
        with self._lock:
            return self._frame_index.get(int(frame_id))

    def decode_any(self, frame_id: int, data: bytes) -> Tuple[str, str, Dict[str, Any]]:
        """
        Returns: (dbc_key, message_name, decoded_signals)
        Raises KeyError if frame_id isn't known in any loaded DBC.
        """
        with self._lock:
            dbc_key = self._frame_index[int(frame_id)]  # raises KeyError
            entry = self._dbcs[dbc_key]
            msg = entry.db.get_message_by_frame_id(int(frame_id))
            return dbc_key, msg.name, msg.decode(data)

    def encode(self, dbc_key: str, frame_id: int, signals: Dict[str, Any]) -> bytes:
        with self._lock:
            db = self._dbcs[dbc_key].db
            msg = db.get_message_by_frame_id(int(frame_id))
            return msg.encode(signals)
