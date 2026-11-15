"""The original stage fence on real V2 SQLite, without exposing API50."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from zlib import compress

import pytest

from backend.app.code_tasks import task_runtime_stop
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.task_candidate_commit import (
    claim_candidate_capture,
    commit_published_candidate,
    load_candidate_capture,
    read_stored_candidate_package,
    record_candidate_seal,
    reserve_candidate_identity,
)
from backend.app.code_tasks.task_candidate_runtime import (
    capture_original_candidate,
    reconcile_original_candidate,
)
from backend.app.code_tasks.task_candidate_worker import CandidateCaptureWorker
from backend.app.code_tasks.task_capture_quiescence import (
    observe_capture_quiescence,
    read_capture_quiescence,
)
from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence
from backend.app.code_tasks.task_model_ingress import read_original_open_window
from backend.app.code_tasks.task_records import record_native_turn, safe_native_records
from backend.app.infrastructure.content_manifest import (
    ContentLimits,
    _canonical,
    build_manifest,
    encode_manifest,
    manifest_sha256,
)
from backend.app.infrastructure.content_package import (
    SealedCandidate,
    verify_candidate_package,
)
from backend.app.infrastructure.content_package_publish import PublishedCandidate
from backend.app.infrastructure.git_content_command import (
    content_config_bytes,
    content_git_arguments,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.content_secret_policy import REFERENCE
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.opencode_instance_control import (
    NativeTurnCompletion,
    NativeTurnRecord,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    PrivatePackageGuard,
)
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_task_stop as stop_fixture
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened
from backend.tests.code_tasks.test_execution_profile_versions import (
    body,
    fixture_snapshot,
    publish,
    resources,
)
from backend.tests.code_tasks.test_task_start import isolated_readiness, stop
from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import ready
from backend.tests.infrastructure.test_v20_command_http import package, service
from backend.tests.code_tasks.v20_git_vector_worker import owned_git_environment
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture(autouse=True)
def candidate_content_limits(monkeypatch, request):
    def publish_candidate_profile(client):
        profile = body()
        if (
            getattr(request.node, 'callspec', None)
            and request.node.callspec.params.get('restore_case') == 'live-control-configuration'
        ):
            profile['executor']['runtime_bundle_ref'] = 'opencode-bundle:sha256:' + 'a' * 64
        profile['limits'].update(
            max_manifest_bytes=4096,
            max_git_output_bytes=4096,
        )
        profile['capture_rules']['secret_policy_ref'] = REFERENCE
        return publish(client, profile)

    content = body()
    if (
        getattr(request.node, 'callspec', None)
        and request.node.callspec.params.get('restore_case') == 'live-control-configuration'
    ):
        content['executor']['runtime_bundle_ref'] = 'opencode-bundle:sha256:' + 'a' * 64
    content['capture_rules']['secret_policy_ref'] = REFERENCE
    previous_scope = stop_fixture.scope
    case = (
        request.node.callspec.params.get('restore_case')
        if getattr(request.node, 'callspec', None)
        else None
    )

    def authorized_scope():
        selected = previous_scope()
        selected['limits'].update(max_manifest_bytes=4096, max_git_output_bytes=4096)
        if case and case.startswith('authorization-') and case != 'authorization-manifest-capacity':
            selected['limits']['max_file_bytes'] = 1
        elif case == 'authorization-manifest-capacity':
            selected['limits']['max_manifest_bytes'] = 1
        return selected

    monkeypatch.setattr(stop_fixture, 'scope', authorized_scope)
    monkeypatch.setattr(stop_fixture, 'publish', publish_candidate_profile)
    monkeypatch.setattr(stop_fixture, 'resources', lambda: resources(fixture_snapshot(content)))


def _capture_operation(database, window):
    at = operation_time(None)
    with database.transaction(write=True) as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (window.task_id,)
        ).fetchone()
        operation = entity_id(connection, EntityKind.OPERATION_RECORD)
        fixed = canonical_input(
            {'purpose': 'HANDOFF', 'expected_state_version': task['state_version']}
        )
        connection.execute(
            """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
               operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
               VALUES(?,?,'TASK',?,?,'CAPTURE_AND_CHECK','10100000-0000-4000-8000-000000000001',?,?,?,'PENDING',?)""",
            (
                operation,
                window.task_id,
                window.task_id,
                window.execution_session_id,
                task['state_version'],
                fixed,
                window.generation,
                at,
            ),
        )
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (window.execution_session_id,)
        ).fetchone()
        prepared = reserve_candidate_identity(
            connection,
            task,
            operation,
            session,
            state_version=task['state_version'] + 1,
        )
        connection.executemany(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
               VALUES(?,?,?,'PENDING',?)""",
            [
                (operation, i, step, prepared.fixed() if step == 'CAPTURE' else fixed)
                for i, step in enumerate(operation_steps('CODING', 'CAPTURE_AND_CHECK'), 1)
            ],
        )
        connection.execute(
            'UPDATE code_tasks SET state_version=state_version+1 WHERE id=?', (window.task_id,)
        )
    return operation


@pytest.mark.parametrize(
    'case', ['settled', 'wrong-receipt', 'changed-during-read', 'unknown-operation']
)
def test_only_original_native_turn_and_guard_may_record_quiescence(opened, tmp_path, case):
    database, runtime, client, proof, credential, _ = opened
    window = proof.window
    operation = _capture_operation(database, window)
    with database.transaction() as connection:
        original = read_capture_quiescence(connection, operation)
        assert read_original_open_window(connection, window, credential) is None
    secret = 'temporary-fixture-control-value'
    observed_text = '保留第一行\n保留第二行'
    raw_records = (
        NativeTurnRecord('prt_text', 'MESSAGE', observed_text),
        NativeTurnRecord('prt_safe', 'TOOL', 'read：已结束。'),
        NativeTurnRecord('prt_secret', 'MESSAGE', '原连接凭据 ' + secret),
        NativeTurnRecord('prt_header', 'MESSAGE', 'Authorization: fixture-header-value'),
        NativeTurnRecord('prt_env', 'MESSAGE', 'export PROVIDER_ACCESS_TOKEN=fixture-env-value'),
        NativeTurnRecord('prt_path', 'MESSAGE', '打开 /root/private-not-for-display.txt'),
    )
    workspace = tmp_path / 'runtime'
    workspace.mkdir()
    with LocalPathGuard(workspace, directory=True) as guard:
        evidence = CaptureTurnEvidence(
            safe_native_records(
                NativeTurnCompletion(
                    window.native_session_id,
                    window.trigger_message_id,
                    'msg_end',
                    'COMPLETED',
                    raw_records,
                ),
                (secret,),
            ),
            original.guard_receipt_sha256,
            1,
            guard.verify(),
        )

    class Driver:
        calls = 0

        def observe_capture_turn(self, scope, model, ref, checkpoint):
            self.calls += 1
            assert (scope, model, ref) == (original.native_owner, window, credential)
            checkpoint()
            if case == 'changed-during-read':
                with database.transaction(write=True) as connection:
                    connection.execute(
                        'UPDATE code_tasks SET state_version=state_version+1 WHERE id=?',
                        (window.task_id,),
                    )
            if case == 'wrong-receipt':
                return replace(evidence, guard_receipt_sha256='0' * 64)
            return evidence

    driver = Driver()
    if case == 'unknown-operation':
        with database.transaction(write=True) as connection:
            other = entity_id(connection, EntityKind.OPERATION_RECORD)
            connection.execute(
                """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
                   operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
                   VALUES(?,?,'TASK',?,?,'RESUME','unknown-fixture',1,'{}',?,'UNKNOWN',?)""",
                (
                    other,
                    window.task_id,
                    window.task_id,
                    window.execution_session_id,
                    window.generation,
                    operation_time(None),
                ),
            )
    if case == 'settled':
        identity = observe_capture_quiescence(runtime, driver, operation, cancelled=lambda: False)
        with database.transaction() as connection:
            observed = connection.execute(
                'SELECT * FROM code_runtime_observations WHERE id=?', (identity,)
            ).fetchone()
            assert (
                observed['operation_id'],
                observed['kind'],
                observed['result'],
                observed['active_process_count'],
            ) == (
                operation,
                'QUIESCE',
                'VERIFIED',
                1,
            )
            step = connection.execute(
                'SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (operation,),
            ).fetchone()
            assert step['status'] == 'SUCCEEDED'
            saved_step = strict_json_object(step['result_ref'])
            assert saved_step['quiesce_observation_id'] == identity
            assert 'records' not in saved_step['proof']['turn']
            assert secret not in step['result_ref']
            model = connection.execute(
                'SELECT model_window FROM code_sessions WHERE id=?', (window.execution_session_id,)
            ).fetchone()[0]
            assert strict_json_object(model)['state'] == 'CLOSED'
            assert read_original_open_window(connection, window, credential) is None
        with pytest.raises(TaskExecutionError, match='NOT_CURRENT'):
            observe_capture_quiescence(runtime, driver, operation, cancelled=lambda: False)
        assert driver.calls == 1
        with database.transaction(write=True) as connection:
            # The subsequent original role observation may see the same events.
            record_native_turn(connection, window, evidence.turn, operation_time(None))
        result = client.get(
            f'/api/v1/code-tasks/{window.task_id}/records',
            params={'session_id': window.execution_session_id},
        )
        assert result.status_code == 200, result.text
        rows = [row for row in result.json()['data']['items'] if row['native_event_id']]
        assert [(row['kind'], row['text']) for row in rows] == [
            ('MESSAGE', observed_text),
            ('TOOL', 'read：已结束。'),
            ('MESSAGE', '此原生记录的内容不可安全显示。'),
            ('MESSAGE', '此原生记录的内容不可安全显示。'),
            ('MESSAGE', '此原生记录的内容不可安全显示。'),
            ('MESSAGE', '此原生记录的内容不可安全显示。'),
        ]
        assert {row['source_id'] for row in rows} == {window.operation_id}
        assert secret not in result.text and 'fixture-header-value' not in result.text
        assert (
            'fixture-env-value' not in result.text and 'private-not-for-display' not in result.text
        )
    else:
        with pytest.raises(TaskExecutionError):
            observe_capture_quiescence(runtime, driver, operation, cancelled=lambda: False)
        assert driver.calls == (0 if case == 'unknown-operation' else 1)
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT count(*) FROM code_runtime_observations WHERE operation_id=?',
                    (operation,),
                ).fetchone()[0]
                == 0
            )
            assert read_original_open_window(connection, window, credential) is None


