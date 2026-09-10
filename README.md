# Chief of Staff

**Your work, moving quietly.** A background professional agent built with the **Strands Agents SDK** that connects Gmail, Google Calendar, Jira, and Slack. It correlates loose ends, prepares concrete next steps, handles permitted routine actions, and brings the consequential decisions to you.

A client asks for extra scope in Gmail. A Jira issue is blocked on that scope. Someone asks for an update in Slack. Chief of Staff prepares a coherent response across that workflow, instead of treating each notification as unrelated work.

**Track:** Professional Agents · **License:** Apache-2.0

## Run locally

Python 3.11+; MongoDB Atlas or a replica set; SMTP for account verification.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env only if you do not already have .env.
# Configure MongoDB, stable keys, and SMTP first.
python web/app.py
# Separate terminal:
python src/run_worker.py
```

Follow [deployment and environment setup](deploy/README.md). Sign up, verify your email, create an organization, then explore sample accounts or connect your tools. Sample simulation does not call external providers or a model. Live mode uses Strands and requires model credentials.

## Implemented workflows

| Tool | Reads | Executes |
|---|---|---|
| Gmail | Unread inbox messages and message/thread metadata | Save reply drafts, mark as read, send an approved reply in the source thread |
| Google Calendar | Upcoming events and pending invitations | Accept, decline, or tentatively respond to an invitation; acceptance checks conflicts |
| Jira Cloud | Issues matching your organization’s JQL in selected authorized sites | Post approved comments and resolve an approved transition name against the issue’s actual workflow |
| Slack | Recent messages from selected channels the bot has joined | Post an approved bot reply in the source thread |

The portal supports multiple organizations and multiple account connections. Each organization has its own context, preference memory, operating mode, schedule, decision queue, and activity history. Jira site selection and Slack channel selection bound the context further. Users sign up and verify their email. Organizations have owner, admin, member and viewer permissions, invitations, and separate connected accounts.

## What happens during a briefing

1. A request or saved schedule queues a durable job; the browser returns immediately.
2. The worker reads connected sources into MongoDB and skips unchanged, already-processed items.
3. The Strands agent receives only the selected organization’s source snapshot and owner preferences.
4. Its typed `propose_action` tool creates structured actions tied to specific source items. It cannot choose arbitrary API URLs, recipients, accounts, or organizations.
5. A separate execution service applies policy. Automatic drafts and optionally mark-as-read actions can run quietly. Email sends, Calendar RSVPs, Jira writes, and Slack posts require human approval.
6. An approval saves the exact edited payload and queues execution. Only a confirmed provider response marks it succeeded.
7. A timeout or interrupted write becomes **uncertain** and is never automatically resent. The owner checks the provider and closes the review.

Model-provided source content is treated as untrusted data. Owners, admins and members can add standing preferences. Preferences guide planning but cannot bypass approval policy.

## Connect accounts

See [integration setup](docs/integrations.md) for provider consoles, scopes, callbacks, and verification steps. OAuth credentials stay in the server environment; encrypted account tokens stay in MongoDB. Never commit `.env`, database files, or encryption keys.

- **Google:** one sign-in grants Gmail and Calendar access for an account.
- **Jira:** an Atlassian 3LO grant can authorize multiple sites. Choose the sites relevant to each organization. Rotating tokens are shared only across mappings of the same account granted by the same user.
- **Slack:** install a bot into each workspace; invite it to channels and choose up to five to monitor. Slack requires an HTTPS OAuth callback. Private channels are available only after the bot is invited.

Connecting an account does not switch the workspace to live mode or silently authorize message sending.

## Scheduling and deployment

The separate worker runs saved schedules and queued approvals independently of the browser. MongoDB persists the queue and elects one worker. Interrupted external writes are held as uncertain for manual review.

See [deployment](deploy/README.md), [architecture](docs/architecture.md), and [integration setup](docs/integrations.md). This implementation needs deployment credentials and real-provider validation before public launch. Existing SQLite data is preserved but not automatically migrated.

## Tests

```sh
pip install -r requirements-dev.txt
pytest -q
```

The suite runs offline with MongoDB and provider test doubles plus a scripted Strands model. It covers account verification, organization isolation, roles, invitations, approvals, recovery, and connector request construction. An opt-in real MongoDB replica-set test also covers rollback and the approval workflow (`COS_TEST_MONGODB_URI`). Real Atlas, SMTP, OAuth, and model access must be validated in your deployment.
