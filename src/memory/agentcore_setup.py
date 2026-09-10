"""
One-time setup: provisions an Amazon Bedrock AgentCore Memory resource with a
`userPreferenceMemoryStrategy`, which is purpose-built for exactly this agent's
job - extracting and storing durable user preferences from conversation events,
namespaced per founder.

Run once:
    python src/memory/agentcore_setup.py

Then copy the printed memory id into .env as AGENTCORE_MEMORY_ID. Requires AWS
credentials with AgentCore permissions configured (see README "AgentCore
deployment" section).
"""

from __future__ import annotations

import os
import sys

from bedrock_agentcore.memory import MemoryClient
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    region = os.getenv("AWS_REGION", "us-west-2")
    client = MemoryClient(region_name=region)

    print(f"Creating AgentCore Memory resource in {region}...")
    memory = client.create_memory_and_wait(
        name="ChiefOfStaffFounderPreferences",
        description="Learned founder preferences for the Chief of Staff triage agent",
        strategies=[
            {
                "userPreferenceMemoryStrategy": {
                    "name": "FounderPreferences",
                    # One namespace per founder - keeps preferences isolated
                    # if this ever becomes multi-tenant.
                    "namespaces": ["/founders/{actorId}/preferences"],
                }
            }
        ],
    )

    memory_id = memory.get("id")
    print("\nDone. Memory resource created:")
    print(f"  id:  {memory_id}")
    print(f"  arn: {memory.get('arn')}")
    print(f"\nAdd this to your .env file:\n  AGENTCORE_MEMORY_ID={memory_id}")


if __name__ == "__main__":
    if not os.getenv("AWS_REGION") and "--yes" not in sys.argv:
        print(
            "AWS_REGION not set - defaulting to us-west-2. "
            "Set AWS_REGION in .env or pass --yes to skip this notice."
        )
    main()
