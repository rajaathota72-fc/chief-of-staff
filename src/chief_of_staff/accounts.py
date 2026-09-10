"""Individual accounts, revocable sessions, email tokens, and organization membership."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import time
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo.errors import DuplicateKeyError

ROLES=('owner','admin','member','viewer')
DUMMY_HASH=generate_password_hash('not-a-user-password')


def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def expiry(seconds):return datetime.now(timezone.utc)+timedelta(seconds=seconds)
def valid_email(value):
    value=value.strip().casefold()
    if len(value)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',value):raise ValueError('Enter a valid email address.')
    return value

def validate_password(value):
    if not 12<=len(value)<=128:raise ValueError('Use a password between 12 and 128 characters.')


class Accounts:
    def __init__(self,store,base_url):self.store,self.base_url=store,base_url.rstrip('/')

    def mail(self,email,subject,body,org_id=None):
        encrypted=self.store.cipher.encrypt(json.dumps({'to':email,'subject':subject,'body':body}).encode()).decode()
        doc=self.store.insert('mail',{'payload':encrypted,'org_id':org_id,'status':'queued','created':time.time()})
        self.store.enqueue('mail',doc['id'],org_id)

    def token(self,user,purpose):
        raw=secrets.token_urlsafe(32)
        self.store.insert('auth_tokens',{'id':digest(raw),'user_id':user['id'],'purpose':purpose,'expires_at':expiry(3600),'created':time.time()})
        return raw

    def register(self,email,password,name):
        email=valid_email(email);validate_password(password)
        if not 1<=len(name.strip())<=80:raise ValueError('Enter your name (up to 80 characters).')
        try:
            with self.store.atomic():
                user=self.store.insert('users',{'email':email,'name':name.strip(),'password_hash':generate_password_hash(password),'verified':False,'created':time.time()})
                token=self.token(user,'verify')
                self.mail(email,'Verify your Chief of Staff account',f'Confirm your email by opening {self.base_url}/verify/{token}\nThis link expires in one hour. If you did not sign up, ignore this email.')
            return user
        except DuplicateKeyError:raise ValueError('Unable to create this account. Try signing in or resetting your password.') from None

    def authenticate(self,email,password):
        user=self.store.one('users',{'email':email.strip().casefold()})
        if not check_password_hash(user['password_hash'] if user else DUMMY_HASH,password):return None
        return user

    def login_with_google(self,email,name):
        # Google has already verified this email address, so a matching account (new or existing) is trusted immediately.
        email=valid_email(email)
        with self.store.atomic():
            user=self.store.one('users',{'email':email})
            if not user:
                user=self.store.insert('users',{'email':email,'name':(name or email.split('@')[0]).strip()[:80] or email.split('@')[0],'password_hash':DUMMY_HASH,'verified':True,'created':time.time()})
            elif not user['verified']:
                self.store.update('users',{'id':user['id']},{'verified':True});user['verified']=True
        return user

    def new_session(self,user):
        raw=secrets.token_urlsafe(32)
        self.store.insert('sessions',{'id':digest(raw),'user_id':user['id'],'expires_at':expiry(86400*7),'created':time.time()})
        return raw

    def session_user(self,raw):
        if not raw:return None
        session=self.store.one('sessions',{'id':digest(raw),'expires_at':{'$gt':datetime.now(timezone.utc)}})
        return self.store.one('users',{'id':session['user_id']}) if session else None

    def consume(self,raw,purpose):
        token=self.store.one('auth_tokens',{'id':digest(raw),'purpose':purpose,'expires_at':{'$gt':datetime.now(timezone.utc)}})
        if not token:raise ValueError('This link is expired or has already been used.')
        self.store.delete('auth_tokens',{'id':token['id']})
        return token

    def verify(self,raw):
        with self.store.atomic():
            token=self.consume(raw,'verify')
            self.store.update('users',{'id':token['user_id']},{'verified':True})

    def reset_request(self,email):
        user=self.store.one('users',{'email':email.strip().casefold()})
        if user:
            with self.store.atomic():
                token=self.token(user,'reset')
                self.mail(user['email'],'Reset your Chief of Staff password',f'Choose a new password at {self.base_url}/reset-password/{token}\nThis link expires in one hour. Ignore it if you did not request a reset.')

    def reset(self,raw,password):
        validate_password(password)
        with self.store.atomic():
            token=self.consume(raw,'reset')
            self.store.update('users',{'id':token['user_id']},{'password_hash':generate_password_hash(password)})
            self.store.delete('sessions',{'user_id':token['user_id']})
            self.store.delete('auth_tokens',{'user_id':token['user_id'],'purpose':'reset'})

    def invite(self,org_id,actor,email,role):
        membership=self.store.membership(org_id,actor)
        if not membership or membership['role'] not in ('owner','admin'):raise ValueError('An owner or administrator must invite members.')
        if role not in ('admin','member','viewer') or (role=='admin' and membership['role']!='owner'):raise ValueError('Only owners can invite administrators.')
        email=valid_email(email)
        org=self.store.one('organizations',{'id':org_id,'status':'active'})
        raw=secrets.token_urlsafe(32)
        with self.store.atomic():
            self.store.insert('invitations',{'id':digest(raw),'org_id':org_id,'email':email,'role':role,'invited_by':actor,'expires_at':expiry(7*86400),'created':time.time()})
            self.mail(email,f'Invitation to {org["name"]} on Chief of Staff',f'You were invited to join {org["name"]} as {role}. Sign in with {email}, then open {self.base_url}/invitations/{raw}\nThis link expires in seven days.',org_id)
        self.store.event('Invitation created for '+email,org_id=org_id,actor=actor)

    def accept(self,raw,user):
        with self.store.atomic():
            invite=self.store.one('invitations',{'id':digest(raw),'email':user['email'],'expires_at':{'$gt':datetime.now(timezone.utc)}})
            if not invite or not user['verified']:raise ValueError('Invitation unavailable for this verified email address.')
            self.store.settings(invite['org_id'])
            inviter=self.store.membership(invite['org_id'],invite['invited_by'])
            if not inviter or inviter['role'] not in ('owner','admin') or (invite['role']=='admin' and inviter['role']!='owner'):
                raise ValueError('The invitation issuer no longer has permission. Request a new invitation.')
            if not self.store.membership(invite['org_id'],user['id']):
                self.store.insert('memberships',{'org_id':invite['org_id'],'user_id':user['id'],'role':invite['role'],'created':time.time()})
            self.store.delete('invitations',{'id':invite['id']})
            return invite['org_id']

    def change_member(self,org_id,actor,target,role):
        with self.store.atomic():
            org=self.store.one('organizations',{'id':org_id})
            # Force concurrent owner-role changes to conflict instead of removing both last owners.
            self.store.update('organizations',{'id':org_id},{'auth_revision':org.get('auth_revision',0)+1})
            own=self.store.membership(org_id,actor); member=self.store.membership(org_id,target)
            if not own or own['role']!='owner' or not member:raise ValueError('Only an owner can change organization roles.')
            if role not in (*ROLES,'remove'):raise ValueError('Choose a valid role.')
            if member['role']=='owner' and role!='owner' and len(self.store.find('memberships',{'org_id':org_id,'role':'owner'}))<=1:
                raise ValueError('Assign another owner before removing the last owner.')
            if role=='remove':
                for conn in self.store.find('connections',{'org_id':org_id,'grant_owner':target,'status':'connected'}):self.store.disconnect(conn['id'])
                self.store.delete('memberships',{'id':member['id']})
            else:self.store.update('memberships',{'id':member['id']},{'role':role})
            self.store.event('Member role changed to '+role,org_id=org_id,actor=actor)

    def delete_org(self,org_id,actor):
        with self.store.atomic():
            member=self.store.membership(org_id,actor)
            if not member or member['role']!='owner':raise ValueError('Only an owner can delete an organization.')
            if self.store.one('jobs',{'org_id':org_id,'status':'running'}):raise ValueError('Wait for running jobs to finish before deleting this organization.')
            self.store.update('organizations',{'id':org_id},{'status':'deleting'})
            for collection in ['connections','items','actions','runs','jobs','preferences','oauth','events','invitations','mail','memberships']:
                self.store.delete(collection,{'org_id':org_id})
            self.store.delete('organizations',{'id':org_id})

    def delete_user(self,user):
        with self.store.atomic():
            for membership in self.store.find('memberships',{'user_id':user['id']}):
                if membership['role']=='owner':raise ValueError('Transfer ownership or delete your owned organizations before deleting your account.')
            for conn in self.store.find('connections',{'grant_owner':user['id'],'status':'connected'}):self.store.disconnect(conn['id'])
            for collection in ['memberships','sessions','auth_tokens']:self.store.delete(collection,{'user_id':user['id']})
            self.store.delete('oauth',{'user_id':user['id']})
            self.store.delete('invitations',{'email':user['email']})
            self.store.delete('users',{'id':user['id']})
