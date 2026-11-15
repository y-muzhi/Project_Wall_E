"""Strict retained C39 facts, launch provenance, and safe public projections."""

import hashlib
import json

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .authorizations import project_grant
from .execution_profile_content import FIELDS
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .task_configuration_effective import supported_live_changes
from .task_configuration_progress import configuration_records

SOURCE_FIELDS = (
    'application_id',
    'start_operation_id',
    'instance_id',
    'launch_profile_id',
    'old_profile_version_id',
    'old_authorization_id',
    'workspace_id',
    'session_id',
    'native_session_id',
    'credential_ref',
    'generation',
    'role',
    'model_window',
    'guard_receipt_sha256',
    'runtime_binding_ref',
)


def stored_profile_content(row):
    return {
        key: row[key]
        if key == 'check_set_version_id' or row[key] is None
        else strict_json_object(row[key])
        if key not in ('commands', 'capability_evidence_refs')
        else json.loads(row[key])
        for key in FIELDS
    }


def _validate_quiescence_record(connection, operation, source, step):
    quiet = exact(strict_json_object(step['result_ref']), ('quiesce_observation_id', 'proof'))
    quiet_id = strict_integer(quiet['quiesce_observation_id'], 'quiesce_observation_id')
    proof = exact(
        quiet['proof'], ('turn', 'guard_receipt_sha256', 'active_process_count', 'workspace')
    )
    turn = exact(
        proof['turn'], ('session_id', 'trigger_message_id', 'assistant_message_id', 'outcome')
    )
    record = connection.execute(
        'SELECT * FROM code_runtime_observations WHERE id=?', (quiet_id,)
    ).fetchone()
    digest = hashlib.sha256(canonical_input(proof).encode()).hexdigest()
    if (
        record is None
        or record['operation_id'] != operation['id']
        or record['task_id'] != operation['task_id']
        or record['instance_id'] != source['instance_id']
        or record['control_generation'] != source['generation']
        or record['runtime_binding_ref'] != source['runtime_binding_ref']
        or (
            record['kind'],
            record['result'],
            record['reason_codes'],
            record['active_process_count'],
        )
        != ('QUIESCE', 'VERIFIED', '[]', 1)
        or record['observed_at'] != step['ended_at']
        or record['evidence_ref']
        != f'sqlite:code_operation_steps/{operation["id"]}/2#sha256={digest}'
        or proof['guard_receipt_sha256'] != source['guard_receipt_sha256']
        or type(proof['active_process_count']) is not int
        or proof['active_process_count'] != 1
        or turn['session_id'] != source['native_session_id']
        or turn['trigger_message_id'] != source['model_window']['native_trigger_message_id']
        or turn['outcome'] not in ('COMPLETED', 'CANCELLED')
        or not _identifier(turn['assistant_message_id'], 'msg')
    ):
        raise StorageUnavailable('Original control quiet observation differs')


