"""
Amazon Bedrock AgentCore Runtime entrypoint for Chief of Staff.

This is what turns the agent from "a script you run locally" into "a service
that runs on a schedule" - the actual requirement behind "runs quietly in the
background." Deploy this with the AgentCore starter toolkit (see
deploy/README.md), then invoke it on a schedule (e.g. EventBridge -> Lambda ->
InvokeAgentRuntime, once every morning) instead of running cli_demo.py by hand.

Local smoke test (still needs a model credential in .env):
    python deploy/agentcore_app.py
    # in another terminal:
    curl -X POST http://localhost:8080/invocations \\
      -H "Content-Type: application/json" \\
      -d '{"founder_id": "demo-founder"}'
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from agent import build_agent  # noqa: E402

app = BedrockAgentCoreApp()

TRIAGE_PROMPT = """\
Please triage the inbox and calendar now: review every unread email and every \
pending meeting request, take action on what you're confident about, escalate \
what you're not, and give me the end-of-run digest.\
"""


@app.entrypoint
def triage(request: dict) -> dict:
    """
    Runs one triage pass for a founder and returns the digest plus the open
    escalation list, structured for a caller (e.g. a scheduler or a thin web
    front end) rather than a terminal.

    Request body: {"founder_id": "demo-founder"}
    """
    founder_id = request.get("founder_id", "demo-founder")
    agent, prefs, escalations = build_agent(founder_id)

    digest = agent(TRIAGE_PROMPT)

    return {
        "founder_id": founder_id,
        "digest": str(digest),
        "open_escalations": [
            {
                "id": e.id,
                "item_type": e.item_type,
                "item_id": e.item_id,
                "reason": e.reason,
                "suggested_action": e.suggested_action,
            }
            for e in escalations.list_open()
        ],
    }


if __name__ == "__main__":
    app.run()
