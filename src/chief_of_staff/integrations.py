"""OAuth and bounded HTTP transports for Google Workspace and Jira Cloud."""
import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import quote, urlencode
import requests

GOOGLE_SCOPES = ['https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/calendar.events']
JIRA_SCOPES = ['read:jira-work', 'write:jira-work', 'read:jira-user', 'offline_access']
GITHUB_SCOPES = ['repo']
PROVIDERS = {
    'google': {'name': 'Google Workspace', 'env': 'GOOGLE', 'auth': 'https://accounts.google.com/o/oauth2/v2/auth', 'token': 'https://oauth2.googleapis.com/token', 'scopes': GOOGLE_SCOPES},
    'slack': {'name': 'Slack', 'env': 'SLACK', 'auth': 'https://slack.com/oauth/v2/authorize', 'token': 'https://slack.com/api/oauth.v2.access', 'scopes': ['channels:read', 'channels:history', 'groups:read', 'groups:history', 'chat:write']},
    'jira': {'name': 'Jira Cloud', 'env': 'ATLASSIAN', 'auth': 'https://auth.atlassian.com/authorize', 'token': 'https://auth.atlassian.com/oauth/token', 'scopes': JIRA_SCOPES},
    'github': {'name': 'GitHub', 'env': 'GITHUB', 'auth': 'https://github.com/login/oauth/authorize', 'token': 'https://github.com/login/oauth/access_token', 'scopes': GITHUB_SCOPES},
}


class IntegrationError(Exception):
    pass


class UncertainDelivery(IntegrationError):
    """A write may have reached the provider; never automatically retry it."""


def configured(provider):
    prefix = PROVIDERS[provider]['env']
    return bool(os.getenv(prefix + '_CLIENT_ID') and os.getenv(prefix + '_CLIENT_SECRET'))


def redirect_uri(provider):
    return os.getenv('COS_BASE_URL', 'http://127.0.0.1:5087').rstrip('/') + '/oauth/' + provider + '/callback'


def auth_url(provider, state):
    conf = PROVIDERS[provider]
    if not configured(provider):
        raise IntegrationError(f"Configure {conf['env']}_CLIENT_ID and {conf['env']}_CLIENT_SECRET first.")
    params = {'client_id': os.environ[conf['env'] + '_CLIENT_ID'], 'redirect_uri': redirect_uri(provider), 'response_type': 'code', 'scope': ' '.join(conf['scopes']), 'state': state}
    if provider == 'slack':
        uri = redirect_uri(provider)
        # Slack requires HTTPS, with an explicit exception for localhost during development.
        if not uri.startswith('https://') and not uri.startswith(('http://localhost', 'http://127.0.0.1')):
            raise IntegrationError('Slack requires an HTTPS callback. Set COS_BASE_URL to your HTTPS deployment or tunnel URL.')
        params['scope'] = ','.join(conf['scopes'])
        return conf['auth'] + '?' + urlencode(params)
    if provider == 'github':
        return conf['auth'] + '?' + urlencode({'client_id': params['client_id'], 'redirect_uri': params['redirect_uri'], 'scope': params['scope'], 'state': state, 'allow_signup': 'false'})
    params.update({'access_type': 'offline', 'prompt': 'consent select_account'} if provider == 'google' else {'audience': 'api.atlassian.com', 'prompt': 'consent'})
    return conf['auth'] + '?' + urlencode(params)


def token_request(provider, values):
    conf = PROVIDERS[provider]
    data = dict(values, client_id=os.getenv(conf['env'] + '_CLIENT_ID'), client_secret=os.getenv(conf['env'] + '_CLIENT_SECRET'))
    try:
        response = requests.post(conf['token'], **({'data': data} if provider in ('google', 'slack', 'github') else {'json': data}), headers={'Accept': 'application/json'}, timeout=25)
    except requests.RequestException:
        raise IntegrationError('The sign-in service is unavailable. Try reconnecting.') from None
    if response.status_code != 200:
        raise IntegrationError('Authorization expired or was declined. Reconnect this account.')
    tokens = response.json()
    if tokens.get('ok') is False:
        raise IntegrationError('Slack authorization failed. Check app permissions and reconnect.')
    if tokens.get('error'):
        raise IntegrationError('GitHub authorization failed. Check app permissions and reconnect.')
    # GitHub OAuth App tokens (unlike Google/Jira) don't expire and carry no refresh_token by default.
    tokens['expires_at'] = time.time() + tokens.get('expires_in', 10**9 if provider in ('slack', 'github') else 3600)
    return tokens


