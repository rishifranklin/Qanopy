from __future__ import annotations

from typing import Optional, Dict, Any

import cantools


class DbcManager:
    def __init__(self) -> None:
        self.db: Optional[cantools.database.Database] = None
        self.path: Optional[str] = None

    def load(self, path: str) -> None:
        self.db = cantools.database.load_file(path)
        self.path = path

    def decode_message(self, frame_id: int, data: bytes) -> Dict[str, Any]:
        if self.db is None:
            raise RuntimeError("DBC not loaded")
        msg = self.db.get_message_by_frame_id(frame_id)
        return msg.decode(data)
