"""Original START authorization bounds content, including retained C39 history."""

import sqlite3

import pytest

from backend.app.code_tasks.task_content_limits import authorized_content_settings
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_task_stop as stops
from backend.tests.code_tasks.test_execution_profile_versions import fixture_snapshot, resources
from backend.tests.code_tasks.test_task_live_configuration import (
    ReadOnlyDriver,
    fixed_price,  # noqa: F401
    idle_task,  # noqa: F401
    isolated_readiness,  # noqa: F401
    opened,  # noqa: F401
    original_instance,  # noqa: F401
    ready,  # noqa: F401
    target_pair,
    versioned_runtime_fixture,  # noqa: F401
)
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401


@pytest.fixture(autouse=True)
def smaller_original_capacity(versioned_runtime_fixture, monkeypatch):  # noqa: F811
    previous = stops.scope

    def scope():
        value = previous()
        value['limits'].update(max_file_bytes=37, max_manifest_bytes=31, max_git_seconds=15)
        return value

    monkeypatch.setattr(stops, 'scope', scope)


@pytest.mark.parametrize(
    'case',
    [
        'minimum',
        'retired-history',
        'wrong-task',
        'wrong-policy',
        'unbound-source',
        'failed-source',
        'wrong-native-owner',
    ],
)
def test_content_limit_proof_never_falls_back_to_profile(idle_task, case):  # noqa: F811
    from uuid import uuid4

    database, runtime, client, _, _, task_id, _, _, _ = idle_task
    original, profile, grant, content = target_pair(
        idle_task, 'content-capacity' if case == 'wrong-policy' else 'controls'
    )
    original_profile = original['execution_profile_version_id']
    if case == 'retired-history':
        with resources(fixture_snapshot(content)):
            accepted = client.post(
                f'/api/v1/code-tasks/{task_id}/configuration',
                json={
                    'expected_state_version': original['state_version'],
                    'execution_profile_version_id': profile,
                    'authorization_id': grant,
                    'reason': '核对退役原授权的固定内容范围',
                },
                headers={'Idempotency-Key': str(uuid4())},
            )
        assert accepted.status_code == 202, accepted.text
        assert advance_live_configuration(
            runtime, ReadOnlyDriver(idle_task), cancelled=lambda: False
        )
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT status FROM code_authorizations WHERE id=?',
                    (original['authorization_id'],),
                ).fetchone()[0]
                == 'RETIRED'
            )
    if case in ('unbound-source', 'wrong-native-owner', 'failed-source'):
        with database.transaction(write=True) as connection:
            if case == 'failed-source':
                connection.execute(
                    "UPDATE code_authorizations SET status='APPLY_FAILED' WHERE id=?",
                    (original['authorization_id'],),
                )
            else:
                step = connection.execute(
                    'SELECT s.* FROM code_operation_steps s JOIN code_operations o ON o.id=s.operation_id '
                    "WHERE o.task_id=? AND o.operation_type='START' AND s.step_no=5",
                    (task_id,),
                ).fetchone()
                source = strict_json_object(step['external_identity'])
                source['authorization_id' if case == 'unbound-source' else 'task_id'] = (
                    grant if case == 'unbound-source' else task_id + 1
                )
                with pytest.raises(sqlite3.IntegrityError, match='ORIGINAL_FACT_IS_FIXED'):
                    connection.execute(
                        'UPDATE code_operation_steps SET external_identity=? WHERE operation_id=? AND step_no=5',
                        (canonical_input(source), step['operation_id']),
                    )
    with database.transaction() as connection:
        if case in ('minimum', 'retired-history', 'unbound-source', 'wrong-native-owner'):
            selected = authorized_content_settings(connection, original_profile, task_id)
            assert (
                selected['max_file_bytes'],
                selected['max_manifest_bytes'],
                selected['max_git_seconds'],
            ) == (37, 31, 15)
            if case == 'retired-history':
                assert authorized_content_settings(connection, profile, task_id) == selected
        else:
            with pytest.raises(StorageUnavailable):
                authorized_content_settings(
                    connection,
                    profile if case == 'wrong-policy' else original_profile,
                    task_id + 1 if case == 'wrong-task' else task_id,
                )
