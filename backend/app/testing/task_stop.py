"""Original Testing termination and proof that its owned execution scope closed."""

from hashlib import sha256

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_integer, strict_json_object

from .assets import NOT_FOUND
from .planning_stop import DRAFT_STOP_POLICY, cancel_closed_drafts, original_draft_stop_scope
from .run_stop import RUN_POLICY, original_run_stop_scope
from .task_views import task_view
from .tasks import read_task_row, task_conflict

STOP_PATH = '/testing-tasks/{testing_task_id}/terminate'
STEPS = operation_steps('TESTING', 'TERMINATE')
POLICY = 'TEST20-EMPTY-STOP-1'
SAFE_LOCAL_OPERATIONS = ('ATTACH_ASSETS', 'INCREASE_TEST_BUDGET')
OWNED_TABLES = (
    'code_commands',
    'code_environment_records',
    'code_verifications',
    'code_runtime_observations',
    'code_waiting_items',
    'code_task_reservations',
    'llm_uses',
    'testing_reports',
)


def stop_operation(connection, task_id):
    return connection.execute(
        """SELECT * FROM code_operations WHERE testing_task_id=? AND task_id IS NULL
           AND resource_kind='TESTING_TASK' AND resource_id=? AND operation_type='TERMINATE'""",
        (task_id, task_id),
    ).fetchone()


def project_accepted(value, task_id):
    data = exact(value, ('testing_task_id', 'operation_id', 'state_version'))
    strict_integer(data['operation_id'], 'operation_id')
    strict_integer(data['state_version'], 'state_version')
    if strict_integer(data['testing_task_id'], 'testing_task_id') != task_id:
        raise ValueError('Original Testing stop crosses owner scope')
    return data


def accepted_stop(task_id, operation, version):
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'testing_task_id': task_id,
                'operation_id': operation,
                'state_version': version,
            },
            'details': None,
        },
        202,
    )


