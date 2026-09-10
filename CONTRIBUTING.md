# Contributing

Chief of Staff is open to contributions under the Apache License 2.0. No
special access needed — fork, branch, PR.

## Workflow

1. Fork the repo, branch off `main`.
2. Make your change. Keep PRs focused — one change, one PR.
3. `pip install -r requirements-dev.txt && pytest -q` before opening the PR.
   CI runs the same suite on every PR.
4. Open the PR against `main` with a short description of what and why.

## Ground rules

- By submitting a Contribution, you agree it's licensed under Apache-2.0
  along with the rest of the project (see `LICENSE`), per section 5 of
  that license — no separate CLA.
- Don't commit secrets, `.env` files, or real OAuth credentials. `.env.example`
  documents every variable the app needs; never put real values there.
- Match the existing code style in the file you're touching rather than
  reformatting unrelated lines.
- New behavior needs a test where the existing suite has a pattern for it
  (`tests/test_integrations.py`, `tests/test_web.py`, etc.).

## Where things live

See `docs/architecture.md` for the system overview before making a
structural change — in particular, the web process (`web/app.py`) never
calls an external provider directly; all of that goes through the worker
(`src/chief_of_staff/worker.py`) via the job queue.

## Reporting issues

Open a GitHub issue. Include repro steps and, for anything touching a
connector (Gmail/Jira/Slack/GitHub), which provider and whether you're in
sample or live mode.
