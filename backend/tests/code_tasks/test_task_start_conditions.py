"""Original startup checks with real SQLite and private NTFS artifacts."""

import hashlib
import sqlite3
from dataclasses import replace

import pytest

from backend.app.code_tasks import task_start_basis, task_start_conditions
from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.workspace_materialization import FixedWorkspaceStage
from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_execution_profile_versions
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_start_basis import prepare
from backend.tests.infrastructure.test_v20_command_http import package, service
from backend.tests.infrastructure.test_v20_opencode_binary import binary_installation
from backend.tests.infrastructure.test_v20_opencode_protocol_source import protocol_document
from backend.tests.infrastructure.test_v20_opencode_runtime_bundle import runtime_bundle


@pytest.mark.parametrize(
    'damage',
    ['none', 'workspace', 'basis', 'legacy', 'stopped', 'managed', 'deadline', 'size', 'lpac'],
)
def test_original_conditions_preserve_proof_and_never_dispatch(
    service,
    tmp_path,
    isolated_readiness,
    monkeypatch,
    damage,
):
    database, app, client = service
    runtime = app.state.walle_runtime
    with PrivatePackageGuard(create_private_package(tmp_path / 'basis')) as parent:

        class OverLimitWorkspace:
            def restore_snapshot(
                self, snapshot_id, _frames, *, parent, nonce, check_active, cancelled, record_stage
            ):
                assert not cancelled()
                raw = b'x' * 101
                entry = ContentEntry(
                    'large.txt', '100644', 'b' * 40, len(raw), hashlib.sha256(raw).hexdigest()
                )
                stage = FixedWorkspaceStage(
                    parent,
                    nonce,
                    check_active,
                    record_stage=lambda identity: record_stage(identity, 'a' * 32),
                )
                stage.consume(entry, raw)
                return stage.publish(
                    BaselineQueryResult({'id': snapshot_id}, (entry,)), lambda: None
                )

        task_id, _, _, key, receipt = prepare(
            database,
            app,
            client,
            parent,
            workspace_actor=OverLimitWorkspace() if damage == 'size' else None,
        )
        operation_id = receipt['operation_id']
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        verify_workspace = task_start_conditions._verify_workspace
        if damage == 'managed':
            monkeypatch.setattr(
                task_start_conditions, 'opencode_managed_source_clear', lambda: False
            )
        elif damage == 'lpac':
            monkeypatch.setattr(
                task_start_conditions, 'probe_lpac_creation_attributes', lambda: False
            )
        elif damage == 'deadline':
            clock = iter((0, 10**16))
            monkeypatch.setattr(task_start_conditions, 'monotonic', lambda: next(clock))
        elif damage == 'workspace':
            (next(parent.path.glob('working-*')) / 'extra.txt').write_bytes(b'foreign')
        elif damage == 'basis':
            next(parent.path.glob('*.b1.md')).write_bytes(b'changed')
        elif damage == 'legacy':

            def old_receipt(parent, allocation, stored, checkpoint, limits):
                original = strict_json_object(stored)
                original.pop('tree_record')
                return verify_workspace(
                    parent, allocation, canonical_input(original), checkpoint, limits
                )

            monkeypatch.setattr(task_start_conditions, '_verify_workspace', old_receipt)
        elif damage == 'stopped':

            def stop_then_verify(parent, allocation, stored, checkpoint, limits):
                response = stop(client, task_id, 3)
                assert response.status_code == 202, response.text
                return verify_workspace(parent, allocation, stored, checkpoint, limits)

            monkeypatch.setattr(task_start_conditions, '_verify_workspace', stop_then_verify)

        assert task_start_conditions.advance_start_conditions(
            runtime, parent, cancelled=lambda: False
        ) == (damage != 'stopped')
        assert not task_start_conditions.advance_start_conditions(
            runtime, parent, cancelled=lambda: False
        )
        operation = original_operation(client, operation_id)
        assert [step['status'] for step in operation['steps'][:2]] == ['SUCCEEDED', 'SUCCEEDED']
        checks = operation['steps'][2]
        assert checks['external_identity'] is None
        if damage == 'stopped':
            assert operation['status'] == 'RUNNING'
            assert checks['status'] == 'PENDING' and checks['result_ref'] is None
        else:
            content = damage in ('none', 'managed', 'lpac')
            assert operation['status'] == 'FAILED'
            assert checks['status'] == 'FAILED'
            assert operation['failure_code'] == (
                'CONFIG_NOT_READY' if content else 'CONTENT_NOT_READY'
            )
            assert checks['result_ref']['fixed_content_verified'] == content
            assert checks['result_ref']['executor_runtime_bundle_verified'] is False
            assert checks['result_ref']['lpac_creation_attributes_available'] is (damage != 'lpac')
            assert {'Q20-OC', 'Q20-WINDOWS'} <= set(checks['result_ref']['capability_codes'])
            if not content:
                assert 'Q20-CONTENT' in checks['result_ref']['capability_codes']
            if damage == 'managed':
                assert checks['result_ref']['system_config_clear'] is False
                assert 'Q20-CONFIG' in checks['result_ref']['capability_codes']
            detail = client.get(f'/api/v1/code-tasks/{task_id}')
            assert detail.status_code == 200, detail.text
            assert detail.json()['data']['active_operations'] == []
            assert (
                detail.json()['data']['available_actions'][0]['reason_code']
                == operation['failure_code']
            )
        assert all(step['status'] == 'PENDING' for step in operation['steps'][3:])
        assert start(client, task_id, key=key).json()['data'] == receipt

    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_invalid_stored_limits_remain_a_storage_failure():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('CREATE TABLE code_execution_profile_versions(id INTEGER, limits TEXT)')
        connection.execute(
            'INSERT INTO code_execution_profile_versions VALUES(?,?)',
            (1, '{"max_capture_seconds":true}'),
        )
        with pytest.raises(StorageUnavailable, match='limits differ'):
            task_start_conditions._limits(connection, 1)
    finally:
        connection.close()


