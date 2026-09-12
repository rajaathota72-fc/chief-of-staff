"""Dodo Payments integration: checkout sessions and webhook verification.

Uses the Standard Webhooks signature scheme (webhook-id / webhook-timestamp /
webhook-signature headers, HMAC-SHA256 over "id.timestamp.body", secret
prefixed "whsec_"). Verify this against your Dodo dashboard's webhook config
before relying on it in production.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import requests

PLANS = {
    'pro': {'label': 'Pro', 'price_display': '$29/mo', 'briefing_limit': None, 'automation': True},
    'team': {'label': 'Team', 'price_display': '$79/mo per seat', 'briefing_limit': None, 'automation': True},
}
TRIAL_BRIEFING_LIMIT = 10
WORKSPACE_LIMITS = {'trial': 1, 'pro': 3, 'team': 5}


def workspace_limit(plans):
    """Highest workspace allowance unlocked by any org the user owns."""
    return max((WORKSPACE_LIMITS.get(p, WORKSPACE_LIMITS['trial']) for p in plans), default=WORKSPACE_LIMITS['trial'])


def configured():
    return bool(os.getenv('DODO_PAYMENTS_API_KEY'))


def _base_url():
    return 'https://dodopayments.com' if os.getenv('DODO_ENV') == 'live' else 'https://test.dodopayments.com'


def _product_id(plan):
    key = 'DODO_PRO_PRODUCT_ID' if plan == 'pro' else 'DODO_TEAM_PRODUCT_ID'
    product_id = os.getenv(key)
    if not product_id:
        raise BillingError(f'{key} is not configured.')
    return product_id


class BillingError(Exception):
    pass


def create_checkout_session(org, plan, user, base_url):
    if plan not in PLANS:
        raise BillingError('Unknown plan.')
    api_key = os.getenv('DODO_PAYMENTS_API_KEY')
    if not api_key:
        raise BillingError('Payments are not configured for this deployment.')
    payload = {
        'product_cart': [{'product_id': _product_id(plan), 'quantity': 1}],
        'customer': {'email': user['email'], 'name': user['name']},
        'return_url': base_url.rstrip('/') + '/billing?checkout=complete',
        'billing_currency': 'USD',
        'metadata': {'org_id': org['id'], 'plan': plan},
    }
    response = requests.post(_base_url() + '/checkouts', json=payload,
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}, timeout=15)
    if response.status_code >= 400:
        raise BillingError('Checkout could not be created. Try again shortly.')
    body = response.json()
    if not body.get('checkout_url'):
        raise BillingError('Checkout session response was missing a checkout URL.')
    return body['checkout_url']


def verify_webhook(headers, raw_body):
    secret = os.getenv('DODO_WEBHOOK_SECRET')
    if not secret:
        raise BillingError('DODO_WEBHOOK_SECRET is not configured.')
    webhook_id = headers.get('webhook-id')
    timestamp = headers.get('webhook-timestamp')
    signature_header = headers.get('webhook-signature')
    if not webhook_id or not timestamp or not signature_header:
        raise BillingError('Missing webhook signature headers.')
    if abs(time.time() - float(timestamp)) > 300:
        raise BillingError('Webhook timestamp is too old.')
    secret_bytes = base64.b64decode(secret.removeprefix('whsec_'))
    signed_content = f'{webhook_id}.{timestamp}.{raw_body.decode() if isinstance(raw_body, bytes) else raw_body}'
    expected = base64.b64encode(hmac.new(secret_bytes, signed_content.encode(), hashlib.sha256).digest()).decode()
    provided = [part.split(',', 1)[1] for part in signature_header.split() if ',' in part]
    if not any(hmac.compare_digest(expected, sig) for sig in provided):
        raise BillingError('Webhook signature did not match.')
    return json.loads(raw_body)


def apply_event(store, event):
    """Update the organization referenced by a verified webhook event. Returns the org_id touched, or None."""
    data = event.get('data', {})
    org_id = (data.get('metadata') or {}).get('org_id')
    if not org_id:
        return None
    event_type = event.get('type', '')
    if event_type == 'subscription.active':
        plan = (data.get('metadata') or {}).get('plan', 'pro')
        store.update('organizations', {'id': org_id}, {
            'plan': plan, 'subscription_id': data.get('subscription_id'), 'subscription_status': 'active'})
    elif event_type == 'subscription.renewed':
        store.update('organizations', {'id': org_id}, {'subscription_status': 'active'})
    elif event_type in ('subscription.failed', 'subscription.on_hold'):
        store.update('organizations', {'id': org_id}, {'subscription_status': 'past_due'})
    elif event_type == 'subscription.updated' and data.get('status') in ('cancelled', 'expired'):
        store.update('organizations', {'id': org_id}, {'plan': 'trial', 'subscription_status': data['status']})
    return org_id
