import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
import mongomock
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
from chief_of_staff.store import Store, defaults
PASSWORD='correct-horse-battery-staple'
HASH=generate_password_hash(PASSWORD)

def make_store():
    store=Store(mongomock.MongoClient(tz_aware=True).cos,Fernet.generate_key(),testing=True)
    store.insert('users',{'id':'owner','email':'owner@example.com','name':'Owner','verified':True,'password_hash':HASH})
    store.insert('organizations',{'id':'personal','name':'My workspace','status':'active','config':defaults(),'created':0,'auth_revision':0})
    store.insert('memberships',{'org_id':'personal','user_id':'owner','role':'owner','created':0})
    return store

def add_user(store,uid,email=None):
    return store.insert('users',{'id':uid,'email':email or uid+'@example.com','name':uid,'verified':True,'password_hash':HASH})
