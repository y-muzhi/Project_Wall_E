"""Real normal main/app/Schema200; only network listener and Guard worker are fixtures."""

import asyncio
import os
import runpy
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
mode = os.environ['WALLE_TEST_DEPLOYMENT_MODE']
listener = ModuleType('uvicorn')
calls = []


def run(app, **options):
    if mode == 'reject':
        raise AssertionError('Invalid deployment reached the application listener')
    from backend.app import service

    class RegistrationFixture:
        testing_cli_resources = None

        def __init__(self, runtime, installation):
            assert runtime.database.schema_release is not None
            assert installation.installation_ref == 'a' * 64
            if mode == 'valid_models':
                assert installation.task_launch is not None
                assert len(installation.coding_models.admissions) == 1
                assert (
                    installation.coding_models.admissions[0].model.api_key
                    == 'fixture-only-model-credential'
                )
            else:
                assert installation.task_launch is None
            if mode == 'valid_checks':
                assert len(installation.testing_cli) == 1
                assert len(installation.testing_browser) == 1
                assert len(installation.case_packs) == 1
                assert not installation.delivery_runtime_admitted
            calls.append(('registration', installation))

        def start(self):
            calls.append(('start', None))

        def close(self):
            calls.append(('close', None))

    service.RepositoryRegistrationWorker = RegistrationFixture
    assert options['host'] == '127.0.0.1' and options['workers'] == 1

    async def lifecycle():
        async with app.router.lifespan_context(app):
            assert app.state.walle_worker.accepting
            assert isinstance(app.state.walle_repository_registration, RegistrationFixture)
            manifest = Path(os.environ['WALLE_CODE_DEPLOYMENT_MANIFEST'])
            try:
                manifest.rename(manifest.with_suffix('.changed'))
            except PermissionError:
                pass
            else:
                raise AssertionError('Manifest was not retained throughout app lifetime')
            with app.state.walle_runtime.database.transaction() as connection:
                assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
                assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
        assert [kind for kind, _ in calls] == ['registration', 'start', 'close']

    asyncio.run(lifecycle())


if mode == 'valid_models':
    # Named fixed-release input port for this isolated fake ZIP/SDK only.
    # All actual path/digest/PE/closure validators still execute in main.
    import hashlib
    import json

    from backend.app.infrastructure import opencode_binary, opencode_protocol_source

    data = json.loads(Path(os.environ['WALLE_CODE_DEPLOYMENT_MANIFEST']).read_bytes())
    executor = data['task']['executor']
    for key in ('archive', 'openapi'):
        assert Path(executor[key]).resolve().is_relative_to(Path(os.environ['WALLE_CHECK_TEMP']))
    opencode_binary.RELEASE_SHA256 = hashlib.sha256(
        Path(executor['archive']).read_bytes()
    ).hexdigest()
    raw = Path(executor['openapi']).read_bytes()
    opencode_protocol_source.OPENAPI_BYTES = len(raw)
    opencode_protocol_source.OPENAPI_BLOB = hashlib.sha1(
        'blob '.encode() + str(len(raw)).encode('ascii') + bytes([0]) + raw
    ).hexdigest()

listener.run = run
sys.modules['uvicorn'] = listener
try:
    runpy.run_module('backend.app', run_name='__main__')
except RuntimeError as error:
    if mode != 'reject' or str(error) != 'CODE_DEPLOYMENT_SOURCE_DIGEST_DIFFERS':
        raise
    assert not calls
    assert not Path(os.environ['WALLE_DATABASE_PATH']).exists()
    print('LOCAL_DEPLOYMENT_REJECTED_BEFORE_DATABASE', flush=True)
else:
    assert mode in ('valid', 'valid_checks', 'valid_models')
    manifest = Path(os.environ['WALLE_CODE_DEPLOYMENT_MANIFEST'])
    manifest.rename(manifest.with_suffix('.released'))
    print('LOCAL_DEPLOYMENT_STARTUP_PASSED', flush=True)
