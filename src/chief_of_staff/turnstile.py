"""Cloudflare Turnstile CAPTCHA verification for signup and login."""
import os
import requests


def configured():
    return bool(os.getenv('TURNSTILE_SITE_KEY') and os.getenv('TURNSTILE_SECRET_KEY'))


def site_key():
    return os.getenv('TURNSTILE_SITE_KEY', '')


def verify(token, remote_ip=None):
    """Returns True if verification passes, or if Turnstile is not configured (no-op in dev)."""
    secret = os.getenv('TURNSTILE_SECRET_KEY')
    if not secret:
        return True
    if not token:
        return False
    payload = {'secret': secret, 'response': token}
    if remote_ip:
        payload['remoteip'] = remote_ip
    try:
        response = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify', data=payload, timeout=10)
        return bool(response.json().get('success'))
    except requests.RequestException:
        return False
