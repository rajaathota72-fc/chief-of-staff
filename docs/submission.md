# Agents for Humans — submission draft

## Project

**Chief of Staff — your work, moving quietly**

**Track:** Professional Agents

## Description

Professionals lose time not only doing small tasks, but reconstructing context across them. A client asks for extra scope in email, a Jira ticket waits for the decision, and a Slack thread asks what is happening. Calendar invitations interrupt the same workday. Each notification looks minor; together they create a second job.

Chief of Staff is a background work agent built with the Strands Agents SDK. It connects Gmail, Google Calendar, Jira, and Slack, reviews new work on a saved schedule, and correlates related requests inside each organization. It prepares concrete reply drafts, invitation responses, issue comments, workflow changes, and Slack replies.

The agent runs quietly under an explicit autonomy policy. Routine email drafts can be created automatically. Messages that leave the system and changes to meetings or projects require a review of the exact payload. Approval queues the action; a separate executor performs it and records the provider’s result. Uncertain network outcomes are held for reconciliation instead of blindly retried.

The user can connect multiple accounts and Slack workspaces across multiple organizations. Preferences, source context, schedules, and decisions remain organization-specific. Corrections become owner-written standing preferences for future Strands runs. The initial audience is professionals, small-business owners, founders, consultants, and people coordinating work across teams.

The implementation includes a responsive portal, OAuth connections, encrypted token storage, persistent job and action queues, background scheduling, duplicate protection, organization boundaries, and provider contract tests. Strands can use Amazon Bedrock or Anthropic. A clearly labeled sample simulation demonstrates the workflow without credentials; live operation uses the real Strands agent.

## Why this fits

- A repetitive, context-heavy professional task rather than a general chat assistant.
- Background runs and owner-defined autonomy, with intervention reserved for decisions.
- Cross-tool context across email, meetings, project work, and team conversation.
- An execution system with real connector methods and auditable results, not buttons that merely change a label.

## Five-minute demo script

**0:00–0:35 — Problem and audience.** “A client email, a blocked Jira issue, and a Slack question are often the same problem. Professionals waste time reconstructing that context. Chief of Staff does the follow-through work and brings back the decisions.”

**0:35–1:05 — Connected workspace.** Show Gmail + Calendar, Jira, and Slack connection cards. Show organization switching and the chosen Slack channels/Jira sites. State whether this recording uses live test accounts or the labeled sample simulation.

**1:05–1:45 — Background run.** Show the schedule and policy. Start a Strands briefing against sample or dedicated test accounts. Explain that the job continues without blocking the browser and that source content is organization-scoped.

**1:45–2:45 — Correlated decision.** Show the client’s scope request, the related Jira blocker, and a proposed Slack thread response. Edit one exact payload. Approve it. Do not describe sample actions as real provider writes.

**2:45–3:20 — Verify execution.** Show Activity reporting a confirmed result. For a live-account recording, show the result directly in Gmail/Jira/Slack. For a simulated recording, explicitly show the simulation label.

**3:20–3:50 — Memory.** Add “Draft a reply before committing to extra scope” as an organization preference. Explain that it guides future Strands planning but does not bypass approval.

**3:50–4:20 — Quiet operation.** Re-run with unchanged items; show that existing actions are not duplicated. Briefly explain the distinction between failed delivery and an uncertain outcome.

**4:20–4:50 — Architecture and close.** Show the architecture diagram, Strands/Bedrock option, durable outbox, and tests. “Less notification management. More work actually moving.”

## Submission checklist

Prepared in the repository:
- Source code and setup instructions
- Apache-2.0 license
- Architecture diagram
- Project description and demo script
- Private deployment recipe

Still requires the project owner:
- Configure OAuth apps and verify dedicated live test accounts
- Publish a public repository and expose the Apache-2.0 license in its About/README metadata
- Record and upload the final video, at most five minutes
- Supply your AWS Builder ID
- Optionally deploy and supply a live demo URL
- Optionally publish a build-story post with “Agents for Humans” in the title before the applicable deadline

Do not claim OAuth verification, public hosting, AgentCore deployment of the connected portal, or live provider validation until those steps have actually completed. Check the current event rules and deadlines before submitting.
