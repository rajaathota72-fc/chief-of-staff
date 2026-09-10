"""Client for invoking a deployed Bedrock AgentCore Runtime from the worker.

This is the real swap-in for the in-process `strands.Agent` call in
service.py's strands_plan(): instead of building and running the agent in
this process, the worker sends the same context (items, preferences, recent
action history) to a Runtime endpoint AWS hosts, and the remote entrypoint
(deploy/agentcore_runtime_entrypoint.py) runs the agent there. The remote
agent's propose_action tool calls back into this app over HTTP (see
web/app.py's /internal/agentcore/propose) since it has no access to this
process's Python objects.

Configured via AGENTCORE_RUNTIME_ARN; falls back to the local in-process
agent (service.py's own strands_plan) when unset, so nothing here is
required for local/demo use.
"""
from __future__ import annotations

import json
import os

import boto3


class AgentCoreRuntimeError(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv('AGENTCORE_RUNTIME_ARN'))


def invoke(org_id: str, mode: str, context: dict) -> str:
    """Runs one briefing pass on the deployed Runtime and returns its digest text.

    The remote entrypoint calls back to this app's /internal/agentcore/propose
    for every proposed action - see AGENTCORE_CALLBACK_SECRET / COS_BASE_URL,
    which must be reachable from AWS (not localhost) for this to work.
    """
    runtime_arn = os.environ['AGENTCORE_RUNTIME_ARN']
    secret = os.getenv('AGENTCORE_CALLBACK_SECRET')
    base_url = os.getenv('COS_BASE_URL', 'http://127.0.0.1:5087')
    if not secret:
        raise AgentCoreRuntimeError('Set AGENTCORE_CALLBACK_SECRET to use AgentCore Runtime.')

    client = boto3.client('bedrock-agentcore', region_name=os.getenv('AWS_REGION', 'us-west-2'))
    payload = json.dumps({
        'org_id': org_id,
        'mode': mode,
        'context': context,
        'callback_url': base_url.rstrip('/') + '/internal/agentcore/propose',
        'callback_token': secret,
    }).encode('utf-8')

    try:
        response = client.invoke_agent_runtime(agentRuntimeArn=runtime_arn, payload=payload)
    except Exception as exc:  # pragma: no cover - network/AWS dependent
        raise AgentCoreRuntimeError(f'AgentCore Runtime invocation failed: {exc}') from None

    body = response['response'].read() if hasattr(response.get('response'), 'read') else response.get('response', b'{}')
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        raise AgentCoreRuntimeError('AgentCore Runtime returned an unreadable response.') from None
    if 'error' in result:
        raise AgentCoreRuntimeError(str(result['error']))
    return str(result.get('digest', ''))
