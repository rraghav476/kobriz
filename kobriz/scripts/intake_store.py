"""Meeting-intake ledger for the kobriz ADLC plugin.

Records which tracker tasks were created from which meeting action items, so re-running
``/kobriz:intake`` on the same meeting never creates a duplicate. Tracker creates are not
idempotent (a retried create makes a second task), so the manager checks here first.

Stored under ``<repo>/.kobriz/intake/``. Holds titles and ids only, never meeting text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from typing import Any, Dict, Optional

from config import Config, atomic_write_json, kobriz_dir, now_iso


def draft_key(title: str) -> str:
    """Stable key for an action item: case, punctuation and spacing do not matter."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    norm = re.sub(r"[\W_]+", " ", folded).strip() or title.strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


class IntakeStore:
    def __init__(self, config: Config) -> None:
        self.dir = os.path.join(kobriz_dir(config), "intake")
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, meeting_id: str) -> str:
        if not str(meeting_id).strip():
            raise ValueError("meeting id is required")
        name = hashlib.sha256(str(meeting_id).encode("utf-8")).hexdigest()[:24]
        return os.path.join(self.dir, f"{name}.json")

    def show(self, meeting_id: str) -> Dict[str, Any]:
        path = self._path(meeting_id)
        if not os.path.isfile(path):
            return {"meeting_id": str(meeting_id), "items": {}}
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def check(self, meeting_id: str, title: str) -> Optional[Dict[str, Any]]:
        """The ledger entry if this action item already became a task, else None."""
        return self.show(meeting_id)["items"].get(draft_key(title))

    def record(self, meeting_id: str, title: str, task_id: str,
               meeting_title: str = "") -> Dict[str, Any]:
        data = self.show(meeting_id)
        key = draft_key(title)
        existing = data["items"].get(key)
        if existing and existing["task_id"] != str(task_id):
            raise ValueError(f"action item already recorded as task {existing['task_id']}")
        if meeting_title:
            data["meeting_title"] = meeting_title
        data["items"][key] = {"title": title, "task_id": str(task_id), "at": now_iso()}
        atomic_write_json(self._path(meeting_id), data)
        return data["items"][key]