@pytest.mark.parametrize('mode', ['current', 'recovered', 'stopped'])
def test_fixed_candidate_commit_is_original_only_and_cas_gated(
    opened, ready, tmp_path, mode, monkeypatch
):
    database, runtime, client, model, _, _ = opened
    late_stop = mode == 'stopped'
    window = model.window
    operation = _capture_operation(database, window)
    source = tmp_path / 'source'
    source.mkdir()
    with LocalPathGuard(source, directory=True) as guard:
        original_source = guard.verify()

    class Driver:
        def observe_capture_turn(self, scope, model, ref, checkpoint):
            checkpoint()
            return CaptureTurnEvidence(
                NativeTurnCompletion(
                    model.native_session_id, model.trigger_message_id, 'msg_end', 'COMPLETED'
                ),
                'c' * 64,
                1,
                original_source,
            )

    observe_capture_quiescence(runtime, Driver(), operation, cancelled=lambda: False)
    with database.transaction(write=True) as connection:
        prepared, root = claim_candidate_capture(connection, operation, at=operation_time(None))
        assert root == original_source
        with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
            claim_candidate_capture(connection, operation, at=operation_time(None))
    assert prepared.binding.object_format == 'sha1'
    limits = ContentLimits(128, 1024, 10, 4096)
    manifest = build_manifest(
        (),
        content_profile_version_id=prepared.binding.content_profile_version_id,
        format='sha1',
        content_tree_oid='4b825dc642cb6eb9a060e54bf8d69288fbee4904',
        limits=limits,
    )
    at = operation_time(None)
    seal = SealedCandidate(
        prepared.binding, manifest, manifest_sha256(encode_manifest(manifest, limits)), at
    )
    parent_path = create_private_package(tmp_path / 'capture-root')
    store = create_private_package(parent_path / 'candidate-store')
    directory = store / prepared.binding.package_name(staged=False)
    if mode == 'current':
        _write_empty_candidate(directory, seal, limits)
        with LocalPathGuard(directory, directory=True) as guard:
            published = PublishedCandidate(seal, guard.verify())
        with database.transaction(write=True) as connection:
            with pytest.raises(TaskExecutionError, match='SEAL_REQUIRED'):
                commit_published_candidate(connection, operation, published, at=at)
            record_candidate_seal(connection, operation, seal, at=at)
            identity = commit_published_candidate(connection, operation, published, at=at)
    else:
        staged = store / prepared.binding.package_name(staged=True)
        _write_empty_candidate(staged, seal, limits)
        with database.transaction(write=True) as connection:
            connection.execute(
                """UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN'
                   WHERE id=?""",
                (operation,),
            )
            connection.execute(
                "UPDATE code_operation_steps SET status='UNKNOWN' WHERE operation_id=? AND step_no=2",
                (operation,),
            )
            if late_stop:
                connection.execute(
                    """UPDATE code_tasks SET status='STOPPING',control_generation=control_generation+1,
                    state_version=state_version+1,stop_requested_at=? WHERE id=?""",
                    (at, window.task_id),
                )

        def unexpected_connection():
            raise AssertionError('Sealed recovery must not contact Guard or run Git')

        binding = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
        with (
            PrivatePackageGuard(parent_path) as parent,
            LaunchJournal(create_private_package(tmp_path / 'capture-journal')) as journal,
        ):
            worker = CandidateCaptureWorker(
                runtime,
                None,
                parent,
                binding,
                journal,
                unexpected_connection,
                cancelled=lambda: False,
                cleanup_timeout_ms=1000,
            )
            assert worker.advance()
            assert not worker.advance()
        assert not staged.exists()
        identity = prepared.binding.candidate_id
        with LocalPathGuard(directory, directory=True) as guard:
            published = PublishedCandidate(seal, guard.verify())
    assert identity == prepared.binding.candidate_id
    at = operation_time(None)
    with database.transaction(write=True) as connection:
        assert commit_published_candidate(connection, operation, published, at=at) == identity
        row = connection.execute('SELECT * FROM code_candidates WHERE id=?', (identity,)).fetchone()
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (window.task_id,)
        ).fetchone()
        assert (
            row['capture_operation_id'] == operation
            and row['manifest_sha256'] == seal.manifest_sha256
        )
        assert (row['file_count'], row['byte_count'], row['published_for_testing_at']) == (
            0,
            0,
            None,
        )
        assert task['current_candidate_id'] == (None if late_stop else identity)
        assert task['status'] == ('STOPPING' if late_stop else 'VERIFYING')
        assert task['current_verification_id'] is None
        assert (
            connection.execute(
                'SELECT status FROM code_operation_steps WHERE operation_id=? AND step_no=4',
                (operation,),
            ).fetchone()[0]
            == 'PENDING'
        )
        wrong = replace(published, directory=replace(published.directory, file_id='1' * 32))
        with pytest.raises(StorageUnavailable, match='candidate result differs'):
            commit_published_candidate(connection, operation, wrong, at=at)

    if not late_stop:
        response = client.get(f'/api/v1/code-tasks/{window.task_id}')
        assert response.status_code == 200, response.text
        task = response.json()['data']
        assert task['status'] == 'VERIFYING' and task['current_candidate_id'] == identity
        assert task['runtime']['activity_status'] == 'QUIESCENT'
        assert task['active_operations'] == [
            {'id': operation, 'operation_type': 'CAPTURE_AND_CHECK', 'status': 'RUNNING'},
        ]
    observed = client.get(f'/api/v1/code-tasks/{window.task_id}/operations/{operation}')
    assert observed.status_code == 200, observed.text
    original = observed.json()['data']
    assert original['status'] == ('CANCELLED' if late_stop else 'RUNNING')
    assert original['content_capture']['state'] == ('FAILED' if late_stop else 'VERIFYING')
    assert original['steps'][2]['result_ref'] == {'candidate_id': identity}
    assert (
        prepared.binding.content_store_key not in observed.text
        and str(directory) not in observed.text
    )
    with database.transaction() as connection:
        actual = read_stored_candidate_package(
            connection,
            connection.execute('SELECT * FROM code_candidates WHERE id=?', (identity,)).fetchone(),
        )
    with PrivatePackageGuard(directory) as owned:
        assert (
            verify_candidate_package(
                owned,
                actual.binding,
                limits=actual.limits,
                git_limits=actual.git_limits,
                started_at=monotonic(),
                active=lambda: None,
            )
            == seal
        )
    url = f'/api/v1/code-tasks/{window.task_id}/candidates'
    response = client.get(url)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['meta']['pagination'] == {
        'page': 1,
        'page_size': 20,
        'total': 1,
        'total_pages': 1,
    }
    (candidate,) = result['data']['items']
    assert candidate['id'] == identity and candidate['file_count'] == 0
    assert 'content_store_key' not in candidate and 'directory' not in candidate
    assert client.get(f'{url}/{identity}').json()['data'] == candidate
    assert client.get(url, params={'page': 2}).json()['data']['items'] == []
    assert client.get(url + '?page=1&page=2').status_code == 422
    assert (
        client.get(f'/api/v1/code-tasks/{window.task_id + 1}/candidates/{identity}').status_code
        == 404
    )
    if mode == 'current':
        task_path = f'/api/v1/code-tasks/{window.task_id}'
        current = client.get(task_path).json()['data']
        received = stop(client, window.task_id, current['state_version'])
        assert received.status_code == 202, received.text
        driver = StopDriver(ready[3])
        for step in range(1, 12):
            clock = datetime.now(UTC) + timedelta(seconds=200 * step)
            monkeypatch.setattr(
                task_runtime_stop,
                'operation_time',
                lambda _: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            )
            task_runtime_stop.advance_owned_stops(runtime, driver, cancelled=lambda: False)
            observed = client.get(task_path)
            assert observed.status_code == 200, observed.text
            if observed.json()['data']['status'] == 'TERMINATED':
                break
        else:
            pytest.fail('Original candidate stop did not terminate')
        assert observed.json()['data']['current_candidate_id'] == identity
        assert client.get(f'{url}/{identity}').json()['data'] == candidate
        cancelled = client.get(f'/api/v1/code-tasks/{window.task_id}/operations/{operation}')
        assert cancelled.json()['data']['status'] == 'CANCELLED'
    loose = directory / 'repo.git' / 'objects' / '4b' / '825dc642cb6eb9a060e54bf8d69288fbee4904'
    with loose.open('ab') as file:
        file.write(b'trailing compressed data')
    for target in (url, f'{url}/{identity}'):
        failure = client.get(target)
        assert failure.status_code == 409, failure.text
        assert failure.json()['error']['code'] == 'CONTENT_NOT_READY'


