from __future__ import annotations

from strands import tool

from memory.escalation_store import EscalationStore


def build_escalation_tools(escalations: EscalationStore) -> list:

    @tool
    def escalate_item(item_type: str, item_id: str, reason: str, suggested_action: str) -> str:
        """
        Escalate an email or calendar request to the founder instead of handling
        it autonomously. Use this for anything involving money, legal/contract
        terms, an ambiguous or high-stakes relationship, or any situation not
        covered by a known preference rule. Always give a concrete reason and a
        concrete suggested action - never escalate with a vague "not sure".

        Args:
            item_type: either "email" or "calendar_request".
            item_id: the id of the item being escalated.
            reason: a short, specific reason this needs a human decision.
            suggested_action: what you'd do if the founder says go ahead.
        """
        esc = escalations.add(item_type, item_id, reason, suggested_action)
        return f"Escalated as {esc.id}: {reason}"

    return [escalate_item]
