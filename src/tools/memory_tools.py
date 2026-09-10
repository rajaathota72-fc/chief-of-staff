from __future__ import annotations

from strands import tool

from memory.preference_store import PreferenceStore


def build_memory_tools(prefs: PreferenceStore) -> list:

    @tool
    def record_preference(rule: str, category: str) -> str:
        """
        Record a new learned preference, based on an explicit founder correction
        or instruction (e.g. "actually, always CC Alex on hiring emails"). Do NOT
        call this speculatively - only when the founder has just told you a rule
        to remember, either directly or by correcting a decision you made.

        Args:
            rule: the plain-English rule to remember going forward.
            category: one of "scheduling", "email", "escalation", "general".
        """
        pref = prefs.add(rule=rule, category=category, source="correction")
        return f"Remembered as {pref.id}: {rule}"

    return [record_preference]
