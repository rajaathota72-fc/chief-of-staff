"""
Runs one triage pass: agent processes the whole inbox + calendar in one go
and returns/prints the digest. This is the function you'd put on a schedule
(e.g. AgentCore Runtime cron, or a Lambda) to run every morning in production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import build_agent  # noqa: E402


TRIAGE_PROMPT = """\
Please triage the inbox and calendar now: review every unread email and every \
pending meeting request, take action on what you're confident about, escalate \
what you're not, and give me the end-of-run digest.\
"""


def run_digest(founder_id: str | None = None) -> str:
    founder_id = founder_id or os.getenv("FOUNDER_ID", "demo-founder")
    agent, prefs, escalations = build_agent(founder_id)
    result = agent(TRIAGE_PROMPT)
    return str(result)


if __name__ == "__main__":
    print(run_digest())
