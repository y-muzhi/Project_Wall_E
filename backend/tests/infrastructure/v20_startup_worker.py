"""Test listener shell: run real production main/lifespan without a network listener."""

import asyncio
from pathlib import Path
import runpy
import sys
from types import ModuleType

# Intentionally no project/database/sqlite3 import before the production main.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
listener = ModuleType('uvicorn')


def run(app, **options):
    assert options['host'] == '127.0.0.1' and options['port'] == 8000
    assert options['workers'] == 1 and options['reload'] is False

    async def lifecycle():
        async with app.router.lifespan_context(app):
            import sqlite3

            runtime = app.state.walle_runtime
            assert runtime.database.schema_release is not None
            assert runtime.worker.accepting
            with runtime.database.transaction() as connection:
                assert (
                    connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
                    == 200
                )
            print('DEFAULT_V20_STARTED ' + sqlite3.sqlite_version, flush=True)

    asyncio.run(lifecycle())


listener.run = run
sys.modules['uvicorn'] = listener
runpy.run_module('backend.app', run_name='__main__')
