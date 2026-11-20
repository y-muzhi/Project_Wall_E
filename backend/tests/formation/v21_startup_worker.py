"""Exercise native main bootstrap and actual lifecycle without opening a listener."""

import asyncio
from pathlib import Path
import runpy
import sys
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
listener = ModuleType('uvicorn')


def run(app, **options):
    assert options['host'] == '127.0.0.1' and options['workers'] == 1 and options['reload'] is False

    async def lifecycle():
        async with app.router.lifespan_context(app):
            import sqlite3

            runtime = app.state.walle_runtime
            assert runtime.worker.accepting and runtime.catalog.collaboration.formation_driven
            with runtime.database.transaction() as connection:
                assert (
                    connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
                    == 210
                )
            import httpx

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url='http://isolated-native'
            ) as client:
                result = await client.get('/api/v1/requirements/1/documents/1/formation/steps')
                assert result.status_code == 404, result.text
                assert result.json()['error']['code'] == 'NOT_FOUND', result.text
            print('EXPLICIT_V21_STARTED ' + sqlite3.sqlite_version, flush=True)

    asyncio.run(lifecycle())


listener.run = run
sys.modules['uvicorn'] = listener
sys.argv = ['backend.app', '--schema-version', '210']
runpy.run_module('backend.app', run_name='__main__')
