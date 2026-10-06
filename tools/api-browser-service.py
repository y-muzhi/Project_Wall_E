"""Private browser verification runner: actual API/SQLite, no Provider.

Only explicit test database paths outside the default production path are
accepted. Startup uses production create_app. Stdin controls test shutdown;
there is no extra HTTP route, fake business result or compatibility bypass.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from backend.app.infrastructure.database import Database, ROOT
from backend.app.service import create_app
from backend.app.guide.worker import GuideWorker


class HeldReviewWorker(GuideWorker):
    """Explicit private dispatch barrier for native cancellation evidence.

    REVIEW acceptance is real; orchestration waits before any model work.
    ASK/INITIALIZE/retries use the production worker. No status/result is faked.
    """
    async def _drive(self, identity, lease):
        with self.database.transaction() as connection:
            action = connection.execute('SELECT action_type FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if action is not None and action[0] == 'REVIEW':
            await asyncio.Event().wait()
        else:
            await super()._drive(identity, lease)


async def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--database', required=True)
    parser.add_argument('--hold-review-dispatch', action='store_true')
    args = parser.parse_args(); path = Path(args.database).resolve()
    if not path.is_relative_to(ROOT / 'output' / 'playwright') or not path.name.startswith('api-walle-') or path.exists():
        raise ValueError('A fresh, explicit verification output database is required')
    # Test processes must not inherit real model credentials or configuration.
    for key in list(os.environ):
        if key.startswith('WALLE_MODEL_'): del os.environ[key]
    os.environ['WALLE_DATABASE_PATH'] = str(path)
    database = Database(path); database.initialize()
    factory = (lambda db, catalog: HeldReviewWorker(db, catalog=catalog)) if args.hold_review_dispatch else None
    server = uvicorn.Server(uvicorn.Config(create_app(worker_factory=factory), host='127.0.0.1', port=0, workers=1,
        timeout_graceful_shutdown=10, log_level='warning'))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done(): await asyncio.sleep(0.01)
    if task.done():
        await task; raise RuntimeError('Actual API startup did not complete')
    address = server.servers[0].sockets[0].getsockname()
    print(json.dumps({'ready': True, 'url': f'http://127.0.0.1:{address[1]}'}), flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    server.should_exit = True; await task
    with database.transaction() as connection:
        facts = {name: connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
            for name in ('requirements', 'requirement_documents', 'revisions', 'comments', 'guide_runs', 'llm_uses')}
    print(json.dumps({'closed': True, 'facts': facts}), flush=True)


if __name__ == '__main__': asyncio.run(main())