def test_conditions_record_binary_proof_without_marking_runtime_ready(
    service,
    tmp_path,
    isolated_readiness,
    binary_installation,
    protocol_document,
    runtime_bundle,
    monkeypatch,
):
    database, app, client = service
    runtime = app.state.walle_runtime
    source, _ = binary_installation
    bundle, reference = runtime_bundle()
    default_profile = test_execution_profile_versions.body

    def fixed_profile():
        value = default_profile()
        value['executor']['runtime_bundle_ref'] = reference
        return value

    monkeypatch.setattr(test_execution_profile_versions, 'body', fixed_profile)
    with PrivatePackageGuard(create_private_package(tmp_path / 'conditions')) as parent:
        task_id, _, _, key, receipt = prepare(database, app, client, parent)
        operation_id = receipt['operation_id']
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        assert task_start_conditions.advance_start_conditions(
            runtime,
            parent,
            cancelled=lambda: False,
            executor_binary=replace(
                source, openapi=protocol_document, bundle=bundle, runtime_bundle_ref=reference
            ),
        )
        result = original_operation(client, operation_id)
        assert result['steps'][2]['result_ref']['executor_binary_verified'] is True
        assert result['steps'][2]['result_ref']['executor_protocol_source_verified'] is True
        assert result['steps'][2]['result_ref']['executor_runtime_bundle_verified'] is True
        assert type(result['steps'][2]['result_ref']['wfp_local_ale_layers_readable']) is bool
        assert result['steps'][2]['result_ref']['fixed_content_verified'] is True
        assert result['failure_code'] == 'CONFIG_NOT_READY'
        assert result['steps'][3]['status'] == 'PENDING'
        assert start(client, task_id, key=key).json()['data'] == receipt
