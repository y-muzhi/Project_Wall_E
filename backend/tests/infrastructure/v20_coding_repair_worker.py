"""Repair a three-stage candidate and rerun actual Guard development checks."""

from contextlib import ExitStack
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from backend.app.code_tasks import task_repair_runtime
from backend.app.code_tasks.coding_model_admission import CodingModelAdmission
from backend.app.code_tasks.task_model_ingress import ModelWindow, read_original_window_state
from backend.app.code_tasks.task_repair_runtime import advance_repairs
from backend.app.code_tasks.task_role_chain import current_role_chain
from backend.app.code_tasks.usage import UsageContract
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, ModelProfile
from backend.app.infrastructure.opencode_identifiers import OpenCodeMessageIds
from backend.app.infrastructure.opencode_instance_control import NativeTurnRecord
from backend.app.infrastructure.runtime_launch_journal import _bytes


def seed_flat_model_price(database):
    with database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO model_price_versions VALUES(1,'deepseek-v2','test-only-snapshot',
               'ARK_CN_BEIJING','test-only-account','default','2026-11-01T00:00:00.000Z',NULL,
               'CNY','1.000000','2.000000','[]',?,'TOTAL_HALF_UP_6DP','test-only-source',
               '2026-11-01T00:00:00.000Z')""",
            (
                _bytes(
                    {'kind': 'FLAT', 'pricing_clock': 'COMPLETED_AT', 'timezone': 'Asia/Shanghai'}
                ).decode(),
            ),
        )


def exercise_checked_repair(
    runtime,
    client,
    path,
    capture,
    worker,
    original_driver,
    *,
    cancel_first=False,
    replace_session=False,
):
    database = runtime.database
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks').fetchone()
        source_id = task['current_candidate_id']
        original_chain = current_role_chain(connection, task)
        original_session_count = connection.execute(
            'SELECT count(*) FROM code_sessions'
        ).fetchone()[0]
        price = connection.execute('SELECT * FROM model_price_versions WHERE id=1').fetchone()
    admission = CodingModelAdmission(
        'test-only-admission',
        'test-only-snapshot',
        'test-only-account',
        sha256(_bytes(dict(price))).hexdigest(),
        ModelProfile('test-only-provider-credential', DEFAULT_PROFILE),
        UsageContract('fixture-sse', 'USAGE_TRAILER', ('input_tokens', 'output_tokens'), ()),
        30,
        1000,
        2000,
        100,
    )
    models = {admission.evidence_ref: admission}
    response = client.post(
        path + '/defects',
        headers={'Idempotency-Key': str(uuid4())},
        json={
            'expected_state_version': task['state_version'],
            'candidate_id': source_id,
            'actual_behavior': '固定三阶段候选仍有实现偏差',
            'expected_behavior': '按固定设计修复后重新检查三个阶段',
            'basis_ref': {
                'document_id': task['document_id'],
                'revision_id': task['design_revision_id'],
                'quote': '原固定设计',
            },
            'evidence_refs': [],
        },
    )
    assert response.status_code == 201, response.text
    request = {
        'expected_state_version': task['state_version'] + 1,
        'candidate_id': source_id,
        'defect_ids': [response.json()['data']['defect_id']],
    }
    headers = {'Idempotency-Key': str(uuid4())}
    response = client.post(path + '/repairs', json=request, headers=headers)
    assert response.status_code == 202, response.text
    repair_id = response.json()['data']['operation_id']
    cancelled_id = repair_id if cancel_first else None
    sends = []
    replacements = []

    class NativeRepairFixture:
        def __init__(self):
            self.message_ids = {}
            self.ids = OpenCodeMessageIds()

        def session_available(self, operation):
            return True

        def observe_capture_turn(self, scope, window, ref, checkpoint):
            proof = original_driver.observe_capture_turn(scope, window, ref, checkpoint)
            return replace(
                proof,
                turn=replace(
                    proof.turn,
                    assistant_message_id=f'msg_repairdone{window.operation_id}',
                    outcome='CANCELLED' if window.operation_id == cancelled_id else 'COMPLETED',
                    records=(
                        NativeTurnRecord(
                            f'prt_repairdone{window.operation_id}',
                            'MESSAGE',
                            '隔离原生回复',
                        ),
                    ),
                ),
            )

        def repair_session_archived_at(self, scope, previous, ref, checkpoint):
            checkpoint()
            self.replacement_source = previous
            return (
                1
                if replace_session and previous.execution_session_id == original_chain.session_id
                else None
            )

        def revoke_session_source(self, scope, previous, ref, checkpoint):
            checkpoint()
            assert previous.execution_session_id == original_chain.session_id

        def create_session(self, scope, checkpoint):
            checkpoint()
            assert scope.role == original_chain.role and scope.transition_kind == 'REPAIR'
            assert scope.control_generation == task['control_generation'] + 1
            replacements.append(scope.session_id)
            return SimpleNamespace(native_id=f'ses_repair{scope.session_id}')

        def gateway_reference(self, scope):
            return 'test:gateway'

        def observe_replacement_source(self, scope, expected, ref, checkpoint):
            return self.observe_capture_turn(scope, self.replacement_source, ref, checkpoint)

        def replacement_repair_payload(self, scope, context, source, defects, checkpoint):
            assert context.native_session_id == f'ses_repair{scope.session_id}'
            return self.repair_payload(
                scope, None, None, checkpoint, context=context, source=source, defects=defects
            )

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
            self.dispatch_continuation(scope, previous, window, 'test:gateway', payload, checkpoint)
            return payload['messageID']

        def repair_payload(self, scope, previous, ref, checkpoint, *, context, source, defects):
            checkpoint()
            assert source['candidate_id'] == source_id
            assert [item['id'] for item in defects] == request['defect_ids']
            assert scope.role == original_chain.role and context.documents
            if repair_id not in self.message_ids:
                self.message_ids[repair_id] = self.ids.allocate('msg')
            return {'messageID': self.message_ids[repair_id], 'parts': []}

        def dispatch_continuation(self, scope, previous, window, ref, payload, checkpoint):
            checkpoint()
            with database.transaction() as connection:
                assert read_original_window_state(connection, window, ref) == 'QUEUED'
                assert read_original_window_state(connection, previous, ref) is None
            sends.append(window)

        def observe_continuation(self, scope, window, ref, payload, checkpoint):
            checkpoint()
            return window.trigger_message_id

    driver = NativeRepairFixture()

    def trace_boundary(action):
        def checked(*args, **kwargs):
            try:
                return action(*args, **kwargs)
            except Exception as error:
                raise AssertionError(
                    'Original repair boundary failed: ' + action.__name__
                ) from error

        return checked

    def advance():
        with ExitStack() as boundaries:
            for name in ('_source', '_prompt_context', '_verify_original_workspace'):
                action = getattr(task_repair_runtime, name)
                boundaries.enter_context(
                    patch.object(task_repair_runtime, name, trace_boundary(action))
                )
            return advance_repairs(
                runtime, driver, capture._parent, models, cancelled=lambda: False
            )

    assert advance()
    if replace_session:
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert not sends and advance() and len(replacements) == 1
        assert advance()
    assert len(sends) == 1, client.get(path + f'/operations/{repair_id}').text
    if cancel_first:
        assert advance()
        stopped = client.get(path + f'/operations/{repair_id}')
        assert stopped.status_code == 200 and stopped.json()['data']['status'] == 'CANCELLED', (
            stopped.text
        )
        closed = client.get(path)
        assert closed.status_code == 200, closed.text
        state = closed.json()['data']
        assert state['current_candidate_id'] == source_id
        assert state['runtime']['activity_status'] == 'QUIESCENT'
        assert next(item for item in state['available_actions'] if item['action'] == 'REPAIR')[
            'enabled'
        ]
        recaptured = client.post(
            path + '/candidates',
            json={'purpose': 'HANDOFF', 'expected_state_version': state['state_version']},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert recaptured.status_code == 202, recaptured.text
        previous_observe = original_driver.observe_capture_turn

        def observe_cancelled_capture(scope, window, ref, checkpoint):
            actual = previous_observe(scope, window, ref, checkpoint)
            return replace(
                actual,
                turn=replace(
                    actual.turn,
                    assistant_message_id=f'msg_repairdone{window.operation_id}',
                    outcome='CANCELLED',
                    records=(
                        NativeTurnRecord(
                            f'prt_repairdone{window.operation_id}',
                            'MESSAGE',
                            '隔离原生回复',
                        ),
                    ),
                ),
            )

        original_driver.observe_capture_turn = observe_cancelled_capture
        try:
            assert capture.advance() and capture.advance()
            assert worker.advance() and not worker.has_retained_command
        finally:
            original_driver.observe_capture_turn = previous_observe
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT count(*) FROM code_execution_records WHERE task_id=? AND source_id=? AND native_event_id=?',
                    (task['id'], cancelled_id, f'prt_repairdone{cancelled_id}'),
                ).fetchone()[0]
                == 1
            )
        snapshot = client.get(path)
        assert snapshot.status_code == 200, snapshot.text
        state = snapshot.json()['data']
        assert state['current_candidate_id'] != source_id
        source_id = state['current_candidate_id']
        stale_defect = client.post(
            path + '/repairs',
            json={
                **request,
                'candidate_id': source_id,
                'expected_state_version': state['state_version'],
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert (
            stale_defect.status_code == 422
            and stale_defect.json()['error']['code'] == 'DEFECT_SOURCE_MISMATCH'
        ), stale_defect.text
        renewed = client.post(
            path + '/defects',
            json={
                'expected_state_version': state['state_version'],
                'candidate_id': source_id,
                'actual_behavior': '人工捕获候选仍有原设计内偏差',
                'expected_behavior': '按固定设计修复并重查',
                'basis_ref': {
                    'document_id': task['document_id'],
                    'revision_id': task['design_revision_id'],
                    'quote': '原固定设计',
                },
                'evidence_refs': [],
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert renewed.status_code == 201, renewed.text
        request = {
            **request,
            'candidate_id': source_id,
            'defect_ids': [renewed.json()['data']['defect_id']],
        }
        state = client.get(path).json()['data']
        headers = {'Idempotency-Key': str(uuid4())}
        request = {**request, 'expected_state_version': state['state_version']}
        response = client.post(path + '/repairs', json=request, headers=headers)
        assert response.status_code == 202, response.text
        repair_id = response.json()['data']['operation_id']
        assert repair_id != cancelled_id and advance()
        assert len(sends) == 2 and sends[-1].operation_id == repair_id
    # Native output stays in the original isolated task workspace.
    proof = original_driver.observe_capture_turn(None, sends[-1], None, lambda: None)
    source = Path(proof.workspace.canonical_path) / 'src/input.bin'
    with source.open('ab') as output:
        output.write(b'repair fixture\r\n')
    assert advance()
    # The same immutable repair owns this child capture. Run its real Guard
    # content commands and project checks, rather than copying old results.
    previous_observe = original_driver.observe_capture_turn

    def observe_repaired_turn(scope, window, ref, checkpoint):
        proof = previous_observe(scope, window, ref, checkpoint)
        return replace(
            proof,
            turn=replace(
                proof.turn,
                assistant_message_id=f'msg_repairdone{window.operation_id}',
                records=(
                    NativeTurnRecord(
                        f'prt_repairdone{window.operation_id}', 'MESSAGE', '隔离原生回复'
                    ),
                ),
            ),
        )

    original_driver.observe_capture_turn = observe_repaired_turn
    try:
        assert capture.advance() and capture.advance()
        assert advance()
        assert worker.advance() and not worker.has_retained_command
    finally:
        original_driver.observe_capture_turn = previous_observe
    operation = client.get(path + f'/operations/{repair_id}')
    assert operation.status_code == 200 and operation.json()['data']['status'] == 'SUCCEEDED', (
        operation.text
    )
    replay = client.post(path + '/repairs', json=request, headers=headers)
    assert replay.status_code == 202 and replay.json()['data'] == response.json()['data']
    view = client.get(path).json()['data']
    assert view['current_candidate_id'] != source_id
    assert len(sends) == (2 if cancel_first else 1)
    verification = client.get(path + f'/verifications/{view["current_refs"]["verification_id"]}')
    assert verification.status_code == 200, verification.text
    checked = verification.json()['data']
    assert checked['eligible'] and checked['scope_stages'] == list(original_chain.stages)
    assert checked['candidate_id'] == view['current_candidate_id']
    with database.transaction() as connection:
        current = connection.execute('SELECT * FROM code_tasks').fetchone()
        latest_chain = current_role_chain(connection, current)
        assert latest_chain.stages == original_chain.stages
        assert latest_chain.operations == original_chain.operations
        assert latest_chain.session_id == (
            replacements[0] if replace_session else original_chain.session_id
        )
        assert connection.execute(
            "SELECT count(*) FROM code_operations WHERE operation_type='HANDOFF_ROLE' AND status='SUCCEEDED'"
        ).fetchone()[0] == len(original_chain.operations)
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[
            0
        ] == original_session_count + int(replace_session)
    return view
