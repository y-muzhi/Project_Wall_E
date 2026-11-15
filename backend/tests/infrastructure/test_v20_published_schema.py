"""Actual compiled Schema200 pin, no candidate loader substitution."""

from contextlib import redirect_stdout
from io import StringIO
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.infrastructure.schema_v20_release import load_release
from backend.app.infrastructure import schema_v20_cli as cli
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.app.service import create_app
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import seeded_source


def invoke(arguments):
    output = StringIO()
    with redirect_stdout(output):
        code = cli.main(arguments)
    assert code == 0, output.getvalue()
    return json.loads(output.getvalue())


def test_published_pin_fresh_200_works_with_actual_old_document_http_and_new_close_control(
    tmp_path,
):
    release = load_release()
    from backend.app.infrastructure.schema_v20_admission import RELEASE_DIRECTORY

    assert release.release_id == RELEASE_DIRECTORY
    database = tmp_path / 'published-fresh.sqlite'
    assert (
        invoke(
            [
                'init-v20',
                '--database',
                str(database),
                '--package',
                str(tmp_path / 'fresh-private'),
                '--maintenance-window-confirmed',
            ]
        )['status']
        == 'INITIALIZED'
    )
    actual = Database(database, schema_release=release)
    with TestClient(create_app(database=actual)) as client:
        created = client.post(
            '/api/v1/requirements',
            json={
                'title': 'V2真实文档路径',
                'requirement_type': 'NEW',
                'initial_idea': '离线保留路径',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert created.status_code == 201, created.text
        document = client.post(
            '/api/v1/requirements/1/documents',
            json={'name': '真实空文档', 'document_kind': 'DESIGN', 'template_ref': None},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert document.status_code == 201, document.text
        assert (
            client.get('/api/v1/requirements/1/current-document?document_id=1').status_code == 200
        )
        key = str(uuid4())
        closed = client.post(
            '/api/v1/command-intents/close',
            json={'method': 'POST', 'path': '/api/v1/test-plans'},
            headers={'Idempotency-Key': key},
        )
        assert closed.status_code == 200, closed.text
        query = client.get(
            '/api/v1/testing-command-receipts',
            params={'method': 'POST', 'path': '/api/v1/test-plans', 'request_key': key},
        )
        assert query.status_code == 200 and query.json()['data']['record_status'] == 'CLOSED'
        assert not any(
            event['event'].startswith('DISPATCH') for event in client.app.state.walle_worker.events
        )
    with actual.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_published_pin_nonempty_151_cli_rehearsal_apply_and_read_only_check(workspace, tmp_path):
    source = workspace[0]
    original = seeded_source(workspace)
    working = source.backup_to(tmp_path / 'published-original.sqlite')
    common = [
        '--database',
        str(working),
        '--package',
        str(tmp_path / 'published-private'),
        '--maintenance-window-confirmed',
    ]
    plan = invoke(['plan', *common, '--no-config-references'])
    bound = [*common, '--upgrade-id', plan['upgrade_id'], '--plan-sha256', plan['plan_sha256']]
    assert invoke(['rehearse', *bound])['status'] == 'PASSED'
    assert invoke(['apply', *bound])['status'] == 'UPGRADED'
    assert invoke(['recover', *bound])['status'] == 'ALREADY_COMMITTED'
    assert invoke(['check-v20', '--database', str(working)])['status'] == 'CHECKED'
    assert inspect_v151_source(source).data == original