def live_configuration_records(connection, operation):
    fixed, application, steps = configuration_records(connection, operation)
    raw_source = strict_json_object(steps[0]['external_identity'])['source']
    source = exact(
        raw_source,
        (
            *SOURCE_FIELDS,
            *(('check_configuration',) if 'check_configuration' in raw_source else ()),
            *(('model_authorization',) if 'model_authorization' in raw_source else ()),
            *(('delivery_authorization',) if 'delivery_authorization' in raw_source else ()),
            *(('native_read_authorization',) if 'native_read_authorization' in raw_source else ()),
            *(
                ('publication_operation_id', 'published_candidate_id')
                if 'publication_operation_id' in raw_source
                else ()
            ),
        ),
    )
    for key in SOURCE_FIELDS:
        if key.endswith('_id') and key != 'native_session_id' or key == 'generation':
            strict_integer(source[key], key)
    if (
        operation['session_id'] != source['session_id']
        or operation['control_generation'] != source['generation']
        or application['id'] != source['application_id']
        or application['old_profile_version_id'] != source['old_profile_version_id']
        or steps[0]['result_ref']
        != canonical_input({'state_version': operation['expected_state_version'] + 1})
        or source['model_window']['state'] != 'CLOSED'
        or steps[0]['external_identity'] != canonical_input({'source': source})
    ):
        raise StorageUnavailable('Original live configuration source differs')
    previous = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (application['old_profile_version_id'],),
    ).fetchone()
    following = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (application['new_profile_version_id'],),
    ).fetchone()
    old_grant = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
        (source['old_authorization_id'], operation['task_id']),
    ).fetchone()
    new_grant = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
        (application['authorization_id'], operation['task_id']),
    ).fetchone()
    if (
        previous is None
        or following is None
        or old_grant is None
        or new_grant is None
        or not supported_live_changes(
            stored_profile_content(previous),
            stored_profile_content(following),
            project_grant(old_grant)['scope'],
            project_grant(new_grant)['scope'],
        )
    ):
        raise StorageUnavailable('Original live configuration exceeds supported changes')
    old_scope = project_grant(old_grant)['scope']
    new_scope = project_grant(new_grant)['scope']
    native_changed = old_scope['read_roots'] != new_scope['read_roots']
    if native_changed != ('native_read_authorization' in source):
        raise StorageUnavailable('Original native read authorization compilation is missing')
    if native_changed:
        from .task_configuration_native import (
            NativeReadAuthorizationError,
            compile_native_read_authorization,
        )

        try:
            native_plan = compile_native_read_authorization(
                connection, operation['task_id'], old_scope, new_scope
            )
        except NativeReadAuthorizationError as error:
            raise StorageUnavailable('Original native read authorization differs') from error
        if canonical_input(native_plan) != canonical_input(source['native_read_authorization']):
            raise StorageUnavailable('Original native read authorization compilation differs')
    changed_models = (
        project_grant(old_grant)['scope']['model_profile_refs']
        != project_grant(new_grant)['scope']['model_profile_refs']
    )
    if changed_models != ('model_authorization' in source):
        raise StorageUnavailable('Original model authorization compilation is missing')
    if changed_models:
        from .task_configuration_models import ModelAuthorizationError, compile_model_authorization

        try:
            compiled = compile_model_authorization(
                connection,
                operation['task_id'],
                strict_json_object(following['models']),
                project_grant(new_grant)['scope'],
            )
        except ModelAuthorizationError as error:
            raise StorageUnavailable('Original model authorization differs') from error
        if canonical_input(source['model_authorization']) != canonical_input(compiled):
            raise StorageUnavailable('Original model authorization compilation differs')
    changed_delivery = (
        project_grant(old_grant)['scope']['allow_local_delivery']
        != project_grant(new_grant)['scope']['allow_local_delivery']
    )
    if changed_delivery != ('delivery_authorization' in source):
        raise StorageUnavailable('Original delivery authorization compilation is missing')
    if changed_delivery:
        from .task_configuration_delivery import (
            DeliveryAuthorizationError,
            compile_delivery_authorization,
        )

        try:
            compiled = compile_delivery_authorization(
                connection,
                operation['task_id'],
                None
                if following['delivery'] is None
                else strict_json_object(following['delivery']),
                project_grant(new_grant)['scope'],
            )
        except DeliveryAuthorizationError as error:
            raise StorageUnavailable('Original delivery authorization differs') from error
        if canonical_input(source['delivery_authorization']) != canonical_input(compiled):
            raise StorageUnavailable('Original delivery authorization compilation differs')
    from .task_configuration_checks import check_configuration_changes

    check_set_changed, output_changed = check_configuration_changes(
        stored_profile_content(previous),
        stored_profile_content(following),
        project_grant(old_grant)['scope'],
        project_grant(new_grant)['scope'],
    )
    checks_changed = check_set_changed or output_changed
    if checks_changed != ('check_configuration' in source):
        raise StorageUnavailable('Original check configuration acceptance is missing')
    if checks_changed:
        from .task_configuration_checks import validate_retained_check_configuration

        if output_changed != ('max_output_bytes' in source['check_configuration']):
            raise StorageUnavailable('Original check output limit acceptance differs')
        validate_retained_check_configuration(
            connection,
            operation['task_id'],
            following,
            project_grant(new_grant)['scope'],
            source['role'],
            source['check_configuration'],
        )

    if 'publication_operation_id' in source:
        from .task_testing_publication import read_candidate_publication

        strict_integer(source['publication_operation_id'], 'publication_operation_id')
        strict_integer(source['published_candidate_id'], 'published_candidate_id')
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (source['published_candidate_id'], operation['task_id']),
        ).fetchone()
        if candidate is None:
            raise StorageUnavailable('Original configuration candidate is missing')
        publication = read_candidate_publication(connection, candidate)
        if (
            source['role'] != 'INTEGRATION'
            or publication['id'] != source['publication_operation_id']
        ):
            raise StorageUnavailable('Original configuration publication differs')

    original = connection.execute(
        """SELECT o.id,s.external_identity,s.result_ref FROM code_operations o
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=4 AND s.status='SUCCEEDED'
           WHERE o.id=? AND o.task_id=? AND o.operation_type='START' AND o.status='SUCCEEDED'""",
        (source['start_operation_id'], operation['task_id']),
    ).fetchone()
    instance = connection.execute(
        'SELECT * FROM code_instances WHERE id=? AND task_id=?',
        (source['instance_id'], operation['task_id']),
    ).fetchone()
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (source['session_id'], operation['task_id']),
    ).fetchone()
    window = exact(
        source['model_window'],
        ('operation_id', 'native_trigger_message_id', 'state', 'opened_at', 'closed_at'),
    )
    strict_integer(window['operation_id'], 'original_window.operation_id')
    _time(window['opened_at'], nullable=False)
    _time(window['closed_at'], nullable=False)
    if (
        original is None
        or instance is None
        or session is None
        or strict_json_object(original['result_ref']) != {'instance_id': source['instance_id']}
        or strict_json_object(original['external_identity'])['effective_profile_version_id']
        != source['launch_profile_id']
        or instance['effective_profile_version_id'] != source['launch_profile_id']
        or instance['workspace_id'] != source['workspace_id']
        or session['instance_id'] != instance['id']
        or session['role'] != source['role']
        or session['control_generation'] != source['generation']
        or session['native_session_id'] != source['native_session_id']
        or not _identifier(source['native_session_id'], 'ses')
        or not _identifier(window['native_trigger_message_id'], 'msg')
        or window['closed_at'] < window['opened_at']
        or window['closed_at'] > operation['created_at']
        or not _hex(source['guard_receipt_sha256'], 64)
        or strict_json_object(instance['process_identity'])['ownership_ref']
        != source['guard_receipt_sha256']
        or strict_json_object(instance['runtime_binding'])['guard_run_ref']
        != source['runtime_binding_ref']
        or type(source['credential_ref']) is not str
        or not source['credential_ref']
        or old_grant['profile_version_id'] != application['old_profile_version_id']
    ):
        raise StorageUnavailable('Original control source is not the original session host')

    if steps[1]['status'] == 'SUCCEEDED':
        _validate_quiescence_record(connection, operation, source, steps[1])

    from .task_configuration_control import retained_control_application, verify_control_result

    control_identity = retained_control_application(operation, application, steps, source)
    if control_identity is not None and native_changed:
        from .task_native_policy import (
            NativePolicyCompilationError,
            validate_managed_policy_evidence,
        )

        quiet = strict_json_object(steps[1]['result_ref'])['proof']
        try:
            validate_managed_policy_evidence(
                control_identity['target_policy'],
                stored_profile_content(following),
                new_scope,
                quiet['workspace'],
                control_identity['target_policy']['agent'],
            )
        except NativePolicyCompilationError as error:
            raise StorageUnavailable('Original native target policy evidence differs') from error

    if operation['status'] == 'SUCCEEDED':
        result = exact(
            strict_json_object(steps[3]['result_ref']),
            (
                'configuration_application_id',
                'start_operation_id',
                'effective_evidence',
                'native_permission_sha256',
            ),
        )
        evidence = exact(
            result['effective_evidence'],
            (
                'instance_id',
                'control_generation',
                'runtime_bundle_ref',
                'configuration_policy_version',
                'source_refs',
                'nonsecret_config_ref',
                'role_model_refs',
                'observed_at',
                'result',
                'difference_kinds',
            ),
        )
        _time(evidence['observed_at'], nullable=False)
        strict_integer(evidence['instance_id'], 'effective.instance_id')
        strict_integer(evidence['control_generation'], 'effective.control_generation')
        effect_profile = stored_profile_content(following)
        models = effect_profile['models']
        model_refs = exact(
            evidence['role_model_refs'],
            (
                'role',
                'agent_ref',
                'primary_profile_ref',
                'auxiliary_profile_refs',
            ),
        )
        if (
            evidence['observed_at'] != operation['ended_at']
            or evidence['difference_kinds'] != []
            or evidence['runtime_bundle_ref'] != effect_profile['executor']['runtime_bundle_ref']
            or evidence['configuration_policy_version'] != 'OC20-CONFIG-1'
            or evidence['source_refs']
            != ['sha256:' + strict_json_object(instance['runtime_binding'])['manifest_ref']]
            or type(evidence['nonsecret_config_ref']) is not str
            or not evidence['nonsecret_config_ref'].startswith('sha256:')
            or not _hex(evidence['nonsecret_config_ref'][7:], 64)
            or not _hex(result['native_permission_sha256'], 64)
            or model_refs['role'] != source['role']
            or model_refs['primary_profile_ref'] != models['primary_profile_ref']
            or model_refs['auxiliary_profile_refs'] != models['auxiliary_profile_refs']
            or type(model_refs['agent_ref']) is not str
            or not model_refs['agent_ref']
        ):
            raise StorageUnavailable('Original control native configuration evidence differs')
        verify_control_result(control_identity, result)
        if (
            application['status'] != 'APPLIED'
            or application['applied_at'] != operation['ended_at']
            or application['effective_evidence'] != canonical_input(result['effective_evidence'])
            or result['effective_evidence']['result'] != 'VERIFIED'
            or result['effective_evidence']['instance_id'] != source['instance_id']
            or result['effective_evidence']['control_generation'] != source['generation']
            or result['start_operation_id'] != source['start_operation_id']
            or result['configuration_application_id'] != application['id']
            or new_grant['status'] not in ('EFFECTIVE', 'RETIRED')
        ):
            raise StorageUnavailable('Original live effective observation differs')
    else:
        expected_application, expected_grant = {
            'RUNNING': ('PENDING', 'BOUND_PENDING_APPLY'),
            'UNKNOWN': ('UNKNOWN', 'APPLY_UNKNOWN'),
            'CANCELLED': ('FAILED', 'APPLY_FAILED'),
        }[operation['status']]
        if (
            application['status'] != expected_application
            or new_grant['status'] != expected_grant
            or application['applied_at'] is not None
            or application['effective_evidence'] is not None
        ):
            raise StorageUnavailable('Original live configuration lifecycle differs')
    return fixed, application, steps, source


