"""Multi-user contracts using a Mongo-compatible test double; no external I/O."""
import json
import time
import unittest
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch,Mock
from tests.helpers import make_store,add_user,PASSWORD
from web.app import create_app
from chief_of_staff.accounts import digest
from chief_of_staff.worker import Worker
from chief_of_staff.integrations import UncertainDelivery

class PortalTests(unittest.TestCase):
    def setUp(self):
        self.store=make_store()
        self.app=create_app({'STORE':self.store,'TESTING':True,'SECRET_KEY':'a'*48})
        self.service,self.accounts=self.app.extensions['service'],self.app.extensions['accounts']
        self.client=self.login_client('owner')

    def login_client(self,user_id):
        c=self.app.test_client()
        with c.session_transaction() as s:s['auth_token']=self.accounts.new_session(self.store.one('users',{'id':user_id}))
        c.get('/')
        return c

    def post(self,path,data=None,client=None,**kwargs):
        c=client or self.client
        c.get('/')
        with c.session_transaction() as s:csrf=s['csrf']
        return c.post(path,data=dict(data or {},csrf_token=csrf),**kwargs)

    def seed_run(self):
        self.service.seed('personal');rid=self.service.request_run('personal','owner');self.service.run(rid);return rid

    def test_unauthenticated_cannot_access_portal_or_api(self):
        c=self.app.test_client()
        self.assertEqual(c.get('/').status_code,302)
        self.assertEqual(c.get('/api/status').status_code,401)

    def test_login_with_totp_enabled_requires_second_step(self):
        import pyotp
        secret=self.accounts.new_totp_secret()
        self.accounts.enable_totp(self.store.one('users',{'id':'owner'}),secret,pyotp.TOTP(secret).now())
        c=self.app.test_client()
        c.get('/login')
        with c.session_transaction() as s:csrf=s['csrf']
        r=c.post('/login',data={'csrf_token':csrf,'email':'owner@example.com','password':PASSWORD})
        self.assertEqual(r.status_code,302)
        self.assertEqual(r.headers['Location'],'/login/2fa')
        with c.session_transaction() as s:self.assertIsNone(s.get('auth_token'));self.assertEqual(s.get('pending_2fa'),'owner')
        r2=c.get('/')
        self.assertEqual(r2.status_code,302)  # still not signed in until 2fa completes
        with c.session_transaction() as s:csrf2=s['csrf']
        r3=c.post('/login/2fa',data={'csrf_token':csrf2,'code':pyotp.TOTP(secret).now()})
        self.assertEqual(r3.status_code,302)
        with c.session_transaction() as s:self.assertIsNotNone(s.get('auth_token'))

    def test_login_with_totp_rejects_wrong_code(self):
        import pyotp
        secret=self.accounts.new_totp_secret()
        self.accounts.enable_totp(self.store.one('users',{'id':'owner'}),secret,pyotp.TOTP(secret).now())
        c=self.app.test_client()
        c.get('/login')
        with c.session_transaction() as s:csrf=s['csrf']
        c.post('/login',data={'csrf_token':csrf,'email':'owner@example.com','password':PASSWORD})
        c.get('/login/2fa')
        with c.session_transaction() as s:csrf2=s['csrf']
        r=c.post('/login/2fa',data={'csrf_token':csrf2,'code':'000000'})
        self.assertEqual(r.status_code,200)
        with c.session_transaction() as s:self.assertIsNone(s.get('auth_token'))

    def test_oauth_redirect_destinations_are_allowed_by_csp(self):
        policy=self.client.get('/?view=connections').headers['Content-Security-Policy']
        directive=next(part.strip() for part in policy.split(';') if part.strip().startswith('form-action'))
        self.assertEqual(directive,"form-action 'self' https://accounts.google.com https://*.atlassian.com https://slack.com https://github.com")

    def test_all_pages_render(self):
        for page in ('briefing','connections','automation','memory','activity','decisions','team'):
            self.assertEqual(self.client.get('/?view='+page).status_code,200)

    def test_signup_requires_verification_and_hashes_password(self):
        c=self.app.test_client();c.get('/signup')
        with c.session_transaction() as s:csrf=s['csrf']
        r=c.post('/signup',data={'csrf_token':csrf,'name':'New user','email':'new@example.com','password':PASSWORD,'accept_terms':'yes'})
        self.assertEqual(r.status_code,302)
        user=self.store.one('users',{'email':'new@example.com'})
        self.assertFalse(user['verified']);self.assertNotEqual(user['password_hash'],PASSWORD)
        self.assertIn('/verify-email',c.get('/').location)
        mail=self.store.find('mail')[-1]
        self.assertNotIn('verify/',mail['payload'])
        payload=json.loads(self.store.cipher.decrypt(mail['payload'].encode()))
        raw=payload['body'].split('/verify/')[1].split()[0]
        c.get('/verify/'+raw)
        with c.session_transaction() as s:csrf=s['csrf']
        c.post('/verify/'+raw,data={'csrf_token':csrf})
        self.assertTrue(self.store.one('users',{'id':user['id']})['verified'])
        self.assertIn(b'Give your work a home',c.get('/').data)

    def test_csrf_and_host_checks(self):
        self.assertEqual(self.client.post('/sample').status_code,400)
        self.assertEqual(self.client.get('/',headers={'Host':'evil.test'}).status_code,400)

    def test_logout_revokes_server_session(self):
        with self.client.session_transaction() as s:token=s['auth_token']
        self.post('/logout')
        self.assertIsNone(self.accounts.session_user(token))

    def test_sample_run_is_deduplicated(self):
        self.seed_run();self.seed_run()
        self.assertEqual(len(self.service.snapshot('personal')['actions']),6)

    def test_approval_executes_edited_payload_once(self):
        self.seed_run();a=next(a for a in self.service.snapshot('personal')['actions'] if a['kind']=='slack_reply')
        self.post('/actions/'+a['id']+'/approve',{'body':'Edited reply'})
        self.service.execute_action(a['id']);self.service.execute_action(a['id'])
        action=self.service.action(a['id'],'personal')
        self.assertEqual(action['status'],'succeeded');self.assertEqual(action['payload']['body'],'Edited reply')
        self.assertEqual(action['approved_by'],'owner')
        with self.assertRaises(ValueError):self.service.approve(a['id'],'personal',actor='owner')

    def test_other_users_cannot_enumerate_or_switch_organizations(self):
        add_user(self.store,'outsider');org=self.store.create_organization('outsider','Other organization')
        c=self.login_client('outsider')
        self.assertNotIn(b'My workspace',c.get('/').data)
        self.assertEqual(self.post('/organizations/switch',{'org_id':'personal'},client=c).status_code,404)
        self.seed_run();aid=self.service.snapshot('personal')['actions'][0]['id']
        self.assertEqual(self.post('/actions/'+aid+'/approve',client=c).status_code,404)

    def test_viewer_has_read_access_but_cannot_mutate(self):
        add_user(self.store,'reader');self.store.insert('memberships',{'org_id':'personal','user_id':'reader','role':'viewer'})
        c=self.login_client('reader');self.seed_run()
        self.assertEqual(c.get('/?view=decisions').status_code,200)
        for path in ('/run','/settings','/connect/slack','/preferences','/sample'):
            self.assertEqual(self.post(path,client=c).status_code,403)

    def test_member_cannot_manage_connections(self):
        add_user(self.store,'member');self.store.insert('memberships',{'org_id':'personal','user_id':'member','role':'member'})
        c=self.login_client('member')
        self.assertEqual(self.post('/connect/google',client=c).status_code,403)
        self.assertEqual(self.post('/settings',client=c).status_code,403)

    def test_revoked_approver_cannot_execute_queued_write(self):
        add_user(self.store,'member');self.store.insert('memberships',{'org_id':'personal','user_id':'member','role':'member'})
        self.seed_run();a=next(a for a in self.service.snapshot('personal')['actions'] if a['kind']=='slack_reply')
        self.service.approve(a['id'],'personal',actor='member')
        self.store.delete('memberships',{'user_id':'member','org_id':'personal'})
        self.service.execute_action(a['id'])
        self.assertEqual(self.service.action(a['id'],'personal')['status'],'failed')

    def test_invitation_is_bound_to_verified_email_and_single_use(self):
        self.accounts.invite('personal','owner','guest@example.com','member')
        mail=self.store.find('mail')[-1];data=json.loads(self.store.cipher.decrypt(mail['payload'].encode()))
        raw=data['body'].split('/invitations/')[1].split()[0]
        wrong=add_user(self.store,'wrong');guest=add_user(self.store,'guest')
        with self.assertRaises(ValueError):self.accounts.accept(raw,wrong)
        self.assertEqual(self.accounts.accept(raw,guest),'personal')
        self.assertEqual(self.store.membership('personal','guest')['role'],'member')
        with self.assertRaises(ValueError):self.accounts.accept(raw,guest)

    def test_last_owner_cannot_be_removed(self):
        with self.assertRaises(ValueError):self.accounts.change_member('personal','owner','owner','remove')
        self.assertEqual(self.store.membership('personal','owner')['role'],'owner')

    def test_oauth_state_checks_session_and_user(self):
        self.assertEqual(self.client.get('/oauth/google/callback?state=forged&code=bad').status_code,400)
        with patch.dict('os.environ',{'GOOGLE_CLIENT_ID':'id','GOOGLE_CLIENT_SECRET':'secret'}):
            response=self.post('/connect/google')
            state=parse_qs(urlparse(response.location).query)['state'][0]
            different=self.login_client('owner')
            self.assertEqual(different.get('/oauth/google/callback?state='+state+'&code=bad').status_code,400)

    def test_oauth_rechecks_role_after_authorization(self):
        add_user(self.store,'admin');self.store.insert('memberships',{'org_id':'personal','user_id':'admin','role':'admin'})
        c=self.login_client('admin')
        with patch.dict('os.environ',{'GOOGLE_CLIENT_ID':'id','GOOGLE_CLIENT_SECRET':'secret'}):
            response=self.post('/connect/google',client=c)
            state=parse_qs(urlparse(response.location).query)['state'][0]
        self.store.update('memberships',{'org_id':'personal','user_id':'admin'},{'role':'viewer'})
        self.assertEqual(c.get('/oauth/google/callback?state='+state+'&code=bad').status_code,403)

    def test_tokens_do_not_cross_application_user_boundaries(self):
        add_user(self.store,'other');org=self.store.create_organization('other','Other')
        a=self.store.connect('jira','Account',{'access_token':'a'},{'identity':'same'},org_id='personal',owner_id='owner')
        b=self.store.connect('jira','Account',{'access_token':'b'},{'identity':'same'},org_id=org['id'],owner_id='other')
        self.store.save_tokens(a,{'access_token':'rotated'})
        self.assertEqual(self.store.connection(b,secret=True)['secrets']['access_token'],'b')
        self.assertNotIn('rotated',self.store.one('connections',{'id':a})['secrets'])

    def test_password_reset_revokes_all_sessions(self):
        user=self.store.one('users',{'id':'owner'});raw=self.accounts.token(user,'reset')
        with self.client.session_transaction() as s:old=s['auth_token']
        self.accounts.reset(raw,'a-new-long-password')
        self.assertIsNone(self.accounts.session_user(old))
        self.assertIsNotNone(self.accounts.authenticate(user['email'],'a-new-long-password'))
        with self.assertRaises(ValueError):self.accounts.reset(raw,PASSWORD)

    def test_disconnect_cancels_queued_action(self):
        self.seed_run();a=next(a for a in self.service.snapshot('personal')['actions'] if a['kind']=='slack_reply')
        self.service.approve(a['id'],'personal',actor='owner');self.store.disconnect(a['connection_id']);self.service.execute_action(a['id'])
        self.assertEqual(self.service.action(a['id'],'personal')['status'],'dismissed')

    def test_uncertain_writes_are_not_retried(self):
        self.seed_run();a=next(a for a in self.service.snapshot('personal')['actions'] if a['kind']=='email_mark_read')
        self.store.update('connections',{'id':a['connection_id']},{'mode':'live'})
        self.store.setting('mode','live','personal');self.service.approve(a['id'],'personal',actor='owner')
        connector=Mock();connector.execute.side_effect=UncertainDelivery('Check provider')
        with patch.object(self.service,'connector',return_value=connector):
            self.service.execute_action(a['id']);self.service.execute_action(a['id'])
        self.assertEqual(connector.execute.call_count,1)
        self.assertEqual(self.service.action(a['id'],'personal')['status'],'uncertain')

    def test_worker_recovery_never_resends_inflight_action(self):
        self.seed_run();aid=self.service.snapshot('personal')['actions'][0]['id']
        self.store.update('actions',{'id':aid},{'status':'executing'});Worker(self.service).recover()
        self.assertEqual(self.service.action(aid,'personal')['status'],'uncertain')

    def test_worker_lease_excludes_second_worker(self):
        self.assertTrue(self.store.lease('worker1'));self.assertFalse(self.store.lease('worker2'))
        token=self.store.execution_owner.set('worker2')
        with self.assertRaises(ValueError):self.store.check_execution()
        self.store.execution_owner.reset(token)

    def test_organization_deletion_cascades_only_that_tenant(self):
        self.seed_run();add_user(self.store,'other');org=self.store.create_organization('other','Other')
        self.accounts.delete_org('personal','owner')
        for collection in ('items','actions','connections','runs','memberships'):
            self.assertEqual(self.store.find(collection,{'org_id':'personal'}),[])
        self.assertIsNotNone(self.store.one('organizations',{'id':org['id']}))

    def test_account_deletion_requires_ownership_resolution(self):
        user=self.store.one('users',{'id':'owner'})
        with self.assertRaises(ValueError):self.accounts.delete_user(user)
        self.accounts.delete_org('personal','owner');self.accounts.delete_user(user)
        self.assertIsNone(self.store.one('users',{'id':'owner'}))

    def test_customer_connections_do_not_display_operator_env_fields(self):
        body=self.client.get('/?view=connections').get_data(as_text=True)
        self.assertNotIn('CLIENT_SECRET',body);self.assertNotIn('CLIENT_ID',body)

    def test_status_omits_source_and_secrets(self):
        self.seed_run();data=self.client.get('/api/status').get_json()
        self.assertEqual(set(data),{'busy','pending','signature'})

    def test_unconfigured_app_shows_setup_without_sqlite_fallback(self):
        with patch.dict('os.environ',{'MONGODB_URI':'','COS_ENCRYPTION_KEY':''}):
            app=create_app({'TESTING':True,'SECRET_KEY':'x'*40})
        self.assertEqual(app.test_client().get('/').status_code,503)

if __name__=='__main__':unittest.main()
