"""MongoDB repository. Production requires a replica set/Atlas for transactions."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import time
import uuid
from cryptography.fernet import Fernet
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


def uid(): return uuid.uuid4().hex

def defaults():
    return {'mode':'demo','engine':'sample','schedule_enabled':False,'interval_minutes':60,'next_run':0,
            'auto_drafts':True,'auto_mark_read':False,'jira_jql':'assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC'}


class Store:
    def __init__(self, database, encryption_key, testing=False):
        self.database, self.testing = database, testing
        self.cipher = Fernet(encryption_key)
        self._session = ContextVar('mongo_session', default=None)
        self.execution_owner = ContextVar('execution_owner',default=None)
        self.create_indexes()

    @classmethod
    def from_env(cls):
        uri, key = os.getenv('MONGODB_URI'), os.getenv('COS_ENCRYPTION_KEY')
        if not uri or not key: raise ValueError('Set MONGODB_URI and COS_ENCRYPTION_KEY before starting the application.')
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, tz_aware=True)
        hello = client.admin.command('hello')
        if not hello.get('setName') and hello.get('msg') != 'isdbgrid':
            raise ValueError('MongoDB must be Atlas, a replica set, or a sharded cluster with transaction support.')
        return cls(client[os.getenv('MONGODB_DATABASE','chief_of_staff')], key)

    def create_indexes(self):
        names = ['users','organizations','memberships','invitations','sessions','auth_tokens','connections','items','actions','runs','jobs','preferences','oauth','events','leases','mail','rate_limits']
        for name in names: self.database[name].create_index('id',unique=True)
        self.database.users.create_index('email',unique=True)
        self.database.memberships.create_index([('org_id',1),('user_id',1)],unique=True)
        self.database.connections.create_index([('org_id',1),('provider',1),('mode',1),('identity',1)],unique=True)
        self.database.items.create_index([('org_id',1),('connection_id',1),('kind',1),('external_id',1)],unique=True)
        self.database.actions.create_index('fingerprint',unique=True)
        self.database.runs.create_index('org_id',unique=True,partialFilterExpression={'active':True})
        self.database.jobs.create_index([('kind',1),('target',1)],unique=True,partialFilterExpression={'active':True})
        for name in ['actions','items','runs','preferences','events','jobs','connections','invitations']:
            self.database[name].create_index([('org_id',1),('created',-1)])
        for name in ['sessions','auth_tokens','oauth','invitations','rate_limits']:
            self.database[name].create_index('expires_at',expireAfterSeconds=0)
        self.database.jobs.create_index([('status',1),('created',1)])

    def options(self):
        session = self._session.get()
        return {'session':session} if session is not None else {}

    @contextmanager
    def atomic(self):
        if self._session.get() is not None:
            yield; return
        if self.testing:
            # Test double rollback. Real transaction behavior is tested separately against a replica set.
            snapshot = {name:list(self.database[name].find()) for name in self.database.list_collection_names()}
            try: yield
            except Exception:
                for name in self.database.list_collection_names():
                    self.database[name].delete_many({})
                    if snapshot.get(name): self.database[name].insert_many(snapshot[name])
                raise
        else:
            with self.database.client.start_session() as session:
                token=self._session.set(session)
                try:
                    with session.start_transaction(read_concern=ReadConcern('snapshot'),write_concern=WriteConcern('majority')):
                        yield
                finally: self._session.reset(token)

    def find(self, collection, query=None, sort=None, limit=0):
        cursor=self.database[collection].find(query or {}, {'_id':0}, **self.options())
        if sort: cursor=cursor.sort(sort)
        if limit: cursor=cursor.limit(limit)
        return list(cursor)

    def one(self, collection, query):
        return self.database[collection].find_one(query, {'_id':0}, **self.options())

    def insert(self, collection, document):
        doc=deepcopy(document); doc.setdefault('id',uid())
        self.database[collection].insert_one(doc,**self.options())
        doc.pop('_id',None)
        return doc

    def update(self, collection, query, values, many=False):
        method=self.database[collection].update_many if many else self.database[collection].update_one
        return method(query,{'$set':values},**self.options()).matched_count

    def delete(self, collection, query):
        return self.database[collection].delete_many(query,**self.options()).deleted_count

    def claim(self, collection, query, values, sort=None):
        doc = self.database[collection].find_one_and_update(query,{'$set':values},sort=sort,
                   return_document=ReturnDocument.AFTER,**self.options())
        if doc: doc.pop('_id',None)
        return doc

    def settings(self, org_id=None):
        if not org_id: return defaults()
        org=self.one('organizations',{'id':org_id,'status':'active'})
        if not org: raise ValueError('Organization not available.')
        return dict(defaults(),**org['config'])

    def setting(self,key,value,org_id):
        self.update('organizations',{'id':org_id,'status':'active'},{'config.'+key:value})

    def event(self,message,level='info',org_id=None,actor=None):
        self.insert('events',{'message':message,'level':level,'org_id':org_id,'actor':actor,'created':time.time()})

    def membership(self,org_id,user_id):
        return self.one('memberships',{'org_id':org_id,'user_id':user_id})

    def organizations_for(self,user_id):
        ids=[m['org_id'] for m in self.find('memberships',{'user_id':user_id})]
        return self.find('organizations',{'id':{'$in':ids},'status':'active'},sort=[('created',1)])

    def create_organization(self,user_id,name):
        if len(self.organizations_for(user_id))>=20: raise ValueError('Organization limit reached. Contact support.')
        with self.atomic():
            org=self.insert('organizations',{'name':name,'status':'active','config':defaults(),'created':time.time(),'auth_revision':0})
            self.insert('memberships',{'org_id':org['id'],'user_id':user_id,'role':'owner','created':time.time()})
        return org

    def connection(self,cid,secret=False,org_id=None):
        query={'id':cid}
        if org_id: query['org_id']=org_id
        conn=self.one('connections',query)
        if conn:
            encrypted=conn.pop('secrets')
            if secret: conn['secrets']=json.loads(self.cipher.decrypt(encrypted.encode()))
        return conn

    def connections(self,mode=None,org_id=None):
        query={}
        if mode: query['mode']=mode
        if org_id: query['org_id']=org_id
        return [self.connection(c['id']) for c in self.find('connections',query,sort=[('created',1)])]

    def connect(self,provider,label,tokens,metadata,mode='live',org_id=None,owner_id=None):
        if not org_id: raise ValueError('An organization is required.')
        self.settings(org_id)
        query={'org_id':org_id,'provider':provider,'mode':mode,'identity':metadata['identity']}
        values={'label':label,'metadata':metadata,'secrets':self.cipher.encrypt(json.dumps(tokens).encode()).decode(),
                'status':'connected','error':None,'grant_owner':owner_id}
        with self.atomic():
            existing=self.one('connections',query)
            if existing:
                cid=existing['id']; self.update('connections',{'id':cid},values)
            else:
                cid=self.insert('connections',dict(query,**values,created=time.time(),last_sync=None))['id']
            if mode=='live': self.save_tokens(cid,tokens)
        return cid

    def save_tokens(self,cid,tokens):
        conn=self.connection(cid)
        # Never share OAuth grants between different application users merely because provider metadata matches.
        query={'provider':conn['provider'],'identity':conn['identity'],'grant_owner':conn.get('grant_owner'),'status':'connected','mode':'live'}
        if not conn.get('grant_owner'): query['id']=cid
        self.update('connections',query,{'secrets':self.cipher.encrypt(json.dumps(tokens).encode()).decode()},many=True)

    def disconnect(self,cid):
        with self.atomic():
            conn=self.connection(cid)
            if self.one('actions',{'connection_id':cid,'status':'executing'}): raise ValueError('Wait for the current action to finish.')
            self.update('connections',{'id':cid},{'status':'disconnected','secrets':self.cipher.encrypt(b'{}').decode()})
            self.update('actions',{'connection_id':cid,'status':{'$in':['proposed','queued','failed']}},{'status':'dismissed','updated':time.time()},many=True)
            self.event('Account disconnected; pending actions canceled.',org_id=conn['org_id'])

    def enqueue(self,kind,target,org_id=None):
        try:
            self.insert('jobs',{'kind':kind,'target':target,'org_id':org_id,'status':'queued','active':True,'created':time.time()})
            return True
        except DuplicateKeyError: return False

    def claim_job(self,owner):
        return self.claim('jobs',{'status':'queued','active':True},{'status':'running','owner':owner,'started':time.time()},sort=[('created',1)])

    def lease(self,owner):
        try:
            result=self.database.leases.find_one_and_update({'id':'worker','$or':[{'owner':owner},{'expires':{'$lt':time.time()}}]},
                {'$set':{'owner':owner,'expires':time.time()+45}},upsert=True,return_document=ReturnDocument.AFTER)
            return result['owner']==owner
        except DuplicateKeyError: return False

    def owns_lease(self,owner):
        return bool(self.one('leases',{'id':'worker','owner':owner,'expires':{'$gt':time.time()}}))

    def rate_limit(self,key,limit,seconds):
        bucket=int(time.time()//seconds)
        rid=hashlib.sha256(f'{key}:{bucket}'.encode()).hexdigest()
        result=self.database.rate_limits.find_one_and_update({'id':rid},{'$inc':{'count':1},'$setOnInsert':{'expires_at':datetime.fromtimestamp((bucket+2)*seconds,timezone.utc)}},upsert=True,return_document=ReturnDocument.AFTER)
        return result['count']<=limit

    def check_execution(self):
        owner=self.execution_owner.get()
        if owner and not self.owns_lease(owner):raise ValueError('Worker lease lost. No further provider calls may execute.')
