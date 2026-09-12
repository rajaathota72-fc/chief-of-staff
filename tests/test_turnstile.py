import unittest
from unittest.mock import patch,Mock
from tests import helpers  # noqa: F401 ensures src/ is on sys.path before chief_of_staff import
from chief_of_staff import turnstile

class TurnstileTests(unittest.TestCase):
    def test_not_configured_without_env_vars(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertFalse(turnstile.configured())

    def test_configured_with_both_keys(self):
        with patch.dict('os.environ',{'TURNSTILE_SITE_KEY':'a','TURNSTILE_SECRET_KEY':'b'}):
            self.assertTrue(turnstile.configured())

    def test_verify_is_noop_pass_when_not_configured(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertTrue(turnstile.verify('',None))
            self.assertTrue(turnstile.verify(None,None))

    @patch.dict('os.environ',{'TURNSTILE_SECRET_KEY':'secret'})
    def test_verify_rejects_missing_token_when_configured(self):
        self.assertFalse(turnstile.verify('',None))
        self.assertFalse(turnstile.verify(None,None))

    @patch.dict('os.environ',{'TURNSTILE_SECRET_KEY':'secret'})
    @patch('chief_of_staff.turnstile.requests.post')
    def test_verify_calls_siteverify_and_honors_success_flag(self,post):
        post.return_value=Mock(json=lambda:{'success':True})
        self.assertTrue(turnstile.verify('tok','1.2.3.4'))
        sent=post.call_args.kwargs['data']
        self.assertEqual(sent['secret'],'secret')
        self.assertEqual(sent['response'],'tok')
        self.assertEqual(sent['remoteip'],'1.2.3.4')

    @patch.dict('os.environ',{'TURNSTILE_SECRET_KEY':'secret'})
    @patch('chief_of_staff.turnstile.requests.post')
    def test_verify_rejects_failed_challenge(self,post):
        post.return_value=Mock(json=lambda:{'success':False})
        self.assertFalse(turnstile.verify('tok',None))

    @patch.dict('os.environ',{'TURNSTILE_SECRET_KEY':'secret'})
    @patch('chief_of_staff.turnstile.requests.post',side_effect=Exception('network down'))
    def test_verify_fails_closed_on_network_error(self,post):
        import requests
        post.side_effect=requests.RequestException('down')
        self.assertFalse(turnstile.verify('tok',None))


if __name__=='__main__':
    unittest.main()