def original_stop_result(connection, operation):
    identity = operation['testing_task_id']
    if (
        identity is None
        or operation['task_id'] is not None
        or operation['resource_kind'] != 'TESTING_TASK'
        or operation['resource_id'] != identity
        or operation['operation_type'] != 'TERMINATE'
    ):
        raise StorageUnavailable('Original Testing termination owner differs')
    command = registered_command(
        'POST', '/api/v1' + STOP_PATH.format(testing_task_id=identity), operation['idempotency_key']
    )
    receipt = connection.execute(
        """SELECT status,http_status,business_input_json,success_result_json FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    expected = accepted_stop(
        identity, operation['id'], increment(operation['expected_state_version'])
    )
    if (
        receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['http_status'] != 202
        or strict_json_object(receipt['business_input_json'])
        != {
            'expected_state_version': operation['expected_state_version'],
        }
        or strict_json_object(receipt['success_result_json']) != expected.result
    ):
        raise StorageUnavailable('Original Testing stop acceptance is missing or differs')
    return expected


def _accept(connection, request):
    task = read_task_row(connection, request.identity)
    if task is None:
        return NOT_FOUND
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return Success(
            {'code': 'TASK_ALREADY_ENDED', 'data': task_view(connection, task), 'details': None},
            200,
        )
    if task['status'] == 'STOPPING':
        original = stop_operation(connection, task['id'])
        if original is None:
            raise StorageUnavailable('Original Testing termination is missing')
        return original_stop_result(connection, original)
    if task['state_version'] != request.expected:
        return task_conflict('VERSION_CONFLICT', task)
    if (
        task['state_version'] >= MAX_SAFE_INTEGER - 1
        or task['control_generation'] == MAX_SAFE_INTEGER
    ):
        return task_conflict('INVALID_STATE', task)

    at = max(operation_time(None), task['created_at'])
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    generation = increment(task['control_generation'])
    version = increment(task['state_version'])
    fixed = canonical_input(
        {
            'expected_state_version': request.expected,
            'prior_status': task['status'],
            'prior_operation_id': task['active_operation_id'],
            'prior_generation': task['control_generation'],
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,
           operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,
           status,created_at,started_at) VALUES(?,?,'TESTING_TASK',?,'TERMINATE',?,?,?,?,'RUNNING',?,?)""",
        (
            identity,
            task['id'],
            task['id'],
            request.idempotency_key,
            request.expected,
            fixed,
            generation,
            at,
            at,
        ),
    )
    fence = canonical_input(
        {
            'closed_generation': generation,
            'prior_generation': task['control_generation'],
        }
    )
    connection.execute(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
           result_ref,started_at,ended_at,last_observed_at)
           VALUES(?,1,?,'SUCCEEDED',?,?,?,?,?)""",
        (identity, STEPS[0], fixed, fence, at, at, at),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(identity, number, step, fixed) for number, step in enumerate(STEPS[1:], 2)],
    )
    changed = connection.execute(
        """UPDATE testing_tasks SET status='STOPPING',stop_requested_at=?,state_version=?,
           control_generation=?,active_operation_id=? WHERE id=? AND status=? AND state_version=?
           AND control_generation=? AND stop_requested_at IS NULL""",
        (
            at,
            version,
            generation,
            identity,
            task['id'],
            task['status'],
            request.expected,
            task['control_generation'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing stop fence was not saved')
    return accepted_stop(task['id'], identity, version)


def terminate_task(runtime, request):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _accept(connection, request),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def _empty_scope(connection, task, operation, fixed):
    if (
        fixed['prior_status'] not in ('DRAFT', 'READY')
        or fixed['prior_operation_id'] is not None
        or task['current_verification_id'] is not None
        or task['report_id'] is not None
        or task['draft_plan_operation_id'] is not None
    ):
        return None
    history = connection.execute(
        """SELECT id,operation_type,status FROM code_operations
           WHERE testing_task_id=? AND id<>? ORDER BY id""",
        (task['id'], operation['id']),
    ).fetchall()
    if any(
        item['operation_type'] not in SAFE_LOCAL_OPERATIONS or item['status'] != 'SUCCEEDED'
        for item in history
    ):
        return None
    counts = {
        table: connection.execute(
            f'SELECT count(*) FROM {table} WHERE testing_task_id=?', (task['id'],)
        ).fetchone()[0]
        for table in OWNED_TABLES
    }
    if any(counts.values()):
        return None
    return {
        'policy': POLICY,
        'testing_task_id': task['id'],
        'operation_id': operation['id'],
        'closed_generation': task['control_generation'],
        'prior_generation': fixed['prior_generation'],
        'checked_local_operation_ids': [item['id'] for item in history],
        'owned_records': counts,
    }


def _save_observation(connection, task, operation, kind, at, evidence, command):
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    connection.execute(
        """INSERT INTO code_runtime_observations(id,testing_task_id,operation_id,control_generation,
           command_id,runtime_binding_ref,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,?,'VERIFIED','[]',0,?,?)""",
        (
            identity,
            task['id'],
            operation['id'],
            task['control_generation'],
            None if command is None else command['command_id'],
            None if command is None else command['runtime_binding_ref'],
            kind,
            at,
            evidence,
        ),
    )
    return identity


def _verify_pending_steps(connection, operation):
    rows = connection.execute(
        'SELECT step_no,step_type,status,fixed_input FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if [tuple(row) for row in rows] != [
        (
            number,
            step,
            'SUCCEEDED'
            if number == 1
            else 'UNKNOWN'
            if number == 2 and operation['status'] == 'UNKNOWN'
            else 'PENDING',
            operation['fixed_input'],
        )
        for number, step in enumerate(STEPS, 1)
    ]:
        raise StorageUnavailable('Original Testing termination steps differ')


def advance_pending_testing_stop(runtime):
    """Finish only a proven empty scope or a verified original CLI closure."""
    with runtime.database.transaction() as connection:
        found = connection.execute(
            """SELECT o.id,o.testing_task_id FROM code_operations o
               WHERE o.testing_task_id IS NOT NULL AND o.task_id IS NULL AND o.operation_type='TERMINATE'
                 AND o.resource_kind='TESTING_TASK'
                 AND (o.status='RUNNING' OR (o.status='UNKNOWN' AND EXISTS(
                      SELECT 1 FROM code_operations prior WHERE prior.id=json_extract(o.fixed_input,'$.prior_operation_id')
                      AND prior.testing_task_id=o.testing_task_id
                      AND ((prior.operation_type='RUN_TEST' AND prior.status='CANCELLED')
                        OR (prior.operation_type='DRAFT_PLAN' AND prior.status IN
                            ('CANCELLED','FAILED','SUCCEEDED','UNKNOWN')
                            AND EXISTS(SELECT 1 FROM llm_uses u WHERE u.operation_id=prior.id
                                AND u.testing_task_id=o.testing_task_id AND u.ended_at IS NOT NULL))))))
               ORDER BY CASE o.status WHEN 'RUNNING' THEN 0 ELSE 1 END,o.id LIMIT 1"""
        ).fetchone()
    if found is None:
        return False
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        task = read_task_row(connection, found['testing_task_id'])
        operation = stop_operation(connection, found['testing_task_id'])
        if (
            task is None
            or operation is None
            or operation['id'] != found['id']
            or operation['status'] not in ('RUNNING', 'UNKNOWN')
            or task['status'] != 'STOPPING'
            or task['active_operation_id'] != operation['id']
            or task['control_generation'] != operation['control_generation']
            or task['state_version'] != increment(operation['expected_state_version'])
        ):
            raise StorageUnavailable('Original Testing termination fence differs')
        original_stop_result(connection, operation)
        fixed = strict_json_object(operation['fixed_input'])
        if (
            fixed['expected_state_version'] != operation['expected_state_version']
            or increment(fixed['prior_generation']) != task['control_generation']
        ):
            raise StorageUnavailable('Original Testing stop generation differs')
        _verify_pending_steps(connection, operation)
        proof = _empty_scope(connection, task, operation, fixed)
        if proof is None:
            proof = original_run_stop_scope(connection, task, operation, fixed)
        if proof is None:
            proof = original_draft_stop_scope(connection, task, operation, fixed)
        at = max(operation_time(None), task['stop_requested_at'])
        if proof is None:
            if operation['status'] == 'UNKNOWN':
                return False
            connection.execute(
                """UPDATE code_operations SET status='UNKNOWN',failure_code='EXECUTION_NOT_STOPPED'
                   WHERE id=? AND status='RUNNING'""",
                (operation['id'],),
            )
            connection.execute(
                """UPDATE code_operation_steps SET status='UNKNOWN',started_at=?,last_observed_at=?
                   WHERE operation_id=? AND step_no=2 AND status='PENDING'""",
                (at, at, operation['id']),
            )
            return True
        if proof['policy'] == DRAFT_STOP_POLICY:
            cancel_closed_drafts(connection, proof, at)
        proof_hash = sha256(canonical_input(proof).encode('utf-8')).hexdigest()
        evidence = 'testing-stop:sha256:' + proof_hash
        command = proof['command_closures'][-1] if proof['policy'] == RUN_POLICY else None
        stopped = _save_observation(connection, task, operation, 'STOP', at, evidence, command)
        cleaned = _save_observation(connection, task, operation, 'CLEANUP', at, evidence, command)
        refs = {'stop_observation_id': stopped, 'cleanup_observation_id': cleaned}
        results = (refs, {'proof': proof, **refs}, refs, {'testing_task_id': task['id']})
        for number, facts in enumerate(results, 2):
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,ended_at=?,
                   last_observed_at=? WHERE operation_id=? AND step_no=? AND status IN ('PENDING','UNKNOWN')""",
                (canonical_input(facts), at, at, at, operation['id'], number),
            )
        connection.execute(
            """UPDATE code_operations SET status='SUCCEEDED',failure_code=NULL,ended_at=?
               WHERE id=? AND status IN ('RUNNING','UNKNOWN')""",
            (at, operation['id']),
        )
        changed = connection.execute(
            """UPDATE testing_tasks SET status='TERMINATED',phase='FINISHED',state_version=?,
               active_operation_id=NULL,stopped_at=?,ended_at=?
               WHERE id=? AND status='STOPPING' AND active_operation_id=? AND control_generation=?""",
            (
                increment(task['state_version']),
                at,
                at,
                task['id'],
                operation['id'],
                task['control_generation'],
            ),
        )
        if changed.rowcount != 1:
            raise StorageUnavailable('Original Testing termination lost its fence')
    return True
