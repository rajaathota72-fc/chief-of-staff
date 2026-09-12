import unittest
import pyotp
from tests.helpers import make_store, PASSWORD
from chief_of_staff.accounts import Accounts

class TotpTests(unittest.TestCase):
    def setUp(self):
        self.store=make_store()
        self.accounts=Accounts(self.store,'http://127.0.0.1:5087')
        self.user=self.store.one('users',{'id':'owner'})

    def test_enable_requires_correct_code(self):
        secret=self.accounts.new_totp_secret()
        with self.assertRaises(ValueError):
            self.accounts.enable_totp(self.user,secret,'000000')

    def test_enable_with_correct_code_persists_secret(self):
        secret=self.accounts.new_totp_secret()
        code=pyotp.TOTP(secret).now()
        self.accounts.enable_totp(self.user,secret,code)
        user=self.store.one('users',{'id':'owner'})
        self.assertTrue(user['totp_enabled'])
        self.assertNotEqual(user['totp_secret'],secret)  # stored encrypted, not raw

    def test_verify_totp_accepts_current_code_after_enable(self):
        secret=self.accounts.new_totp_secret()
        self.accounts.enable_totp(self.user,secret,pyotp.TOTP(secret).now())
        user=self.store.one('users',{'id':'owner'})
        self.assertTrue(self.accounts.verify_totp(user,pyotp.TOTP(secret).now()))

    def test_verify_totp_rejects_wrong_code(self):
        secret=self.accounts.new_totp_secret()
        self.accounts.enable_totp(self.user,secret,pyotp.TOTP(secret).now())
        user=self.store.one('users',{'id':'owner'})
        self.assertFalse(self.accounts.verify_totp(user,'000000'))

    def test_verify_totp_false_when_not_enabled(self):
        user=self.store.one('users',{'id':'owner'})
        self.assertFalse(self.accounts.verify_totp(user,'123456'))

    def test_disable_clears_secret(self):
        secret=self.accounts.new_totp_secret()
        self.accounts.enable_totp(self.user,secret,pyotp.TOTP(secret).now())
        self.accounts.disable_totp(self.user)
        user=self.store.one('users',{'id':'owner'})
        self.assertFalse(user['totp_enabled'])
        self.assertIsNone(user['totp_secret'])

    def test_totp_uri_contains_issuer_and_email(self):
        secret=self.accounts.new_totp_secret()
        uri=self.accounts.totp_uri(self.user,secret)
        self.assertIn('Chief%20of%20Staff',uri)
        self.assertIn('owner%40example.com',uri)

    def test_qr_data_uri_is_a_png_data_url(self):
        secret=self.accounts.new_totp_secret()
        uri=self.accounts.totp_uri(self.user,secret)
        data_uri=self.accounts.totp_qr_data_uri(uri)
        self.assertTrue(data_uri.startswith('data:image/png;base64,'))


if __name__=='__main__':
    unittest.main()
