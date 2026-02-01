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

from typing import Dict, Tuple, List, Any


def dbc_frame_id_map(db: Any) -> Dict[int, str]:
    """
    Returns {frame_id: message_name} for all messages in a cantools database.
    """
    out: Dict[int, str] = {}
    for m in getattr(db, "messages", []):
        try:
            fid = int(m.frame_id)
            name = str(getattr(m, "name", ""))
            out[fid] = name
        except Exception:
            continue
    return out


def find_frame_id_collisions(existing: Dict[int, Tuple[str, str]], new_map: Dict[int, str], new_dbc_key: str) -> List[Tuple[int, Tuple[str, str], str]]:
    """
    existing: {frame_id: (dbc_key, msg_name)}
    new_map : {frame_id: msg_name}
    returns: [(frame_id, (old_dbc_key, old_msg_name), new_msg_name), ...]
    """
    collisions: List[Tuple[int, Tuple[str, str], str]] = []
    for fid, new_name in new_map.items():
        if fid in existing:
            collisions.append((fid, existing[fid], new_name))
    collisions.sort(key=lambda x: x[0])
    return collisions