def public_live_configuration_operation(connection, operation):
    fixed, application, steps, source = live_configuration_records(connection, operation)
    projected = []
    for step in steps:
        result = None if step['result_ref'] is None else strict_json_object(step['result_ref'])
        if step['step_no'] == 2 and result is not None:
            result = {'scope': 'CURRENT_SESSION'}
        if step['step_no'] == 4 and result is not None:
            result = {
                'configuration_application_id': application['id'],
                'start_operation_id': source['start_operation_id'],
            }
        projected.append(
            {**dict(step), 'fixed_input': fixed, 'external_identity': None, 'result_ref': result}
        )
    return project_live_configuration_operation(
        {**dict(operation), 'fixed_input': fixed, 'content_capture': None, 'steps': projected},
        operation['id'],
    )


def _live_step_states(row):
    states = [exact(step, STEP_FIELDS)['status'] for step in row['steps'][1:]]
    if row['status'] == 'SUCCEEDED':
        if states != ['SUCCEEDED'] * 3:
            raise ValueError('Original live configuration completion differs')
        return states
    completed = 0
    while completed < len(states) and states[completed] == 'SUCCEEDED':
        completed += 1
    if completed == len(states):
        raise ValueError('Original live configuration has no current step')
    active = states[completed]
    allowed = {
        'RUNNING': ('PENDING', 'RUNNING'),
        'UNKNOWN': ('UNKNOWN',),
        'CANCELLED': ('CANCELLED',),
    }[row['status']]
    following = 'CANCELLED' if row['status'] == 'CANCELLED' else 'PENDING'
    if active not in allowed or states[completed + 1 :] != [following] * (2 - completed):
        raise ValueError('Original live configuration step order differs')
    return states


