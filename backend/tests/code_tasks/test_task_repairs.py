"""Explicit Coding repair acceptance and original one-send recovery."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_repair_runtime, task_role_reconciliation
from backend.app.code_tasks.task_model_ingress import read_original_window_state
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened  # noqa: F401
from backend.tests.code_tasks.test_task_start import isolated_readiness, stop  # noqa: F401
from backend.tests.code_tasks.test_task_start_instance import original_instance  # noqa: F401
from backend.tests.code_tasks.test_task_start_session import ready  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_cli_run import _candidate_fixture


@pytest.mark.parametrize(
    'failure',
    [
        'lost-message',
        'changed-source',
        'stopped-before-write',
        'custody-release-error',
        'native-cancelled',
    ],
)
def test_repair_request_recovers_original_send_and_reserves_one_new_capture(
    opened,  # noqa: F811
    ready,  # noqa: F811
    monkeypatch,
    failure,
):
    database, runtime, client, ingress, credential, _ = opened
    _, _, _, parent, task_id, _, _ = ready
    original = ingress.window
    candidate, basis = _candidate_fixture(database, task_id)
    at = operation_time(None)
    with database.transaction(write=True) as connection:
        row = connection.execute(
            'SELECT capture_operation_id FROM code_candidates WHERE id=?', (candidate,)
        ).fetchone()
        connection.execute(
            """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,
               control_generation,runtime_binding_ref,kind,result,reason_codes,active_process_count,
               observed_at,evidence_ref) VALUES(?,?,?,?,?,'fixture:guard','QUIESCE','VERIFIED','[]',1,?,'fixture:quiet')""",
            (
                entity_id(connection, EntityKind.RUNTIME_OBSERVATION),
                task_id,
                original.instance_id,
                row[0],
                original.generation,
                at,
            ),
        )
        session = connection.execute(
            'SELECT model_window FROM code_sessions WHERE id=?', (original.execution_session_id,)
        ).fetchone()
        window = strict_json_object(session[0])
        window.update(state='CLOSED', closed_at=at)
        connection.execute(
            'UPDATE code_sessions SET model_window=? WHERE id=?',
            (canonical_input(window), original.execution_session_id),
        )
        connection.execute(
            """UPDATE code_tasks SET status='VERIFYING',current_candidate_id=? WHERE id=?""",
            (candidate, task_id),
        )
        version = connection.execute(
            'SELECT state_version FROM code_tasks WHERE id=?', (task_id,)
        ).fetchone()[0]
    url = f'/api/v1/code-tasks/{task_id}'
    defect = client.post(
        url + '/defects',
        headers={'Idempotency-Key': str(uuid4())},
        json={
            'candidate_id': candidate,
            'expected_state_version': version,
            'actual_behavior': '原结果缺少固定文本',
            'expected_behavior': '保留固定文本',
            'basis_ref': {
                'document_id': basis['document_id'],
                'revision_id': basis['design_revision_id'],
                'quote': '原固定设计',
            },
            'evidence_refs': [],
        },
    )
    assert defect.status_code == 201, defect.text
    defect_id = defect.json()['data']['defect_id']
    body = {
        'expected_state_version': version + 1,
        'candidate_id': candidate,
        'defect_ids': [defect_id],
    }
    headers = {'Idempotency-Key': str(uuid4())}

    def request(fixed=body, auth=headers):
        return client.post(url + '/repairs', json=fixed, headers=auth)

    assert request().status_code == 503
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
    if failure == 'lost-message':
        from backend.app.code_tasks.task_repairs import repair_action_reason

        with database.transaction(write=True) as connection:
            pending = entity_id(connection, EntityKind.OPERATION_RECORD)
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            connection.execute(
                """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
                   operation_type,idempotency_key,expected_state_version,fixed_input,
                   control_generation,status,created_at)
                   VALUES(?,?,'TASK',?,?,'HANDOFF_ROLE',?,?,'{}',?,'PENDING',?)""",
                (
                    pending,
                    task_id,
                    task_id,
                    original.execution_session_id,
                    str(uuid4()),
                    task['state_version'],
                    original.generation,
                    at,
                ),
            )
            assert repair_action_reason(connection, task, True) == 'OPERATION_CONFLICT'
        blocked = request(auth={'Idempotency-Key': str(uuid4())})
        assert (
            blocked.status_code == 409 and blocked.json()['error']['code'] == 'OPERATION_CONFLICT'
        )
        assert blocked.json()['error']['details']['related_operation_id'] == pending
        with database.transaction(write=True) as connection:
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',ended_at=? WHERE id=?", (at, pending)
            )

    bad = request({**body, 'defect_ids': [defect_id, defect_id]}, {'Idempotency-Key': str(uuid4())})
    assert bad.status_code == 422
    foreign = request({**body, 'defect_ids': [9999]}, {'Idempotency-Key': str(uuid4())})
    assert (
        foreign.status_code == 422 and foreign.json()['error']['code'] == 'DEFECT_SOURCE_MISMATCH'
    )
    accepted = request()
    assert accepted.status_code == 202, accepted.text
    fixed = accepted.json()['data']
    assert request().json()['data'] == fixed
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': url + '/repairs',
            'request_key': headers['Idempotency-Key'],
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()['data']['original_outcome']['data'] == fixed
    listing = client.get(url + '/repairs')
    assert listing.status_code == 200, listing.text
    (record,) = listing.json()['data']['items']
    assert record['defect_ids'] == [defect_id] and record['source_candidate_id'] == candidate
    assert client.get(url + f'/repairs/{record["id"]}').json()['data'] == record
    assert client.get('/api/v1/code-tasks/999/repairs/1').status_code == 404
    assert client.get(url + '/repairs?page=2').json()['data']['items'] == []
    operation_id = fixed['operation_id']
    with database.transaction() as connection:
        stored_defect = connection.execute(
            'SELECT * FROM code_defects WHERE id=?', (defect_id,)
        ).fetchone()
    stored = dict(stored_defect)
    stored['basis_ref'] = strict_json_object(stored['basis_ref'])
    stored['evidence_refs'] = []
    monkeypatch.setattr(task_repair_runtime, '_source', lambda *_: ('fixed', (stored,)))

    def verify_source(parent, source, driver, owner, checkpoint, publish, prepare, archive_scope):
        if failure == 'stopped-before-write':
            checkpoint()
            current = client.get(url).json()['data']
            stopped = stop(client, task_id, current['state_version'])
            assert stopped.status_code == 202, stopped.text

            def unexpected_write():
                pytest.fail('Accepted STOP must fence the actual workspace write')

            publish(unexpected_write)
            pytest.fail('The original publication fence did not reject STOP')
        if failure == 'changed-source':
            raise task_repair_runtime.RepairSourceChanged('Fixture changed selected file bytes')
        with database.transaction() as connection:
            digest = connection.execute(
                'SELECT manifest_sha256 FROM code_candidates WHERE id=?', (candidate,)
            ).fetchone()[0]
        prepare({'candidate_id': candidate, 'manifest_sha256': digest}, checkpoint)
        if failure == 'custody-release-error':
            raise PathBoundaryError('Fixture cannot verify original handle close')

    monkeypatch.setattr(task_repair_runtime, '_verify_original_workspace', verify_source)
    monkeypatch.setattr(task_repair_runtime, '_model_capacity_available', lambda *_: True)
    monkeypatch.setattr(task_repair_runtime, '_OBSERVE_RECHECK_SECONDS', 0)

    class Driver:
        sends = 0
        observes = 0

        def session_available(self, operation):
            return operation == original.operation_id

        def repair_session_archived_at(self, scope, previous, ref, checkpoint):
            checkpoint()
            return None

        def repair_payload(
            self, scope, previous, credential, checkpoint, *, context, source, defects
        ):
            checkpoint()
            assert previous == original and context.native_session_id == original.native_session_id
            assert source['candidate_id'] == candidate and defects == (stored,)
            return {'messageID': 'msg_repair'}

        def dispatch_continuation(self, scope, previous, window, credential, payload, checkpoint):
            checkpoint()
            self.sends += 1
            with database.transaction() as connection:
                assert read_original_window_state(connection, window, credential) == 'QUEUED'
            raise TaskExecutionError('Fixture lost original response')

        def observe_continuation(self, scope, window, credential, payload, checkpoint):
            checkpoint()
            self.observes += 1
            assert payload['messageID'] == window.trigger_message_id
            return (None, 'msg_foreign', window.trigger_message_id)[self.observes - 1]

        def observe_capture_turn(self, scope, window, credential, checkpoint):
            checkpoint()
            with database.transaction() as connection:
                assert read_original_window_state(connection, window, credential) == 'OPEN'
            if failure == 'native-cancelled':
                from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence
                from backend.app.infrastructure.opencode_instance_control import (
                    NativeTurnCompletion,
                )

                return CaptureTurnEvidence(
                    NativeTurnCompletion(
                        window.native_session_id,
                        window.trigger_message_id,
                        'msg_cancelled',
                        'CANCELLED',
                    ),
                    'c' * 64,
                    1,
                    parent.verify(),
                )
            return SimpleNamespace(turn=SimpleNamespace(outcome='COMPLETED'))

    driver = Driver()

    def advance():
        return task_repair_runtime.advance_repairs(
            runtime, driver, parent, {}, cancelled=lambda: False
        )

    def original_status():
        observed = client.get(url + f'/operations/{operation_id}')
        assert observed.status_code == 200, observed.text
        assert 'msg_repair' not in observed.text
        return observed.json()['data']['status']

    if failure == 'stopped-before-write':
        assert advance()
        assert driver.sends == driver.observes == 0
        after = client.get(url).json()['data']
        assert after['status'] == 'STOPPING'
        with database.transaction() as connection:
            step = connection.execute(
                'SELECT status, external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=2',
                (operation_id,),
            ).fetchone()
            assert tuple(step) == ('PENDING', None)
            assert read_original_window_state(connection, original, credential) is None
        return

    if failure == 'changed-source':
        assert advance() and original_status() == 'FAILED'
        operation_view = client.get(url + f'/operations/{operation_id}').json()['data']
        assert operation_view['failure_code'] == 'SOURCE_CHANGED'
        assert [row['status'] for row in operation_view['steps']] == ['FAILED'] + ['PENDING'] * 3
        failed = client.get(url + f'/repairs/{record["id"]}').json()['data']
        assert failed['failure_code'] == 'SOURCE_CHANGED'
        assert failed['result_candidate_id'] is None and failed['source_candidate_id'] == candidate
        with database.transaction() as connection:
            after = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            assert (after['status'], after['current_candidate_id']) == ('VERIFYING', candidate)
            model_window = strict_json_object(
                connection.execute(
                    'SELECT model_window FROM code_sessions WHERE id=?',
                    (original.execution_session_id,),
                ).fetchone()[0]
            )
            assert (
                model_window['state'],
                model_window['operation_id'],
                model_window['native_trigger_message_id'],
            ) == ('CLOSED', original.operation_id, original.trigger_message_id)
            assert read_original_window_state(connection, original, credential) is None
        assert driver.sends == driver.observes == 0
        assert request().json()['data'] == fixed
        assert not advance()
        return

    assert advance() and original_status() == 'UNKNOWN'
    if failure == 'custody-release-error':
        assert driver.sends == 0 and driver.observes == 1
        with database.transaction() as connection:
            source_step, message_step = connection.execute(
                'SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no<=2 ORDER BY step_no',
                (operation_id,),
            ).fetchall()
            assert source_step['status'] == 'SUCCEEDED'
            assert message_step['status'] == 'UNKNOWN'
            assert (
                strict_json_object(message_step['external_identity'])['payload']['messageID']
                == 'msg_repair'
            )
        return
    for expected in ('UNKNOWN', 'RUNNING'):
        task = client.get(url)
        assert task.status_code == 200, task.text
        current = task.json()['data']
        action = next(
            item for item in current['available_actions'] if item['action'] == 'RECONCILE'
        )
        assert action == {
            'action': 'RECONCILE',
            'enabled': True,
            'related_id': operation_id,
            'reason_code': None,
        }
        intent = {'expected_state_version': current['state_version'], 'operation_id': operation_id}
        key = {'Idempotency-Key': str(uuid4())}
        accepted = client.post(url + '/reconcile', json=intent, headers=key)
        assert accepted.status_code == 202, accepted.text
        check_id = accepted.json()['data']['operation_id']
        assert not advance()
        assert task_role_reconciliation.advance_role_reconciliation(
            runtime, driver, cancelled=lambda: False
        )
        recovered = client.get(url + f'/operations/{check_id}')
        assert recovered.status_code == 200, recovered.text
        final = recovered.json()['data']
        assert final['status'] == 'SUCCEEDED'
        assert final['steps'][-1]['result_ref'] == {
            'operation_id': operation_id,
            'original_status': expected,
        }
        assert 'msg_repair' not in recovered.text
        assert (
            client.post(url + '/reconcile', json=intent, headers=key).json()['data']
            == accepted.json()['data']
        )
        assert original_status() == expected

    if failure == 'native-cancelled':
        assert advance() and original_status() == 'CANCELLED'
        from backend.app.code_tasks.task_cancelled_repair import read_cancelled_repair
        from backend.app.code_tasks.task_repairs import repair_action_reason

        with database.transaction() as connection:
            current = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()
            session = connection.execute(
                'SELECT * FROM code_sessions WHERE id=?', (current['active_session_id'],)
            ).fetchone()
            closed = strict_json_object(session['model_window'])
            assert current['status'] == 'VERIFYING' and current['current_candidate_id'] == candidate
            assert read_cancelled_repair(connection, current, session, closed) is not None
            assert repair_action_reason(connection, current, True) is None
            assert (
                read_cancelled_repair(
                    connection,
                    {**dict(current), 'control_generation': current['control_generation'] + 1},
                    session,
                    closed,
                )
                is None
            )
            with pytest.raises(StorageUnavailable):
                read_cancelled_repair(
                    connection,
                    current,
                    session,
                    {**closed, 'native_trigger_message_id': 'msg_foreign'},
                )
        explicit = request(
            {**body, 'expected_state_version': current['state_version']},
            {'Idempotency-Key': str(uuid4())},
        )
        assert explicit.status_code == 202, explicit.text
        assert explicit.json()['data']['operation_id'] != operation_id
        assert driver.sends == 1 and driver.observes == 3
        assert request().json()['data'] == fixed
        return

    assert advance() and original_status() == 'RUNNING'
    assert driver.sends == 1 and driver.observes == 3
    with database.transaction() as connection:
        pending = connection.execute(
            """SELECT id FROM code_operations WHERE task_id=? AND operation_type='CAPTURE_AND_CHECK'
               AND status='PENDING'""",
            (task_id,),
        ).fetchall()
        assert len(pending) == 1
        assert (
            connection.execute('SELECT result_candidate_id FROM code_repairs').fetchone()[0] is None
        )
        assert (
            connection.execute('SELECT current_candidate_id FROM code_tasks').fetchone()[0]
            == candidate
        )
