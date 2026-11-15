"""Delivery transaction and pending view, with report and target admission fixtures."""

from contextlib import ExitStack
from dataclasses import asdict
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_delivery, task_report_link
from backend.app.code_tasks.task_delivery import DeliveryTargetObservation
from backend.app.code_tasks.task_resume_runtime import _step
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_loads, strict_json_object
from backend.tests.infrastructure.test_v20_check_runner_bundle import bundle  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package  # noqa: F401
from backend.tests.test_testing_pack_seal import installed  # noqa: F401
from backend.tests.test_testing_report_api import completed_fixture  # noqa: F401


def _post(client, path, data, key=None):
    return client.post(path, json=data, headers={'Idempotency-Key': key or str(uuid4())})


@pytest.mark.parametrize('completed_fixture', ['candidate-delivery'], indirect=True)
@pytest.mark.parametrize(
    'loss',
    [
        'stop-before-write',
        'private-may-before-sqlite',
        'verified-reference-abort',
        'verified-reference-abort-after-lock',
    ],
)
def test_link_preview_and_accept_have_separate_original_receipts(
    completed_fixture,  # noqa: F811
    monkeypatch,
    loss,
):
    client, _ = completed_fixture
    runtime = client.app.state.walle_runtime
    db = runtime.database
    at = operation_time(None)
    with db.transaction(write=True) as connection:
        task = connection.execute('SELECT * FROM code_tasks').fetchone()
        testing = connection.execute('SELECT * FROM testing_reports').fetchone()
        coverage = strict_json_loads(testing['manual_coverage_ids'], 'manual_coverage_ids')
        connection.execute(
            """INSERT INTO code_workspaces(id,task_id,base_snapshot_id,private_location_key,status,created_at)
               VALUES(1,?,?,'fixture:workspace','READY',?)""",
            (task['id'], task['base_snapshot_id'], at),
        )
        connection.execute(
            """INSERT INTO code_instances(id,task_id,workspace_id,executor_version,control_generation,
               effective_profile_version_id,status,created_at) VALUES(1,?,1,'fixture',1,1,'READY',?)""",
            (task['id'], at),
        )
        connection.execute(
            """INSERT INTO code_sessions(id,task_id,instance_id,role,control_generation,status,created_at)
               VALUES(1,?,1,'INTEGRATION',1,'ACTIVE',?)""",
            (task['id'], at),
        )
        connection.execute(
            'UPDATE code_tasks SET workspace_id=1,active_session_id=1 WHERE id=?', (task['id'],)
        )
    url = f'/api/v1/code-tasks/{task["id"]}'
    fixed = {
        'candidate_id': task['current_candidate_id'],
        'test_report_id': testing['id'],
        'expected_state_version': task['state_version'],
    }
    monkeypatch.setattr(task_report_link, '_selection', lambda *_: (None, 1))
    diagnostic = _post(client, url + '/test-reports', fixed)
    assert diagnostic.status_code == 409, diagnostic.text
    assert diagnostic.json()['error']['code'] == 'TEST_REPORT_NOT_ELIGIBLE'

    def eligible(*values):
        report = values[-2]
        assert report['id'] == testing['id']
        return None, {'delivery_eligible': True, 'manual_coverage_ids': coverage}

    monkeypatch.setattr(task_report_link, 'qualify_report', eligible)
    monkeypatch.setattr(task_delivery, 'qualify_report', eligible)
    monkeypatch.setattr(task_delivery, '_deliver_authorization', lambda *_: 120)
    link = _post(client, url + '/test-reports', fixed)
    assert link.status_code == 200, link.text
    fixed['expected_state_version'] = link.json()['data']['state_version']

    class Worker:
        accepts_delivery_previews = True
        delivery_epoch = runtime.commands().process_lock.owner_epoch
        calls = 0
        moved = False

        def wake(self):
            pass

        def observe_delivery_plan(self, task_id, plan_id):
            assert task_id == task['id']
            self.calls += 1
            return (
                'TARGET_CHANGED'
                if self.moved
                else DeliveryTargetObservation(
                    plan_id,
                    '8' * 40,
                    '9' * 40,
                    operation_time(None),
                    self.delivery_epoch,
                )
            )

    worker = Worker()
    monkeypatch.setattr(client.app.state, 'walle_repository_registration', worker, raising=False)
    preview_key = str(uuid4())
    preview = _post(client, url + '/delivery-plans', fixed, preview_key)
    assert preview.status_code == 202, preview.text
    reserved = preview.json()['data']
    assert _post(client, url + '/delivery-plans', fixed, preview_key).json()['data'] == reserved
    identity = reserved['operation_id']
    with db.transaction(write=True) as connection:
        operation, _, steps = task_delivery.original_operation(
            connection, identity, 'PREPARE_DELIVERY'
        )
        claim = strict_json_object(steps[2]['external_identity'])
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=?',
            (fixed['candidate_id'],),
        ).fetchone()
        at = operation_time(None)
        connection.execute(
            """INSERT INTO code_delivery_plans(id,task_id,candidate_id,test_report_id,repository_id,
               target_branch,expected_target_commit,target_tree_oid,target_content_store_key,
               target_manifest_sha256,result_tree_oid,operation_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                claim['plan_id'],
                task['id'],
                candidate['id'],
                testing['id'],
                task['repository_id'],
                task['target_branch'],
                '8' * 40,
                '9' * 40,
                claim['content_store_key'],
                'b' * 64,
                candidate['content_tree_oid'],
                identity,
                at,
            ),
        )
        for step in (1, 2, 3, 4):
            _step(
                connection,
                identity,
                step,
                'SUCCEEDED',
                at,
                result={'delivery_plan_id': claim['plan_id']} if step == 4 else None,
            )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',started_at=?,ended_at=? WHERE id=?",
            (at, at, operation['id']),
        )
        connection.execute(
            'UPDATE code_tasks SET current_delivery_plan_id=?,state_version=state_version+1 WHERE id=?',
            (claim['plan_id'], task['id']),
        )
    plan = client.get(url + f'/operations/{identity}')
    assert plan.status_code == 200, plan.text
    assert plan.json()['data']['steps'][-1]['result_ref'] == {'delivery_plan_id': claim['plan_id']}
    acceptance = {
        **fixed,
        'expected_state_version': reserved['state_version'] + 1,
        'delivery_plan_id': claim['plan_id'],
        'expected_target_commit': '8' * 40,
        'repository_quiescent_confirmed': True,
        'manual_risk_accepted': bool(coverage),
    }
    rejected = _post(
        client, url + '/accept', {**acceptance, 'manual_risk_accepted': not bool(coverage)}
    )
    assert rejected.status_code == 422, rejected.text
    worker.moved = True
    moved = _post(client, url + '/accept', acceptance)
    assert moved.status_code == 409 and moved.json()['error']['code'] == 'TARGET_CHANGED'
    worker.moved = False
    key = str(uuid4())
    accepted = _post(client, url + '/accept', acceptance, key)
    assert accepted.status_code == 202, accepted.text
    receipt = accepted.json()['data']
    assert _post(client, url + '/accept', acceptance, key).json()['data'] == receipt
    assert worker.calls == 3
    ref = client.get(
        '/api/v1/code-command-receipts',
        params={'method': 'POST', 'path': url + '/accept', 'request_key': key},
    )
    assert ref.status_code == 200, ref.text
    assert ref.json()['data']['original_outcome']['data'] == receipt
    delivery = client.get(url + f'/deliveries/{receipt["delivery_id"]}')
    assert delivery.status_code == 200, delivery.text
    row = delivery.json()['data']
    assert row['status'] == 'PENDING' and row['delivered_at'] is None
    assert row['delivery_window']['state'] == 'REQUIRED'
    assert row['manual_risk_accepted'] == bool(coverage)
    assert client.get(url + '/deliveries?page=1').json()['data']['items'] == [row]
    assert client.get(url + '/deliveries?page=2').json()['data']['items'] == []
    assert client.get('/api/v1/code-tasks/999/deliveries/1').status_code == 404
    assert 'controller_epoch_ref' not in delivery.text and 'commit_input_ref' not in delivery.text
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_acceptances').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_deliveries').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_delivery_windows').fetchone()[0] == 1

    # The accepted record is reused for a real SQLite stop/commit fence check.
    # Only the prepared native process identity is a fixture in this check.
    from backend.app.code_tasks import task_delivery_write
    from backend.app.infrastructure.database import StorageUnavailable
    from backend.app.infrastructure.git_baseline_ref_transaction import RefProcessBinding
    from backend.app.infrastructure.git_receipt_store import GitReceiptStore
    from backend.app.infrastructure.git_receipts import (
        GitReceipt,
        GitReceiptBinding,
        GitReceiptFacts,
    )
    from backend.app.infrastructure.git_ref_protocol import delivery_update
    from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
    from backend.app.infrastructure.windows_private_package import create_private_package
    from backend.app.infrastructure.windows_private_record import PrivateRecordAppend

    monkeypatch.setattr(task_delivery_write, '_deliver_authorization', lambda *_: 120)
    monkeypatch.setattr(task_delivery_write, '_report_assets_current', lambda *_: True)
    original_id = receipt['operation_id']

    from backend.app.code_tasks import task_delivery_window
    from backend.app.code_tasks.command_registry import registered_command
    from backend.app.code_tasks.task_resume import ResumeRequest, accept_resume

    monkeypatch.setattr(task_delivery_window, '_deliver_authorization', lambda *_: 120)
    directory = create_private_package(db.path.parent / ('delivery-fence-' + uuid4().hex[:8]))
    publish_private = PrivateRecordAppend.publish

    def lose_after_payload(writer):
        publish_private(writer)
        raise StorageUnavailable('Fixture lost original database publication')

    with LaunchJournal(directory) as journal:
        with monkeypatch.context() as failure:
            failure.setattr(PrivateRecordAppend, 'publish', lose_after_payload)
            with pytest.raises(StorageUnavailable, match='lost original'):
                task_delivery_write.fix_delivery_payload(
                    runtime,
                    journal._package,
                    original_id,
                    worker.delivery_epoch,
                    format='sha1',
                    maximum=4096,
                )
        assert task_delivery_write.recover_fixed_delivery_payload(
            runtime,
            journal._package,
            original_id,
            maximum=4096,
        )
        with db.transaction() as connection:
            fixed_payload = task_delivery_write.load_original_delivery(connection, original_id)
            commit = task_delivery_write.read_delivery_payload(
                journal._package,
                fixed_payload,
                format='sha1',
                maximum=4096,
            )
            assert commit.payload.endswith(f'WALL-E-Delivery: {commit.delivery_id}\n'.encode())
            assert '作者' in commit.payload.decode()
    task_delivery_write.hold_original_delivery(runtime, original_id, native_commands_closed=True)

    def request_window(epoch):
        with db.transaction() as connection:
            saved = task_delivery_write.load_original_delivery(connection, original_id)
            wait = task_delivery_window.renewable_delivery(connection, saved.task, original_id)[1]
            version = saved.task['state_version']
        path = url + '/resume'
        command = registered_command('POST', path, str(uuid4()))
        request = ResumeRequest(task['id'], version, original_id, (wait['id'],), True, command)
        accepted = accept_resume(runtime, request, available=False, delivery_epoch=epoch)
        assert accepted['code'] == 'OPERATION_ACCEPTED'
        return accepted['data']['operation_id']

    first_resume = request_window('1' * 32)
    assert task_delivery_window.advance_delivery_window_resume(runtime, worker.delivery_epoch)
    failed = client.get(url + f'/operations/{first_resume}')
    assert failed.status_code == 200, failed.text
    assert failed.json()['data']['status'] == 'FAILED'

    second_resume = request_window(worker.delivery_epoch)
    assert task_delivery_window.advance_delivery_window_resume(runtime, worker.delivery_epoch)
    renewed = client.get(url + f'/operations/{second_resume}')
    assert renewed.status_code == 200, renewed.text
    renewed_row = renewed.json()['data']
    assert renewed_row['status'] == 'SUCCEEDED'
    assert renewed_row['fixed_input']['repository_quiescent_confirmed'] is True
    with db.transaction() as connection:
        saved = task_delivery_write.load_original_delivery(connection, original_id)
        assert saved.window['id'] == renewed_row['steps'][-1]['result_ref']['delivery_window_id']
        assert (
            saved.window['operation_id'] == second_resume
            and saved.window['id'] != row['current_window_id']
        )
        assert saved.task['status'] == 'AWAITING_ACCEPTANCE'
        assert saved.delivery['id'] == receipt['delivery_id']
        assert saved.acceptance['id'] == receipt['acceptance_id']
        stop_version = saved.task['state_version']
    with LaunchJournal(directory) as journal:
        assert (
            task_delivery_write.fix_delivery_payload(
                runtime,
                journal._package,
                original_id,
                worker.delivery_epoch,
                format='sha1',
                maximum=4096,
            )
            == commit
        )
    # The original Git owner has closed its object commands and fixed the commit.
    # A ref command of any status still requires separate native observation.
    from backend.app.code_tasks.task_delivery_git import DeliveryGitDispatch
    from backend.app.infrastructure.guard_control_git_input import (
        CONFIG_COMMAND_REF,
        DELIVERY_OBJECT_COMMAND_REF,
        DELIVERY_REF_COMMAND_REF,
        OBJECT_BATCH_COMMAND_REF,
    )
    from backend.app.infrastructure.identifiers import EntityKind, entity_id

    def record_command(connection, ref, status='SUCCEEDED'):
        at = operation_time(None)
        identity = entity_id(connection, EntityKind.COMMAND_EXECUTION)
        connection.execute(
            """INSERT INTO code_commands(id,task_id,operation_id,purpose,command_ref,
               config_version_id,status,created_at,started_at,ended_at,session_id,
               process_identity,runtime_binding,exit_code)
               VALUES(?,?,?,'CONTROL_GIT',?,?,?,?,?,?,?,?,?,?)""",
            (
                identity,
                task['id'],
                original_id,
                ref,
                task['execution_profile_version_id'],
                status,
                at,
                at,
                at if status != 'RUNNING' else None,
                1,
                '{"fixture":true}' if status != 'RUNNING' else None,
                canonical_input(
                    {'run_kind': 'CONTROL_GIT', 'guard_run_ref': 'c' * 32, 'job_refs': ['b' * 32]}
                )
                if status != 'RUNNING'
                else None,
                0 if status != 'RUNNING' else None,
            ),
        )
        return identity

    with db.transaction(write=True) as connection:
        for ref in (CONFIG_COMMAND_REF, DELIVERY_OBJECT_COMMAND_REF, OBJECT_BATCH_COMMAND_REF):
            record_command(connection, ref)
    task_delivery_write.hold_original_delivery(runtime, original_id, native_commands_closed=True)
    with db.transaction() as connection:
        saved = task_delivery_write.load_original_delivery(connection, original_id)
        assert saved.steps[1]['status'] == 'UNKNOWN'
        assert (
            task_delivery_write.unwritten_delivery_stage(connection, saved)
            == 'RECOVER_OBJECT_BUILD'
        )
    object_resume = request_window(worker.delivery_epoch)
    assert task_delivery_window.advance_delivery_window_resume(runtime, worker.delivery_epoch)
    with LaunchJournal(directory) as journal:
        assert (
            task_delivery_write.fix_delivery_payload(
                runtime,
                journal._package,
                original_id,
                worker.delivery_epoch,
                format='sha1',
                maximum=4096,
            )
            == commit
        )
        backend = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
        dispatch = DeliveryGitDispatch(runtime, None, backend, journal)
        dispatch.bind(original_id)
        try:
            with pytest.raises(StorageUnavailable, match='read-only'):
                dispatch.reserve(2, DELIVERY_OBJECT_COMMAND_REF)
        finally:
            dispatch.close()
    with db.transaction(write=True) as connection:
        saved = task_delivery_write.load_original_delivery(connection, original_id)
        assert saved.window['operation_id'] == object_resume
        assert saved.steps[1]['status'] == 'RUNNING'
        assert strict_json_object(saved.steps[1]['external_identity']) == {
            'planned_commit_oid': commit.commit_oid
        }
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM code_commands WHERE operation_id=?', (original_id,)
            ).fetchone()[0]
            == 3
        )
        at = operation_time(None)
        _step(connection, original_id, 2, 'SUCCEEDED', at)
        _step(
            connection,
            original_id,
            3,
            'SUCCEEDED',
            at,
            result={'planned_commit_oid': commit.commit_oid},
        )
        _step(connection, original_id, 4, 'RUNNING', at)
    task_delivery_write.hold_original_delivery(runtime, original_id, native_commands_closed=True)
    with db.transaction(write=True) as connection:
        saved = task_delivery_write.load_original_delivery(connection, original_id)
        assert saved.steps[3]['status'] == 'UNKNOWN'
        fixed_steps = tuple(dict(step) for step in saved.steps[:3])
        assert task_delivery_write.unwritten_delivery_stage(connection, saved) == 'VERIFY_OBJECTS'

    class RollBackFixtureChange(RuntimeError):
        pass

    with pytest.raises(RollBackFixtureChange), db.transaction(write=True) as connection:
        record_command(connection, DELIVERY_REF_COMMAND_REF)
        assert task_delivery_window.renewable_delivery(connection, saved.task, original_id) is None
        raise RollBackFixtureChange
    with pytest.raises(RollBackFixtureChange), db.transaction(write=True) as connection:
        record_command(connection, OBJECT_BATCH_COMMAND_REF, 'RUNNING')
        assert task_delivery_window.renewable_delivery(connection, saved.task, original_id) is None
        raise RollBackFixtureChange

    continued_resume = request_window(worker.delivery_epoch)
    assert task_delivery_window.advance_delivery_window_resume(runtime, worker.delivery_epoch)
    with LaunchJournal(directory) as journal:
        assert (
            task_delivery_write.fix_delivery_payload(
                runtime,
                journal._package,
                original_id,
                worker.delivery_epoch,
                format='sha1',
                maximum=4096,
            )
            == commit
        )
    with db.transaction() as connection:
        saved = task_delivery_write.load_original_delivery(connection, original_id)
        assert saved.window['operation_id'] == continued_resume
        assert saved.operation['status'] == 'RUNNING'
        assert saved.steps[3]['status'] == 'RUNNING'
        assert tuple(dict(step) for step in saved.steps[:3]) == fixed_steps
        assert saved.delivery['id'] == receipt['delivery_id']
        assert saved.acceptance['id'] == receipt['acceptance_id']
        stop_version = saved.task['state_version']
    intent = delivery_update(
        commit.delivery_id,
        task['target_branch'],
        commit.commit_oid,
        commit.parent_oid,
        format='sha1',
    )
    controller = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
    scope = controller.scope(original_id, 4, '2' * 32)
    process = RefProcessBinding(scope, str(uuid4()), intent.input_sha256)
    if loss in ('verified-reference-abort', 'verified-reference-abort-after-lock'):
        from types import SimpleNamespace

        from backend.app.code_tasks.task_delivery_write_runtime import DeliveryWriteRun

        saved_lock = loss == 'verified-reference-abort-after-lock'
        with LaunchJournal(directory) as journal, ExitStack() as resources:
            receipts = GitReceiptStore(
                journal,
                GitReceiptBinding(
                    scope, 'c' * 32, task['repository_id'], 'd' * 64, commit.commit_oid, 'sha1'
                ),
                max_receipt_bytes=4096,
                max_records=40,
                unique_phases=True,
            )
            resources.callback(receipts.close)
            at = operation_time(None)
            with db.transaction(write=True) as connection:
                command_id = record_command(connection, DELIVERY_REF_COMMAND_REF, 'FAILED')
                if saved_lock:
                    prepared = receipts.append(
                        GitReceipt(
                            receipts._binding,
                            'PREPARED',
                            at,
                            GitReceiptFacts(True, None, None, None, None, 'NOT_RUN'),
                        )
                    )
                    _step(
                        connection,
                        original_id,
                        4,
                        'SUCCEEDED',
                        at,
                        result={'git_receipt_ref': asdict(prepared)},
                    )
                    _step(connection, original_id, 5, 'SUCCEEDED', at)
                    _step(connection, original_id, 6, 'RUNNING', at)
                    connection.execute(
                        "UPDATE code_deliveries SET git_write_status='PREPARED' WHERE id=?",
                        (commit.delivery_id,),
                    )
            task_delivery_write.hold_original_delivery(
                runtime, original_id, native_commands_closed=True
            )
            with db.transaction() as connection:
                saved = task_delivery_write.load_original_delivery(connection, original_id)
                assert saved.delivery['git_write_status'] == 'UNKNOWN'
                commands = task_delivery_write.reference_abort_commands(connection, saved)
                assert tuple(row['id'] for row in commands) == (command_id,)
            observer = SimpleNamespace(_reference_receipts=lambda *args: receipts)

            def proof(original):
                return DeliveryWriteRun._proved_aborts(
                    observer, original, commands, commit, require_saved_lock=saved_lock
                )

            assert proof(saved) == ()
            receipts.append(
                GitReceipt(
                    receipts._binding,
                    'ABORTED',
                    operation_time(None),
                    GitReceiptFacts(True, False, None, None, None, 'NOT_RUN'),
                )
            )
            proved = proof(saved)
            if saved_lock:
                altered = list(saved.steps)
                altered[3] = {**saved.steps[3], 'result_ref': '{}'}
                assert proof(SimpleNamespace(steps=altered)) == ()
            assert proved == (command_id,)
            assert task_delivery_write.record_original_ref_abort(runtime, original_id, proved)
            retry = request_window(worker.delivery_epoch)
            assert task_delivery_window.advance_delivery_window_resume(
                runtime, worker.delivery_epoch
            )
            with pytest.raises(StorageUnavailable, match='abort receipts must be rechecked'):
                task_delivery_write.fix_delivery_payload(
                    runtime,
                    journal._package,
                    original_id,
                    worker.delivery_epoch,
                    format='sha1',
                    maximum=4096,
                )
            assert (
                task_delivery_write.fix_delivery_payload(
                    runtime,
                    journal._package,
                    original_id,
                    worker.delivery_epoch,
                    format='sha1',
                    maximum=4096,
                    proved_aborts=proved,
                )
                == commit
            )
            if saved_lock:
                dispatch = DeliveryGitDispatch(runtime, None, controller, journal)
                dispatch.bind(original_id)
                try:
                    with db.transaction() as connection:
                        for step in (4, 5):
                            dispatch._step_no = step
                            with pytest.raises(StorageUnavailable, match='dispatch is fenced'):
                                dispatch._active_step(connection, original_id)
                            dispatch._ref_retry_window = retry
                            assert (
                                dispatch._active_step(connection, original_id)['status']
                                == 'SUCCEEDED'
                            )
                            dispatch._ref_retry_window = None
                finally:
                    dispatch.close()
            receipts.append(
                GitReceipt(
                    receipts._binding,
                    'COMMIT_MAY_BE_SENT',
                    operation_time(None),
                    GitReceiptFacts(True, None, None, None, None, 'NOT_RUN'),
                )
            )
            assert proof(saved) == ()
        with db.transaction() as connection:
            reopened = task_delivery_write.load_original_delivery(connection, original_id)
            assert reopened.window['operation_id'] == retry
            if saved_lock:
                assert [dict(step) for step in reopened.steps[3:5]] == [
                    dict(step) for step in saved.steps[3:5]
                ]
                assert reopened.steps[5]['status'] == 'RUNNING'
                assert reopened.steps[5]['external_identity'] is None
            else:
                assert reopened.steps[3]['status'] == 'RUNNING'
                assert reopened.steps[4]['status'] == 'PENDING'
            assert reopened.delivery['git_write_status'] == 'NOT_DISPATCHED'
            assert reopened.delivery['planned_commit_oid'] == commit.commit_oid
            assert reopened.acceptance['id'] == saved.acceptance['id']
        return
    with LaunchJournal(directory) as journal, ExitStack() as resources:
        native = GitReceiptStore(
            journal,
            GitReceiptBinding(
                scope, 'c' * 32, task['repository_id'], 'd' * 64, commit.commit_oid, 'sha1'
            ),
            max_receipt_bytes=4096,
            max_records=40,
            unique_phases=True,
        )
        resources.callback(native.close)
        at = operation_time(None)
        native.append(
            GitReceipt(
                native._binding,
                'PREPARED',
                at,
                GitReceiptFacts(True, None, None, None, None, 'NOT_RUN'),
            )
        )
        with db.transaction(write=True) as connection:
            connection.execute(
                "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
                (at, original_id),
            )
            connection.execute(
                """UPDATE code_deliveries SET status='PREPARING',git_write_status='PREPARED',
                   planned_commit_oid=?,commit_input_sha256=? WHERE id=?""",
                (commit.commit_oid, commit.payload_sha256, commit.delivery_id),
            )
            for step in range(4, 7):
                _step(connection, original_id, step, 'SUCCEEDED' if step < 6 else 'RUNNING', at)

        if loss == 'private-may-before-sqlite':
            from backend.app.code_tasks.task_role_reconciliation import delivery_reconcile_source

            real_validate = task_delivery_write.DeliverySendFence._validate

            def lose_sqlite(fence, connection, binding, phase):
                result = real_validate(fence, connection, binding, phase)
                if native.read_phase('COMMIT_MAY_BE_SENT') is not None:
                    raise task_delivery_write.DeliveryFenced('Injected failure before SQLite MAY')
                return result

            with monkeypatch.context() as interrupted:
                interrupted.setattr(task_delivery_write.DeliverySendFence, '_validate', lose_sqlite)
                fence = task_delivery_write.DeliverySendFence(
                    runtime, original_id, worker.delivery_epoch, intent, native, lambda: None
                )
                with (
                    pytest.raises(task_delivery_write.DeliveryFenced, match='before SQLite MAY'),
                    fence(process),
                ):
                    pytest.fail('A private MAY alone authorized a ref write')
            with db.transaction() as connection:
                saved = task_delivery_write.load_original_delivery(connection, original_id)
                assert saved.delivery['git_write_status'] == 'PREPARED'
            assert native.read_phase('COMMIT_MAY_BE_SENT') is not None
            assert native.read_phase('COMMIT_ACK') is None
            task_delivery_write.hold_original_delivery(
                runtime, original_id, native_commands_closed=True
            )
            with db.transaction() as connection:
                saved = task_delivery_write.load_original_delivery(connection, original_id)
                assert saved.delivery['git_write_status'] == 'UNKNOWN'
                assert saved.delivery['delivered_at'] is None
                assert (
                    task_delivery_window.renewable_delivery(connection, saved.task, original_id)
                    is None
                )
                assert delivery_reconcile_source(connection, saved.task, saved.operation)
            return

        checks = 0

        def stop_before_single_write():
            nonlocal checks
            checks += 1
            if checks == 2:
                response = _post(
                    client, url + '/terminate', {'expected_state_version': stop_version}
                )
                assert response.status_code == 202, response.text

        fence = task_delivery_write.DeliverySendFence(
            runtime,
            original_id,
            worker.delivery_epoch,
            intent,
            native,
            stop_before_single_write,
        )
        with pytest.raises(task_delivery_write.DeliveryFenced), fence(process):
            pytest.fail('The accepted STOP still allowed the original COMMIT')
        assert native.read_phase('COMMIT_MAY_BE_SENT') is not None
        assert native.read_phase('COMMIT_ACK') is None
        assert not task_delivery_write.record_reconciled_delivery(
            runtime,
            original_id,
            commit,
            native,
            observed_target=commit.parent_oid,
            postcheck='UNKNOWN',
            original_objects_verified=True,
        )
        with db.transaction() as connection:
            saved = task_delivery_write.load_original_delivery(connection, original_id)
            assert saved.delivery['status'] == 'UNKNOWN'
            assert saved.task['status'] == 'STOPPING'
        assert task_delivery_write.record_reconciled_delivery(
            runtime,
            original_id,
            commit,
            native,
            observed_target=commit.commit_oid,
            postcheck='VERIFIED',
            original_objects_verified=True,
        )
        with db.transaction() as connection:
            saved = task_delivery_write.load_original_delivery(connection, original_id)
            assert saved.delivery['status'] == 'SUCCEEDED'
            assert saved.delivery['delivered_at'] is not None
            assert saved.task['status'] == 'STOPPING'
            assert saved.steps[-1]['status'] == 'PENDING'

        delivered_at = saved.delivery['delivered_at']
        assert task_delivery_write.record_reconciled_delivery(
            runtime,
            original_id,
            commit,
            native,
            observed_target=commit.parent_oid,
            postcheck='CONFLICT',
            original_objects_verified=True,
        )
        with db.transaction() as connection:
            late = task_delivery_write.load_original_delivery(connection, original_id)
            assert late.delivery['status'] == 'SUCCEEDED'
            assert late.delivery['delivered_at'] == delivered_at
            assert late.delivery['postcheck_status'] == 'CONFLICT'
            assert late.task['status'] == 'STOPPING'
