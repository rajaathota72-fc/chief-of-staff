"""Contract tests for provider requests with mocked HTTP; no live sends."""
import base64
from email import message_from_bytes
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from tests.helpers import make_store
from chief_of_staff.integrations import GoogleConnector, JiraConnector, SlackConnector, Transport, IntegrationError, UncertainDelivery, message_body, auth_url


class IntegrationTests(unittest.TestCase):
    def test_mime_body_prefers_plain_text(self):
        encoded=lambda value:base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')
        payload={'parts':[{'mimeType':'text/plain','body':{'data':encoded('Hello')}} ,{'mimeType':'text/html','body':{'data':encoded('<script>ignore</script><b>Hello</b>')}}]}
        self.assertEqual(message_body(payload),'Hello')

    def test_gmail_reply_stays_in_original_thread(self):
        http=Mock()
        http.request.side_effect=[{'threadId':'thread-1','payload':{'headers':[{'name':'From','value':'Pat <pat@example.com>'},{'name':'Subject','value':'Question'},{'name':'Message-ID','value':'<m1@example.com>'}]}},{'id':'sent-1'}]
        result=GoogleConnector(http).execute({'kind':'email_reply','payload':{'body':'Approved reply'}},{'external_id':'m1','data':{'sender':'Pat <pat@example.com>'}})
        call=http.request.call_args
        mime=message_from_bytes(base64.urlsafe_b64decode(call.kwargs['body']['raw']))
        self.assertEqual(mime['To'],'pat@example.com')
        self.assertEqual(mime['In-Reply-To'],'<m1@example.com>')
        self.assertEqual(call.kwargs['body']['threadId'],'thread-1')
        self.assertEqual(result['provider_id'],'sent-1')

    def test_gmail_draft_uses_drafts_endpoint(self):
        http=Mock(); http.request.side_effect=[{'threadId':'th','payload':{'headers':[{'name':'From','value':'a@example.com'}]}},{'id':'draft'}]
        GoogleConnector(http).execute({'kind':'email_draft','payload':{'body':'draft'}},{'external_id':'m','data':{'sender':'a@example.com'}})
        self.assertEqual(http.request.call_args.args[1],'/gmail/v1/users/me/drafts')

    def test_gmail_recipient_change_blocks_send(self):
        http=Mock(); http.request.return_value={'threadId':'th','payload':{'headers':[{'name':'From','value':'changed@example.com'}]}}
        with self.assertRaises(IntegrationError):
            GoogleConnector(http).execute({'kind':'email_reply','payload':{'body':'reply'}},{'external_id':'m','data':{'sender':'original@example.com'}})
        self.assertEqual(http.request.call_count,1)

    def test_calendar_accept_checks_conflicts_before_write(self):
        http=Mock(); event={'etag':'e1','start':{'dateTime':'2026-09-12T09:00:00Z'},'end':{'dateTime':'2026-09-12T10:00:00Z'},'attendees':[{'self':True,'email':'me@example.com','responseStatus':'needsAction'}]}
        http.request.side_effect=[event,{'items':[{'id':'other'}]}]
        with self.assertRaises(IntegrationError):
            GoogleConnector(http).execute({'kind':'calendar_rsvp','payload':{'response':'accepted'}},{'external_id':'event1','data':{'etag':'e1'}})
        self.assertTrue(all(c.args[0]=='GET' for c in http.request.call_args_list))

    def test_calendar_rsvp_uses_if_match(self):
        http=Mock(); http.request.side_effect=[{'etag':'e1','attendees':[{'self':True,'email':'me@example.com','responseStatus':'needsAction'}]},{}]
        GoogleConnector(http).execute({'kind':'calendar_rsvp','payload':{'response':'declined'}},{'external_id':'event1','data':{'etag':'e1'}})
        self.assertEqual(http.request.call_args.kwargs['etag'],'e1')
        self.assertEqual(http.request.call_args.kwargs['params'],{'sendUpdates':'all'})

    def test_jira_comment_uses_adf_and_authorized_site(self):
        http=Mock(); http.request.return_value={'id':'comment'}
        JiraConnector(http,[],'').execute({'kind':'jira_comment','payload':{'body':'Approved update'}},{'data':{'site':'site1','key':'ABC-2'}})
        call=http.request.call_args
        self.assertEqual(call.kwargs['site'],'site1')
        self.assertEqual(call.kwargs['body']['body']['type'],'doc')
        self.assertEqual(call.args[1],'/rest/api/3/issue/ABC-2/comment')

    def test_jira_transition_resolves_named_workflow_transition(self):
        http=Mock(); http.request.side_effect=[{'fields':{'updated':'now'}},{'transitions':[{'id':'31','name':'Done'}]},{}]
        JiraConnector(http,[],'').execute({'kind':'jira_transition','payload':{'transition':'Done'}},{'data':{'site':'s','key':'A-1','updated':'now'}})
        self.assertEqual(http.request.call_args.kwargs['body'],{'transition':{'id':'31'}})

    def test_slack_reply_is_threaded_and_mentions_escaped(self):
        http=Mock(); http.request.return_value={'ts':'123'}
        SlackConnector(http,{'channels':[{'id':'C1'}]}).execute({'kind':'slack_reply','payload':{'body':'Hello <!channel>'}},{'data':{'channel':'C1','thread_ts':'111'}})
        body=http.request.call_args.kwargs['body']
        self.assertEqual(body['thread_ts'],'111')
        self.assertEqual(body['channel'],'C1')
        self.assertIn('&lt;!channel&gt;',body['text'])
        self.assertFalse(body['unfurl_links'])

    def test_slack_unselected_channel_never_posts(self):
        http=Mock()
        with self.assertRaises(IntegrationError):
            SlackConnector(http,{'channels':[]}).execute({'kind':'slack_reply','payload':{'body':'reply'}},{'data':{'channel':'C1'}})
        http.request.assert_not_called()

    def test_slack_oauth_requires_https(self):
        with patch.dict('os.environ',{'SLACK_CLIENT_ID':'id','SLACK_CLIENT_SECRET':'secret','COS_BASE_URL':'http://example.com'}):
            with self.assertRaises(IntegrationError):auth_url('slack','state')

    def test_slack_oauth_allows_localhost_http_for_dev(self):
        with patch.dict('os.environ',{'SLACK_CLIENT_ID':'id','SLACK_CLIENT_SECRET':'secret','COS_BASE_URL':'http://127.0.0.1:5087'}):
            self.assertIn('slack.com',auth_url('slack','state'))

    def test_transport_does_not_retry_ambiguous_write(self):
        import requests
        with tempfile.TemporaryDirectory() as root:
            store=make_store(); cid=store.connect('google','me',{'access_token':'token','expires_at':time.time()+3600},{'identity':'me'},org_id='personal',owner_id='owner')
            with patch('chief_of_staff.integrations.requests.request',side_effect=requests.Timeout) as request:
                with self.assertRaises(UncertainDelivery):Transport(store,cid).request('POST','/gmail/v1/users/me/messages/send',body={})
                self.assertEqual(request.call_count,1)


if __name__=='__main__':unittest.main()
