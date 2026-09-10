"""
Escalation queue: the small set of items the agent decided it should NOT
handle alone. This is the whole point of the agent - most of the inbox/
calendar gets processed silently, and only this list surfaces to the founder.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class Escalation:
    id: str
    item_type: str  # "email" | "calendar_request"
    item_id: str
    reason: str
    suggested_action: str
    created_at: str
    status: str = "open"  # "open" | "resolved"
    resolution: str | None = None


class EscalationStore:
    # Strands can dispatch multiple tool calls from one turn concurrently (each
    # on its own thread), so read-modify-write access to the JSON file must be
    # serialized to avoid two concurrent write_text() calls interleaving and
    # corrupting the file. One lock per founder_id path would be more precise,
    # but a single process-wide lock is simpler and this store is low-volume.
    _LOCK = threading.Lock()

    def __init__(self, founder_id: str) -> None:
        self.path = DATA_DIR / f"escalations.{founder_id}.json"
        if not self.path.exists():
            self._save([])

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text())

    def _save(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, indent=2))

    def add(self, item_type: str, item_id: str, reason: str, suggested_action: str) -> Escalation:
        with self._LOCK:
            items = self._load()
            new_id = f"esc_{len(items) + 1:03d}"
            esc = Escalation(
                id=new_id,
                item_type=item_type,
                item_id=item_id,
                reason=reason,
                suggested_action=suggested_action,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            items.append(asdict(esc))
            self._save(items)
            return esc

    def list_open(self) -> list[Escalation]:
        return [Escalation(**e) for e in self._load() if e["status"] == "open"]

    def resolve(self, escalation_id: str, resolution: str) -> None:
        with self._LOCK:
            items = self._load()
            for e in items:
                if e["id"] == escalation_id:
                    e["status"] = "resolved"
                    e["resolution"] = resolution
            self._save(items)

    def reset(self) -> None:
        with self._LOCK:
            self._save([])
