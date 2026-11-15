"""Complete reserved repository publication uses original operation state only."""

from contextlib import contextmanager
from dataclasses import replace
import sqlite3
from unittest.mock import patch

import pytest

from backend.app.code_tasks import repository_registration as module
from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.infrastructure.database import CommitOutcomeUnknown, StorageUnavailable
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.tests.code_tasks.test_repository_acceptance import request, runtime
from backend.tests.infrastructure.test_v20_command_http import package

AT = '2026-11-06T00:00:00.000Z'


def capture():
    return module.RepositoryRegistrationCapture(
        r'C:\fixture', r'C:\fixture', r'C:\fixture\.git', 'sha1', 'a' * 64
    )


def prepared(runtime):
    original = request()
    operation_id = accept_repository_operation(runtime, original)['data']['operation_id']
    module.start_repository_registration(runtime, operation_id)
    return original, operation_id


def test_complete_record_steps_and_original_202_publish_together(runtime):
    original, operation_id = prepared(runtime)
    assert module.publish_repository_registration(runtime, operation_id, capture()) == 1
    assert module.publish_repository_registration(runtime, operation_id) == 1
    assert accept_repository_operation(runtime, original)['data']['operation_status'] == 'PENDING'
    with runtime.database.transaction() as c:
        row = c.execute('SELECT * FROM code_repositories').fetchone()
        assert dict(row) == {
            'id': 1,
            'name': 'fixture',
            'canonical_root': r'C:\fixture',
            'git_common_dir': r'C:\fixture\.git',
            'object_format': 'sha1',
            'created_at': row['created_at'],
        }
        assert c.execute('SELECT status FROM code_operations').fetchone()[0] == 'SUCCEEDED'
        assert [r[0] for r in c.execute('SELECT status FROM code_operation_steps')] == [
            'SUCCEEDED',
            'SUCCEEDED',
        ]
        assert c.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
    assert runtime.commands().command_receipt(original.command.scope)['original_http_status'] == 202


@pytest.mark.parametrize(
    'changed',
    [
        {'selected_path': r'C:\other'},
        {'canonical_root': r'C:\fixture\..\other'},
        {'git_common_dir': r'\\server\share'},
        {'object_format': 'sha512'},
        {'metadata_sha256': 'g' * 64},
    ],
)
def test_invalid_capture_never_completes_validation_or_creates_repository(runtime, changed):
    operation_id = accept_repository_operation(runtime, request())['data']['operation_id']
    module.start_repository_registration(runtime, operation_id)
    with pytest.raises((StorageUnavailable, PathBoundaryError)):
        module.publish_repository_registration(runtime, operation_id, replace(capture(), **changed))
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
        assert (
            c.execute('SELECT status FROM code_operation_steps WHERE step_no=1').fetchone()[0]
            == 'RUNNING'
        )


def test_pending_or_cancelled_operation_cannot_publish(runtime):
    operation_id = accept_repository_operation(runtime, request())['data']['operation_id']
    with pytest.raises(StorageUnavailable):
        module.publish_repository_registration(runtime, operation_id, capture())
    module.start_repository_registration(runtime, operation_id)
    module.start_repository_registration(runtime, operation_id)
    with runtime.database.transaction(write=True) as c:
        c.execute("UPDATE code_operations SET status='CANCELLED',ended_at=?", (AT,))
    with pytest.raises(StorageUnavailable):
        module.publish_repository_registration(runtime, operation_id, capture())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0


def test_failure_after_repository_insert_rolls_back_publication(runtime):
    _, operation_id = prepared(runtime)
    with patch.object(module, 'compact', side_effect=OSError('owned failure')):
        with pytest.raises(OSError):
            module.publish_repository_registration(runtime, operation_id, capture())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
        assert c.execute('SELECT status FROM code_operations').fetchone()[0] == 'RUNNING'
        assert (
            c.execute('SELECT status FROM code_operation_steps WHERE step_no=2').fetchone()[0]
            == 'PENDING'
        )
    assert module.publish_repository_registration(runtime, operation_id, capture()) == 1


def test_lost_commit_ack_reconciles_original_repository_without_capture_or_new_ids(runtime):
    _, operation_id = prepared(runtime)
    transaction = runtime.database.transaction
    armed = True

    @contextmanager
    def lost_ack(*, write=False):
        nonlocal armed
        with transaction(write=write) as c:
            yield c
        if write and armed:
            armed = False
            raise CommitOutcomeUnknown('owned acknowledgment loss')

    with patch.object(runtime.database, 'transaction', lost_ack):
        with pytest.raises(CommitOutcomeUnknown):
            module.publish_repository_registration(runtime, operation_id, capture())
    assert module.publish_repository_registration(runtime, operation_id) == 1
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 1
        assert (
            c.execute(
                "SELECT last_value FROM sequences WHERE entity_kind='CodeRepository'"
            ).fetchone()[0]
            == 1
        )


def test_same_original_common_directory_cannot_create_second_repository(runtime):
    _, first = prepared(runtime)
    module.publish_repository_registration(runtime, first, capture())
    _, second = prepared(runtime)
    assert second == 2
    with pytest.raises(sqlite3.IntegrityError):
        module.publish_repository_registration(runtime, second, capture())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 1
        assert c.execute('SELECT status FROM code_operations WHERE id=2').fetchone()[0] == 'RUNNING'
        assert (
            c.execute(
                "SELECT last_value FROM sequences WHERE entity_kind='CodeRepository'"
            ).fetchone()[0]
            == 2
        )
