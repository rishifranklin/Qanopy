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
