"""Exercise the real Strands tool loop with an in-process model, without network I/O."""
import json
import tempfile
import unittest
from unittest.mock import patch
from strands.models import Model
from tests.helpers import make_store
from chief_of_staff.service import Service
from chief_of_staff.service import decode


class ScriptedModel(Model):
    def __init__(self, source_id): self.source_id, self.calls = source_id, 0
    def update_config(self, **config): pass
    def get_config(self): return {'model_id':'offline-contract-model','context_window_limit':100000}
    async def structured_output(self, *args, **kwargs):
        raise NotImplementedError
        yield
    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        yield {'messageStart':{'role':'assistant'}}
        if self.calls == 1:
            assert any(spec['name']=='propose_action' for spec in tool_specs)
            yield {'contentBlockStart':{'start':{'toolUse':{'toolUseId':'test-tool-1','name':'propose_action'}}}}
            payload={'item_id':self.source_id,'action_kind':'slack_reply','payload':{'body':'Prepared through the real Strands tool loop.'},'reason':'Respond to the source thread after owner review.'}
            yield {'contentBlockDelta':{'delta':{'toolUse':{'input':json.dumps(payload)}}}}
            yield {'contentBlockStop':{}}
            yield {'messageStop':{'stopReason':'tool_use'}}
        else:
            yield {'contentBlockStart':{'start':{}}}
            yield {'contentBlockDelta':{'delta':{'text':'A Slack reply is ready for approval.'}}}
            yield {'contentBlockStop':{}}
            yield {'messageStop':{'stopReason':'end_turn'}}
        yield {'metadata':{'usage':{'inputTokens':1,'outputTokens':1,'totalTokens':2},'metrics':{'latencyMs':1}}}


class StrandsWorkflowTests(unittest.TestCase):
    def test_real_sdk_dispatches_validated_proposal(self):
        with tempfile.TemporaryDirectory() as root:
            store=make_store(); service=Service(store)
            service.seed('personal');service.sync('personal','demo')
            source=decode(store.one('items',{'kind':'slack','org_id':'personal'}))
            model=ScriptedModel(source['id'])
            with patch('agent._build_model',return_value=model):
                digest=service.strands_plan('personal','demo',[source])
            self.assertIn('ready for approval',digest)
            action=service.snapshot('personal')['actions'][0]
            self.assertEqual(action['status'],'proposed')
            self.assertEqual(action['payload']['body'],'Prepared through the real Strands tool loop.')
            self.assertEqual(model.calls,2)


if __name__=='__main__':unittest.main()
