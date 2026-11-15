"""Safe public facts for the original Coding START and its native handoff."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.code_errors import CAPABILITIES
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .coding_model_wait import project_task_wait
from .command_registry import registered_command
from .costs import parse_balance, parse_money
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .task_start import START_PATH, START_STEPS, original_start_steps

START_FAILURE_CODES = ('CONTENT_NOT_READY', 'CONFIG_NOT_READY')


def public_start_operation(connection, operation):
    fixed, steps = original_start_steps(connection, operation)
    refs = {}
    stopped, cleaned = _owned_stop_history(connection, operation)
    first, basis, checks, instance, session, initial = steps
    if first['status'] in ('RUNNING', 'SUCCEEDED', 'UNKNOWN'):
        binding = strict_json_object(first['external_identity'])
        workspace_id = strict_integer(binding['workspace_id'], 'workspace_id')
        workspace = connection.execute(
            'SELECT * FROM code_workspaces WHERE id=? AND task_id=?',
            (workspace_id, operation['task_id']),
        ).fetchone()
        if (
            workspace is None
            or workspace['base_snapshot_id'] != binding['snapshot_id']
            or workspace['private_location_key'] != 'working-' + binding['nonce']
            or workspace['status']
            != {
                'RUNNING': 'PREPARING',
                'UNKNOWN': 'UNKNOWN',
                'SUCCEEDED': 'RELEASED' if cleaned else 'READY',
            }.get(first['status'])
        ):
            raise StorageUnavailable('Original START workspace differs')
        if first['status'] == 'SUCCEEDED':
            result = strict_json_object(first['result_ref'])
            if result['workspace_id'] != workspace_id or workspace['ready_at'] != first['ended_at']:
                raise StorageUnavailable('Original START workspace result differs')
            refs[1] = {'workspace_id': workspace_id}
    if basis['status'] == 'SUCCEEDED':
        binding = strict_json_object(basis['external_identity'])
        result = strict_json_object(basis['result_ref'])
        count = strict_integer(result['document_count'], 'document_count')
        if (
            binding['operation_id'] != operation['id']
            or binding['task_id'] != operation['task_id']
            or binding['workspace_id'] != refs[1]['workspace_id']
            or binding['generation'] != operation['control_generation']
            or binding['document_count'] != count
        ):
            raise StorageUnavailable('Original START basis result differs')
        refs[2] = {'document_count': count}
    if checks['status'] in ('FAILED', 'SUCCEEDED'):
        report = strict_json_object(checks['result_ref'])
        if (
            checks['status'] == 'SUCCEEDED'
            and report.pop('runtime_launch_admission', None) is not True
        ):
            raise StorageUnavailable('Original START admission is unavailable')
        refs[3] = report
    if instance['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
        binding = strict_json_object(instance['external_identity'])
        instance_id = strict_integer(binding['instance_id'], 'instance_id')
        saved = connection.execute(
            'SELECT * FROM code_instances WHERE id=? AND task_id=?',
            (instance_id, operation['task_id']),
        ).fetchone()
        expected_status = {'RUNNING': 'STARTING', 'UNKNOWN': 'UNKNOWN', 'SUCCEEDED': 'READY'}
        if (
            binding['operation_id'] != operation['id']
            or binding['task_id'] != operation['task_id']
            or binding['control_generation'] != operation['control_generation']
            or binding['state_version'] != operation['expected_state_version'] + 2
            or saved is None
            or saved['workspace_id'] != refs[1]['workspace_id']
            or saved['control_generation'] != operation['control_generation']
            or saved['effective_profile_version_id'] != binding['effective_profile_version_id']
            or saved['status'] != ('STOPPED' if stopped else expected_status[instance['status']])
            or saved['created_at'] != instance['started_at']
        ):
            raise StorageUnavailable('Original START instance differs')
        if instance['status'] == 'SUCCEEDED':
            if (
                strict_json_object(instance['result_ref']) != {'instance_id': instance_id}
                or saved['ready_at'] != instance['ended_at']
                or any(
                    saved[field] is None
                    for field in (
                        'process_identity',
                        'runtime_binding',
                        'connection_ref',
                        'native_storage_ref',
                    )
                )
            ):
                raise StorageUnavailable('Original START instance readiness differs')
            refs[4] = {'instance_id': instance_id}
    if session['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
        binding = strict_json_object(session['external_identity'])
        session_id = strict_integer(binding['session_id'], 'session_id')
        saved = connection.execute(
            'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
            (session_id, operation['task_id']),
        ).fetchone()
        if (
            binding['task_id'] != operation['task_id']
            or binding['operation_id'] != operation['id']
            or binding['control_generation'] != operation['control_generation']
            or binding['state_version'] != operation['expected_state_version'] + 2
            or binding['instance_id'] != refs[4]['instance_id']
            or binding['workspace_id'] != refs[1]['workspace_id']
            or session_id != operation['session_id']
            or saved is None
            or saved['instance_id'] != binding['instance_id']
            or saved['control_generation'] != binding['control_generation']
            or saved['role'] != 'BACKEND'
            or saved['created_at'] != session['started_at']
            or (
                session['status'] == 'UNKNOWN'
                and saved['status'] != ('RETIRED' if cleaned else 'UNKNOWN')
            )
        ):
            raise StorageUnavailable('Original START session differs')
        reference = {'session_id': session_id}
        if session['status'] == 'SUCCEEDED':
            if (
                strict_json_object(session['result_ref']) != reference
                or not saved['native_session_id']
            ):
                raise StorageUnavailable('Original START session result differs')
            refs[5] = reference
        if initial['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
            message = strict_json_object(initial['external_identity'])
            if (
                message['session_id'] != session_id
                or message['native_session_id'] != saved['native_session_id']
                or message['native_message_id'] != saved['native_message_id']
                or message['gateway_credential_ref'] != saved['gateway_credential_ref']
                or (
                    initial['status'] == 'UNKNOWN'
                    and saved['status'] != ('RETIRED' if cleaned else 'UNKNOWN')
                )
            ):
                raise StorageUnavailable('Original START message binding differs')
            if initial['status'] == 'SUCCEEDED':
                if strict_json_object(initial['result_ref']) != reference:
                    raise StorageUnavailable('Original START message result differs')
                refs[6] = reference
    public = {
        **dict(operation),
        'fixed_input': fixed,
        'content_capture': None,
        'steps': [
            {
                **dict(step),
                'fixed_input': fixed,
                'external_identity': None if step['external_identity'] is None else {},
                'result_ref': refs.get(step['step_no']),
            }
            for step in steps
        ],
    }
    return project_start_operation(public, operation['id'])


def _owned_stop_history(connection, start):
    from .task_stop import is_owned_progress, read_stop_progress, stop_operation

    stop = stop_operation(connection, start['task_id'])
    if stop is None or stop['control_generation'] != start['control_generation'] + 1:
        return False, False
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (start['task_id'],)).fetchone()
    steps, observed = read_stop_progress(connection, task, stop)
    if not is_owned_progress(steps):
        return False, False
    return observed['stop_observation_id'] is not None, observed[
        'cleanup_observation_id'
    ] is not None


def project_start_operation(data, operation_id):
    row = exact(data, OPERATION_FIELDS)
    task_id = strict_integer(row['task_id'], 'task_id')
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    strict_integer(row['control_generation'], 'control_generation')
    if (
        strict_integer(row['id'], 'operation_id') != operation_id
        or row['resource_id'] != task_id
        or row['resource_kind'] != 'TASK'
        or row['operation_type'] != 'START'
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['status']
        not in ('PENDING', 'RUNNING', 'UNKNOWN', 'CANCELLED', 'FAILED', 'SUCCEEDED')
        or (
            row['failure_code'] not in START_FAILURE_CODES
            if row['status'] == 'FAILED'
            else row['failure_code']
            != ('EXTERNAL_RESULT_UNKNOWN' if row['status'] == 'UNKNOWN' else None)
        )
        or row['fixed_input'] != {'task_id': task_id, 'expected_state_version': version}
    ):
        raise ValueError('Original START projection differs')
    registered_command('POST', START_PATH.format(task_id=task_id), row['idempotency_key'])
    _time(row['created_at'], nullable=False)
    cancelled = row['status'] == 'CANCELLED'
    terminal = cancelled or row['status'] in ('FAILED', 'SUCCEEDED')
    _time(row['ended_at'], nullable=not terminal)
    if (row['ended_at'] is not None) != terminal:
        raise ValueError('Original START completion time differs')
    undispatched = row['status'] == 'PENDING' or cancelled
    _time(row['started_at'], nullable=undispatched)
    if undispatched and row['started_at'] is not None:
        raise ValueError('Original START is not dispatched')
    if type(row['steps']) is not list or len(row['steps']) != len(START_STEPS):
        raise ValueError('Original START projection steps differ')
    first, basis, checks, instance, session, initial = row['steps']
    status = row['status']
    stage_states = {
        'PENDING': {('PENDING', 'PENDING')},
        'RUNNING': {
            ('RUNNING', 'PENDING'),
            ('SUCCEEDED', 'PENDING'),
            ('SUCCEEDED', 'RUNNING'),
            ('SUCCEEDED', 'SUCCEEDED'),
        },
        'UNKNOWN': {('UNKNOWN', 'PENDING'), ('SUCCEEDED', 'UNKNOWN')},
        'FAILED': {('SUCCEEDED', 'FAILED')},
        'CANCELLED': {('CANCELLED', 'CANCELLED')},
    }
    blocked = checks['status'] == 'FAILED'
    if checks['status'] in ('FAILED', 'SUCCEEDED'):
        report = checks['result_ref']
        report_fields = ('fixed_content_verified', 'capability_codes', 'system_config_clear')
        for field in (
            'executor_binary_verified',
            'executor_protocol_source_verified',
            'executor_runtime_bundle_verified',
            'lpac_creation_attributes_available',
            'wfp_local_ale_layers_readable',
        ):
            if type(report) is dict and field in report:
                report_fields += (field,)
                if type(report[field]) is not bool:
                    raise ValueError('Original START preflight evidence differs')
        report = exact(report, report_fields)
        codes = report['capability_codes']
        verified = report['fixed_content_verified']
        if (
            status not in (('FAILED',) if blocked else ('RUNNING', 'UNKNOWN', 'SUCCEEDED'))
            or first['status'] != 'SUCCEEDED'
            or basis['status'] != 'SUCCEEDED'
            or type(verified) is not bool
            or type(report['system_config_clear']) is not bool
            or type(codes) is not list
            or bool(codes) != blocked
            or any(type(code) is not str or code not in CAPABILITIES for code in codes)
            or codes != sorted(set(codes))
            or verified != (not blocked or row['failure_code'] == 'CONFIG_NOT_READY')
            or (not verified and 'Q20-CONTENT' not in codes)
            or (not report['system_config_clear'] and 'Q20-CONFIG' not in codes)
            or (
                report.get('executor_runtime_bundle_verified') is False
                and 'Q20-CONFIG' not in codes
            )
        ):
            raise ValueError('Original START condition report differs')
    elif (
        checks['status'] != ('CANCELLED' if cancelled else 'PENDING')
        or (first['status'], basis['status']) not in stage_states[status]
        or (status == 'FAILED' and row['failure_code'] != 'CONTENT_NOT_READY')
    ):
        raise ValueError('Original START preparation order differs')
    native_status = (instance['status'], session['status'], initial['status'])
    if checks['status'] == 'SUCCEEDED':
        allowed = {
            'RUNNING': {
                ('PENDING', 'PENDING', 'PENDING'),
                ('RUNNING', 'PENDING', 'PENDING'),
                ('SUCCEEDED', 'PENDING', 'PENDING'),
                ('SUCCEEDED', 'RUNNING', 'PENDING'),
                ('SUCCEEDED', 'SUCCEEDED', 'PENDING'),
                ('SUCCEEDED', 'SUCCEEDED', 'RUNNING'),
            },
            'UNKNOWN': {
                ('UNKNOWN', 'PENDING', 'PENDING'),
                ('SUCCEEDED', 'UNKNOWN', 'PENDING'),
                ('SUCCEEDED', 'SUCCEEDED', 'UNKNOWN'),
            },
            'SUCCEEDED': {('SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED')},
        }
        if native_status not in allowed.get(status, ()):
            raise ValueError('Original START native step order differs')
    else:
        expected = 'CANCELLED' if cancelled else 'PENDING'
        if native_status != (expected,) * 3:
            raise ValueError('Original START native step has no conditions')
    if session['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
        strict_integer(row['session_id'], 'session_id')
    elif row['session_id'] is not None:
        raise ValueError('Original START has no native session')
    if status == 'SUCCEEDED' and initial['ended_at'] != row['ended_at']:
        raise ValueError('Original START completion differs from accepted message')
    for number, step in enumerate(row['steps'], 1):
        exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != number
            or step['step_type'] != START_STEPS[number - 1]
            or step['fixed_input'] != row['fixed_input']
        ):
            raise ValueError('Original START step differs')
        pending = step['status'] == 'PENDING'
        complete = step['status'] == 'SUCCEEDED'
        if cancelled:
            if (
                any(
                    step[key] is not None
                    for key in ('external_identity', 'result_ref', 'started_at')
                )
                or step['ended_at'] != row['ended_at']
                or step['last_observed_at'] != row['ended_at']
            ):
                raise ValueError('Cancelled START cannot contain external facts')
            continue
        if pending:
            if any(
                step[key] is not None
                for key in (
                    'external_identity',
                    'result_ref',
                    'started_at',
                    'ended_at',
                    'last_observed_at',
                )
            ):
                raise ValueError('Original pending START step has external facts')
            continue
        failed = step['status'] == 'FAILED'
        _time(step['started_at'], nullable=False)
        _time(step['last_observed_at'], nullable=False)
        if (
            step['external_identity'] != (None if failed or number == 3 else {})
            or (number == 1 and step['started_at'] != row['started_at'])
            or (number > 1 and step['started_at'] < row['steps'][number - 2]['ended_at'])
            or step['last_observed_at'] < step['started_at']
        ):
            raise ValueError('Original START step must hide its binding')
        if complete:
            if number != 3:
                fields = {
                    1: 'workspace_id',
                    2: 'document_count',
                    4: 'instance_id',
                    5: 'session_id',
                    6: 'session_id',
                }
                field = fields[number]
                ref = exact(step['result_ref'], (field,))
                strict_integer(ref[field], field)
                if number in (5, 6) and ref[field] != row['session_id']:
                    raise ValueError('Original START safe session reference differs')
            if step['ended_at'] != step['last_observed_at']:
                raise ValueError('Original START completion time differs')
        elif failed:
            if (
                (step['result_ref'] is not None and number != 3)
                or step['ended_at'] != row['ended_at']
                or step['ended_at'] != step['last_observed_at']
            ):
                raise ValueError('Original START failure time differs')
        elif step['result_ref'] is not None or step['ended_at'] is not None:
            raise ValueError('Original START step has no verified result')
    return row


def start_task_view(
    task, materials, differences, start_id, status, restore_status, stop=None, *, failure_code=None
):
    from .initial_task_view import initial_task_view, stopping_task_view

    if stop is None:
        data = initial_task_view(task, materials, differences, False)
    else:
        data = stopping_task_view(task, materials, differences, stop[0], stop[1])
        if stop[1] == 'UNKNOWN':
            data['runtime'].update(stop_status='UNKNOWN', cleanup_status='UNKNOWN')
    if stop is None or status == 'FAILED':
        start_action = data['available_actions'][0]
        start_action.update(
            reason_code={
                'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN',
                'FAILED': failure_code,
            }.get(status, 'OPERATION_IN_PROGRESS'),
            related_id=start_id,
        )
    if status != 'FAILED':
        data['active_operations'].append(
            {'id': start_id, 'operation_type': 'START', 'status': status}
        )
    if restore_status in ('RUNNING', 'UNKNOWN'):
        data['runtime'].update(
            environment_status='UNKNOWN' if restore_status == 'UNKNOWN' else 'PREPARING',
            activity_status='UNKNOWN',
        )
    return data


def validate_preparing_task(data, task_id):
    from .initial_task_view import _validate_fixed_view

    if (
        data['id'] != task_id
        or data['phase'] != 'PREPARING'
        or data['status'] not in ('PENDING', 'STOPPING')
    ):
        raise ValueError('Original preparing task differs')
    limit, materials, differences = _validate_fixed_view(data, data['document_id'])
    stopping = data['status'] == 'STOPPING'
    version = strict_integer(data['state_version'], 'state_version', minimum=3 if stopping else 2)
    strict_integer(data['control_generation'], 'control_generation')
    if any(
        data[name] is not None
        for name in (
            'active_session_id',
            'current_candidate_id',
            'resume_phase',
            'started_at',
            'ended_at',
            'stopped_at',
            'last_observed_at',
        )
    ):
        raise ValueError('Task has execution outside the preparing branch')
    start_action = next(
        action for action in data['available_actions'] if action['action'] == 'START'
    )
    failed = (
        start_action['reason_code'] in START_FAILURE_CODES
        and start_action['related_id'] is not None
    )
    if type(data['active_operations']) is not list or len(data['active_operations']) != int(
        stopping
    ) + int(not failed):
        raise ValueError('Original preparing task operations differ')
    if failed:
        start_id = strict_integer(start_action['related_id'], 'start_operation_id')
        status = 'FAILED'
    else:
        start = exact(data['active_operations'][-1], ('id', 'operation_type', 'status'))
        start_id = strict_integer(start['id'], 'start_operation_id')
        status = start['status']
        if start['operation_type'] != 'START' or status not in ('PENDING', 'RUNNING', 'UNKNOWN'):
            raise ValueError('Original preparing task START differs')
    workspace_id = data['workspace_id']
    if workspace_id is not None:
        strict_integer(workspace_id, 'workspace_id')
        if status not in ('RUNNING', 'UNKNOWN', 'FAILED') or version < (4 if stopping else 3):
            raise ValueError('Workspace requires the verified original preparation')
        restore_status = 'SUCCEEDED'
    elif failed:
        raise ValueError('Original basis failure requires a verified workspace')
    else:
        restore_status = status
    stop = None
    if stopping:
        operation = exact(data['active_operations'][0], ('id', 'operation_type', 'status'))
        identity = strict_integer(data['termination_operation_id'], 'stop_operation_id')
        if (
            identity == start_id
            or operation['id'] != identity
            or operation['operation_type'] != 'TERMINATE'
            or operation['status'] not in ('PENDING', 'UNKNOWN')
        ):
            raise ValueError('Original preparing task stop differs')
        _time(data['stop_requested_at'], nullable=False)
        if not data['created_at'] <= data['stop_requested_at'] <= data['updated_at']:
            raise ValueError('Original preparing task stop time differs')
        stop = (identity, operation['status'])
    elif data['stop_requested_at'] is not None:
        raise ValueError('Pending START cannot have a stop request')
    if data != start_task_view(
        {**data, 'budget_limit_cny': limit},
        materials,
        differences,
        start_id,
        status,
        restore_status,
        stop,
        failure_code=start_action['reason_code'] if failed else None,
    ):
        raise ValueError('Original preparing task view differs')


def started_task_view(
    task,
    materials,
    differences,
    stop=None,
    *,
    budget=None,
    waits=(),
    resume=None,
    answer=None,
    handoff=None,
):
    """Initial running projection with no invented tool or model activity."""
    from .initial_task_view import initial_task_view, stopping_task_view

    if stop is None:
        data = initial_task_view(task, materials, differences, False)
        data['available_actions'] = [
            {
                **item,
                'enabled': item['action'] in ('TERMINATE', 'INCREASE_BUDGET'),
                'reason_code': None
                if item['action'] in ('TERMINATE', 'INCREASE_BUDGET')
                else 'INVALID_STATE',
            }
            for item in data['available_actions']
        ]
    else:
        data = stopping_task_view(task, materials, differences, stop[0], stop[1])
        if stop[1] == 'UNKNOWN':
            data['runtime'].update(stop_status='UNKNOWN', cleanup_status='UNKNOWN')
    if resume is not None:
        resume_id, reason, status = resume
        for item in data['available_actions']:
            if item['action'] == 'RESUME':
                item.update(enabled=reason is None, related_id=resume_id, reason_code=reason)
        if status is not None:
            data['active_operations'] = [
                {'id': resume_id, 'operation_type': 'RESUME', 'status': status}
            ]
    if answer is not None:
        data['active_operations'] = [
            {'id': answer[0], 'operation_type': answer[2], 'status': answer[1]}
        ]
    if handoff is not None:
        identity, status, verification = handoff
        data['active_operations'] = [
            {'id': identity, 'operation_type': 'HANDOFF_ROLE', 'status': status}
        ]
        data['current_refs']['verification_id'] = verification
        if task['status'] == 'VERIFYING':
            for item in data['verification_purposes']:
                item['reason_code'] = 'RESOURCE_NOT_READY'
    if budget is not None:
        data['budget'] = budget
    data['waiting_items'] = list(waits)
    data['runtime'].update(
        environment_status='VERIFIED' if stop is None else 'UNKNOWN',
        activity_status='UNKNOWN',
        observed_at=task['last_observed_at'],
    )
    return data


def validate_started_task(data, task_id):
    from .initial_task_view import _validate_fixed_view

    handoff = None
    active = data['active_operations']
    if len(active) == 1 and active[0]['operation_type'] == 'HANDOFF_ROLE':
        operation = exact(active[0], ('id', 'operation_type', 'status'))
        status = operation['status']
        if status not in ('PENDING', 'RUNNING', 'UNKNOWN') or data['status'] != (
            'WAITING' if status == 'UNKNOWN' else 'VERIFYING'
        ):
            raise ValueError('Original active role handoff differs')
        handoff = (
            strict_integer(operation['id'], 'operation_id'),
            status,
            strict_integer(data['current_refs']['verification_id'], 'verification_id'),
        )
    if (
        data['id'] != task_id
        or data['status'] not in ('RUNNING', 'WAITING', 'STOPPING', 'VERIFYING')
        or data['status'] == 'VERIFYING'
        and handoff is None
        or data['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
    ):
        raise ValueError('Original started task differs')
    limit, materials, differences = _validate_fixed_view(data, data['document_id'])
    stopping = data['status'] == 'STOPPING'
    waiting = data['status'] == 'WAITING'
    waits = [project_task_wait(row, task_id) for row in data['waiting_items']]
    if bool(waits) != waiting or data['resume_phase'] != (data['phase'] if waiting else None):
        raise ValueError('Original started task wait projection differs')
    strict_integer(data['workspace_id'], 'workspace_id')
    if handoff is None or data['active_session_id'] is not None:
        strict_integer(data['active_session_id'], 'active_session_id')
    strict_integer(data['control_generation'], 'control_generation', minimum=2 if stopping else 1)
    strict_integer(data['state_version'], 'state_version', minimum=5 if stopping or waiting else 4)
    _time(data['started_at'], nullable=False)
    _time(data['last_observed_at'], nullable=False)
    if not data['created_at'] <= data['started_at'] <= data['last_observed_at'] <= data[
        'updated_at'
    ] or any(data[key] is not None for key in ('ended_at', 'stopped_at')):
        raise ValueError('Original started task chronology differs')
    if data['current_candidate_id'] is not None:
        strict_integer(data['current_candidate_id'], 'candidate_id')
    elif handoff is not None:
        raise ValueError('Original role handoff candidate is missing')
    stop = None
    if stopping:
        stop_id = strict_integer(data['termination_operation_id'], 'stop_operation_id')
        if type(data['active_operations']) is not list or len(data['active_operations']) != 1:
            raise ValueError('Original active STOP is unavailable')
        operation = exact(data['active_operations'][0], ('id', 'operation_type', 'status'))
        if (
            operation['id'] != stop_id
            or operation['operation_type'] != 'TERMINATE'
            or operation['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN')
        ):
            raise ValueError('Original active STOP differs')
        requested = data['stop_requested_at']
        _time(requested, nullable=False)
        if not data['started_at'] <= requested <= data['updated_at']:
            raise ValueError('Original active STOP chronology differs')
        stop = (stop_id, operation['status'])
    elif data['stop_requested_at'] is not None:
        raise ValueError('Original running task already has a stop')
    resume = answer = None
    active = data['active_operations']
    native_waits = {'ANSWER_QUESTION': 'QUESTION', 'DECIDE_PERMISSION': 'PERMISSION'}
    if not stopping and active and active[0]['operation_type'] in native_waits:
        operation = exact(active[0], ('id', 'operation_type', 'status'))
        if (
            len(active) != 1
            or not any(item['kind'] == native_waits[operation['operation_type']] for item in waits)
            or operation['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN')
        ):
            raise ValueError('Original active question response differs')
        answer = (
            strict_integer(operation['id'], 'operation_id'),
            operation['status'],
            operation['operation_type'],
        )
    if waiting and handoff is None:
        action = next(item for item in data['available_actions'] if item['action'] == 'RESUME')
        if action['related_id'] is not None:
            identity = strict_integer(action['related_id'], 'resume_operation_id')
            reason = action['reason_code']
            if reason not in (None, 'EXTERNAL_RESULT_UNKNOWN', 'OPERATION_IN_PROGRESS'):
                raise ValueError('Original continuation action differs')
            status = None
            if data['active_operations'] and answer is None:
                active = exact(data['active_operations'][0], ('id', 'operation_type', 'status'))
                status = active['status']
                if (
                    status not in ('PENDING', 'RUNNING', 'UNKNOWN')
                    or active['id'] != identity
                    or active['operation_type'] != 'RESUME'
                    or reason
                    != (
                        'EXTERNAL_RESULT_UNKNOWN'
                        if status == 'UNKNOWN'
                        else 'OPERATION_IN_PROGRESS'
                    )
                ):
                    raise ValueError('Original active continuation differs')
            elif reason == 'OPERATION_IN_PROGRESS':
                raise ValueError('Original active continuation is missing')
            resume = (identity, reason, status)
    budget = exact(
        data['budget'],
        ('limit_cny', 'settled_cny', 'reserved_cny', 'available_cny', 'unresolved_call_count'),
    )
    strict_integer(budget['unresolved_call_count'], 'unresolved_call_count', minimum=0)
    if parse_balance(budget['available_cny']) != (
        parse_money(limit)
        - parse_money(budget['settled_cny'])
        - parse_money(budget['reserved_cny'])
    ):
        raise ValueError('Original started task budget differs')
    if data != started_task_view(
        {**data, 'budget_limit_cny': limit},
        materials,
        differences,
        stop,
        budget=budget,
        waits=waits,
        resume=resume,
        answer=answer,
        handoff=handoff,
    ):
        raise ValueError('Original started task projection differs')
