# Connecting Chief of Staff

Create OAuth apps owned by you, add their client IDs and secrets to `.env`, restart the server, and use **Connections**. The server never asks you to paste provider access tokens into chat or the portal.

## Base URL and private access

For local Google/Jira testing, the default callback origin is `http://127.0.0.1:5087`. Register each callback exactly. For Slack, use a HTTPS deployment or a tunnel:

```dotenv
COS_BASE_URL=https://your-private-host.example
COS_ENV=production
# Also configure MongoDB, stable application keys, and SMTP; see deploy/README.md.
```

Use the same HTTPS origin to sign in and initiate OAuth, so the session-bound `state` cookie survives the redirect. For a tunnel, keep the local server running and protect the public portal with the owner password. The application does not trust arbitrary forwarded headers. Configure the proxy to preserve the registered Host header.

## Gmail and Google Calendar

1. In Google Cloud Console, create a project and enable **Gmail API** and **Google Calendar API**.
2. Configure the OAuth consent screen. Add your test account while the application is in testing.
3. Create a **Web application** OAuth client.
4. Register `COS_BASE_URL/oauth/google/callback` as an authorized redirect URI.
5. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` and restart the app.
6. Select the organization, click **Connect Google account**, and grant both scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/calendar.events`
7. Add other accounts with the same button. Switch to Live mode separately when ready.

Offline access is requested so the worker can refresh tokens. Testing-mode grants and administrator policies can limit grant lifetime. Public distribution involving Gmail restricted scopes may require Google verification; a local test connection is not evidence of public verification.

Provider documentation: [Web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Gmail sending and MIME](https://developers.google.com/workspace/gmail/api/guides/sending), [Calendar events patch](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch).

## Jira Cloud

1. In the Atlassian developer console, create an **OAuth 2.0 (3LO)** app.
2. Configure `COS_BASE_URL/oauth/jira/callback` as its callback.
3. Add Jira classic scopes `read:jira-work`, `write:jira-work`, `read:jira-user`, and `offline_access`.
4. Set `ATLASSIAN_CLIENT_ID` and `ATLASSIAN_CLIENT_SECRET` and restart.
5. Connect the account. Then select **Choose sites** on the connection card.
6. Choose only the sites relevant to the selected organization. Until you select sites, no Jira issues are collected.
7. Set the organization’s JQL under Automation. The default monitors your unresolved assigned issues.

The service calls `api.atlassian.com/ex/jira/{cloudId}/rest/api/3`, uses enhanced `/search/jql`, and looks up transition IDs at execution time. An account can be mapped into multiple organization workspaces with different selected sites; its refresh-token updates propagate to its other mappings.

Provider documentation: [Atlassian OAuth 3LO](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/), [Jira issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).

## Slack — required core integration

1. Create a Slack app and a bot user. Set `COS_BASE_URL` to your HTTPS origin.
2. Register `COS_BASE_URL/oauth/slack/callback` under OAuth & Permissions.
3. Add bot scopes `channels:read`, `channels:history`, `groups:read`, `groups:history`, and `chat:write`.
4. Set `SLACK_CLIENT_ID` and `SLACK_CLIENT_SECRET` and restart.
5. Click **Connect Slack**, select the intended Slack workspace, and authorize installation.
6. Invite the bot to the public/private channels you want it to monitor.
7. Select **Choose channels** on the connection card and save up to five. Zero selected channels means no Slack messages are collected.
8. Repeat the installation for additional Slack workspaces or switch organization before connecting its workspace.

Approved replies appear as the bot, in the original source thread. The code prevents the model from selecting an arbitrary channel, suppresses link previews, and escapes Slack mention markup. Sync is intentionally bounded to 15 recent messages per selected channel; it does not read private DMs or claim to index all Slack history. Provider rate limits surface as connection errors rather than aggressive automatic retries.

Provider documentation: [Slack OAuth](https://docs.slack.dev/authentication/installing-with-oauth/), [Channel history](https://docs.slack.dev/reference/methods/conversations.history/), [Posting messages](https://docs.slack.dev/reference/methods/chat.postMessage/).

## Verify with your own test accounts

Start in Sample mode. After configuring OAuth, use dedicated test accounts/channels and Live mode:

1. Run a briefing. Confirm each connection reports a successful sync or a clear provider error.
2. Inspect the decision’s account, destination, source context, and exact payload.
3. Approve one test action. Verify it directly in the provider and compare with Activity.
4. Re-run the briefing; unchanged inputs should not generate duplicate actions.
5. Disconnect a test account and confirm pending actions are canceled.

A disconnected account’s token is removed locally. Revoke the app in the provider console to revoke the grant itself. Keep the encryption key with database backups; losing that key requires reconnecting accounts.
