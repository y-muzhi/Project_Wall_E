"""Original PREPARE_BASIS with actual SQLite and private NTFS records."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.code_tasks import task_start_basis, task_start_workspace
from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.task_basis import TaskBasisUnavailable
from backend.app.code_tasks.workspace_materialization import FixedWorkspaceStage
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.service import create_app
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.infrastructure.test_v20_command_http import package, service


class WorkspaceActor:
    def restore_snapshot(
        self, snapshot_id, _frames, *, parent, nonce, check_active, cancelled, record_stage
    ):
        assert not cancelled()
        stage = FixedWorkspaceStage(
            parent,
            nonce,
            check_active,
            record_stage=lambda identity: record_stage(identity, 'a' * 32),
        )
        return stage.publish(BaselineQueryResult({'id': snapshot_id}, ()), lambda: None)


def prepare(database, app, client, parent, *, workspace_actor=None, before_start=None):
    runtime = app.state.walle_runtime
    task_id = seed_task(database, runtime, client)
    workspace = (database, runtime.commands(), runtime.catalog)
    material = document(workspace, kind='DESIGN', name='固定空附录')['data']
    document_id, revision = material['document']['id'], material['revision_id']
    confirmed = metadata(
        workspace,
        document_id,
        1,
        {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': revision},
    )
    assert confirmed['code'] == 'UPDATED'
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_task_materials(task_id,document_id,revision_id) VALUES(?,?,?)',
            (task_id, document_id, revision),
        )
        main_id = connection.execute(
            'SELECT document_id FROM code_tasks WHERE id=?', (task_id,)
        ).fetchone()[0]
    key = str(uuid4())
    version = 1 if before_start is None else before_start(task_id)
    received = start(client, task_id, version, key=key)
    assert received.status_code == 202, received.text
    task_start_workspace.advance_workspace_start(
        runtime,
        WorkspaceActor() if workspace_actor is None else workspace_actor,
        None,
        parent,
        cancelled=lambda: False,
    )
    return task_id, main_id, document_id, key, received.json()['data']


def test_basis_publishes_full_fixed_bytes_and_reads_only_original_task(
    service, tmp_path, isolated_readiness
):
    database, app, client = service
    runtime = app.state.walle_runtime
    with PrivatePackageGuard(create_private_package(tmp_path / 'basis')) as parent:
        task_id, main_id, material_id, key, receipt = prepare(database, app, client, parent)
        operation_id = receipt['operation_id']
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        operation = original_operation(client, operation_id)
        assert [step['status'] for step in operation['steps'][:3]] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'PENDING',
        ]
        assert operation['steps'][1]['result_ref'] == {'document_count': 2}
        assert operation['steps'][1]['external_identity'] == {}
        assert 'canonical_path' not in str(operation) and '原固定设计' not in str(operation)
        main = task_start_basis.read_prepared_basis_document(runtime, parent, operation_id, main_id)
        assert main == '原固定设计\n'.encode('utf-8')
        assert (
            task_start_basis.read_prepared_basis_document(
                runtime, parent, operation_id, material_id
            )
            == b''
        )
        with pytest.raises(TaskBasisUnavailable, match='document'):
            task_start_basis.read_prepared_basis_document(runtime, parent, operation_id, 999)
        assert not task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        assert start(client, task_id, key=key).json()['data'] == receipt
        document_file = next(parent.path.glob('*.b1.md'))
        document_file.write_bytes(b'wrong')
        with pytest.raises(TaskBasisUnavailable, match='bytes'):
            task_start_basis.read_prepared_basis_document(runtime, parent, operation_id, main_id)
        response = stop(client, task_id, 3)
        assert response.status_code == 202, response.text
        with pytest.raises(TaskBasisUnavailable, match='fenced'):
            task_start_basis.read_prepared_basis_document(
                runtime, parent, operation_id, material_id
            )


@pytest.mark.parametrize('sealed', [True, False])
def test_restart_observes_seal_or_retains_incomplete_original(
    package, tmp_path, isolated_readiness, monkeypatch, sealed
):
    root, release = package
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database)
    with PrivatePackageGuard(create_private_package(tmp_path / 'basis')) as parent:
        with TestClient(app) as client:
            task_id, main_id, _, key, receipt = prepare(database, app, client, parent)
            operation_id = receipt['operation_id']
            with monkeypatch.context() as patch:

                def lose_after_seal(*args, **kwargs):
                    raise SystemExit('simulated owner retirement')

                def lose_during_write(parent, binding, originals, check_active):
                    check_active()
                    with PrivateRecordAppend(
                        parent,
                        binding['nonce'] + '.b1.md',
                        originals[0].utf8,
                        max_record_bytes=4096,
                    ) as first:
                        first.publish()
                    raise SystemExit('simulated owner retirement')

                if sealed:
                    patch.setattr(task_start_basis, 'read_basis_package', lose_after_seal)
                else:
                    patch.setattr(task_start_basis, 'publish_basis_package', lose_during_write)
                with pytest.raises(SystemExit):
                    task_start_basis.advance_start_basis(
                        app.state.walle_runtime, parent, cancelled=lambda: False
                    )
            assert original_operation(client, operation_id)['steps'][1]['status'] == 'RUNNING'
            before = {
                file.name: (file.stat().st_ino, file.read_bytes())
                for file in parent.path.glob('*.b*')
            }
        reopened = create_app(database=database)
        with TestClient(reopened) as client:
            runtime = reopened.state.walle_runtime
            if sealed:
                assert task_start_basis.advance_start_basis(
                    runtime, parent, cancelled=lambda: False
                )
                assert task_start_basis.read_prepared_basis_document(
                    runtime, parent, operation_id, main_id
                ) == '原固定设计\n'.encode('utf-8')
            else:
                with pytest.raises(PathBoundaryError):
                    task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
                detail = client.get(f'/api/v1/code-tasks/{task_id}')
                assert detail.status_code == 200, detail.text
                assert detail.json()['data']['active_operations'][0]['status'] == 'UNKNOWN'
            assert {
                file.name: (file.stat().st_ino, file.read_bytes())
                for file in parent.path.glob('*.b*')
            } == before
            assert original_operation(client, operation_id)['steps'][1]['status'] == (
                'SUCCEEDED' if sealed else 'UNKNOWN'
            )
            assert start(client, task_id, key=key).json()['data'] == receipt
            assert not task_start_basis.advance_start_basis(
                runtime, parent, cancelled=lambda: False
            )


@pytest.mark.parametrize('stop_after_first', [True, False])
def test_basis_stop_or_missing_source_never_claims_completion(
    service,
    tmp_path,
    isolated_readiness,
    monkeypatch,
    stop_after_first,
):
    database, app, client = service
    runtime = app.state.walle_runtime
    with PrivatePackageGuard(create_private_package(tmp_path / 'basis')) as parent:
        task_id, _, _, _, receipt = prepare(database, app, client, parent)
        operation_id = receipt['operation_id']
        if stop_after_first:
            publish = task_start_basis.publish_basis_package

            def stopped_publish(parent, binding, originals, check_active):
                with PrivateRecordAppend(
                    parent,
                    binding['nonce'] + '.b1.md',
                    originals[0].utf8,
                    max_record_bytes=4096,
                ) as first:
                    first.publish()
                response = stop(client, task_id, 3)
                assert response.status_code == 202, response.text
                return publish(parent, binding, originals, check_active)

            monkeypatch.setattr(task_start_basis, 'publish_basis_package', stopped_publish)
            with pytest.raises(TaskBasisUnavailable, match='fenced'):
                task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
            assert len(list(parent.path.glob('*.b1.md'))) == 1
            assert not list(parent.path.glob('*.b2.md'))
        else:

            def missing(*args, **kwargs):
                raise TaskBasisUnavailable('Original fixture is unavailable')

            monkeypatch.setattr(task_start_basis, 'read_task_basis', missing)
            assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
            assert not list(parent.path.glob('*.b*.md'))
        assert not list(parent.path.glob('*.basis-seal.json'))
        operation = original_operation(client, operation_id)
        assert operation['steps'][0]['status'] == 'SUCCEEDED'
        assert operation['steps'][1]['status'] == ('UNKNOWN' if stop_after_first else 'FAILED')
        assert operation['failure_code'] == (
            'EXTERNAL_RESULT_UNKNOWN' if stop_after_first else 'CONTENT_NOT_READY'
        )
        detail = client.get(f'/api/v1/code-tasks/{task_id}')
        assert detail.status_code == 200, detail.text
        view = detail.json()['data']
        assert view['workspace_id'] == operation['steps'][0]['result_ref']['workspace_id']
        if not stop_after_first:
            assert view['active_operations'] == []
            assert view['available_actions'][0] == {
                'action': 'START',
                'enabled': False,
                'reason_code': 'CONTENT_NOT_READY',
                'related_id': operation_id,
            }
        assert not task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
