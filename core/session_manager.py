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

import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from qanopy.core.can_session import CanConfig, CanSession
from qanopy.core.datastore import DataStore


@dataclass(frozen=True)
class SessionCreateRequest:
    display_name: str
    can_cfg: CanConfig
    dbc_path: Optional[str] = None  # initial DBC to add (optional)


class SessionManager:
    def __init__(
        self,
        datastore: DataStore,
        on_error: Callable[[str, str], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.datastore = datastore
        self.on_error = on_error
        self.on_status = on_status
        self._sessions: Dict[str, CanSession] = {}
        self._session_names: List[str] = []

    def create_session(self, req: SessionCreateRequest) -> str:
        if req.display_name in self._session_names:
            return None

        session_id = uuid.uuid4().hex[:8]
        s = CanSession(
            session_id=session_id,
            display_name=req.display_name,
            can_cfg=req.can_cfg,
            datastore=self.datastore,
            on_error=self.on_error,
            on_status=self.on_status,
        )

        if req.dbc_path:
            s.add_dbc(req.dbc_path)

        self._sessions[session_id] = s
        self._session_names.append(s.display_name)
        return session_id

    def get(self, session_id: str) -> CanSession:
        try:
            return self._sessions[session_id]
        except:
            return None

    def all_sessions(self) -> Dict[str, CanSession]:
        return dict(self._sessions)

    def remove_session(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s is None:
            return
        try:
            s.disconnect()
        except Exception:
            pass
        self._sessions.pop(session_id, None)
        self._session_names.remove(s.display_name)

    def connect(self, session_id: str) -> None:
        self._sessions[session_id].connect()

    def disconnect(self, session_id: str) -> None:
        self._sessions[session_id].disconnect()

    def shutdown_all(self) -> None:
        for sid in list(self._sessions.keys()):
            try:
                self._sessions[sid].disconnect()
            except Exception:
                pass