def project_live_configuration_operation(value, identity):
    from .command_registry import registered_command
    from .task_configuration_apply import BODY, PATH, STEPS, TYPE

    row = exact(value, OPERATION_FIELDS)
    fixed = exact(row['fixed_input'], ('task_id', *BODY))
    for key in (
        'id',
        'task_id',
        'resource_id',
        'session_id',
        'control_generation',
        'expected_state_version',
    ):
        strict_integer(row[key], key)
    for key in ('task_id', *BODY[:-1]):
        strict_integer(fixed[key], key)
    if (
        row['id'] != identity
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['operation_type'] != TYPE
        or fixed['task_id'] != row['task_id']
        or fixed['expected_state_version'] != row['expected_state_version']
        or not isinstance(fixed['reason'], str)
        or not fixed['reason'].strip()
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
        or row['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED', 'CANCELLED')
    ):
        raise ValueError('Original live configuration projection differs')
    registered_command('POST', PATH.format(task_id=row['task_id']), row['idempotency_key'])
    _time(row['created_at'], nullable=False)
    if row['started_at'] != row['created_at']:
        raise ValueError('Original live configuration start differs')
    ended = row['ended_at']
    _time(ended)
    terminal = row['status'] in ('SUCCEEDED', 'CANCELLED')
    if terminal != (ended is not None) or (ended is not None and ended < row['created_at']):
        raise ValueError('Original live configuration end differs')
    expected_failure = {
        'RUNNING': None,
        'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN',
        'SUCCEEDED': None,
        'CANCELLED': 'TASK_ENDED',
    }[row['status']]
    if row['failure_code'] != expected_failure:
        raise ValueError('Original live configuration failure differs')
    states = _live_step_states(row)
    previous_ended = row['created_at']
    for number, (step, kind) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(step, STEP_FIELDS)
        strict_integer(step['operation_id'], 'step.operation_id')
        strict_integer(step['step_no'], 'step.step_no')
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != kind
            or canonical_input(step['fixed_input']) != canonical_input(fixed)
            or step['external_identity'] is not None
        ):
            raise ValueError('Original live configuration step identity differs')
        for key in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[key])
        if number == 1:
            if (
                step['status'] != 'SUCCEEDED'
                or strict_integer(
                    exact(step['result_ref'], ('state_version',))['state_version'],
                    'step.state_version',
                )
                != row['expected_state_version'] + 1
                or any(
                    step[k] != row['created_at']
                    for k in ('started_at', 'ended_at', 'last_observed_at')
                )
            ):
                raise ValueError('Original live configuration block differs')
            continue
        expected = states[number - 2]
        if step['status'] != expected:
            raise ValueError('Original live configuration step state differs')
        if expected == 'PENDING':
            if any(
                step[k] is not None
                for k in ('started_at', 'ended_at', 'last_observed_at', 'result_ref')
            ):
                raise ValueError('Original live configuration has premature evidence')
        else:
            if (
                step['started_at'] is None
                or step['last_observed_at'] is None
                or step['started_at'] < previous_ended
                or step['last_observed_at'] < step['started_at']
                or (expected in ('RUNNING', 'UNKNOWN') and step['ended_at'] is not None)
                or (
                    expected in ('SUCCEEDED', 'CANCELLED')
                    and (
                        step['ended_at'] is None
                        or step['ended_at'] < step['started_at']
                        or step['last_observed_at'] != step['ended_at']
                        or (ended is not None and step['ended_at'] > ended)
                        or ((expected == 'CANCELLED' or number == 4) and step['ended_at'] != ended)
                    )
                )
            ):
                raise ValueError('Original live configuration observation time differs')
            if step['ended_at'] is not None:
                previous_ended = step['ended_at']
            if expected == 'SUCCEEDED':
                fields = (
                    ('scope',)
                    if number == 2
                    else ('configuration_application_id',)
                    if number == 3
                    else ('configuration_application_id', 'start_operation_id')
                )
                result = exact(step['result_ref'], fields)
                if number == 2:
                    if result['scope'] != 'CURRENT_SESSION':
                        raise ValueError('Original live configuration quiescence differs')
                else:
                    strict_integer(
                        result['configuration_application_id'], 'configuration_application_id'
                    )
                    if number == 4:
                        strict_integer(result['start_operation_id'], 'start_operation_id')
                        if (
                            result['configuration_application_id']
                            != row['steps'][2]['result_ref']['configuration_application_id']
                        ):
                            raise ValueError('Original live configuration application differs')
            elif step['result_ref'] is not None:
                raise ValueError('Original live configuration has an unconfirmed result')
    return row


