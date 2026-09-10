# Multi-user deployment

The portal uses MongoDB for accounts, memberships, encrypted OAuth grants, source snapshots, actions, schedules, and its durable queue. Run the web service and worker separately with the same environment. MongoDB Atlas or a replica set is required because approval and queue changes use transactions. A standalone MongoDB server is not supported.

## Configure

Copy `.env.example` only if `.env` does not already exist. Set:

- `MONGODB_URI`: Atlas application connection string with a database user and network access from your deployment. Keep it server-side.
- `MONGODB_DATABASE`: application database, default `chief_of_staff`.
- `FLASK_SECRET_KEY`: generate with `python -c 'import secrets; print(secrets.token_hex(32))'`.
- `COS_ENCRYPTION_KEY`: generate with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
- `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_FROM`, and authenticated provider credentials `SMTP_USERNAME` / `SMTP_PASSWORD`. SMTP must support STARTTLS. Verification, reset, and invitation emails are sent by the worker.
- One model provider: Anthropic API key, or AWS credentials/workload role and Bedrock model access.
- Google, Atlassian and Slack client IDs/secrets as described in [integrations](../docs/integrations.md).

Keep both application keys stable across restarts and replicas. Back up the encryption key separately from MongoDB; losing it makes existing grants unreadable. Customers do not supply provider client secrets.

## Local start

```sh
pip install -r requirements.txt
python web/app.py
# In a second terminal, with the same .env:
python src/run_worker.py
```

Without MongoDB and the encryption key, development shows a setup screen. Sign up, open the verification email, create an organization, and connect accounts or explore the sample simulation. Set `COS_SIGNUP_ENABLED=0` to close new registrations.

## Hosted start

Set `COS_ENV=production`, `COS_BASE_URL=https://your-domain.example`, stable keys and SMTP. Production fails startup if these prerequisites or MongoDB are missing. Put an HTTPS reverse proxy in front of port 5087, preserving the public Host header. Do not expose the internal HTTP port directly.

```sh
docker compose up --build -d
```

Both containers connect to your external Atlas database. The web service never starts a worker. A MongoDB lease elects one queue consumer; jobs are currently serialized, so this is a small-deployment architecture, not unlimited parallel processing. `/health` returns database readiness. Monitor worker logs, failed runs and account-email failures separately.

Register the exact public `/oauth/google/callback`, `/oauth/jira/callback`, and `/oauth/slack/callback` URLs in the respective provider consoles. Complete the providers' distribution/verification requirements before onboarding outside their testing allowances. Configure a verified SMTP sender, public operator/contact details, appropriate privacy/terms text, monitoring, backups and restore drills before public launch. The supplied legal pages are operational drafts and need your deployment-specific review.

## Access and data

Users have verified email and server-side sessions. Each organization has owner, admin, member and viewer roles. Owners manage membership roles and organization deletion. Admins manage integrations and settings; members can approve actions; viewers read the organization. Treat every member as authorized to read that organization's connected content. Connect private accounts only to the intended team.

Approvals record the user; execution rechecks membership. Credentials are encrypted and refresh sharing is restricted to the same granting user. Removing a member disconnects their grants in that organization. Account deletion requires transferring or deleting owned organizations first. Organization history may retain contributions after a user leaves. MongoDB backups require their own retention policy.

An interrupted external write is marked uncertain and not automatically retried. Provider APIs do not offer a universal exactly-once guarantee; inspect the provider before closing an uncertain action. Do not manually requeue uncertain writes.

## Existing local data

The old SQLite database and key files are preserved and are not read by the multi-user portal. No automatic assignment of old private workspaces to new signups occurs. Start with new organizations and reconnect accounts. Keep any old data backup private; importing legacy history requires a deliberate, owner-mapped migration that is not included in this release.

## Validation

`pip install -r requirements-dev.txt && pytest -q` runs offline contracts, provider transport mocks, and a scripted Strands workflow. Most tests use mongomock. Set `COS_TEST_MONGODB_URI` to an isolated replica set to enable the real transaction and approval workflow test; it creates and deletes a unique test database. The full 52-test suite passed against a local replica set during development. This does not establish production load behavior or Atlas configuration. Before launch, test your Atlas connection, SMTP delivery, each provider's OAuth callback and an explicitly approved live action with dedicated accounts.

## AgentCore Runtime (optional)

The worker's `strands_plan()` runs the agent in-process by default (zero
AWS setup). Set `AGENTCORE_RUNTIME_ARN` (and `AGENTCORE_CALLBACK_SECRET`)
to instead have the worker invoke a deployed **Bedrock AgentCore Runtime**
for each briefing — see `src/chief_of_staff/agentcore_client.py` (the
caller), `deploy/agentcore_runtime_entrypoint.py` (what you deploy to
Runtime), and the `/internal/agentcore/propose` callback in `web/app.py`.
Deploy that entrypoint with the AgentCore starter toolkit
(`agentcore configure && agentcore launch`, pointed at
`deploy/agentcore_runtime_entrypoint.py`), then set the resulting ARN.

`deploy/agentcore_app.py` (the older single-tenant prototype) is unrelated
to this and still not the portal's deployment entry point.

## Lightsail

See `deploy/lightsail/README.md` for a systemd-based deploy (web + worker,
one instance, external Atlas) as an alternative to Docker Compose above.
