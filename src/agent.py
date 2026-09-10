"""
Builds the Chief of Staff Strands Agent for a given founder.

Model provider selection: Anthropic API if ANTHROPIC_API_KEY is set, otherwise
falls back to Amazon Bedrock (Strands' default), matching the two paths judges/
graders are most likely to have credentials for.

Memory provider selection: if AGENTCORE_MEMORY_ID is set, preference memory is
backed by real Amazon Bedrock AgentCore Memory (a `userPreferenceMemoryStrategy`
namespace, one per founder) via Strands' AgentCoreMemoryToolProvider. Otherwise
it falls back to the local JSON PreferenceStore, so the demo runs with zero AWS
setup. Nothing else in this file (or in the tools/ package) needs to change
between the two - see memory/agentcore_preference_store.py for the adapter.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from strands import Agent

from connectors.mock_connector import MockCalendar, MockInbox
from memory.escalation_store import EscalationStore
from memory.preference_store import PreferenceStore
from tools.calendar_tools import build_calendar_tools
from tools.email_tools import build_email_tools
from tools.escalation_tools import build_escalation_tools
from tools.memory_tools import build_memory_tools

load_dotenv()

SYSTEM_PROMPT_TEMPLATE = """\
You are Chief of Staff, an autonomous agent that triages a startup founder's \
inbox and calendar so they don't have to touch either unless a real decision \
is needed.

For every unread email and every pending meeting request, decide ONE of:
1. HANDLE IT — call the appropriate tool (send_email_reply, book_meeting, \
decline_meeting, snooze_email) when you are confident about the right action, \
based on the founder's known preferences below and ordinary good judgment.
2. ESCALATE IT — call escalate_item when it involves money, legal/contract \
terms, an ambiguous or high-stakes relationship, a scheduling conflict with \
no clearly-correct resolution, or anything not covered by a known preference. \
Always give a specific reason and a specific suggested action.

Rules:
- Process every unread email and every pending calendar request exactly once \
this session — don't leave items untouched.
- Prefer handling over escalating whenever a preference rule clearly applies. \
Don't escalate things that are genuinely routine just to be safe — that \
defeats the point of this agent.
- Never send a reply that commits to money, legal terms, or a public/external \
statement without escalating first.
- When declining or replying, write briefly and in a friendly, direct, \
founder voice — not corporate-sounding.
- If the founder gives you an explicit instruction or correction during this \
conversation (e.g. "actually always do X"), save it as a standing preference \
using your memory tool before continuing.
- At the end, summarize in a short digest: what you handled, what you \
escalated (and why), organized as two clear lists. Be concise.

Founder's known preferences (learned from past corrections):
{preferences}
"""


def _build_model():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": api_key},
            model_id=os.getenv("MODEL_ID", "claude-sonnet-4-5-20250929"),
            max_tokens=2048,
        )
    # Falls back to Strands' default Bedrock provider, using BEDROCK_MODEL_ID
    # and standard AWS credential discovery (env vars / profile / SSO).
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        ),
        region_name=os.getenv("AWS_REGION", "us-west-2"),
    )


def build_agent(founder_id: str):
    """Returns a ready-to-invoke Agent plus its preference and escalation stores
    (the stores are returned too so the CLI/digest/web layer can read them
    directly without another tool round-trip).

    Preference memory backend is selected automatically:
    - AGENTCORE_MEMORY_ID set  -> real AgentCore Memory (see agentcore_preference_store.py)
    - otherwise                -> local JSON PreferenceStore (zero-setup demo path)
    """

    inbox = MockInbox()
    calendar = MockCalendar()
    escalations = EscalationStore(founder_id)

    agentcore_memory_id = os.getenv("AGENTCORE_MEMORY_ID")
    if agentcore_memory_id:
        from memory.agentcore_preference_store import AgentCorePreferenceStore

        prefs = AgentCorePreferenceStore(founder_id, agentcore_memory_id)
        memory_tools = prefs.tools
        memory_note = (
            "You have an `agent_core_memory` tool for preferences - use "
            'action="record" to save a new standing preference (instead of a '
            "custom record_preference tool)."
        )
    else:
        prefs = PreferenceStore(founder_id)
        memory_tools = build_memory_tools(prefs)
        memory_note = (
            "Use the record_preference tool to save a new standing preference."
        )

    tools = [
        *build_email_tools(inbox),
        *build_calendar_tools(calendar),
        *build_escalation_tools(escalations),
        *memory_tools,
    ]

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(preferences=prefs.as_prompt_block())
    system_prompt += f"\n{memory_note}\n"

    agent = Agent(
        model=_build_model(),
        system_prompt=system_prompt,
        tools=tools,
        name="chief-of-staff",
        description="Autonomous founder inbox & calendar triage agent",
    )
    return agent, prefs, escalations