def without_live_configuration_projection(data):
    active = [
        row for row in data['active_operations'] if row['operation_type'] == 'APPLY_CONFIGURATION'
    ]
    if (
        data['status'] == 'WAITING'
        and any(item['kind'] == 'CONFIGURATION' for item in data['waiting_items'])
        and not active
    ):
        raise ValueError('Original configuration wait has no current operation')
    actions = []
    for action in data['available_actions']:
        if action['action'] == 'APPLY_CONFIGURATION' and data['status'] not in (
            'PENDING',
            'STOPPING',
            'TERMINATED',
            'COMPLETED',
        ):
            reason = action['reason_code']
            if (
                action['enabled'] != (reason is None)
                or reason
                not in (
                    None,
                    'INVALID_STATE',
                    'OPERATION_IN_PROGRESS',
                    'CONFIG_NOT_READY',
                    'WRITER_ACTIVE',
                )
                or (
                    action['enabled']
                    and (
                        data['status']
                        not in ('VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE')
                        or data['waiting_items']
                        or data['active_operations']
                    )
                )
                or action['related_id'] != (active[0]['id'] if active else None)
            ):
                raise ValueError('Original configuration action differs')
            action = {
                **action,
                'enabled': False,
                'reason_code': 'INVALID_STATE',
                'related_id': None,
            }
        actions.append(action)
    if active:
        application = data['configuration_application']
        if (
            len(active) != 1
            or len(data['active_operations']) != 1
            or active[0]['status'] not in ('RUNNING', 'UNKNOWN')
            or data['status'] != 'WAITING'
            or data['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
            or application is None
            or application['status']
            != ('UNKNOWN' if active[0]['status'] == 'UNKNOWN' else 'PENDING')
            or len(data['waiting_items']) != 1
            or (
                data['waiting_items'][0]['kind'],
                data['waiting_items'][0]['source_kind'],
                data['waiting_items'][0]['source_id'],
            )
            != ('CONFIGURATION', 'OPERATION', active[0]['id'])
        ):
            raise ValueError('Original live configuration task differs')
    return {
        **data,
        'available_actions': actions,
        'active_operations': [] if active else data['active_operations'],
    }