def finish_oauth(store, provider, code, org_id, owner_id=None):
    tokens = token_request(provider, {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(provider)})
    headers = {'Authorization': 'Bearer ' + tokens['access_token']}
    try:
        if provider == 'google':
            response = requests.get('https://gmail.googleapis.com/gmail/v1/users/me/profile', headers=headers, timeout=25)
            response.raise_for_status()
            email = response.json()['emailAddress']
            granted = tokens.get('scope', '').split()
            if not all(scope in granted for scope in GOOGLE_SCOPES):
                raise IntegrationError('Grant Gmail and Calendar access together to connect this account.')
            if not tokens.get('refresh_token'):
                raise IntegrationError('Offline access was not granted. Remove the previous grant in Google and reconnect.')
            store.connect('google', email, tokens, {'identity': email, 'email': email}, org_id=org_id, owner_id=owner_id)
        elif provider == 'slack':
            granted = tokens.get('scope', '').split(',')
            if not all(scope in granted for scope in PROVIDERS['slack']['scopes']):
                raise IntegrationError('The Slack grant is missing required channel permissions.')
            team = tokens.get('team')
            if not team or not team.get('id'):
                raise IntegrationError('Install into an individual Slack workspace, rather than an enterprise-wide grant.')
            store.connect('slack', team['name'], tokens, {'identity': team['id'], 'team_id': team['id'], 'bot_user_id': tokens.get('bot_user_id'), 'channels': []}, org_id=org_id, owner_id=owner_id)
        elif provider == 'github':
            granted = {s.strip() for s in tokens.get('scope', '').split(',') if s.strip()}
            if not all(scope in granted for scope in PROVIDERS['github']['scopes']):
                raise IntegrationError('Grant repository access to connect this account.')
            response = requests.get('https://api.github.com/user', headers={**headers, 'Accept': 'application/vnd.github+json'}, timeout=25)
            response.raise_for_status()
            account = response.json()
            store.connect('github', account['login'], tokens, {'identity': account['login'], 'repos': []}, org_id=org_id, owner_id=owner_id)
        else:
            response = requests.get('https://api.atlassian.com/oauth/token/accessible-resources', headers=headers, timeout=25)
            response.raise_for_status()
            sites = [s for s in response.json() if 'read:jira-work' in s.get('scopes', []) and 'write:jira-work' in s.get('scopes', [])]
            if not sites:
                raise IntegrationError('No Jira sites with read and write access were granted.')
            # One grant per Atlassian user, with all sites under that grant. A shared refresh token must not be rotated per site.
            profile = requests.get('https://api.atlassian.com/ex/jira/' + quote(sites[0]['id'], safe='') + '/rest/api/3/myself', headers=headers, timeout=25)
            profile.raise_for_status()
            account = profile.json()
            store.connect('jira', account.get('displayName', 'Jira account'), tokens,
                          {'identity': account['accountId'], 'selected_sites': [], 'sites': [{'id': s['id'], 'name': s['name'], 'url': s['url']} for s in sites]}, org_id=org_id, owner_id=owner_id)
    except requests.RequestException:
        raise IntegrationError('Could not verify account access. Check the enabled APIs and OAuth scopes.') from None
    store.event(PROVIDERS[provider]['name'] + ' connected successfully.')


_TOKEN_LOCK = threading.Lock()


