"""Multi-user Chief of Staff portal. Tenant authorization is checked on every request."""
from __future__ import annotations
from datetime import datetime, timezone
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
import requests
from dotenv import load_dotenv
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from pymongo.errors import PyMongoError
from chief_of_staff.store import Store
from chief_of_staff.accounts import Accounts, digest, expiry, ROLES
from chief_of_staff.service import Service, ACTION_KINDS
from chief_of_staff.integrations import PROVIDERS, IntegrationError, auth_url, configured, finish_oauth, redirect_uri
from chief_of_staff import billing, turnstile
load_dotenv()

GOOGLE_LOGIN_SCOPES = ['openid', 'email', 'profile']


def create_app(test_config=None):
    app=Flask(__name__)
    app.config.update(PRODUCTION=os.getenv('COS_ENV')=='production',BASE_URL=os.getenv('COS_BASE_URL','http://127.0.0.1:5087'),
        SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),SESSION_COOKIE_NAME='cos_session_v2',SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COS_BASE_URL','').startswith('https://'),MAX_CONTENT_LENGTH=64*1024,
        SIGNUP_ENABLED=os.getenv('COS_SIGNUP_ENABLED','1')=='1')
    if test_config:app.config.update(test_config)
    configured_store=app.config.get('STORE')
    if app.config['PRODUCTION']:
        if not app.config['BASE_URL'].startswith('https://') or not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
            raise RuntimeError('Production needs HTTPS COS_BASE_URL and a stable FLASK_SECRET_KEY of at least 32 characters.')
        if not os.getenv('SMTP_HOST') or not os.getenv('SMTP_FROM'):raise RuntimeError('Production needs SMTP_HOST and SMTP_FROM for account email.')
    if not app.config['SECRET_KEY']:app.secret_key=secrets.token_hex(32)
    setup_error=None
    try:store=configured_store if configured_store is not None else Store.from_env()
    except (ValueError,PyMongoError):
        if app.config['PRODUCTION']:raise RuntimeError('MongoDB configuration is unavailable. Check the deployment environment.') from None
        store=None;setup_error='Configure MongoDB and stable application keys to start the multi-user portal. Your previous SQLite data is unchanged.'
    service=Service(store) if store else None
    accounts=Accounts(store,app.config['BASE_URL']) if store else None
    app.extensions.update(store=store,service=service,accounts=accounts)

    def back(view=None):return redirect(url_for('index',view=view) if view else url_for('index'))
    def org_id():
        org=session.get('org')
        if org and store.membership(org,g.user['id']) and store.one('organizations',{'id':org,'status':'active'}):return org
        organizations=store.organizations_for(g.user['id'])
        if not organizations:abort(409,'Create or join an organization first.')
        session['org']=organizations[0]['id'];return session['org']
    def require_role(*roles):
        membership=store.membership(org_id(),g.user['id'])
        if not membership or membership['role'] not in roles:abort(403,'Your organization role does not permit this action.')
        return membership
    def limit(key,n=10,seconds=900):
        if not store.rate_limit(key,n,seconds):abort(429,'Too many attempts. Please try again later.')

    public={'login','signup','verify','forgot_password','reset_password','health','static','privacy','terms','invitation','google_login_start','google_login_callback','agentcore_propose','billing_webhook','login_2fa'}
    admin={'settings','connect','disconnect','channels','save_channels','sites','repos','save_repos','invite_member','revoke_invite','billing_checkout'}
    member={'run','approve','dismiss','preference','delete_preference','sample'}
    @app.before_request
    def guard():
        host=urlparse(request.host_url).hostname
        expected=urlparse(app.config['BASE_URL']).hostname
        if host not in ({expected} if app.config['PRODUCTION'] else {expected,'localhost','127.0.0.1','::1'}):abort(400)
        if request.endpoint=='static':return
        if not app.config['PRODUCTION'] and request.remote_addr not in ('127.0.0.1','::1'):abort(403,'Public access requires COS_ENV=production.')
        if store is None and request.endpoint!='health':return render_template('setup.html',message=setup_error),503
        if request.endpoint=='health':return
        session.setdefault('csrf',secrets.token_urlsafe(32));session.setdefault('sid',secrets.token_urlsafe(32))
        if request.method=='POST' and request.endpoint not in ('agentcore_propose','billing_webhook') and not hmac.compare_digest(session['csrf'],request.form.get('csrf_token','')):abort(400,'Form expired. Reload the page and try again.')
        g.user=accounts.session_user(session.get('auth_token'))
        if request.endpoint not in public:
            if not g.user:
                if request.path.startswith('/api/'):return jsonify(error='Sign in again.'),401
                return redirect(url_for('login'))
            if not g.user['verified'] and request.endpoint not in {'verification_pending','resend_verification','logout','account','delete_account'}:
                return redirect(url_for('verification_pending'))
        if request.endpoint in admin:require_role('owner','admin')
        elif request.endpoint in member:require_role('owner','admin','member')
        if request.method=='POST':limit('post:'+ (g.user['id'] if g.user else request.remote_addr),120,60)

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data:; frame-src https://challenges.cloudflare.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com https://*.atlassian.com https://slack.com https://github.com"})
        if app.config['PRODUCTION']:response.headers['Strict-Transport-Security']='max-age=31536000'
        if request.endpoint!='static':response.headers['Cache-Control']='no-store'
        return response

    @app.context_processor
    def helpers():
        return {'csrf_token':lambda:session.get('csrf',''),'action_kinds':ACTION_KINDS,'current_user':getattr(g,'user',None),
            'production':app.config['PRODUCTION'],'roles':ROLES,'google_login_available':configured('google')}

    from chief_of_staff.formatting import render_markdown, source_preview
    app.add_template_filter(render_markdown, 'markdown')
    app.add_template_filter(source_preview, 'source_preview')

    @app.template_filter('localtime')
    def localtime(value):return datetime.fromtimestamp(value).strftime('%b %d, %H:%M') if value else 'Not yet'

    @app.get('/health')
    def health():
        if store is None:return jsonify(status='setup_required'),503
        try:store.database.command('ping')
        except Exception:
            if not store.testing:return jsonify(status='database_unavailable'),503
        return jsonify(status='ok')

    @app.post('/internal/agentcore/propose')
    def agentcore_propose():
        """Callback the AgentCore Runtime entrypoint uses for its propose_action
        tool - Runtime runs in a separate AWS-managed process/container with no
        access to this process's Python closures, so the tool call comes back
        over HTTP instead. Authenticated by shared secret, not a user session."""
        secret=os.getenv('AGENTCORE_CALLBACK_SECRET')
        if not secret:abort(404)
        given=(request.headers.get('Authorization') or '').removeprefix('Bearer ')
        if not hmac.compare_digest(given,secret):abort(401)
        body=request.get_json(silent=True) or {}
        try:
            result=service.propose(body['org_id'],body['mode'],body['item_id'],body['action_kind'],body['payload'],body['reason'])
        except (KeyError,ValueError) as exc:
            return jsonify(error=str(exc)),400
        return jsonify(result)

    @app.route('/signup',methods=['GET','POST'])
    def signup():
        if not app.config['SIGNUP_ENABLED']:abort(403,'New registrations are closed.')
        if request.method=='POST':
            limit('signup-ip:'+request.remote_addr,5,3600)
            if not turnstile.verify(request.form.get('cf-turnstile-response',''),request.remote_addr):raise ValueError('Verification failed. Try again.')
            if request.form.get('accept_terms')!='yes':raise ValueError('Accept the terms and privacy notice to create an account.')
            user=accounts.register(request.form.get('email',''),request.form.get('password',''),request.form.get('name',''))
            pending=session.get('invite_token');session.clear();session['auth_token']=accounts.new_session(user)
            if pending:session['invite_token']=pending
            return redirect(url_for('verification_pending'))
        return render_template('auth.html',screen='signup',turnstile_site_key=turnstile.site_key(),turnstile_enabled=turnstile.configured())

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            email=request.form.get('email','')
            limit('login-ip:'+request.remote_addr,30,900);limit('login-email:'+digest(email.casefold()),10,900)
            if not turnstile.verify(request.form.get('cf-turnstile-response',''),request.remote_addr):raise ValueError('Verification failed. Try again.')
            user=accounts.authenticate(email,request.form.get('password',''))
            if user:
                if user.get('totp_enabled'):
                    pending=session.get('invite_token');session.clear();session['pending_2fa']=user['id']
                    if pending:session['invite_token']=pending
                    return redirect(url_for('login_2fa'))
                pending=session.get('invite_token');session.clear();session['auth_token']=accounts.new_session(user)
                if pending:session['invite_token']=pending
                return back()
            flash('Email or password did not match.','error')
        return render_template('auth.html',screen='login',turnstile_site_key=turnstile.site_key(),turnstile_enabled=turnstile.configured())

    @app.route('/login/2fa',methods=['GET','POST'])
    def login_2fa():
        uid=session.get('pending_2fa')
        if not uid:return redirect(url_for('login'))
        if request.method=='POST':
            limit('2fa-attempt:'+uid,10,900)
            user=store.one('users',{'id':uid})
            if user and accounts.verify_totp(user,request.form.get('code','')):
                pending=session.get('invite_token');session.clear();session['auth_token']=accounts.new_session(user)
                if pending:session['invite_token']=pending
                return back()
            flash('Incorrect code. Try again.','error')
        return render_template('auth.html',screen='totp')

    @app.get('/auth/google')
    def google_login_start():
        if not configured('google'):abort(404)
        limit('google-login-ip:'+request.remote_addr,20,900)
        state=secrets.token_urlsafe(32);session['login_state']=state
        params={'client_id':os.environ['GOOGLE_CLIENT_ID'],'redirect_uri':app.config['BASE_URL']+'/auth/google/callback',
            'response_type':'code','scope':' '.join(GOOGLE_LOGIN_SCOPES),'state':state,'prompt':'select_account'}
        return redirect('https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params))

    @app.get('/auth/google/callback')
    def google_login_callback():
        state=session.pop('login_state',None)
        if not state or state!=request.args.get('state'):abort(400,'Sign-in expired. Start again from the sign-in page.')
        if request.args.get('error') or not request.args.get('code'):flash('Sign-in canceled.','error');return redirect(url_for('login'))
        try:
            token_response=requests.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['GOOGLE_CLIENT_ID'],
                'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'code':request.args['code'],'redirect_uri':app.config['BASE_URL']+'/auth/google/callback',
                'grant_type':'authorization_code'},headers={'Accept':'application/json'},timeout=25)
            token_response.raise_for_status()
            access_token=token_response.json()['access_token']
            profile_response=requests.get('https://www.googleapis.com/oauth2/v3/userinfo',headers={'Authorization':'Bearer '+access_token},timeout=25)
            profile_response.raise_for_status();profile=profile_response.json()
        except requests.RequestException:flash('Could not complete Google sign-in. Try again.','error');return redirect(url_for('login'))
        if not profile.get('email') or not profile.get('email_verified'):flash('Use a Google account with a verified email address.','error');return redirect(url_for('login'))
        user=accounts.login_with_google(profile['email'],profile.get('name',''))
        pending=session.get('invite_token');session.clear();session['auth_token']=accounts.new_session(user)
        if pending:session['invite_token']=pending
        return redirect(url_for('index'))

    @app.post('/logout')
    def logout():
        if session.get('auth_token'):store.delete('sessions',{'id':digest(session['auth_token'])})
        session.clear();return redirect(url_for('login'))

    @app.get('/verify-email')
    def verification_pending():return render_template('auth.html',screen='pending')

    @app.post('/verify-email/resend')
    def resend_verification():
        limit('verify:'+g.user['id'],3,3600)
        if not g.user['verified']:
            with store.atomic():
                token=accounts.token(g.user,'verify')
                accounts.mail(g.user['email'],'Verify your Chief of Staff account',f'Confirm your email: {app.config["BASE_URL"]}/verify/{token}')
        flash('Verification email queued. Check your inbox and spam folder.','success')
        return redirect(url_for('verification_pending'))

    @app.route('/verify/<raw>',methods=['GET','POST'])
    def verify(raw):
        if request.method=='POST':accounts.verify(raw);flash('Email verified. Sign in to continue.','success');return back()
        return render_template('auth.html',screen='verify')

    @app.route('/forgot-password',methods=['GET','POST'])
    def forgot_password():
        if request.method=='POST':
            limit('reset-ip:'+request.remote_addr,5,3600)
            accounts.reset_request(request.form.get('email',''))
            flash('If an account matches, a password reset email has been queued.','success')
        return render_template('auth.html',screen='forgot')

    @app.route('/reset-password/<raw>',methods=['GET','POST'])
    def reset_password(raw):
        if request.method=='POST':
            accounts.reset(raw,request.form.get('password',''));session.clear();flash('Password changed. Sign in again.','success');return redirect(url_for('login'))
        return render_template('auth.html',screen='reset')

    @app.get('/')
    def index():
        if session.get('invite_token'):return redirect(url_for('invitation',raw=session.pop('invite_token')))
        organizations=store.organizations_for(g.user['id'])
        if not organizations:return render_template('onboarding.html')
        org=org_id();membership=store.membership(org,g.user['id']);state=service.snapshot(org)
        lease=store.one('leases',{'id':'worker'})
        members=[]
        for entry in store.find('memberships',{'org_id':org}):
            user=store.one('users',{'id':entry['user_id']})
            if user:members.append(dict(entry,name=user['name'],email=user['email']))
        return render_template('index.html',**state,organizations=organizations,organization=store.one('organizations',{'id':org}),
            providers=PROVIDERS,configured={p:configured(p) for p in PROVIDERS},callbacks={p:redirect_uri(p) for p in PROVIDERS},
            owner_login=True,worker_online=bool(lease and lease['expires']>time.time()),page=request.args.get('view','briefing'),
            membership=membership,can_manage=membership['role'] in ('owner','admin'),can_act=membership['role']!='viewer',members=members,
            invitations=store.find('invitations',{'org_id':org}) if membership['role'] in ('owner','admin') else [])

    @app.get('/api/status')
    def status():
        state=service.snapshot(org_id())
        signature=[[r['id'],r['status']] for r in state['runs']]+[[a['id'],a['status']] for a in state['actions']]
        return jsonify(busy=state['busy'],pending=state['pending'],signature=digest(json.dumps(signature)))

    @app.post('/organizations')
    def add_org():
        name=request.form.get('name','').strip()
        if not 1<=len(name)<=80:raise ValueError('Enter an organization name up to 80 characters.')
        session['org']=store.create_organization(g.user['id'],name)['id']
        return back('connections')

    @app.post('/organizations/switch')
    def switch_org():
        oid=request.form.get('org_id')
        if not store.membership(oid,g.user['id']):abort(404)
        store.settings(oid);session['org']=oid;return back()

    @app.post('/organizations/invite')
    def invite_member():
        accounts.invite(org_id(),g.user['id'],request.form.get('email',''),request.form.get('role','member'))
        flash('Invitation email queued.','success');return back('team')

    @app.post('/organizations/invitations/<iid>/revoke')
    def revoke_invite(iid):
        store.delete('invitations',{'id':iid,'org_id':org_id()});return back('team')

    @app.route('/invitations/<raw>',methods=['GET','POST'])
    def invitation(raw):
        if not g.user:session['invite_token']=raw;return redirect(url_for('login'))
        if not g.user['verified']:session['invite_token']=raw;return redirect(url_for('verification_pending'))
        if request.method=='POST':session['org']=accounts.accept(raw,g.user);return back()
        invite=store.one('invitations',{'id':digest(raw),'email':g.user['email'],'expires_at':{'$gt':datetime.now(timezone.utc)}})
        if not invite:abort(404,'Invitation not available for this account.')
        return render_template('auth.html',screen='invite',invite=invite,invited_org=store.one('organizations',{'id':invite['org_id']}))

    @app.post('/organizations/members/<user_id>')
    def change_member(user_id):
        require_role('owner');accounts.change_member(org_id(),g.user['id'],user_id,request.form.get('role'))
        return back('team')

    @app.post('/organizations/delete')
    def delete_org():
        require_role('owner')
        if not accounts.authenticate(g.user['email'],request.form.get('password','')):raise ValueError('Confirm your password to delete this organization.')
        org=store.one('organizations',{'id':org_id()})
        if request.form.get('confirmation')!=org['name']:raise ValueError('Type the organization name exactly.')
        accounts.delete_org(org['id'],g.user['id']);session.pop('org',None);return back()

    @app.get('/account')
    def account():return render_template('account.html')

    @app.post('/account/delete')
    def delete_account():
        if not accounts.authenticate(g.user['email'],request.form.get('password','')):raise ValueError('Confirm your password to delete your account.')
        accounts.delete_user(g.user);session.clear();return redirect(url_for('signup'))

    @app.get('/account/2fa/setup')
    def totp_setup():
        if g.user.get('totp_enabled'):return redirect(url_for('account'))
        secret=session.get('pending_totp_secret') or accounts.new_totp_secret()
        session['pending_totp_secret']=secret
        uri=accounts.totp_uri(g.user,secret)
        return render_template('totp_setup.html',secret=secret,qr=accounts.totp_qr_data_uri(uri))

    @app.post('/account/2fa/enable')
    def totp_enable():
        secret=session.get('pending_totp_secret')
        if not secret:raise ValueError('Start setup again from your account page.')
        accounts.enable_totp(g.user,secret,request.form.get('code',''))
        session.pop('pending_totp_secret',None)
        flash('Two-factor authentication is enabled.','success');return redirect(url_for('account'))

    @app.post('/account/2fa/disable')
    def totp_disable():
        if not accounts.authenticate(g.user['email'],request.form.get('password','')):raise ValueError('Confirm your password to disable two-factor authentication.')
        accounts.disable_totp(g.user)
        flash('Two-factor authentication is disabled.','success');return redirect(url_for('account'))

    @app.get('/billing')
    def billing_page():
        org=store.one('organizations',{'id':org_id()})
        return render_template('billing.html',billing_org=org,plans=billing.PLANS,trial_limit=billing.TRIAL_BRIEFING_LIMIT,
            payments_configured=billing.configured())

    @app.post('/billing/checkout')
    def billing_checkout():
        plan=request.form.get('plan')
        if plan not in billing.PLANS:abort(404)
        try:
            url=billing.create_checkout_session(store.one('organizations',{'id':org_id()}),plan,g.user,app.config['BASE_URL'])
        except billing.BillingError as exc:
            flash(str(exc),'error');return redirect(url_for('billing_page'))
        return redirect(url)

    @app.post('/billing/webhook')
    def billing_webhook():
        try:
            event=billing.verify_webhook(request.headers,request.get_data())
        except billing.BillingError as exc:
            abort(400,str(exc))
        touched=billing.apply_event(store,event)
        if touched:store.event('Billing plan updated.',org_id=touched)
        return jsonify(received=True)

    @app.post('/sample')
    def sample():
        service.seed(org_id());store.setting('mode','demo',org_id());flash('Sample accounts are ready. No external actions will be sent.','success');return back()

    @app.post('/run')
    def run():
        service.request_run(org_id(),g.user['id']);flash('Briefing queued.','success');return back()

    @app.post('/actions/<aid>/approve')
    def approve(aid):
        action=service.action(aid,org_id())
        if not action:abort(404)
        payload=dict(action['payload'])
        for key in ACTION_KINDS[action['kind']][2]:
            if key in request.form:payload[key]=request.form[key].strip()
        service.approve(aid,org_id(),payload,g.user['id']);flash('Approved and queued. Activity will confirm completion.','success');return back('decisions')

    @app.post('/actions/<aid>/dismiss')
    def dismiss(aid):
        service.dismiss(aid,org_id(),g.user['id']);return back('decisions')

    @app.post('/preferences')
    def preference():
        rule=request.form.get('rule','').strip()
        if not 1<=len(rule)<=2000:raise ValueError('Write a preference up to 2,000 characters.')
        store.insert('preferences',{'org_id':org_id(),'rule':rule,'created_by':g.user['id'],'created':time.time()});return back('memory')

    @app.post('/preferences/<pid>/delete')
    def delete_preference(pid):store.delete('preferences',{'id':pid,'org_id':org_id()});return back('memory')

    @app.post('/settings')
    def settings():
        mode,engine=request.form.get('mode','demo'),request.form.get('engine','sample')
        if mode not in ('demo','live') or engine not in ('sample','strands'):raise ValueError('Choose a valid operating mode.')
        interval=int(request.form.get('interval_minutes','60'))
        if interval not in (15,30,60,180,1440):raise ValueError('Choose a supported interval.')
        jql=request.form.get('jira_jql','').strip()
        if not 1<=len(jql)<=1000:raise ValueError('Enter a Jira query up to 1,000 characters.')
        schedule_enabled='schedule_enabled' in request.form
        if schedule_enabled and store.one('organizations',{'id':org_id()}).get('plan','pro')=='trial':
            raise ValueError('Automatic scheduling requires a Pro or Team plan. Upgrade in Billing.')
        values={'mode':mode,'engine':engine,'interval_minutes':interval,'schedule_enabled':schedule_enabled,
            'auto_drafts':'auto_drafts' in request.form,'auto_mark_read':'auto_mark_read' in request.form,'jira_jql':jql,'next_run':time.time()+interval*60}
        with store.atomic():
            old=store.settings(org_id());old.update(values);store.update('organizations',{'id':org_id()},{'config':old})
            store.event('Automation policy updated.',org_id=org_id(),actor=g.user['id'])
        flash('Automation settings saved.','success');return back('automation')

    @app.post('/connect/<provider>')
    def connect(provider):
        if provider not in PROVIDERS:abort(404)
        if len(store.connections(org_id=org_id()))>=20:raise ValueError('Connection limit reached for this organization.')
        state=secrets.token_urlsafe(32);url=auth_url(provider,state)
        store.insert('oauth',{'id':digest(state),'provider':provider,'session_id':session['sid'],'user_id':g.user['id'],'org_id':org_id(),'expires_at':expiry(600)})
        return redirect(url)

    @app.get('/oauth/<provider>/callback')
    def callback(provider):
        with store.atomic():
            auth=store.one('oauth',{'id':digest(request.args.get('state','')),'provider':provider,'session_id':session.get('sid'),'user_id':g.user['id'],'expires_at':{'$gt':datetime.now(timezone.utc)}})
            if not auth:abort(400,'Sign-in expired. Start again from Connections.')
            member=store.membership(auth['org_id'],g.user['id'])
            if not member or member['role'] not in ('owner','admin'):abort(403)
            store.delete('oauth',{'id':auth['id']})
        if request.args.get('error') or not request.args.get('code'):flash('Connection canceled.','error');return back('connections')
        finish_oauth(store,provider,request.args['code'],auth['org_id'],g.user['id'])
        session['org']=auth['org_id'];flash('Account connected. Choose live mode separately when ready.','success');return back('connections')

    def owned_connection(cid):
        conn=store.connection(cid,org_id=org_id())
        if not conn:abort(404)
        return conn

    @app.post('/connections/<cid>/disconnect')
    def disconnect(cid):owned_connection(cid);store.disconnect(cid);return back('connections')

    @app.get('/connections/<cid>/channels')
    def channels(cid):
        conn=owned_connection(cid)
        if conn['provider']!='slack' or conn['mode']!='live' or conn['status']!='connected':abort(400)
        available=service.connector(conn).channels();metadata=conn['metadata'];metadata['available_channels']={c['id']:c['name'] for c in available}
        store.update('connections',{'id':cid,'org_id':org_id()},{'metadata':metadata})
        return render_template('channels.html',connection=conn,channels=available,selected=[c['id'] for c in metadata.get('channels',[])])

    @app.post('/connections/<cid>/channels')
    def save_channels(cid):
        conn=owned_connection(cid)
        if conn['provider']!='slack' or conn['status']!='connected':abort(400)
        choices=conn['metadata'].get('available_channels',{});selected=request.form.getlist('channels')
        if len(selected)>5 or any(c not in choices for c in selected):raise ValueError('Choose up to five available channels.')
        metadata=conn['metadata'];metadata['channels']=[{'id':c,'name':choices[c]} for c in selected]
        store.update('connections',{'id':cid,'org_id':org_id()},{'metadata':metadata});service.invalidate_scope(cid);return back('connections')

    @app.route('/connections/<cid>/sites',methods=['GET','POST'])
    def sites(cid):
        conn=owned_connection(cid)
        if conn['provider']!='jira' or conn['mode']!='live' or conn['status']!='connected':abort(400)
        if request.method=='POST':
            selected=request.form.getlist('sites')
            if any(s not in [v['id'] for v in conn['metadata']['sites']] for s in selected):abort(400)
            metadata=conn['metadata'];metadata['selected_sites']=selected
            store.update('connections',{'id':cid,'org_id':org_id()},{'metadata':metadata});service.invalidate_scope(cid);return back('connections')
        return render_template('sites.html',connection=conn)

    @app.get('/connections/<cid>/repos')
    def repos(cid):
        conn=owned_connection(cid)
        if conn['provider']!='github' or conn['mode']!='live' or conn['status']!='connected':abort(400)
        available=service.connector(conn).repos();metadata=conn['metadata'];metadata['available_repos']={r['full_name']:r['full_name'] for r in available}
        store.update('connections',{'id':cid,'org_id':org_id()},{'metadata':metadata})
        return render_template('repos.html',connection=conn,repos=available,selected=[r['full_name'] for r in metadata.get('repos',[])])

    @app.post('/connections/<cid>/repos')
    def save_repos(cid):
        conn=owned_connection(cid)
        if conn['provider']!='github' or conn['status']!='connected':abort(400)
        choices=conn['metadata'].get('available_repos',{});selected=request.form.getlist('repos')
        if len(selected)>10 or any(r not in choices for r in selected):raise ValueError('Choose up to ten available repositories.')
        metadata=conn['metadata'];metadata['repos']=[{'full_name':r} for r in selected]
        store.update('connections',{'id':cid,'org_id':org_id()},{'metadata':metadata});service.invalidate_scope(cid);return back('connections')

    @app.get('/privacy')
    def privacy():return render_template('legal.html',kind='privacy')
    @app.get('/terms')
    def terms():return render_template('legal.html',kind='terms')

    @app.errorhandler(ValueError)
    @app.errorhandler(IntegrationError)
    def expected_error(error):
        flash(str(error),'error')
        if request.endpoint in {'signup','login','forgot_password','reset_password','verify','invitation'}:
            return redirect(request.path)
        if request.endpoint=='delete_account':return redirect(url_for('account'))
        return back()

    @app.errorhandler(PyMongoError)
    def database_error(error):
        app.logger.error('Database operation failed: %s',type(error).__name__)
        return render_template('error.html',message='The database is temporarily unavailable. Your request was not confirmed. Refresh before retrying.'),503

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(429)
    def http_error(error):return render_template('error.html',message=error.description),error.code
    return app


app=create_app()
if __name__=='__main__':app.run(host=os.getenv('COS_HOST','127.0.0.1'),port=int(os.getenv('PORT','5087')),debug=False)
