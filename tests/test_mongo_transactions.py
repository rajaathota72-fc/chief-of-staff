"""Opt-in real replica-set test; uses and deletes a uniquely named test database."""
import os
import uuid
import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from cryptography.fernet import Fernet
from tests.helpers import HASH
from chief_of_staff.store import Store
from chief_of_staff.service import Service

@pytest.mark.skipif(not os.getenv('COS_TEST_MONGODB_URI'),reason='Set COS_TEST_MONGODB_URI to an isolated replica set')
def test_real_transactions_and_workflow():
    client=MongoClient(os.environ['COS_TEST_MONGODB_URI'],serverSelectionTimeoutMS=5000)
    name='cos_test_'+uuid.uuid4().hex
    try:
        store=Store(client[name],Fernet.generate_key())
        with pytest.raises(RuntimeError):
            with store.atomic():
                store.insert('users',{'id':'rollback','email':'rollback@example.com'})
                raise RuntimeError('rollback')
        assert store.one('users',{'id':'rollback'}) is None
        store.insert('users',{'id':'owner','email':'owner@example.com','verified':True,'password_hash':HASH})
        org=store.create_organization('owner','Transaction test')
        service=Service(store);service.seed(org['id'])
        run=service.request_run(org['id'],'owner')
        with pytest.raises(ValueError,match='already queued'):service.request_run(org['id'],'owner')
        service.run(run)
        assert store.one('runs',{'id':run})['status']=='succeeded'
        actions=service.snapshot(org['id'])['actions']
        assert len(actions)==5
        action=next(a for a in actions if a['kind']=='slack_reply')
        service.approve(action['id'],org['id'],actor='owner')
        service.execute_action(action['id'])
        assert store.one('actions',{'id':action['id']})['status']=='succeeded'
    finally:
        client.drop_database(name);client.close()
