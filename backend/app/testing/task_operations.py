"""Read original Testing task operations without exposing private scope evidence."""

from hashlib import sha256

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import strict_enum, strict_integer, strict_json_object

from .assets import NOT_FOUND, _read
from .planning import DRAFT_TYPE, read_original_draft
from .planning_stop import DRAFT_STOP_POLICY, original_draft_stop_scope
from .run_ownership import read_original_run
from .run_records import accepted_run
from .run_stop import RUN_POLICY, original_run_stop_scope
from .task_recovery import RECOVERY_TYPES, recovery_source
from .task_stop import OWNED_TABLES, POLICY, original_stop_result
from .tasks import read_task_row

CONTROL = {
    'TERMINATE': ('terminate', ('expected_state_version',)),
    'ATTACH_ASSETS': (
        'assets',
        ('expected_state_version', 'plan_version_id', 'test_pack_version_id'),
    ),
    'INCREASE_TEST_BUDGET': (
        'budget',
        ('expected_state_version', 'new_budget_limit_cny', 'authorization_id'),
    ),
}
_SELECT = """SELECT * FROM code_operations WHERE resource_kind='TESTING_TASK'
    AND testing_task_id=resource_id AND task_id IS NULL
    AND operation_type IN ('TERMINATE','ATTACH_ASSETS','INCREASE_TEST_BUDGET','RUN_TEST','RESUME','RECONCILE','DRAFT_PLAN')"""


def _stop_refs(value):
    refs = exact(value, ('stop_observation_id', 'cleanup_observation_id'))
    for field in refs:
        strict_integer(refs[field], field)
    if refs['stop_observation_id'] == refs['cleanup_observation_id']:
        raise ValueError('Original Testing STOP and CLEANUP require distinct observations')
    return refs


def _stop_evidence(connection, operation, rows):
    refs = _stop_refs(strict_json_object(rows[1]['result_ref']))
    verify = exact(
        strict_json_object(rows[2]['result_ref']),
        ('stop_observation_id', 'cleanup_observation_id', 'proof'),
    )
    cleaned = _stop_refs(strict_json_object(rows[3]['result_ref']))
    if any(verify[key] != refs[key] or cleaned[key] != refs[key] for key in refs):
        raise StorageUnavailable('Original Testing stop and cleanup disagree')
    proof = verify['proof']
    command = None
    if type(proof) is dict and proof.get('policy') == RUN_POLICY:
        task = read_task_row(connection, operation['testing_task_id'])
        fixed = strict_json_object(operation['fixed_input'])
        if task is None or proof != original_run_stop_scope(connection, task, operation, fixed):
            raise StorageUnavailable('Original Testing run closure differs')
        command = proof['command_closures'][-1]
    elif type(proof) is dict and proof.get('policy') == DRAFT_STOP_POLICY:
        task = read_task_row(connection, operation['testing_task_id'])
        fixed = strict_json_object(operation['fixed_input'])
        if task is None or proof != original_draft_stop_scope(connection, task, operation, fixed):
            raise StorageUnavailable('Original Testing draft transport closure differs')
    else:
        exact(
            proof,
            (
                'policy',
                'testing_task_id',
                'operation_id',
                'closed_generation',
                'prior_generation',
                'checked_local_operation_ids',
                'owned_records',
            ),
        )
        if (
            proof['policy'] != POLICY
            or proof['testing_task_id'] != operation['testing_task_id']
            or proof['operation_id'] != operation['id']
            or proof['closed_generation'] != operation['control_generation']
            or proof['prior_generation'] + 1 != proof['closed_generation']
            or type(proof['owned_records']) is not dict
            or set(proof['owned_records']) != set(OWNED_TABLES)
            or any(
                type(count) is not int or count != 0 for count in proof['owned_records'].values()
            )
        ):
            raise StorageUnavailable('Original Testing empty execution proof differs')
    digest = sha256(canonical_input(proof).encode('utf-8')).hexdigest()
    for kind, identity in zip(
        ('STOP', 'CLEANUP'),
        (refs['stop_observation_id'], refs['cleanup_observation_id']),
        strict=True,
    ):
        row = connection.execute(
            'SELECT * FROM code_runtime_observations WHERE id=?', (identity,)
        ).fetchone()
        if (
            row is None
            or row['task_id'] is not None
            or row['testing_task_id'] != operation['testing_task_id']
            or row['operation_id'] != operation['id']
            or row['control_generation'] != operation['control_generation']
            or row['kind'] != kind
            or row['result'] != 'VERIFIED'
            or row['instance_id'] is not None
            or row['command_id'] != (None if command is None else command['command_id'])
            or row['runtime_binding_ref']
            != (None if command is None else command['runtime_binding_ref'])
            or row['active_process_count'] != 0
            or row['evidence_ref'] != 'testing-stop:sha256:' + digest
        ):
            raise StorageUnavailable('Original Testing stop observation differs')
    return refs


