import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch,Mock
from tests.helpers import make_store
from chief_of_staff import billing
from chief_of_staff.service import Service

SECRET_BYTES=b'0123456789abcdef0123456789abcdef'
SECRET='whsec_'+base64.b64encode(SECRET_BYTES).decode()

def sign(webhook_id,timestamp,body):
    content=f'{webhook_id}.{timestamp}.{body}'
    return 'v1,'+base64.b64encode(hmac.new(SECRET_BYTES,content.encode(),hashlib.sha256).digest()).decode()

class BillingTests(unittest.TestCase):
    def setUp(self):
        self.store=make_store()

    @patch.dict('os.environ',{'DODO_PAYMENTS_API_KEY':'key','DODO_PRO_PRODUCT_ID':'prod_pro'})
    @patch('chief_of_staff.billing.requests.post')
    def test_create_checkout_session_returns_url(self,post):
        post.return_value=Mock(status_code=200,json=lambda:{'checkout_url':'https://test.checkout.dodopayments.com/session/x'})
        org=self.store.one('organizations',{'id':'personal'})
        user={'email':'owner@example.com','name':'Owner'}
        url=billing.create_checkout_session(org,'pro',user,'http://127.0.0.1:5087')
        self.assertEqual(url,'https://test.checkout.dodopayments.com/session/x')
        sent=post.call_args.kwargs['json']
        self.assertEqual(sent['product_cart'],[{'product_id':'prod_pro','quantity':1}])
        self.assertEqual(sent['metadata'],{'org_id':'personal','plan':'pro'})

    def test_create_checkout_session_requires_api_key(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(billing.BillingError):
                billing.create_checkout_session({'id':'personal'},'pro',{'email':'a','name':'b'},'http://x')

    @patch.dict('os.environ',{'DODO_WEBHOOK_SECRET':SECRET})
    def test_verify_webhook_accepts_valid_signature(self):
        body=json.dumps({'type':'subscription.active','data':{'metadata':{'org_id':'personal','plan':'pro'},'subscription_id':'sub_1'}})
        ts=str(int(time.time()))
        headers={'webhook-id':'msg_1','webhook-timestamp':ts,'webhook-signature':sign('msg_1',ts,body)}
        event=billing.verify_webhook(headers,body.encode())
        self.assertEqual(event['type'],'subscription.active')

    @patch.dict('os.environ',{'DODO_WEBHOOK_SECRET':SECRET})
    def test_verify_webhook_rejects_bad_signature(self):
        body=json.dumps({'type':'subscription.active','data':{}})
        ts=str(int(time.time()))
        headers={'webhook-id':'msg_1','webhook-timestamp':ts,'webhook-signature':'v1,'+base64.b64encode(b'wrong').decode()}
        with self.assertRaises(billing.BillingError):
            billing.verify_webhook(headers,body.encode())

    @patch.dict('os.environ',{'DODO_WEBHOOK_SECRET':SECRET})
    def test_verify_webhook_rejects_stale_timestamp(self):
        body=json.dumps({'type':'subscription.active','data':{}})
        ts=str(int(time.time())-3600)
        headers={'webhook-id':'msg_1','webhook-timestamp':ts,'webhook-signature':sign('msg_1',ts,body)}
        with self.assertRaises(billing.BillingError):
            billing.verify_webhook(headers,body.encode())

    def test_apply_event_activates_subscription(self):
        event={'type':'subscription.active','data':{'metadata':{'org_id':'personal','plan':'pro'},'subscription_id':'sub_1'}}
        org_id=billing.apply_event(self.store,event)
        self.assertEqual(org_id,'personal')
        org=self.store.one('organizations',{'id':'personal'})
        self.assertEqual(org['plan'],'pro')
        self.assertEqual(org['subscription_status'],'active')

    def test_apply_event_cancellation_reverts_to_trial(self):
        self.store.update('organizations',{'id':'personal'},{'plan':'pro','subscription_id':'sub_1'})
        event={'type':'subscription.updated','data':{'metadata':{'org_id':'personal'},'status':'cancelled'}}
        billing.apply_event(self.store,event)
        org=self.store.one('organizations',{'id':'personal'})
        self.assertEqual(org['plan'],'trial')

    def test_apply_event_ignores_events_without_org_metadata(self):
        event={'type':'subscription.active','data':{}}
        self.assertIsNone(billing.apply_event(self.store,event))


class TrialGatingTests(unittest.TestCase):
    def setUp(self):
        self.store=make_store()
        self.service=Service(self.store)
        self.store.update('organizations',{'id':'personal'},{'plan':'trial','trial_briefings_used':0})
        self.service.seed('personal')

    def test_trial_org_can_run_up_to_the_limit(self):
        for _ in range(billing.TRIAL_BRIEFING_LIMIT):
            rid=self.service.request_run('personal','owner')
            self.service.run(rid)
        org=self.store.one('organizations',{'id':'personal'})
        self.assertEqual(org['trial_briefings_used'],billing.TRIAL_BRIEFING_LIMIT)

    def test_trial_org_blocked_after_limit(self):
        self.store.update('organizations',{'id':'personal'},{'trial_briefings_used':billing.TRIAL_BRIEFING_LIMIT})
        with self.assertRaises(ValueError):
            self.service.request_run('personal','owner')

    def test_pro_org_has_no_briefing_limit(self):
        self.store.update('organizations',{'id':'personal'},{'plan':'pro','trial_briefings_used':999})
        self.service.request_run('personal','owner')


class WorkspaceLimitTests(unittest.TestCase):
    def setUp(self):
        self.store=make_store()
        self.store.update('organizations',{'id':'personal'},{'plan':'trial'})

    def test_second_trial_workspace_blocked(self):
        with self.assertRaises(ValueError):
            self.store.create_organization('owner','Second Workspace')

    def test_can_create_another_workspace_after_upgrading_existing_one(self):
        self.store.update('organizations',{'id':'personal'},{'plan':'pro'})
        org=self.store.create_organization('owner','Second Workspace')
        self.assertEqual(org['plan'],'trial')

    def test_pro_owner_gets_three_workspaces(self):
        self.store.update('organizations',{'id':'personal'},{'plan':'pro'})
        self.store.create_organization('owner','Second Workspace')
        self.store.create_organization('owner','Third Workspace')
        with self.assertRaises(ValueError):
            self.store.create_organization('owner','Fourth Workspace')

    def test_team_owner_gets_five_workspaces(self):
        self.store.update('organizations',{'id':'personal'},{'plan':'team'})
        for i in range(4):
            self.store.create_organization('owner',f'Workspace {i}')
        with self.assertRaises(ValueError):
            self.store.create_organization('owner','One Too Many')

    def test_legacy_org_without_plan_field_is_treated_as_trial_tier(self):
        self.store.update('organizations',{'id':'personal'},{'plan':None})
        with self.assertRaises(ValueError):
            self.store.create_organization('owner','Second Workspace')


if __name__=='__main__':
    unittest.main()
