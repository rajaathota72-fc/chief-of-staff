"""
Preference memory: the part of this agent that actually learns.

Every time the founder corrects a decision (via cli_demo.py's review flow, or
in production via a reply/thumbs-down in the digest UI), that correction is
written here as a durable preference rule. On the next run, `get_preferences()`
is injected into the agent's context so it factors those rules into new
decisions.

This is deliberately a thin, swappable interface: in a production/AgentCore
deployment, this file is replaced by calls to AgentCore Memory (per-founder
memory namespace) - the tool functions in `tools/memory_tools.py` would not
need to change, only this module's implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class Preference:
    id: str
    rule: str  # plain-English rule, e.g. "Always CC cofounder on anything mentioning Delta Corp"
    category: str  # e.g. "scheduling", "email", "escalation"
    created_at: str
    source: str  # "correction" | "seed"


class PreferenceStore:
    def __init__(self, founder_id: str) -> None:
        self.founder_id = founder_id
        self.path = DATA_DIR / f"preferences.{founder_id}.json"
        if not self.path.exists():
            self._save([])

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text())

    def _save(self, prefs: list[dict]) -> None:
        self.path.write_text(json.dumps(prefs, indent=2))

    def list_all(self) -> list[Preference]:
        return [Preference(**p) for p in self._load()]

    def add(self, rule: str, category: str, source: str = "correction") -> Preference:
        prefs = self._load()
        new_id = f"pref_{len(prefs) + 1:03d}"
        pref = Preference(
            id=new_id,
            rule=rule,
            category=category,
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source,
        )
        prefs.append(asdict(pref))
        self._save(prefs)
        return pref

    def as_prompt_block(self) -> str:
        """Render learned preferences as a block to inject into the agent's system prompt."""
        prefs = self.list_all()
        if not prefs:
            return "(No learned preferences yet - use sensible defaults and escalate when unsure.)"
        lines = [f"- [{p.category}] {p.rule}" for p in prefs]
        return "\n".join(lines)
