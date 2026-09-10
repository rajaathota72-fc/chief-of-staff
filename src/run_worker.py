"""Run separately from the web process; both connect to the same MongoDB database."""
from dotenv import load_dotenv
from chief_of_staff.store import Store
from chief_of_staff.service import Service
from chief_of_staff.worker import Worker
load_dotenv()
if __name__=='__main__':
    worker=Worker(Service(Store.from_env()))
    try:worker.loop()
    except KeyboardInterrupt:worker.stop_event.set()