def _write_empty_candidate(directory, seal, limits):
    create_private_package(directory)
    tree = seal.manifest.content_tree_oid
    repo = directory / 'repo.git'
    for name in (
        'objects/info',
        'objects/pack',
        f'objects/{tree[:2]}',
        'refs/heads',
        'refs/tags',
        'refs/walle',
    ):
        (repo / name).mkdir(parents=True, exist_ok=True)
    records = {
        'repo.git/HEAD': b'ref: refs/heads/walle-content\n',
        'repo.git/config': content_config_bytes(seal.binding.object_format),
        'repo.git/refs/walle/content': tree.encode() + b'\n',
        f'repo.git/objects/{tree[:2]}/{tree[2:]}': compress(b'tree 0\0'),
        'manifest.json': encode_manifest(seal.manifest, limits),
        'seal.json': _canonical(
            seal.binding.seal(seal.manifest, seal.manifest_sha256, seal.captured_at)
        ),
    }
    for name, raw in records.items():
        with (directory / name).open('xb') as stream:
            stream.write(raw)


@pytest.mark.parametrize(
    'restore_case',
    [
        'changed-and-extra',
        'authorization-file-capacity',
        'authorization-manifest-capacity',
        'authorization-version-unknown',
        'authorization-seal-unknown',
        'authorization-command-unknown',
        'authorization-stop-unknown',
        'authorization-worker-unknown',
        'authorization-owner-retired',
        'live-control-configuration',
        'file-blocks-directory',
        'cancelled-turn',
        'archived-session',
        'archived-session-lost-create',
        'archived-session-create-reconcile',
        'archived-session-create-reconcile-stop',
        'archived-session-lost-message',
        'archived-session-stop',
        'archived-session-source-drift',
        'archived-session-cancel',
        'archived-session-cancel-archived',
    ],
)
def test_original_capture_runs_fixed_git_and_recovers_without_source(
    opened, ready, tmp_path, monkeypatch, restore_case
):
    from types import SimpleNamespace
    from uuid import uuid4

    from backend.app.code_tasks.task_repair_runtime import (
        RepairSourceChanged,
        RepairWriterUnverified,
        _verify_original_workspace,
        advance_repairs,
    )
    from backend.app.code_tasks.task_basis_package import runtime_basis_plan
    from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
    from backend.app.code_tasks.task_model_ingress import ModelWindow, read_original_window_state
    from backend.app.code_tasks.task_native_actions import TaskNativeActions
    from backend.app.code_tasks.task_project_check import fail_unprepared_project_check
    from backend.app.code_tasks.task_start import original_start_steps
    from backend.app.code_tasks.task_start_workspace import workspace_allocation
    from backend.app.infrastructure.opencode_identifiers import OpenCodeMessageIds
    from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceError

    archived_case = restore_case.startswith('archived-session')
    cancelled_case = restore_case in (
        'cancelled-turn',
        'archived-session-cancel',
        'archived-session-cancel-archived',
    )
    database, runtime, client, model, credential, admission = opened
    _, _, _, workspace_parent, _, _, _ = ready
    operation = _capture_operation(database, model.window)
    source = tmp_path / 'original-writer' / 'workspace'
    source.mkdir(parents=True)
    scratch = source.with_name('scratch')
    scratch.mkdir()
    result_file = source / 'src' / 'inner' / 'result.txt'
    result_file.parent.mkdir(parents=True)
    with result_file.open('xb') as file:
        file.write(b'original bytes\r\n')
    with LocalPathGuard(source, directory=True) as directory:
        source_identity = directory.verify()
    with LocalPathGuard(scratch, directory=True) as directory:
        scratch_identity = directory.verify()

    class Driver:
        observations = 0
        scratch = scratch_identity

        def observe_capture_turn(self, scope, window, ref, checkpoint):
            checkpoint()
            self.observations += 1
            return CaptureTurnEvidence(
                NativeTurnCompletion(
                    window.native_session_id,
                    window.trigger_message_id,
                    'msg_end' if window == model.window else f'msg_repair{window.operation_id}',
                    'CANCELLED'
                    if cancelled_case
                    and window != model.window
                    and window.operation_id == original_repair_operation
                    else 'COMPLETED',
                ),
                'c' * 64,
                1,
                source_identity,
                self.scratch,
            )

    driver = Driver()
    observe_capture_quiescence(runtime, driver, operation, cancelled=lambda: False)
    store_path = create_private_package(tmp_path / 'candidate-store')
    build = tmp_path / 'git-scratch'
    build.mkdir()
    environment = owned_git_environment(build)
    git = (
        Path(__file__).resolve().parents[3]
        / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'
    )
    executions = []

    def exchange(intent, repo, raw, maximum, remaining):
        arguments = content_git_arguments(intent, repo)
        executions.append(arguments)
        report = build / f'original-{len(executions)}.bin'
        code = (
            'import subprocess; from pathlib import Path; '
            f'row=subprocess.run({[str(git), *arguments]!r}, input={raw!r}, env={environment!r}, '
            f'capture_output=True, timeout={remaining!r}, check=True); '
            f'assert not row.stderr and len(row.stdout) <= {maximum}; '
            f'with_path=Path({str(report)!r}); with_path.open("xb").write(row.stdout)'
        )
        child = TestSuspendedRoot(job, build, code)
        try:
            child.resume()
            with ObservedProcess(child.pid) as observed:
                deadline = monotonic() + remaining
                while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                    sleep(0.01)
                outcome = observed.observe()
            assert outcome.state == 'EXITED' and outcome.exit_code == 0
            return report.read_bytes()
        finally:
            child.close()

    with PrivatePackageGuard(store_path) as store:
        job = OwnedJob(active_process_limit=8, job_memory_limit_bytes=512 * 1024 * 1024)
        try:
            if restore_case.startswith('authorization-'):
                from contextlib import nullcontext

                from backend.app.code_tasks.task_candidate_commit import capture_package_limits

                with database.transaction() as connection:
                    prepared, _, _, _ = load_candidate_capture(connection, operation)
                    effective, _ = capture_package_limits(
                        connection,
                        prepared.binding.content_profile_version_id,
                        task_id=model.window.task_id,
                    )
                    assert (
                        effective.max_file_bytes
                        if restore_case != 'authorization-manifest-capacity'
                        else effective.max_manifest_bytes
                    ) == 1
                rejected = []
                capacity_cancelled = [False]
                process_lock = runtime.commands().process_lock
                original_owned = process_lock.assert_owned

                class LocalCaptureWorker(CandidateCaptureWorker):
                    def _store(self, *, create):
                        return nullcontext(store)

                    def _exchange(self, _operation, *values):
                        return exchange(*values)

                    def _fail_capacity(self, identity, error):
                        rejected.append(error)
                        if restore_case == 'authorization-seal-unknown':
                            stage = store.path / prepared.binding.package_name(staged=True)
                            if not stage.exists():
                                create_private_package(stage)
                            with (stage / 'seal.json').open('xb') as marker:
                                marker.write(b'{}')
                        elif restore_case == 'authorization-command-unknown':
                            from backend.app.infrastructure.git_content_command import (
                                CONTENT_COMMAND_REF,
                            )

                            with database.transaction(write=True) as connection:
                                connection.execute(
                                    """INSERT INTO code_commands(id,task_id,session_id,operation_id,
                                       purpose,command_ref,config_version_id,status,created_at)
                                       VALUES(?,?,?,?,'CONTROL_GIT',?,?,'UNKNOWN',?)""",
                                    (
                                        entity_id(connection, EntityKind.COMMAND_EXECUTION),
                                        prepared.task_id,
                                        prepared.session_id,
                                        identity,
                                        CONTENT_COMMAND_REF,
                                        prepared.binding.content_profile_version_id,
                                        operation_time(None),
                                    ),
                                )
                        elif restore_case == 'authorization-version-unknown':
                            with database.transaction(write=True) as connection:
                                connection.execute(
                                    'UPDATE code_tasks SET state_version=state_version+1,updated_at=? WHERE id=?',
                                    (operation_time(None), prepared.task_id),
                                )
                        elif restore_case == 'authorization-owner-retired':

                            def no_longer_owned():
                                raise RuntimeError('FIXTURE_EXECUTION_OWNER_RETIRED')

                            monkeypatch.setattr(process_lock, 'assert_owned', no_longer_owned)
                        elif restore_case == 'authorization-worker-unknown':
                            capacity_cancelled[0] = True
                        elif restore_case == 'authorization-stop-unknown':
                            with database.transaction() as connection:
                                version = connection.execute(
                                    'SELECT state_version FROM code_tasks WHERE id=?',
                                    (prepared.task_id,),
                                ).fetchone()[0]
                            stopped = stop(client, prepared.task_id, version)
                            assert stopped.status_code == 202, stopped.text
                        return super()._fail_capacity(identity, error)

                local = LocalCaptureWorker(
                    runtime,
                    driver,
                    workspace_parent,
                    None,
                    None,
                    lambda: nullcontext(None),
                    cancelled=lambda: capacity_cancelled[0],
                    cleanup_timeout_ms=30000,
                )
                if restore_case == 'authorization-owner-retired':
                    try:
                        with pytest.raises(RuntimeError, match='FIXTURE_EXECUTION_OWNER_RETIRED'):
                            local.advance()
                    finally:
                        monkeypatch.setattr(process_lock, 'assert_owned', original_owned)
                else:
                    assert local.advance()
                    assert not local.advance()
                assert len(rejected) == 1
                causes = []
                error = rejected[0]
                while error is not None and len(causes) < 20:
                    causes.append(str(error))
                    error = error.__cause__ or error.__context__
                expected = (
                    'CONFIG_READ_BYTES_EXCEEDED'
                    if restore_case != 'authorization-manifest-capacity'
                    else 'CONTENT_MANIFEST_BYTES_EXCEEDED'
                )
                assert any(expected in cause for cause in causes), causes
                with database.transaction() as connection:
                    assert (
                        connection.execute('SELECT count(*) FROM code_candidates').fetchone()[0]
                        == 0
                    )
                    assert (
                        connection.execute(
                            'SELECT current_candidate_id FROM code_tasks WHERE id=?',
                            (model.window.task_id,),
                        ).fetchone()[0]
                        is None
                    )
                    assert connection.execute(
                        'SELECT status FROM code_operation_steps WHERE operation_id=? AND step_no=2',
                        (operation,),
                    ).fetchone()[0] == (
                        'RUNNING'
                        if restore_case == 'authorization-owner-retired'
                        else 'UNKNOWN'
                        if restore_case.endswith('-unknown')
                        else 'FAILED'
                    )
                detail = client.get(f'/api/v1/code-tasks/{model.window.task_id}')
                assert detail.status_code == 200, detail.text
                result = client.get(
                    f'/api/v1/code-tasks/{model.window.task_id}/operations/{operation}'
                )
                assert result.status_code == 200, result.text
                if restore_case == 'authorization-owner-retired':
                    assert result.json()['data']['status'] == 'RUNNING'
                    assert result.json()['data']['content_capture']['state'] == 'READING'
                    assert detail.json()['data']['state_version'] == prepared.state_version
                elif restore_case.endswith('-unknown'):
                    assert result.json()['data']['status'] == 'UNKNOWN'
                    assert result.json()['data']['content_capture']['state'] == 'UNKNOWN'
                    if restore_case == 'authorization-stop-unknown':
                        assert detail.json()['data']['status'] == 'STOPPING'
                    if restore_case == 'authorization-seal-unknown':
                        assert (
                            store.path / prepared.binding.package_name(staged=True) / 'seal.json'
                        ).read_bytes() == b'{}'
                else:
                    assert result.json()['data']['status'] == 'FAILED'
                    assert result.json()['data']['failure_code'] == 'CONTENT_NOT_READY'
                    assert result.json()['data']['content_capture']['state'] == 'FAILED'
                    assert [row['status'] for row in result.json()['data']['steps']] == [
                        'SUCCEEDED',
                        'FAILED',
                        'CANCELLED',
                        'CANCELLED',
                    ]
                import json
                import subprocess

                decoder = """
import {readFileSync} from 'node:fs';
import {decodeCaptureOperation} from './frontend/src/api/code-task-capture-operation.ts';
import {decodeTaskView} from './frontend/src/api/code-task-creation.ts';
const data = JSON.parse(readFileSync(0, 'utf8'));
const operation = decodeCaptureOperation(data.operation);
const task = decodeTaskView(data.task);
if (operation.task_id !== task.id) throw Error('Original task association differs');
console.log('CAPTURE_FAILURE_DTO_PASSED');
"""
                decoded = subprocess.run(
                    [
                        'C:/Program Files/nodejs/node.exe',
                        '--require',
                        str(Path(__file__).resolve().parents[3] / 'tools/quality_node.cjs'),
                        '--input-type=module',
                        '-e',
                        decoder,
                    ],
                    cwd=Path(__file__).resolve().parents[3],
                    input=json.dumps(
                        {
                            'operation': result.json()['data'],
                            'task': detail.json()['data'],
                        }
                    ),
                    text=True,
                    encoding='utf-8',
                    capture_output=True,
                    timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
                assert decoded.returncode == 0, decoded.stderr
                assert 'CAPTURE_FAILURE_DTO_PASSED' in decoded.stdout
                if restore_case == 'authorization-file-capacity':
                    stopped = stop(
                        client,
                        prepared.task_id,
                        detail.json()['data']['state_version'],
                    )
                    assert stopped.status_code == 202, stopped.text
                    closing = client.get(f'/api/v1/code-tasks/{prepared.task_id}')
                    assert closing.status_code == 200, closing.text
                    assert closing.json()['data']['status'] == 'STOPPING'
                    history = client.get(
                        f'/api/v1/code-tasks/{prepared.task_id}/operations/{operation}'
                    )
                    assert (
                        history.status_code == 200 and history.json()['data']['status'] == 'FAILED'
                    )
                assert not (store.path / prepared.binding.package_name(staged=False)).exists()
                return
            identity = capture_original_candidate(
                runtime,
                driver,
                operation,
                workspace_parent=workspace_parent,
                store=store,
                exchange=exchange,
                materialization_root=tmp_path / 'check',
                cancelled=lambda: False,
            )
        finally:
            job.close()
        assert len(executions) == 11 and driver.observations == 3
        with database.transaction() as connection:
            candidate = connection.execute(
                'SELECT * FROM code_candidates WHERE id=?', (identity,)
            ).fetchone()
            original = read_stored_candidate_package(connection, candidate)
            start = connection.execute(
                "SELECT * FROM code_operations WHERE task_id=? AND operation_type='START'",
                (model.window.task_id,),
            ).fetchone()
            _, steps = original_start_steps(connection, start)
            rules = connection.execute(
                'SELECT capture_rules FROM code_execution_profile_versions WHERE id=?',
                (original.binding.content_profile_version_id,),
            ).fetchone()[0]
        if restore_case == 'live-control-configuration':
            with database.transaction(write=True) as connection:
                assert fail_unprepared_project_check(
                    connection, operation, 'CONFIG_NOT_READY', at=operation_time(None)
                )
            from backend.tests.infrastructure.v20_live_configuration_worker import (
                exercise_live_control_configuration,
            )

            monkeypatch.setattr(
                client.app.state,
                'walle_repository_registration',
                SimpleNamespace(
                    accepts_live_configuration=True,
                    accepts_native_responses=True,
                    accepts_candidate_capture=True,
                    project_check_admissions=(),
                    wake=lambda: None,
                ),
                raising=False,
            )
            exercise_live_control_configuration(
                runtime,
                client,
                f'/api/v1/code-tasks/{model.window.task_id}',
                driver,
            )
            from base64 import b64decode

            content = client.get(
                f'/api/v1/code-tasks/{model.window.task_id}/candidates/{identity}/file',
                params={'path': 'src/inner/result.txt'},
            )
            assert content.status_code == 200, content.text
            assert (
                b64decode(content.json()['data']['content_base64'], validate=True)
                == b'original bytes\r\n'
            )
            assert result_file.read_bytes() == b'original bytes\r\n'
            return
        repair_source = (
            original,
            (),
            workspace_allocation(start, steps[0]),
            steps[0]['result_ref'],
            strict_json_object(rules),
        )
        owner = SimpleNamespace(scope=None, previous=model.window, credential_ref=credential)
        assert (
            _verify_original_workspace(
                workspace_parent, repair_source, driver, owner, lambda: None
            )['candidate_id']
            == identity
        )
        result_file.unlink()
        result_file.parent.rmdir()
        result_file.parent.parent.rmdir()

        def restore(publish):
            publish()

        driver.scratch = None
        with pytest.raises(RepairWriterUnverified):
            _verify_original_workspace(
                workspace_parent, repair_source, driver, owner, lambda: None, restore
            )
        assert not result_file.exists()
        driver.scratch = scratch_identity
        alias = source / 'SRC'
        alias.mkdir()
        with pytest.raises(CandidateWorkspaceError, match='SOURCE_CHANGED'):
            _verify_original_workspace(
                workspace_parent, repair_source, driver, owner, lambda: None, restore
            )
        assert not list(alias.iterdir())
        alias.rmdir()
        prepared_sources = []

        def prepare(proof, verify_locked_source):
            with pytest.raises(PermissionError):
                with result_file.open('ab'):
                    pytest.fail('Original selected file was released before intent')
            verify_locked_source()
            prepared_sources.append(proof)

        repaired = _verify_original_workspace(
            workspace_parent, repair_source, driver, owner, lambda: None, restore, prepare
        )
        assert prepared_sources == [repaired]
        assert repaired['restored_file_count'] == 1
        assert result_file.read_bytes() == b'original bytes\r\n'
        assert not list(scratch.iterdir())

        with result_file.open('ab') as changed:
            changed.write(b'later edit')
        with pytest.raises(RepairSourceChanged):
            _verify_original_workspace(
                workspace_parent, repair_source, driver, owner, lambda: None, restore
            )
        assert result_file.read_bytes() == b'original bytes\r\nlater edit'
        result_file.unlink()
        extra = source / 'extra.txt'
        with extra.open('xb') as unexpected:
            unexpected.write(b'untouched')
        with pytest.raises(RepairSourceChanged):
            _verify_original_workspace(
                workspace_parent, repair_source, driver, owner, lambda: None, restore
            )
        assert not result_file.exists() and extra.read_bytes() == b'untouched'
        observations = driver.observations
        assert (
            reconcile_original_candidate(
                runtime,
                operation,
                store=store,
                materialization_root=tmp_path / 'check',
                cancelled=lambda: False,
            )
            == identity
        )
        with pytest.raises(TaskExecutionError):
            capture_original_candidate(
                runtime,
                driver,
                operation,
                workspace_parent=workspace_parent,
                store=store,
                exchange=exchange,
                materialization_root=tmp_path / 'check',
                cancelled=lambda: False,
            )
        assert len(executions) == 11 and driver.observations == observations
    reply = client.get(f'/api/v1/code-tasks/{model.window.task_id}/candidates/{identity}')
    assert reply.status_code == 200, reply.text
    assert (reply.json()['data']['file_count'], reply.json()['data']['byte_count']) == (1, 16)

    # The prior check could not start, so the task still owns the original
    # sealed candidate and its verified, closed session. Use the real HTTP
    # admission and repair worker for the subsequent explicit request.
    extra.unlink()
    if restore_case == 'file-blocks-directory':
        result_file.parent.rmdir()
        result_file.parent.parent.rmdir()
        changed_path = source / 'src'
    else:
        changed_path = result_file
    with changed_path.open('xb') as changed:
        changed.write(b'preserve this changed file')
    with extra.open('xb') as surplus:
        surplus.write(b'preserve this additional file')
    task_id = model.window.task_id
    url = f'/api/v1/code-tasks/{task_id}'
    with database.transaction(write=True) as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        materials = connection.execute(
            'SELECT document_id,revision_id FROM code_task_materials WHERE task_id=? ORDER BY document_id',
            (task_id,),
        ).fetchall()
        at = max(operation_time(None), task['updated_at'])
        assert fail_unprepared_project_check(connection, operation, 'CONFIG_NOT_READY', at=at)
    defect = client.post(
        url + '/defects',
        headers={'Idempotency-Key': str(uuid4())},
        json={
            'candidate_id': identity,
            'expected_state_version': task['state_version'],
            'actual_behavior': '固定实现仍有原报告所述偏差',
            'expected_behavior': '按固定设计纠正偏差',
            'basis_ref': {
                'document_id': task['document_id'],
                'revision_id': task['design_revision_id'],
                'quote': '原固定设计',
            },
            'evidence_refs': [],
        },
    )
    assert defect.status_code == 201, defect.text
    defect_id = defect.json()['data']['defect_id']
    second = client.post(
        url + '/defects',
        headers={'Idempotency-Key': str(uuid4())},
        json={
            'candidate_id': identity,
            'expected_state_version': task['state_version'] + 1,
            'actual_behavior': '固定候选还遗漏一个边界',
            'expected_behavior': '先修复边界',
            'basis_ref': {
                'document_id': task['document_id'],
                'revision_id': task['design_revision_id'],
                'quote': '原固定设计',
            },
            'evidence_refs': [],
        },
    )
    assert second.status_code == 201, second.text
    selected_defects = [second.json()['data']['defect_id'], defect_id]
    monkeypatch.setattr(
        client.app.state,
        'walle_repository_registration',
        SimpleNamespace(
            accepts_model_resumes=True,
            accepts_candidate_capture=True,
            accepts_native_responses=True,
            project_check_admissions=(),
            wake=lambda: None,
        ),
        raising=False,
    )
    headers = {'Idempotency-Key': str(uuid4())}
    request = {
        'expected_state_version': task['state_version'] + 2,
        'candidate_id': identity,
        'defect_ids': selected_defects,
    }
    accepted = client.post(url + '/repairs', headers=headers, json=request)
    assert accepted.status_code == 202, accepted.text
    repair_operation = accepted.json()['data']['operation_id']
    original_repair_operation = repair_operation
    sends = []
    basis = runtime_basis_plan(
        workspace_parent,
        strict_json_object(steps[1]['external_identity']),
        strict_json_object(steps[1]['result_ref'])['seal'],
        lambda: None,
    )

    created_sessions = []
    revoked_sessions = []
    replacement_payloads = {}
    lost_create = []
    creation_observations = []
    allow_message_observation = restore_case != 'archived-session-lost-message'

    class RepairDriver(Driver):
        def repair_session_archived_at(self, scope, previous, ref, checkpoint):
            checkpoint()
            return (
                1
                if archived_case
                and (
                    previous == model.window
                    or (
                        restore_case == 'archived-session-cancel-archived'
                        and previous.operation_id == original_repair_operation
                    )
                )
                else None
            )

        def revoke_session_source(self, scope, previous, ref, checkpoint):
            checkpoint()
            assert previous in (model.window, *sends)
            revoked_sessions.append(previous.execution_session_id)

        def create_session(self, scope, checkpoint):
            checkpoint()
            assert scope.transition_kind == 'REPAIR' and scope.transition_step_no == 1
            assert scope.metadata()['walle']['operation_id'] == repair_operation
            with database.transaction() as connection:
                parent = connection.execute(
                    'SELECT control_generation FROM code_operations WHERE id=?',
                    (scope.transition_operation_id,),
                ).fetchone()
                assert scope.control_generation == parent['control_generation'] + 1
            assert scope.role == 'BACKEND'
            if scope.session_id not in created_sessions:
                created_sessions.append(scope.session_id)
                if (
                    restore_case
                    in (
                        'archived-session-lost-create',
                        'archived-session-create-reconcile',
                        'archived-session-create-reconcile-stop',
                    )
                    and not lost_create
                ):
                    lost_create.append(True)
                    raise OSError('Injected original create applied before reply')
            return SimpleNamespace(native_id=f'ses_repairNew{scope.session_id}')

        def observe_created_session(self, scope, checkpoint):
            checkpoint()
            assert scope.session_id in created_sessions
            creation_observations.append(scope.session_id)
            if (
                restore_case == 'archived-session-create-reconcile'
                and len(creation_observations) == 1
            ):
                return None
            return f'ses_repairNew{scope.session_id}'

        def gateway_reference(self, scope):
            return credential

        def observe_replacement_source(self, scope, expected, ref, checkpoint):
            previous = next(
                window
                for window in (model.window, *sends)
                if window.native_session_id == expected['turn']['session_id']
                and window.trigger_message_id == expected['turn']['trigger_message_id']
            )
            evidence = self.observe_capture_turn(scope, previous, ref, checkpoint)
            assert evidence.scope_proof() == expected
            return evidence

        def replacement_repair_payload(self, scope, context, evidence, defects, checkpoint):
            from backend.app.code_tasks.task_initial_prompt import repair_texts

            checkpoint()
            assert context.native_session_id == f'ses_repairNew{scope.session_id}'
            if scope.session_id not in replacement_payloads:
                parts = repair_texts(scope, context, basis, source_identity, evidence, defects)
                replacement_payloads[scope.session_id] = self.continuation_payload(
                    scope, model.window, credential, checkpoint, parts=parts
                )
            return replacement_payloads[scope.session_id]

        def send_successor(self, scope, previous, original, payload, checkpoint):
            window = ModelWindow(
                scope.task_id,
                scope.instance_id,
                scope.control_generation,
                scope.session_id,
                original['native_session_id'],
                scope.transition_operation_id,
                payload['messageID'],
            )
            self.dispatch_continuation(scope, previous, window, credential, payload, checkpoint)
            return payload['messageID']

        repair_payload = TaskInstanceDriver.repair_payload

        def _continuation_owner(self, scope, ref):
            assert scope.operation_id == model.window.operation_id and ref == credential
            return SimpleNamespace(basis_plan=basis, workspace=source_identity)

        def session_available(self, operation_id):
            return operation_id == model.window.operation_id

        def continuation_payload(self, scope, previous, ref, checkpoint, *, parts):
            checkpoint()
            assert previous in (model.window, *sends)
            assert parts[0] == f'task_id={task_id}'
            assert parts[1].startswith('当前角色 BACKEND。')
            assert strict_json_object(parts[2].split('\n', 1)[1]) == {
                'candidate_id': identity,
                'manifest_sha256': original.seal['manifest_sha256'],
            }
            assert parts[3].endswith(str(source))
            fixed_defects = strict_json_object(parts[4].split('\n', 1)[1])['defects']
            assert [row['id'] for row in fixed_defects] == selected_defects
            assert [row['expected_behavior'] for row in fixed_defects] == [
                '先修复边界',
                '按固定设计纠正偏差',
            ]
            evidence = strict_json_object(parts[5].split('\n', 1)[1])['defects']
            assert [row['id'] for row in evidence] == selected_defects
            assert all(row['basis_ref']['quote'] == '原固定设计' for row in evidence)
            documents = strict_json_object(parts[6].split('\n', 1)[1])['documents']
            assert [(row['document_id'], row['revision_id']) for row in documents] == [
                (task['document_id'], task['design_revision_id']),
                *((row['document_id'], row['revision_id']) for row in materials),
            ]
            assert [row['role'] for row in documents] == ['MAIN', *(['MATERIAL'] * len(materials))]
            for document, member in zip(documents, basis.members, strict=True):
                assert document['path'].endswith(member.filename)
                assert document['sha256'] == member.sha256
            authorization = strict_json_object(parts[7].split('\n', 1)[1])
            assert authorization['authorization_id'] == task['authorization_id']
            assert authorization['write_workspace_only'] is True
            assert (
                parts[8] == '仅修复以上原设计内的实现偏差；需要新规则时保留问题，不修改固定依据。'
            )
            actions = SimpleNamespace(_ids=OpenCodeMessageIds())
            return TaskNativeActions.initial_payload(
                actions, 'walle-code', 'walle', 'walle-code', parts
            )

        def dispatch_continuation(self, scope, previous, window, ref, payload, checkpoint):
            checkpoint()
            assert result_file.read_bytes() == b'original bytes\r\n'
            archived = list(scratch.glob('.walle-repair-*.saved'))
            assert len(archived) == 2
            assert {item.read_bytes() for item in archived} == {
                b'preserve this changed file',
                b'preserve this additional file',
            }
            assert not extra.exists()
            with database.transaction() as connection:
                assert read_original_window_state(connection, window, ref) == 'QUEUED'
                source_step = connection.execute(
                    'SELECT result_ref FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                    (window.operation_id,),
                ).fetchone()
                restored_result = strict_json_object(source_step['result_ref'])
                if 'replacement_session_id' in restored_result:
                    assert (
                        restored_result.pop('replacement_session_id') == window.execution_session_id
                    )
                    assert restored_result.pop('native_session_id') == window.native_session_id
                assert restored_result == {
                    'candidate_id': identity,
                    'manifest_sha256': original.seal['manifest_sha256'],
                    'restored_file_count': 1
                    if window.operation_id == original_repair_operation
                    else 0,
                }
            sends.append(window)
            if restore_case == 'archived-session-lost-message':
                raise OSError('Injected initial repair native acceptance lost')

        def observe_continuation(self, scope, window, ref, payload, checkpoint):
            checkpoint()
            return window.trigger_message_id if allow_message_observation else None

    def advance_original_repair():
        return advance_repairs(
            runtime,
            RepairDriver(),
            workspace_parent,
            {admission.evidence_ref: admission},
            cancelled=lambda: False,
        )

    if restore_case == 'changed-and-extra':
        from backend.app.code_tasks import task_repair_runtime

        class ControllerExited(BaseException):
            pass

        original_archive = task_repair_runtime.archive_changed_candidate_file

        def archive_with_lost_ack(
            package, workspace, scratch, original, entry, key, checkpoint, publish
        ):
            def publish_before_exit(move):
                publish(move)
                raise ControllerExited

            return original_archive(
                package, workspace, scratch, original, entry, key, checkpoint, publish_before_exit
            )

        with monkeypatch.context() as interruption:
            interruption.setattr(
                task_repair_runtime, 'archive_changed_candidate_file', archive_with_lost_ack
            )
            with pytest.raises(ControllerExited):
                advance_original_repair()
        interrupted = client.get(url + f'/operations/{repair_operation}').json()['data']
        assert interrupted['status'] == 'PENDING'
        assert not sends and not extra.exists()
        assert changed_path.read_bytes() == b'preserve this changed file'
        assert len(list(scratch.glob('.walle-repair-*.saved'))) == 1

    assert advance_original_repair()
    if archived_case:
        assert not sends and not created_sessions
        pending = client.get(url)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['status'] == 'WAITING'
        if restore_case == 'archived-session-stop':
            stopped = client.post(
                url + '/terminate',
                json={'expected_state_version': pending.json()['data']['state_version']},
                headers={'Idempotency-Key': str(uuid4())},
            )
            assert stopped.status_code == 202, stopped.text
            assert not advance_original_repair() and not sends and not created_sessions
            with database.transaction() as connection:
                assert (
                    connection.execute(
                        'SELECT status FROM code_sessions WHERE id=?',
                        (model.window.execution_session_id,),
                    ).fetchone()[0]
                    == 'RETIRED'
                )
            return
        assert advance_original_repair()
        if restore_case in (
            'archived-session-lost-create',
            'archived-session-create-reconcile',
            'archived-session-create-reconcile-stop',
        ):
            missed = client.get(url + f'/operations/{repair_operation}')
            assert missed.status_code == 200 and missed.json()['data']['status'] == 'UNKNOWN', (
                missed.text
            )
            pending = client.get(url)
            assert pending.status_code == 200, pending.text
            from backend.app.code_tasks import task_repair_runtime

            monkeypatch.setattr(task_repair_runtime, '_OBSERVE_RECHECK_SECONDS', 0)
            if restore_case.startswith('archived-session-create-reconcile'):
                from backend.app.code_tasks import task_role_reconciliation

                for expected_status in ('UNKNOWN', 'RUNNING'):
                    view = client.get(url).json()['data']
                    action = next(
                        item for item in view['available_actions'] if item['action'] == 'RECONCILE'
                    )
                    assert action['enabled'], action
                    observed_create = client.post(
                        task_role_reconciliation.PATH.format(task_id=task_id),
                        json={
                            'expected_state_version': view['state_version'],
                            'operation_id': repair_operation,
                        },
                        headers={'Idempotency-Key': str(uuid4())},
                    )
                    assert observed_create.status_code == 202, observed_create.text
                    if restore_case.endswith('-stop'):
                        stopping = client.get(url).json()['data']
                        stopped = client.post(
                            url + '/terminate',
                            json={'expected_state_version': stopping['state_version']},
                            headers={'Idempotency-Key': str(uuid4())},
                        )
                        assert stopped.status_code == 202, stopped.text
                        assert not task_role_reconciliation.advance_role_reconciliation(
                            runtime, RepairDriver(), cancelled=lambda: False
                        )
                        assert not creation_observations and not sends
                        assert len(created_sessions) == 1
                        assert not advance_original_repair()
                        from backend.tests.code_tasks.test_task_runtime_stop import StopDriver

                        class UnknownCreationStop(StopDriver):
                            def abort_original(self, original, checkpoint, *, timeout_ms):
                                self.calls.append('abort')
                                assert original.native_session_id is None
                                checkpoint()
                                return 'NO_VERIFIED_SESSION'

                        clock = datetime.now(UTC) + timedelta(days=1)

                        def after_grace(_):
                            nonlocal clock
                            clock += timedelta(minutes=2)
                            return clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

                        monkeypatch.setattr(task_runtime_stop, 'operation_time', after_grace)
                        stop_driver = UnknownCreationStop(workspace_parent)
                        for _ in range(10):
                            task_runtime_stop.advance_owned_stops(
                                runtime, stop_driver, cancelled=lambda: False
                            )
                            final = client.get(url)
                            assert final.status_code == 200, final.text
                            if final.json()['data']['status'] == 'TERMINATED':
                                break
                        assert final.json()['data']['status'] == 'TERMINATED', final.text
                        assert final.json()['data']['runtime']['cleanup_status'] == 'VERIFIED'
                        receipt_id = observed_create.json()['data']['operation_id']
                        receipt = client.get(url + f'/operations/{receipt_id}')
                        assert receipt.status_code == 200, receipt.text
                        assert receipt.json()['data']['status'] == 'CANCELLED'
                        original = client.get(url + f'/operations/{repair_operation}')
                        assert original.status_code == 200, original.text
                        assert original.json()['data']['status'] == 'CANCELLED'
                        assert not creation_observations and not sends
                        assert len(created_sessions) == 1 and stop_driver.calls.count('abort') == 1
                        assert stop_driver.calls[-2:] == ['workspace', 'retire']
                        assert result_file.read_bytes() == b'original bytes\r\n'
                        return
                    assert task_role_reconciliation.advance_role_reconciliation(
                        runtime, RepairDriver(), cancelled=lambda: False
                    )
                    assert not sends and len(created_sessions) == 1
                    receipt_id = observed_create.json()['data']['operation_id']
                    receipt = client.get(url + f'/operations/{receipt_id}')
                    assert receipt.status_code == 200, receipt.text
                    assert receipt.json()['data']['steps'][-1]['result_ref'] == {
                        'operation_id': repair_operation,
                        'original_status': expected_status,
                    }
                    op = client.get(url + f'/operations/{repair_operation}')
                    assert (
                        op.status_code == 200 and op.json()['data']['status'] == expected_status
                    ), op.text
                    assert op.json()['data']['steps'][1]['status'] == 'PENDING'
                assert creation_observations == created_sessions * 2
            else:
                assert advance_original_repair()
        assert len(created_sessions) == 1 and not sends
        if restore_case == 'archived-session-source-drift':
            with result_file.open('ab') as outside:
                outside.write(b'changed after original create')
            assert advance_original_repair()
            assert not sends and len(created_sessions) == 1
            assert result_file.read_bytes() == b'original bytes\r\nchanged after original create'
            failed_source = client.get(url + f'/operations/{repair_operation}')
            assert failed_source.status_code == 200, failed_source.text
            assert failed_source.json()['data']['failure_code'] == 'SOURCE_CHANGED', (
                failed_source.text
            )
            assert failed_source.json()['data']['steps'][1]['status'] == 'PENDING'
            pending = client.get(url)
            assert pending.status_code == 200, pending.text
            stopped = client.post(
                url + '/terminate',
                json={'expected_state_version': pending.json()['data']['state_version']},
                headers={'Idempotency-Key': str(uuid4())},
            )
            assert stopped.status_code == 202, stopped.text
            assert not advance_original_repair()
            return
        assert advance_original_repair()
        assert len(created_sessions) == len(revoked_sessions) == 1
        if restore_case == 'archived-session-lost-message':
            view = client.get(url)
            assert view.status_code == 200, view.text
            state = view.json()['data']
            unknown = client.get(url + f'/operations/{repair_operation}')
            assert unknown.json()['data']['status'] == 'UNKNOWN', unknown.text
            from backend.app.code_tasks import task_role_reconciliation

            confirm = client.post(
                task_role_reconciliation.PATH.format(task_id=task_id),
                json={
                    'expected_state_version': state['state_version'],
                    'operation_id': repair_operation,
                },
                headers={'Idempotency-Key': str(uuid4())},
            )
            assert confirm.status_code == 202, confirm.text
            allow_message_observation = True
            from backend.app.code_tasks import task_repair_runtime

            monkeypatch.setattr(task_repair_runtime, '_OBSERVE_RECHECK_SECONDS', 0)
            assert task_role_reconciliation.advance_role_reconciliation(
                runtime, RepairDriver(), cancelled=lambda: False
            )
            assert len(sends) == 1
        with database.transaction() as connection:
            immutable = connection.execute(
                'SELECT * FROM code_operations WHERE id=?', (repair_operation,)
            ).fetchone()
            assert immutable['session_id'] == model.window.execution_session_id
            assert immutable['control_generation'] == model.window.generation
            source_session = connection.execute(
                'SELECT * FROM code_sessions WHERE id=?', (model.window.execution_session_id,)
            ).fetchone()
            assert source_session['status'] == 'RETIRED'
            from backend.app.code_tasks.task_role_chain import current_role_chain

            task_current = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()
            chain = current_role_chain(connection, task_current)
            assert chain.stages == ('BACKEND',) and chain.operations == ()
    observed = client.get(url + f'/operations/{repair_operation}').json()
    assert len(sends) == 1, (observed['data']['status'], observed['data']['failure_code'])
    (sent,) = sends
    with database.transaction() as connection:
        assert read_original_window_state(connection, sent, credential) == 'OPEN'
    assert '原代码工作区' not in str(observed) and sent.trigger_message_id not in str(observed)
    replay = client.post(url + '/repairs', headers=headers, json=request)
    assert replay.status_code == 202
    assert replay.json()['data'] == accepted.json()['data']

    if cancelled_case:
        assert advance_original_repair()
        operation_after = client.get(url + f'/operations/{repair_operation}').json()['data']
        assert operation_after['status'] == 'CANCELLED'
        assert operation_after['failure_code'] is None
        assert [step['status'] for step in operation_after['steps']] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'CANCELLED',
            'CANCELLED',
        ]
        task_after = client.get(url)
        assert task_after.status_code == 200, task_after.text
        view = task_after.json()['data']
        assert view['status'] == 'VERIFYING' and view['current_candidate_id'] == identity
        assert view['runtime']['activity_status'] == 'QUIESCENT'
        action = next(item for item in view['available_actions'] if item['action'] == 'REPAIR')
        assert action['enabled'], action
        prior = client.get(url + '/repairs').json()['data']['items'][0]
        assert prior['status'] == 'CANCELLED' and prior['result_candidate_id'] is None
        with database.transaction() as connection:
            quiet = connection.execute(
                "SELECT observed_at FROM code_runtime_observations WHERE operation_id=? AND kind='QUIESCE' AND result='VERIFIED' ORDER BY id DESC",
                (repair_operation,),
            ).fetchone()
            assert view['runtime']['observed_at'] == quiet['observed_at']
        repeated = client.post(
            url + '/repairs',
            headers={'Idempotency-Key': str(uuid4())},
            json={**request, 'expected_state_version': view['state_version']},
        )
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()['data']['operation_id'] != repair_operation
        assert len(sends) == 1
        repair_operation = repeated.json()['data']['operation_id']
        assert advance_original_repair()
        if restore_case == 'archived-session-cancel-archived':
            assert advance_original_repair() and advance_original_repair()
            assert len(created_sessions) == 2
        assert len(sends) == 2 and sends[-1].operation_id == repair_operation

    if restore_case in ('changed-and-extra', 'cancelled-turn') or archived_case:
        # The offline model fixture now finishes this exact repair window.
        # Use the original worker and real MinGit/NTFS publication to preserve
        # the old immutable candidate and capture only one new child.
        with result_file.open('wb') as model_output:
            model_output.write(b'corrected implementation\r\n')
        assert advance_original_repair()
        with database.transaction() as connection:
            capture = connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=4',
                (repair_operation,),
            ).fetchone()
            child = strict_json_object(capture['external_identity'])['capture_operation_id']
        repair_driver = RepairDriver()
        assert observe_capture_quiescence(runtime, repair_driver, child, cancelled=lambda: False)
        with PrivatePackageGuard(store_path) as store:
            job = OwnedJob(active_process_limit=8, job_memory_limit_bytes=512 * 1024 * 1024)
            try:
                corrected = capture_original_candidate(
                    runtime,
                    repair_driver,
                    child,
                    workspace_parent=workspace_parent,
                    store=store,
                    exchange=exchange,
                    materialization_root=tmp_path / 'repair-check',
                    cancelled=lambda: False,
                )
            finally:
                job.close()
        assert corrected != identity
        assert advance_original_repair()
        finished = client.get(url + f'/operations/{repair_operation}').json()['data']
        assert finished['status'] == 'SUCCEEDED'
        with database.transaction() as connection:
            old = connection.execute(
                'SELECT * FROM code_candidates WHERE id=?', (identity,)
            ).fetchone()
            current = connection.execute(
                'SELECT * FROM code_candidates WHERE id=?', (corrected,)
            ).fetchone()
            repair = connection.execute(
                'SELECT * FROM code_repairs WHERE operation_id=?', (repair_operation,)
            ).fetchone()
            task_after = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()
            assert old == candidate
            assert current['parent_candidate_id'] == identity
            assert current['capture_operation_id'] == child
            assert repair['source_candidate_id'] == identity
            assert repair['result_candidate_id'] == corrected
            assert task_after['current_candidate_id'] == corrected
            assert task_after['current_test_report_id'] is None
            assert task_after['current_delivery_plan_id'] is None
            assert (
                connection.execute(
                    'SELECT count(*) FROM code_candidates WHERE capture_operation_id=?', (child,)
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    'SELECT status FROM code_operation_steps WHERE operation_id=? AND step_type=?',
                    (child, 'CHECK'),
                ).fetchone()[0]
                == 'PENDING'
            )
        from base64 import b64decode

        for candidate_id, expected_bytes in (
            (identity, b'original bytes\r\n'),
            (corrected, b'corrected implementation\r\n'),
        ):
            content = client.get(
                url + f'/candidates/{candidate_id}/file',
                params={'path': 'src/inner/result.txt'},
            )
            assert content.status_code == 200, content.text
            chunk = content.json()['data']
            assert chunk['candidate_id'] == candidate_id
            assert b64decode(chunk['content_base64'], validate=True) == expected_bytes
        history = client.get(url + '/repairs')
        assert history.status_code == 200, history.text
        repaired_history = history.json()['data']['items']
        assert len(repaired_history) == (2 if cancelled_case else 1)
        succeeded = next(row for row in repaired_history if row['operation_id'] == repair_operation)
        assert succeeded['source_candidate_id'] == identity
        assert succeeded['result_candidate_id'] == corrected
        assert succeeded['status'] == 'SUCCEEDED'
        if cancelled_case:
            cancelled = next(
                row for row in repaired_history if row['operation_id'] == original_repair_operation
            )
            assert cancelled['status'] == 'CANCELLED'
            assert cancelled['result_candidate_id'] is None
        assert len(sends) == (2 if cancelled_case else 1)
        # A completed repair is a new candidate, not a passed check or report.
        assert not advance_original_repair()
