"""
Real Amazon Bedrock AgentCore Memory backend for founder preferences.

This is the production swap-in for `preference_store.PreferenceStore`: same
job (persist learned preferences, render them into the system prompt), but
backed by an actual AgentCore Memory resource with a `userPreferenceMemoryStrategy`
instead of a local JSON file - so preferences survive redeploys, are isolated
per founder by namespace, and are semantically searchable.

Provisioning a memory resource is a one-time step - see
`memory/agentcore_setup.py`. Once you have a memory id, set
AGENTCORE_MEMORY_ID in .env and agent.py automatically switches to this class.

Tool wiring: rather than exposing a custom `record_preference` tool (as the
local-store path does in tools/memory_tools.py), this class exposes AgentCore's
own `agent_core_memory` tool (via Strands' AgentCoreMemoryToolProvider) directly
to the agent - so recording *and* semantic retrieval both go through AgentCore's
native memory operations.
"""

from __future__ import annotations

import os

from bedrock_agentcore.memory import MemoryClient
from strands_tools.agent_core_memory import AgentCoreMemoryToolProvider


class AgentCorePreferenceStore:
    def __init__(self, founder_id: str, memory_id: str, region: str | None = None) -> None:
        self.founder_id = founder_id
        self.memory_id = memory_id
        self.region = region or os.getenv("AWS_REGION", "us-west-2")
        self.namespace = f"/founders/{founder_id}/preferences"
        self.session_id = f"{founder_id}-chief-of-staff"

        self.client = MemoryClient(region_name=self.region)
        self.provider = AgentCoreMemoryToolProvider(
            memory_id=self.memory_id,
            actor_id=self.founder_id,
            session_id=self.session_id,
            namespace=self.namespace,
            region=self.region,
        )

    @property
    def tools(self) -> list:
        """Strands tools this store contributes to the agent (record/retrieve/list/get/delete)."""
        return self.provider.tools

    def as_prompt_block(
        self,
        query: str = "founder scheduling, email, and escalation preferences",
        top_k: int = 10,
    ) -> str:
        """Render the founder's learned preferences (retrieved via semantic
        search over AgentCore Memory) as a block for the system prompt."""
        try:
            records = self.client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=self.namespace,
                query=query,
                top_k=top_k,
            )
        except Exception as exc:  # pragma: no cover - network/AWS dependent
            return f"(Could not retrieve AgentCore memory: {exc}. Proceeding with defaults.)"

        if not records:
            return "(No learned preferences yet in AgentCore Memory - use sensible defaults and escalate when unsure.)"

        lines = []
        for r in records:
            text = r.get("content", {}).get("text") if isinstance(r.get("content"), dict) else None
            lines.append(f"- {text or r}")
        return "\n".join(lines)
