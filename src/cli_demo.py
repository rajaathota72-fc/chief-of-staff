"""
Interactive terminal demo for Chief of Staff.

Flow:
  1. Reset the mock inbox/calendar to seed data (fresh demo state).
  2. Run one triage pass and print the digest (what got handled autonomously,
     what got escalated and why).
  3. Walk through the open escalations one at a time and let you respond -
     approve the suggested action, or give a correction. Corrections get
     written to preference memory via the agent, so a second run behaves
     differently.
  4. Offer to run a second triage pass so you can see the memory take effect.

Run: `python src/cli_demo.py` (from repo root, with the venv activated and
ANTHROPIC_API_KEY set in .env).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import build_agent  # noqa: E402
from connectors.mock_connector import reset_demo_data  # noqa: E402

TRIAGE_PROMPT = """\
Please triage the inbox and calendar now: review every unread email and every \
pending meeting request, take action on what you're confident about, escalate \
what you're not, and give me the end-of-run digest.\
"""


def hr(char: str = "-") -> None:
    print(char * 72)


def main() -> None:
    founder_id = os.getenv("FOUNDER_ID", "demo-founder")

    print("Chief of Staff — demo")
    hr("=")
    print(f"Founder: {founder_id}")
    print("Resetting demo inbox/calendar to seed data...")
    reset_demo_data()

    agent, prefs, escalations = build_agent(founder_id)

    print("\nLearned preferences going into this run:")
    print(prefs.as_prompt_block())
    hr("=")

    print("\nRunning triage pass #1...\n")
    result = agent(TRIAGE_PROMPT)
    print(result)
    hr("=")

    open_escalations = escalations.list_open()
    if not open_escalations:
        print("\nNo open escalations. Nothing needs you today.")
        return

    print(f"\n{len(open_escalations)} item(s) need your input:\n")
    for esc in open_escalations:
        hr()
        print(f"[{esc.id}] ({esc.item_type} {esc.item_id})")
        print(f"Why it's escalated: {esc.reason}")
        print(f"Agent's suggested action: {esc.suggested_action}")
        choice = input(
            "\n  (a) approve suggested action   "
            "(c) give a correction/instruction   "
            "(s) skip for now\n  > "
        ).strip().lower()

        if choice == "a":
            escalations.resolve(esc.id, f"Approved: {esc.suggested_action}")
            print("  -> Approved. (In production this would trigger the actual send/book action.)")
        elif choice == "c":
            correction = input("  What should the agent do instead / remember going forward?\n  > ").strip()
            if correction:
                # Feed the correction back to the agent so it decides whether/how
                # to record it as a standing preference via record_preference.
                followup = (
                    f"For escalation {esc.id} ({esc.reason}), here's my correction: "
                    f"{correction}. Please remember this as a standing preference "
                    f"if it's a general rule, then confirm what you'll do differently next time."
                )
                response = agent(followup)
                print(f"\n  Agent: {response}")
                escalations.resolve(esc.id, f"Corrected: {correction}")
        else:
            print("  -> Left open.")

    hr("=")
    again = input("\nRun a second triage pass to see memory in effect? (y/n)\n> ").strip().lower()
    if again == "y":
        print("\nLearned preferences going into pass #2:")
        print(prefs.as_prompt_block())
        hr()
        # Rebuild the agent so the system prompt picks up any newly recorded preferences.
        agent2, _, _ = build_agent(founder_id)
        print("\nRunning triage pass #2...\n")
        print(agent2(TRIAGE_PROMPT))


if __name__ == "__main__":
    main()