def _project_run_operation(row, identity, owner):
    task = strict_integer(row['testing_task_id'], 'testing_task_id')
    if (
        row['id'] != identity
        or owner is not None
        and task != owner
        or row['resource_kind'] != 'TESTING_TASK'
        or row['resource_id'] != task
        or any(row[key] is not None for key in ('task_id', 'session_id', 'content_capture'))
    ):
        raise ValueError('Original Testing run projection owner differs')
    registered_command('POST', f'/api/v1/testing-tasks/{task}/run', row['idempotency_key'])
    fixed = exact(row['fixed_input'], ('expected_state_version', 'input_fingerprint'))
    if strict_integer(row['expected_state_version'], 'expected_state_version') != fixed[
        'expected_state_version'
    ] or not valid_sha256(fixed['input_fingerprint']):
        raise ValueError('Original Testing run projection input differs')
    strict_integer(row['control_generation'], 'control_generation')
    status = strict_enum(
        row['status'], 'status', ('RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    )
    ended = status in ('SUCCEEDED', 'FAILED', 'CANCELLED')
    expected_failure = {'UNKNOWN': 'EXECUTION_NOT_STOPPED', 'FAILED': 'EVIDENCE_INCOMPLETE'}
    if row['failure_code'] != expected_failure.get(status):
        raise ValueError('Original Testing run projection failure differs')
    _time(row['created_at'], nullable=False)
    _time(row['started_at'], nullable=False)
    _time(row['ended_at'], nullable=not ended)
    if (
        row['created_at'] > row['started_at']
        or (row['ended_at'] is not None) != ended
        or ended
        and row['ended_at'] < row['started_at']
    ):
        raise ValueError('Original Testing run projection chronology differs')
    definitions = operation_steps('TESTING', 'RUN_TEST')
    if type(row['steps']) is not list or len(row['steps']) != len(definitions):
        raise ValueError('Original Testing run projection steps differ')
    for number, (step, name) in enumerate(zip(row['steps'], definitions, strict=True), 1):
        exact(step, STEP_FIELDS)
        state = strict_enum(
            step['status'],
            'status',
            ('PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED'),
        )
        start, observed, end = (step[key] for key in ('started_at', 'last_observed_at', 'ended_at'))
        for value in (start, observed, end):
            _time(value)
        final = state in ('SUCCEEDED', 'FAILED', 'CANCELLED')
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or ended
            and not final
            or (start is None) != (state == 'PENDING')
            or (observed is None) != (state == 'PENDING')
            or (end is not None) != final
            or start is not None
            and not row['started_at'] <= start <= observed
            or final
            and not start <= end <= observed
            or ended
            and observed > row['ended_at']
        ):
            raise ValueError('Original Testing run step projection differs')
        if name == 'SAVE_REPORT' and state == 'SUCCEEDED':
            report = exact(step['result_ref'], ('report_id',))
            strict_integer(report['report_id'], 'report_id')
        elif step['result_ref'] is not None:
            raise ValueError('Private Testing run evidence cannot appear in an operation read')
    return row


def _run_public(connection, operation):
    run = read_original_run(connection, operation['id'])
    if run is None:
        raise StorageUnavailable('Original Testing run is missing')
    fixed = strict_json_object(operation['fixed_input'])
    public_input = {key: fixed[key] for key in ('expected_state_version', 'input_fingerprint')}
    command = registered_command(
        'POST', f'/api/v1/testing-tasks/{run.task["id"]}/run', operation['idempotency_key']
    )
    saved = connection.execute(
        """SELECT status,http_status,business_input_json,success_result_json FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    version = fixed['expected_state_version']
    expected = accepted_run(run.task['id'], operation['id'], version + 1)
    if saved is None and run.task['kind'] == 'PACK_VALIDATION':
        from .pack_validation import original_validation

        validation = original_validation(connection, run.task['validation_id'])
        if (
            validation is None
            or validation[0]['test_pack_version_id'] != run.pack['id']
            or not any(child['id'] == run.task['id'] for child in validation[3])
        ):
            raise StorageUnavailable('Original Testing internal run ancestry differs')
    elif (
        saved is None
        or saved['status'] != 'SUCCEEDED'
        or saved['http_status'] != 202
        or strict_json_object(saved['business_input_json']) != {'expected_state_version': version}
        or strict_json_object(saved['success_result_json']) != expected.result
    ):
        raise StorageUnavailable('Original Testing run receipt differs')
    steps = []
    for step in connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ):
        result = None
        if step['step_type'] == 'SAVE_REPORT' and step['status'] == 'SUCCEEDED':
            result = strict_json_object(step['result_ref'])
            report = connection.execute(
                'SELECT id FROM testing_reports WHERE id=? AND testing_task_id=? AND verification_id=?',
                (run.task['report_id'], run.task['id'], run.verification['id']),
            ).fetchone()
            if report is None or result != {'report_id': report['id']}:
                raise StorageUnavailable('Original Testing run result differs')
        steps.append(
            {
                **dict(step),
                'fixed_input': public_input,
                'external_identity': None,
                'result_ref': result,
            }
        )
    return _project_run_operation(
        {**dict(operation), 'fixed_input': public_input, 'content_capture': None, 'steps': steps},
        operation['id'],
        run.task['id'],
    )


def _project_recovery_operation(row, identity, owner):
    task = strict_integer(row['testing_task_id'], 'testing_task_id')
    if (
        row['id'] != identity
        or owner is not None
        and task != owner
        or row['resource_kind'] != 'TESTING_TASK'
        or row['resource_id'] != task
        or any(row[key] is not None for key in ('task_id', 'session_id', 'content_capture'))
    ):
        raise ValueError('Original Testing recovery projection owner differs')
    action = row['operation_type']
    registered_command(
        'POST', f'/api/v1/testing-tasks/{task}/{action.lower()}', row['idempotency_key']
    )
    fixed = exact(row['fixed_input'], ('operation_id', 'expected_state_version'))
    target = strict_integer(fixed['operation_id'], 'operation_id')
    version = strict_integer(fixed['expected_state_version'], 'expected_state_version')
    if target == identity or version != row['expected_state_version']:
        raise ValueError('Original Testing recovery projection input differs')
    strict_integer(row['control_generation'], 'control_generation')
    status = strict_enum(row['status'], 'status', ('PENDING', 'SUCCEEDED', 'FAILED'))
    if (row['failure_code'] is not None) != (status == 'FAILED'):
        raise ValueError('Original Testing recovery failure differs')
    pending = status == 'PENDING'
    _time(row['created_at'], nullable=False)
    for field in ('started_at', 'ended_at'):
        _time(row[field], nullable=pending)
        if (row[field] is None) != pending:
            raise ValueError('Original Testing recovery chronology differs')
    if not pending and not row['created_at'] <= row['started_at'] <= row['ended_at']:
        raise ValueError('Original Testing recovery chronology differs')
    steps = operation_steps('TESTING', action)
    if type(row['steps']) is not list or len(row['steps']) != len(steps):
        raise ValueError('Original Testing recovery projection steps differ')
    observed_status = None
    for number, (step, name) in enumerate(zip(row['steps'], steps, strict=True), 1):
        exact(step, STEP_FIELDS)
        expected = (
            'PENDING'
            if pending
            else 'FAILED'
            if status == 'FAILED' and number == len(steps)
            else 'SUCCEEDED'
        )
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['status'] != expected
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
        ):
            raise ValueError('Original Testing recovery step projection differs')
        times = [step[key] for key in ('started_at', 'ended_at', 'last_observed_at')]
        if pending:
            if any(value is not None for value in (*times, step['result_ref'])):
                raise ValueError('Original pending Testing recovery contains facts')
        else:
            for value in times:
                _time(value, nullable=False)
            if not row['started_at'] <= times[0] <= times[1] <= times[2] <= row['ended_at']:
                raise ValueError('Original Testing recovery step chronology differs')
            outcome = exact(step['result_ref'], ('operation_id', 'observed_status'))
            seen = strict_enum(
                outcome['observed_status'],
                'observed_status',
                ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'),
            )
            if outcome['operation_id'] != target or observed_status not in (None, seen):
                raise ValueError('Original Testing recovery result crosses operation')
            observed_status = seen
    return row


def _recovery_public(connection, operation):
    original = recovery_source(connection, operation)
    fixed = strict_json_object(operation['fixed_input'])
    path = f'/api/v1/testing-tasks/{operation["testing_task_id"]}/{operation["operation_type"].lower()}'
    command = registered_command('POST', path, operation['idempotency_key'])
    saved = connection.execute(
        """SELECT status,http_status,business_input_json,success_result_json FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    expected = accepted_run(
        operation['testing_task_id'], operation['id'], operation['expected_state_version']
    )
    if (
        saved is None
        or saved['status'] != 'SUCCEEDED'
        or saved['http_status'] != 202
        or strict_json_object(saved['business_input_json']) != fixed
        or strict_json_object(saved['success_result_json']) != expected.result
        or original['id'] != fixed['operation_id']
    ):
        raise StorageUnavailable('Original Testing recovery receipt differs')
    steps = []
    for step in connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ):
        if step['fixed_input'] != operation['fixed_input'] or step['external_identity'] is not None:
            raise StorageUnavailable('Original Testing recovery step input differs')
        result = None if step['result_ref'] is None else strict_json_object(step['result_ref'])
        steps.append({**dict(step), 'fixed_input': fixed, 'result_ref': result})
    return _project_recovery_operation(
        {**dict(operation), 'fixed_input': fixed, 'content_capture': None, 'steps': steps},
        operation['id'],
        operation['testing_task_id'],
    )


def _project_draft_operation(row, identity, owner):
    task = strict_integer(row['testing_task_id'], 'testing_task_id')
    status = strict_enum(
        row['status'], 'status', ('RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    )
    fixed = exact(row['fixed_input'], ('expected_state_version',))
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    strict_integer(row['control_generation'], 'control_generation')
    if (
        row['id'] != identity
        or owner is not None
        and owner != task
        or row['resource_kind'] != 'TESTING_TASK'
        or row['resource_id'] != task
        or any(row[field] is not None for field in ('task_id', 'session_id', 'content_capture'))
        or fixed['expected_state_version'] != version
    ):
        raise ValueError('Original Testing draft operation scope differs')
    registered_command('POST', f'/api/v1/testing-tasks/{task}/draft-plan', row['idempotency_key'])
    _time(row['created_at'], nullable=False)
    _time(row['started_at'], nullable=False)
    terminal = status in ('SUCCEEDED', 'FAILED', 'CANCELLED')
    _time(row['ended_at'], nullable=not terminal)
    if (
        terminal != (row['ended_at'] is not None)
        or row['created_at'] > row['started_at']
        or terminal
        and row['started_at'] > row['ended_at']
        or (status == 'UNKNOWN') != (row['failure_code'] == 'EXTERNAL_RESULT_UNKNOWN')
        or status in ('RUNNING', 'SUCCEEDED', 'CANCELLED')
        and row['failure_code'] is not None
        or status == 'FAILED'
        and row['failure_code'] not in ('CONFIG_NOT_READY', 'EVIDENCE_INCOMPLETE')
    ):
        raise ValueError('Original Testing draft operation outcome differs')
    sequences = operation_steps('TESTING', DRAFT_TYPE)
    if type(row['steps']) is not list or len(row['steps']) != len(sequences):
        raise ValueError('Original Testing draft steps are incomplete')
    for index, (kind, step) in enumerate(zip(sequences, row['steps'], strict=True), 1):
        exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != index
            or step['step_type'] != kind
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
        ):
            raise ValueError('Original Testing draft step scope differs')
        states = (
            ('SUCCEEDED',)
            if index <= 2
            else (
                ('SUCCEEDED',)
                if status == 'SUCCEEDED'
                else ('UNKNOWN',)
                if status == 'UNKNOWN' and index == 3
                else ('PENDING',)
                if status == 'UNKNOWN'
                else ('PENDING', 'RUNNING')
                if status == 'RUNNING' and index == 3
                else ('PENDING',)
                if status == 'RUNNING'
                else ('CANCELLED',)
                if status == 'CANCELLED'
                else ('FAILED', 'SUCCEEDED')
                if index == 3
                else ('FAILED', 'CANCELLED')
            )
        )
        strict_enum(step['status'], 'step_status', states)
        ended = step['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED')
        for time in ('started_at', 'last_observed_at', 'ended_at'):
            _time(step[time], nullable=not ended)
        if ended != (step['ended_at'] is not None):
            raise ValueError('Original Testing draft step timestamp differs')
        if index == len(sequences) and status == 'SUCCEEDED':
            result = exact(step['result_ref'], ('plan_id', 'plan_version_id'))
            for key in result:
                strict_integer(result[key], key)
        elif step['result_ref'] is not None:
            raise ValueError('Original Testing draft step exposes private evidence')
    return row


def project_task_operation(value, identity, *, owner=None):
    row = exact(value, OPERATION_FIELDS)
    if row['operation_type'] == DRAFT_TYPE:
        return _project_draft_operation(row, identity, owner)
    if row['operation_type'] == 'RUN_TEST':
        return _project_run_operation(row, identity, owner)
    if row['operation_type'] in RECOVERY_TYPES:
        return _project_recovery_operation(row, identity, owner)
    task = strict_integer(row['testing_task_id'], 'testing_task_id')
    status = strict_enum(row['status'], 'status', ('RUNNING', 'UNKNOWN', 'SUCCEEDED'))
    action = strict_enum(row['operation_type'], 'operation_type', tuple(CONTROL))
    if (
        strict_integer(row['id'], 'operation_id') != identity
        or (owner is not None and task != owner)
        or row['resource_kind'] != 'TESTING_TASK'
        or row['resource_id'] != task
        or any(row[field] is not None for field in ('task_id', 'session_id', 'content_capture'))
        or row['failure_code'] != ('EXECUTION_NOT_STOPPED' if status == 'UNKNOWN' else None)
        or action != 'TERMINATE'
        and status != 'SUCCEEDED'
    ):
        raise ValueError('Original Testing operation owner or phase differs')
    route, fields = CONTROL[action]
    registered_command('POST', f'/api/v1/testing-tasks/{task}/{route}', row['idempotency_key'])
    fixed = exact(row['fixed_input'], fields)
    if (
        strict_integer(row['expected_state_version'], 'expected_state_version')
        != fixed['expected_state_version']
    ):
        raise ValueError('Original Testing operation version differs')
    strict_integer(row['control_generation'], 'control_generation')
    _time(row['created_at'], nullable=False)
    _time(row['started_at'], nullable=False)
    _time(row['ended_at'], nullable=status != 'SUCCEEDED')
    if (
        row['started_at'] < row['created_at']
        or (row['ended_at'] is not None) != (status == 'SUCCEEDED')
        or row['ended_at'] is not None
        and row['ended_at'] < row['started_at']
    ):
        raise ValueError('Original Testing operation time differs')
    steps = operation_steps('TESTING', action)
    if type(row['steps']) is not list or len(row['steps']) != len(steps):
        raise ValueError('Original Testing operation steps differ')
    for number, (expected, projection) in enumerate(zip(steps, row['steps'], strict=True), 1):
        step = exact(projection, STEP_FIELDS)
        state = (
            'SUCCEEDED'
            if status == 'SUCCEEDED' or number == 1
            else 'UNKNOWN'
            if status == 'UNKNOWN' and number == 2
            else 'PENDING'
        )
        if (
            step['operation_id'] != identity
            or step['step_type'] != expected
            or step['step_no'] != number
            or step['status'] != state
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
        ):
            raise ValueError('Original Testing step order differs')
        start, observed, end = (step[key] for key in ('started_at', 'last_observed_at', 'ended_at'))
        for instant in (start, observed, end):
            _time(instant)
        if state == 'SUCCEEDED':
            if not all((start, observed, end)) or not row['started_at'] <= start <= end <= observed:
                raise ValueError('Original Testing step chronology differs')
            if action == 'TERMINATE' and number == 2:
                _stop_refs(step['result_ref'])
            elif step['result_ref'] is not None:
                raise ValueError('Private Testing evidence cannot appear in an operation read')
        elif state == 'PENDING':
            if any(value is not None for value in (start, observed, end, step['result_ref'])):
                raise ValueError('Original pending Testing step contains facts')
        elif (
            not start
            or not observed
            or observed < start
            or end is not None
            or step['result_ref'] is not None
        ):
            raise ValueError('Original unknown Testing step is inconsistent')
    return row


def _draft_public(connection, operation):
    original = read_original_draft(connection, operation)
    version = operation['expected_state_version']
    fixed = {'expected_state_version': version}
    command = registered_command(
        'POST',
        f'/api/v1/testing-tasks/{original.task["id"]}/draft-plan',
        operation['idempotency_key'],
    )
    saved = connection.execute(
        """SELECT status,http_status,business_input_json,success_result_json FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    expected = accepted_run(original.task['id'], operation['id'], version + 1)
    if (
        saved is None
        or saved['status'] != 'SUCCEEDED'
        or saved['http_status'] != 202
        or strict_json_object(saved['business_input_json']) != fixed
        or strict_json_object(saved['success_result_json']) != expected.result
    ):
        raise StorageUnavailable('Original Testing draft receipt differs')
    steps = []
    for step in connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ):
        if step['fixed_input'] != operation['fixed_input']:
            raise StorageUnavailable('Original Testing draft fixed input differs')
        refs = None
        if step['step_type'] == 'SAVE_DRAFT' and step['status'] == 'SUCCEEDED':
            refs = exact(strict_json_object(step['result_ref']), ('plan_id', 'plan_version_id'))
            if (
                connection.execute(
                    'SELECT 1 FROM testing_plan_versions WHERE id=? AND plan_id=?',
                    (refs['plan_version_id'], refs['plan_id']),
                ).fetchone()
                is None
            ):
                raise StorageUnavailable('Original Testing draft output disappeared')
        steps.append(
            {**dict(step), 'fixed_input': fixed, 'result_ref': refs, 'external_identity': None}
        )
    return _project_draft_operation(
        {**dict(operation), 'fixed_input': fixed, 'steps': steps, 'content_capture': None},
        operation['id'],
        original.task['id'],
    )


def _public(connection, operation):
    action = operation['operation_type']
    if action == DRAFT_TYPE:
        return _draft_public(connection, operation)
    if action == 'RUN_TEST':
        return _run_public(connection, operation)
    if action in RECOVERY_TYPES:
        return _recovery_public(connection, operation)
    _, fields = CONTROL[action]
    full = strict_json_object(operation['fixed_input'])
    fixed = {field: full[field] for field in fields}
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(operation_steps('TESTING', action)) or any(
        step['fixed_input'] != operation['fixed_input'] for step in steps
    ):
        raise StorageUnavailable('Original Testing operation inputs differ')
    refs = None
    if action == 'TERMINATE':
        original_stop_result(connection, operation)
        if operation['status'] == 'SUCCEEDED':
            refs = _stop_evidence(connection, operation, steps)
    return project_task_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': [
                {
                    **dict(step),
                    'fixed_input': fixed,
                    'external_identity': None,
                    'result_ref': refs if step['step_no'] == 2 else None,
                }
                for step in steps
            ],
        },
        operation['id'],
    )


def read_task_operation(runtime, identity, *, owner=None):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(_SELECT + ' AND id=?', (identity,)).fetchone()
        if row is None or owner is not None and row['testing_task_id'] != owner:
            return NOT_FOUND.result
        try:
            return _read(_public(connection, row))
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Testing task operation is unreadable') from error


def list_task_operations(runtime, owner, page):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if read_task_row(connection, owner) is None:
            return NOT_FOUND.result
        selector = _SELECT + ' AND testing_task_id=?'
        total = connection.execute('SELECT count(*) FROM (' + selector + ')', (owner,)).fetchone()[
            0
        ]
        rows = connection.execute(
            selector + ' ORDER BY id LIMIT ? OFFSET ?', (owner, PAGE_SIZE, page_offset(page))
        ).fetchall()
        try:
            return _read(
                {**page_metadata(page, total), 'items': [_public(connection, row) for row in rows]}
            )
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Testing task operations are unreadable') from error
