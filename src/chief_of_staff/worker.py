"""Dedicated leased worker with durable Mongo jobs and conservative recovery."""
import logging
import threading
import time
from .store import uid
from .mail import deliver

log=logging.getLogger(__name__)

class Worker:
    def __init__(self,service):
        self.service,self.store=service,service.store
        self.owner,self.stop_event=uid(),threading.Event()
        self.leader=False;self.thread=None

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.thread=threading.Thread(target=self.loop,name='cos-worker',daemon=True);self.thread.start()

    def heartbeat(self):
        while not self.stop_event.is_set():
            try:self.leader=self.store.lease(self.owner)
            except Exception:self.leader=False
            self.stop_event.wait(8)

    def recover(self):
        with self.store.atomic():
            self.store.update('actions',{'status':'executing'},{'status':'uncertain','error':'The worker stopped before completion was confirmed. Check the provider before closing this item.'},many=True)
            self.store.update('runs',{'status':'running'},{'status':'failed','active':False,'error':'The worker stopped during this briefing. Existing actions are preserved.','finished':time.time()},many=True)
            self.store.update('mail',{'status':'sending'},{'status':'failed','payload':None},many=True)
            self.store.update('jobs',{'status':'running'},{'status':'done','active':False,'finished':time.time()},many=True)
            for collection,kind in [('runs','run'),('actions','action'),('mail','mail')]:
                for row in self.store.find(collection,{'status':'queued'}):self.store.enqueue(kind,row['id'],row.get('org_id'))

    def tick(self):
        if not self.store.owns_lease(self.owner):return
        for org in self.store.find('organizations',{'status':'active','config.schedule_enabled':True,'config.next_run':{'$lte':time.time()}}):
            settings=self.store.settings(org['id'])
            try:self.service.request_run(org['id'])
            except ValueError:pass
            self.store.setting('next_run',time.time()+settings['interval_minutes']*60,org['id'])
        job=self.store.claim_job(self.owner)
        if not job:return
        token=self.store.execution_owner.set(self.owner)
        try:
            self.store.check_execution()
            if job['kind']=='run':self.service.run(job['target'])
            elif job['kind']=='action':self.service.execute_action(job['target'])
            elif job['kind']=='mail':deliver(self.store,job['target'])
        except Exception:
            log.exception('Background job failed: %s',job['id'])
        finally:
            self.store.execution_owner.reset(token)
            self.store.update('jobs',{'id':job['id'],'owner':self.owner,'status':'running'},{'status':'done','active':False,'finished':time.time()})

    def loop(self):
        threading.Thread(target=self.heartbeat,daemon=True).start()
        recovered=False
        while not self.stop_event.is_set():
            try:
                if self.leader:
                    if not recovered:self.recover();recovered=True
                    self.tick()
                else:recovered=False
            except Exception:log.exception('Worker tick failed')
            self.stop_event.wait(1)