class Transport:
    def __init__(self, store, connection_id):
        self.store, self.cid = store, connection_id

    def request(self, method, path, *, site=None, params=None, body=None, etag=None):
        self.store.check_execution()
        with _TOKEN_LOCK:
            conn = self.store.connection(self.cid, secret=True)
            if not conn or conn['status'] != 'connected':
                raise IntegrationError('Account is disconnected. Reconnect before continuing.')
            tokens = conn['secrets']
            if tokens.get('expires_at', 0) < time.time() + 60:
                if not tokens.get('refresh_token'):
                    raise IntegrationError('Offline access expired. Reconnect the account.')
                new = token_request(conn['provider'], {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']})
                tokens.update(new)
                self.store.save_tokens(self.cid, tokens)
            access = tokens['access_token']
        if conn['provider'] == 'google':
            if not path.startswith(('/gmail/v1/', '/calendar/v3/')):
                raise ValueError('Unsupported Google endpoint')
            base = 'https://www.googleapis.com'
        elif conn['provider'] == 'slack':
            if path not in ('/conversations.list', '/conversations.history', '/chat.postMessage'):
                raise ValueError('Unsupported Slack endpoint')
            base = 'https://slack.com/api'
        elif conn['provider'] == 'jira':
            if site not in [s['id'] for s in conn['metadata']['sites']] or not path.startswith('/rest/api/3/'):
                raise ValueError('Unsupported Jira site or endpoint')
            base = 'https://api.atlassian.com/ex/jira/' + quote(site, safe='')
        else:
            if not (path == '/user/repos' or path.startswith('/search/issues') or path.startswith('/repos/')):
                raise ValueError('Unsupported GitHub endpoint')
            base = 'https://api.github.com'
        accept = 'application/vnd.github+json' if conn['provider'] == 'github' else 'application/json'
        headers = {'Authorization': 'Bearer ' + access, 'Accept': accept, **({'If-Match': etag} if etag else {}), **({'X-GitHub-Api-Version': '2022-11-28'} if conn['provider'] == 'github' else {})}
        try:
            response = requests.request(method, base + path, headers=headers, params=params, json=body, timeout=(10, 35), allow_redirects=False)
        except requests.RequestException:
            if method != 'GET':
                raise UncertainDelivery('Delivery could not be confirmed. Check the provider before closing this item.') from None
            raise IntegrationError('The provider could not be reached. Try syncing later.') from None
        if response.status_code >= 500 and method != 'GET':
            raise UncertainDelivery('The provider returned an error after the request. Check whether the action completed.')
        if response.status_code == 429:
            raise IntegrationError('Provider rate limit reached. Wait before retrying.')
        if response.status_code in (401, 403):
            raise IntegrationError('Account access is missing or expired. Reconnect and check permissions.')
        if not 200 <= response.status_code < 300:
            raise IntegrationError(f'Provider rejected the request (HTTP {response.status_code}). Refresh the source item before trying again.')
        result = response.json() if response.content else {}
        if conn['provider'] == 'slack' and not result.get('ok'):
            raise IntegrationError('Slack rejected the request. Check channel membership and granted permissions.')
        return result


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def message_body(payload):
    chunks = []
    def walk(part):
        if part.get('mimeType') in ('text/plain', 'text/html') and part.get('body', {}).get('data'):
            data = part['body']['data']
            value = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf8', errors='replace')
            if part['mimeType'] == 'text/html':
                parser = TextOnly(); parser.feed(value); value = ' '.join(parser.parts)
            chunks.append((part['mimeType'], value))
        for child in part.get('parts', []): walk(child)
    walk(payload)
    plain = [value for kind, value in chunks if kind == 'text/plain']
    return '\n'.join(plain or [v for _, v in chunks])[:12000]


def item(kind, external_id, title, body, data, revision=None):
    revision = revision or hashlib.sha256(json.dumps([title, body, data], sort_keys=True).encode()).hexdigest()
    return dict(kind=kind, external_id=external_id, title=title, body=body, data=data, revision=str(revision))


class GoogleConnector:
    def __init__(self, transport): self.http = transport

    def sync(self):
        result = []
        # Bound each sweep; pagination continues until the batch cap. Processed items are deduplicated in SQLite.
        messages = self.http.request('GET', '/gmail/v1/users/me/messages', params={'q': 'is:unread in:inbox', 'maxResults': 50})
        for ref in messages.get('messages', []):
            m = self.http.request('GET', '/gmail/v1/users/me/messages/' + quote(ref['id'], safe=''), params={'format': 'full'})
            headers = {h['name'].lower(): h['value'] for h in m.get('payload', {}).get('headers', [])}
            data = {'sender': headers.get('from', ''), 'subject': headers.get('subject', '(No subject)'), 'thread_id': m['threadId'],
                    'reply_to': headers.get('reply-to', headers.get('from', '')), 'message_id': headers.get('message-id', ''), 'references': headers.get('references', '')}
            result.append(item('email', m['id'], data['subject'], message_body(m.get('payload', {})), data, m['id']))
        now = datetime.now(timezone.utc)
        events = self.http.request('GET', '/calendar/v3/calendars/primary/events', params={'timeMin': now.isoformat(), 'timeMax': (now + timedelta(days=14)).isoformat(), 'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 100})
        for event in events.get('items', []):
            if event.get('status') == 'cancelled': continue
            mine = next((a for a in event.get('attendees', []) if a.get('self')), None)
            data = {'start': event.get('start', {}), 'end': event.get('end', {}), 'attendees': event.get('attendees', []), 'organizer': event.get('organizer', {}), 'etag': event.get('etag'), 'pending': bool(mine and mine.get('responseStatus') == 'needsAction')}
            result.append(item('calendar', event['id'], event.get('summary', '(Untitled event)'), event.get('description', '')[:12000], data, event.get('etag')))
        return result

    def execute(self, action, source):
        payload, kind = action['payload'], action['kind']
        mid = quote(source['external_id'], safe='')
        if kind in ('email_draft', 'email_reply'):
            # Re-read authoritative headers; model output can never choose a new recipient.
            current = self.http.request('GET', '/gmail/v1/users/me/messages/' + mid, params={'format': 'metadata', 'metadataHeaders': ['From', 'Reply-To', 'Subject', 'Message-ID', 'References']})
            headers = {h['name'].lower(): h['value'] for h in current.get('payload', {}).get('headers', [])}
            message = EmailMessage()
            recipient = parseaddr(headers.get('reply-to', headers.get('from', '')))[1]
            if not recipient or '@' not in recipient: raise IntegrationError('The source message has no valid reply address.')
            expected = parseaddr(source['data'].get('reply_to', source['data'].get('sender', '')))[1]
            if recipient.casefold() != expected.casefold():
                raise IntegrationError('The reply destination changed. Sync and review before sending.')
            message['To'] = recipient
            subject = headers.get('subject', '(No subject)')
            message['Subject'] = subject if subject.lower().startswith('re:') else 'Re: ' + subject
            if headers.get('message-id'):
                message['In-Reply-To'] = headers['message-id']
                message['References'] = (headers.get('references', '') + ' ' + headers['message-id']).strip()
            message.set_content(payload['body'])
            encoded = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode(), 'threadId': current['threadId']}
            if kind == 'email_draft':
                response = self.http.request('POST', '/gmail/v1/users/me/drafts', body={'message': encoded})
                return {'detail': 'Reply draft saved in Gmail; nothing sent.', 'provider_id': response.get('id')}
            response = self.http.request('POST', '/gmail/v1/users/me/messages/send', body=encoded)
            return {'detail': 'Reply sent in the original Gmail thread.', 'provider_id': response.get('id')}
        if kind == 'email_mark_read':
            self.http.request('POST', '/gmail/v1/users/me/messages/' + mid + '/modify', body={'removeLabelIds': ['UNREAD']})
            return {'detail': 'Email marked as read.'}
        if kind == 'calendar_rsvp':
            path = '/calendar/v3/calendars/primary/events/' + mid
            event = self.http.request('GET', path)
            if event.get('etag') != source['data'].get('etag'):
                raise IntegrationError('The invitation changed after review. Sync again before responding.')
            attendees = event.get('attendees', [])
            mine = next((a for a in attendees if a.get('self')), None)
            if not mine: raise IntegrationError('This account is not an attendee of the invitation.')
            if payload['response'] == 'accepted':
                start, end = event['start'], event['end']
                # Accept only invitations with precise timestamps; all-day events remain manual.
                if not start.get('dateTime') or not end.get('dateTime'):
                    raise IntegrationError('Respond to all-day invitations directly in Calendar.')
                conflicts = self.http.request('GET', '/calendar/v3/calendars/primary/events', params={'timeMin': start['dateTime'], 'timeMax': end['dateTime'], 'singleEvents': 'true', 'maxResults': 250})
                if conflicts.get('nextPageToken'):
                    raise IntegrationError('Too many calendar events to verify availability. Review in Calendar.')
                for other in conflicts.get('items', []):
                    own = next((a for a in other.get('attendees', []) if a.get('self')), {})
                    if other['id'] != source['external_id'] and other.get('status') != 'cancelled' and other.get('transparency') != 'transparent' and own.get('responseStatus') != 'declined':
                        raise IntegrationError('A calendar conflict was found. Review the invitation before accepting.')
            mine['responseStatus'] = payload['response']
            # attendeesOmitted permits updating only this attendee response.
            self.http.request('PATCH', path, params={'sendUpdates': 'all'}, body={'attendees': [mine], 'attendeesOmitted': True}, etag=event.get('etag'))
            return {'detail': 'Calendar response updated to ' + payload['response'] + '.'}
        raise ValueError('Unsupported Google action')


def flatten_adf(node):
    if isinstance(node, dict):
        return node.get('text', '') + ' '.join(flatten_adf(n) for n in node.get('content', []))
    return ''


def adf(text):
    return {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': line}]} for line in text.splitlines() if line.strip()]}


class JiraConnector:
    def __init__(self, transport, sites, jql): self.http, self.sites, self.jql = transport, sites, jql

    def sync(self):
        result = []
        for site in self.sites:
            data = self.http.request('POST', '/rest/api/3/search/jql', site=site['id'], body={'jql': self.jql, 'maxResults': 50, 'fields': ['summary', 'description', 'status', 'priority', 'updated', 'assignee', 'duedate']})
            for issue in data.get('issues', []):
                fields = issue['fields']
                meta = {'site': site['id'], 'site_name': site['name'], 'key': issue['key'], 'status': fields.get('status', {}).get('name'), 'priority': (fields.get('priority') or {}).get('name'), 'due': fields.get('duedate'), 'url': site['url'] + '/browse/' + issue['key'], 'updated': fields.get('updated')}
                result.append(item('jira', site['id'] + ':' + issue['key'], issue['key'] + ' · ' + fields['summary'], flatten_adf(fields.get('description'))[:12000], meta, fields.get('updated')))
        return result

    def execute(self, action, source):
        site, key = source['data']['site'], quote(source['data']['key'], safe='')
        payload = action['payload']
        if action['kind'] == 'jira_comment':
            response = self.http.request('POST', '/rest/api/3/issue/' + key + '/comment', site=site, body={'body': adf(payload['body'])})
            return {'detail': 'Comment posted to ' + source['data']['key'] + '.', 'provider_id': response.get('id')}
        if action['kind'] == 'jira_transition':
            current = self.http.request('GET', '/rest/api/3/issue/' + key, site=site, params={'fields': 'updated,status'})
            if current['fields'].get('updated') != source['data'].get('updated'):
                raise IntegrationError('The issue changed since review. Sync and review its current state.')
            transitions = self.http.request('GET', '/rest/api/3/issue/' + key + '/transitions', site=site).get('transitions', [])
            match = next((t for t in transitions if t['name'].casefold() == payload['transition'].casefold()), None)
            if not match: raise IntegrationError('That transition is unavailable for this issue. Check its Jira workflow.')
            self.http.request('POST', '/rest/api/3/issue/' + key + '/transitions', site=site, body={'transition': {'id': match['id']}})
            return {'detail': 'Moved ' + source['data']['key'] + ' using ' + match['name'] + '.'}
        raise ValueError('Unsupported Jira action')


class GitHubConnector:
    def __init__(self, transport, login, repos): self.http, self.login, self.repos_selected = transport, login, repos

    def repos(self):
        result, page = [], 1
        for _ in range(10):
            batch = self.http.request('GET', '/user/repos', params={'per_page': 100, 'page': page, 'sort': 'pushed', 'affiliation': 'owner,collaborator,organization_member'})
            result.extend({'full_name': r['full_name']} for r in batch)
            if len(batch) < 100: break
            page += 1
        return result

    def sync(self):
        result = []
        for repo in self.repos_selected:
            data = self.http.request('GET', '/search/issues', params={'q': 'repo:' + repo['full_name'] + ' is:open involves:' + self.login, 'per_page': 50, 'sort': 'updated'})
            for issue in data.get('items', []):
                is_pr = 'pull_request' in issue
                meta = {'repo': repo['full_name'], 'number': issue['number'], 'is_pr': is_pr, 'url': issue['html_url'], 'updated': issue['updated_at']}
                title = repo['full_name'] + '#' + str(issue['number']) + ' · ' + issue['title']
                result.append(item('github', repo['full_name'] + '#' + str(issue['number']), title, (issue.get('body') or '')[:12000], meta, issue['updated_at']))
        return result

    def execute(self, action, source):
        repo, number = source['data']['repo'], source['data']['number']
        path = '/repos/' + repo + '/issues/' + str(number)
        payload = action['payload']
        if action['kind'] == 'github_comment':
            response = self.http.request('POST', path + '/comments', body={'body': payload['body']})
            return {'detail': 'Comment posted to ' + repo + '#' + str(number) + '.', 'provider_id': str(response.get('id'))}
        if action['kind'] == 'github_close':
            current = self.http.request('GET', path)
            if current.get('updated_at') != source['data'].get('updated'):
                raise IntegrationError('The issue changed since review. Sync and review its current state.')
            self.http.request('PATCH', path, body={'state': 'closed'})
            return {'detail': 'Closed ' + repo + '#' + str(number) + '.'}
        raise ValueError('Unsupported GitHub action')


class SlackConnector:
    def __init__(self, transport, metadata): self.http, self.metadata = transport, metadata

    def channels(self):
        result, cursor = [], None
        for _ in range(10):
            params = {'types': 'public_channel,private_channel', 'exclude_archived': 'true', 'limit': 200}
            if cursor: params['cursor'] = cursor
            page = self.http.request('GET', '/conversations.list', params=params)
            result.extend({'id': c['id'], 'name': c['name']} for c in page.get('channels', []) if c.get('is_member'))
            cursor = page.get('response_metadata', {}).get('next_cursor')
            if not cursor: break
        return result

    def sync(self):
        result = []
        for channel in self.metadata.get('channels', []):
            page = self.http.request('GET', '/conversations.history', params={'channel': channel['id'], 'oldest': str(time.time() - 7 * 86400), 'limit': 15})
            for message in page.get('messages', []):
                if message.get('bot_id') or message.get('subtype') or not message.get('text'): continue
                data = {'channel': channel['id'], 'channel_name': channel['name'], 'ts': message['ts'], 'thread_ts': message.get('thread_ts', message['ts']), 'user': message.get('user')}
                result.append(item('slack', channel['id'] + ':' + message['ts'], '#' + channel['name'] + ' · ' + message['text'][:85], message['text'][:12000], data, message.get('edited', {}).get('ts', message['ts'])))
        return result

    def execute(self, action, source):
        if action['kind'] != 'slack_reply': raise ValueError('Unsupported Slack action')
        if source['data']['channel'] not in [c['id'] for c in self.metadata.get('channels', [])]:
            raise IntegrationError('This channel is no longer selected. Review its connection settings.')
        result = self.http.request('POST', '/chat.postMessage', body={'channel': source['data']['channel'], 'thread_ts': source['data']['thread_ts'], 'text': action['payload']['body'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), 'mrkdwn': False, 'parse': 'none', 'unfurl_links': False, 'unfurl_media': False})
        return {'detail': 'Reply posted in the original Slack thread.', 'provider_id': result.get('ts')}
