# Contributing

Chief of Staff is open to contributions under the Apache License 2.0. No
special access needed — fork, branch, PR.

## Workflow

1. Fork the repo, branch off `master`.
2. Make your change. Keep PRs focused — one change, one PR.
3. `pip install -r requirements-dev.txt && pytest -q` before opening the PR.
   CI runs the same suite on every PR.
4. Open the PR against `master` with a short description of what and why.

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

## Adding a new tool / connector

This is the highest-value contribution and the codebase is set up as a
plugin-like pattern for it — Gmail+Calendar, Jira, Slack, and GitHub all
follow the same shape (see `src/chief_of_staff/integrations.py`). Adding a
new one (Notion, Linear, Zoom, whatever people actually need) touches these
spots, roughly in order:

1. **`src/chief_of_staff/integrations.py`**
   - Add the provider to `PROVIDERS` (name, env prefix, OAuth `auth`/`token`
     URLs, scopes).
   - Add a branch in `auth_url()` and `finish_oauth()` for anything the
     provider needs beyond the default OAuth dance (Jira and Slack both
     have provider-specific quirks there — read those branches first).
   - Add an allow-list entry in `Transport.request()` — the model never
     gets a raw HTTP client, only fixed endpoints this list permits.
   - Add a `<Provider>Connector` class with `sync()` (pull items into the
     common `item(...)` shape) and `execute()` (perform one approved
     action). Look at `GitHubConnector` — it's the newest and closest
     template to follow.

2. **`src/chief_of_staff/service.py`**
   - Add the new `action_kind`s to `ACTION_KINDS`.
   - Wire the connector into `Service.connector()`.
   - Add a case to `Service.samples()` (sample-mode demo data) and
     `Service.in_scope()` if the provider needs scope selection (a repo
     picker, a site picker — see how Jira/GitHub do this vs. Slack's
     channel picker).

3. **`web/app.py`** — if the provider needs a scope-selection step (which
   repos/sites/channels to include), add routes mirroring `repos()` +
   `save_repos()` (GitHub, split GET/POST) or `sites()` (Jira, one
   combined GET/POST route) — either shape is fine, match whichever reads
   better for the new provider.

4. **Templates** — add the provider to the connect-tools grid in
   `web/templates/index.html`, and a picker template if it needs one
   (copy `repos.html`).

5. **Tests** — `tests/test_integrations.py` has the OAuth/transport
   contract tests; follow the existing per-provider pattern there.

Open an issue first if you're not sure the provider fits the model (source
items → proposed actions → human-approved writes) before building the
whole thing.

## Reporting issues

Open a GitHub issue. Include repro steps and, for anything touching a
connector (Gmail/Jira/Slack/GitHub), which provider and whether you're in
sample or live mode.
