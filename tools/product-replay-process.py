"""Fresh Python process: actual startup and original-key HTTP receipt replay.

The isolated test file is supplied explicitly. Default compatibility remains
closed and credentials are absent. A diagnostic Gateway rejects/counts every
attempted send, never fabricates a model result. All success is native replay.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from time import monotonic
import traceback
import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.service import create_app
from backend.app.guide.worker import GuideWorker
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.process_lock import ProcessLock


async def replay(record, database_path, request_path):
    allowed = (ROOT / 'output/product-flow').resolve()
    if not database_path.is_relative_to(allowed) or not request_path.is_relative_to(allowed):
        raise ValueError('Only explicitly isolated product-flow paths are accepted')
    request_data = json.loads(request_path.read_text(encoding='utf-8'))
    record['request_sha256'] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    database = Database(database_path); attempts = []
    class ForbiddenSend(ModelGateway):
        async def send(self, *args, **kwargs):
            attempts.append({'attempted': True})
            raise AssertionError('A persistent success replay must not send a model request')
    def factory(db, resources):
        return GuideWorker(db, catalog=resources, orchestrator_options={'gateway': ForbiddenSend()})
    application = create_app(database=database, worker_factory=factory)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(); listener.setblocking(False)
    server = uvicorn.Server(uvicorn.Config(application, log_level='error', access_log=False, lifespan='on'))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        due = monotonic() + 10
        while not server.started and not serving.done() and monotonic() < due: await asyncio.sleep(0.01)
        if not server.started or serving.done(): raise AssertionError('Fresh-process startup must admit after native recovery')
        worker = application.state.walle_worker
        record['owner_epoch'] = worker.process_lock.owner_epoch
        record['startup_events'] = list(worker.events)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:' + str(listener.getsockname()[1]), trust_env=False, timeout=10) as client:
            response = await client.post('/api/v1' + request_data['path'], json=request_data['body'],
                                         headers={'Idempotency-Key': request_data['key']})
            record['http_status'] = response.status_code; record['response'] = response.json()
            if response.status_code != request_data['status']: raise AssertionError('Fresh process must replay original successful HTTP status')
            due = monotonic() + 5
            while worker.live_run_ids and monotonic() < due: await asyncio.sleep(0.01)
            if worker.live_run_ids: raise AssertionError('Fresh-process original-key replay must settle without model execution')
        record['model_send_attempts'] = attempts
        if attempts: raise AssertionError('A fresh-process replay attempted model execution')
        record['worker_events_after_replay'] = list(worker.events)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 15); listener.close()
        with ProcessLock.for_database(database.path): record['process_lock_reacquired_after_close'] = True


def main():
    if len(sys.argv) != 4: raise SystemExit('Supply isolated database, request and evidence paths')
    database, request_path, evidence = (Path(value).resolve() for value in sys.argv[1:])
    if not evidence.is_relative_to((ROOT / 'output/product-flow').resolve()): raise SystemExit('Evidence must stay inside isolated output')
    record = {'scope': __doc__, 'pid': os.getpid(), 'parent_pid': os.getppid(),
              'normal_database_access': False, 'paid_requests': 0, 'credential_present': bool(os.environ.get('WALLE_MODEL_API_KEY'))}
    try:
        if record['credential_present']: raise AssertionError('Fresh-process diagnostic must have no model credential')
        asyncio.run(replay(record, database, request_path)); record['passed'] = True
    except Exception:
        record['passed'] = False; record['failure_traceback'] = traceback.format_exc()
    evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': record['passed'], 'evidence': str(evidence)}))
    if not record['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
