"""Apply one original C39 control pair after independently observed native quiescence."""

import hashlib
import json
from datetime import datetime, timedelta

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .authorizations import project_grant
from .coding_check_plan import CodingCheckPlanError
from .task_basis import TaskBasisUnavailable
from .task_configuration_effective import supported_live_changes
from .task_configuration_live_records import (
    live_configuration_records,
    public_live_configuration_operation,
)
from .task_initial_configuration import InitialConfigurationObservation
from .task_instance_driver import CaptureTurnEvidence, ControlConfigurationObservation
from .task_model_ingress import ModelWindow
from .task_start_session import original_active_session_scope

_OBSERVE_RECHECK_SECONDS = 2


def supported_configuration_pair(connection, task, before, after, authorization_id):
    previous = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
        (task['authorization_id'], task['id']),
    ).fetchone()
    following = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?',
        (authorization_id,),
    ).fetchone()
    if previous is None or following is None or previous['status'] != 'EFFECTIVE':
        return False
    return supported_live_changes(
        before, after, project_grant(previous)['scope'], project_grant(following)['scope']
    )


def idle_configuration_source(connection, task):
    from .task_capture_quiescence import _unsettled_inputs

    published = task['status'] in ('AWAITING_TESTING', 'AWAITING_ACCEPTANCE')
    if published:
        if task['current_delivery_id'] is not None:
            return None
        from .task_testing_publication import published_check_task

        task = published_check_task(connection, task, for_read=True)
    if task['status'] != 'VERIFYING' or task['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION'):
        return None
    from .task_capture_quiescence import current_capture_owner

    session, scope, window, _ = current_capture_owner(connection, task)
    if (
        window.get('state') != 'CLOSED'
        or window.get('closed_at') is None
        or _unsettled_inputs(connection, task['id'], 0, session['instance_id'])
    ):
        return None
    instance = connection.execute(
        'SELECT * FROM code_instances WHERE id=?', (scope.instance_id,)
    ).fetchone()
    if (
        instance is None
        or instance['status'] != 'READY'
        or not instance['runtime_binding']
        or not instance['process_identity']
    ):
        return None
    publication = {}
    if published:
        from .task_testing_publication import read_current_publication

        publication['publication_operation_id'] = read_current_publication(connection, task)['id']
        publication['published_candidate_id'] = task['current_candidate_id']
    return {
        **publication,
        'start_operation_id': scope.operation_id,
        'instance_id': scope.instance_id,
        'launch_profile_id': scope.profile_id,
        'old_profile_version_id': task['execution_profile_version_id'],
        'old_authorization_id': task['authorization_id'],
        'workspace_id': task['workspace_id'],
        'session_id': session['id'],
        'native_session_id': session['native_session_id'],
        'credential_ref': session['gateway_credential_ref'],
        'generation': task['control_generation'],
        'role': session['role'],
        'model_window': window,
        'guard_receipt_sha256': strict_json_object(instance['process_identity'])['ownership_ref'],
        'runtime_binding_ref': strict_json_object(instance['runtime_binding'])['guard_run_ref'],
    }


def reserve_live_configuration(connection, task, request, source):
    from .task_configuration_apply import STEPS, TYPE

    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    application = entity_id(connection, EntityKind.TASK_CONFIGURATION_APPLICATION)
    waiting = entity_id(connection, EntityKind.WAITING_ITEM)
    at = max(operation_time(None), task['updated_at'])
    fixed = canonical_input(request.business_input())
    source = {**source, 'application_id': application}
    version = increment(task['state_version'])
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
           operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,
           status,created_at,started_at) VALUES(?,?,'TASK',?,?,?,?,?,?,?,'RUNNING',?,?)""",
        (
            identity,
            task['id'],
            task['id'],
            source['session_id'],
            TYPE,
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
            at,
        ),
    )
    for number, kind in enumerate(STEPS, 1):
        connection.execute(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
               external_identity,result_ref,started_at,ended_at,last_observed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                identity,
                number,
                kind,
                'SUCCEEDED' if number == 1 else 'PENDING',
                fixed,
                canonical_input({'source': source}) if number == 1 else None,
                canonical_input({'state_version': version}) if number == 1 else None,
                at if number == 1 else None,
                at if number == 1 else None,
                at if number == 1 else None,
            ),
        )
    changed = connection.execute(
        """UPDATE code_authorizations SET task_id=?,status='BOUND_PENDING_APPLY'
           WHERE id=? AND task_id IS NULL AND status='APPROVED_UNBOUND'""",
        (task['id'], request.authorization_id),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original control authorization binding changed')
    connection.execute(
        """INSERT INTO code_configuration_applications(id,task_id,old_profile_version_id,
           new_profile_version_id,authorization_id,operation_id,status,created_at)
           VALUES(?,?,?,?,?,?,'PENDING',?)""",
        (
            application,
            task['id'],
            task['execution_profile_version_id'],
            request.execution_profile_version_id,
            request.authorization_id,
            identity,
            at,
        ),
    )
    changed = connection.execute(
        """UPDATE code_tasks SET status='WAITING',phase=?,resume_phase=?,state_version=?,updated_at=?
           WHERE id=? AND state_version=? AND status=? AND phase=? AND stop_requested_at IS NULL""",
        (
            source['role'],
            source['role'],
            version,
            at,
            task['id'],
            task['state_version'],
            task['status'],
            task['phase'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original live configuration was fenced')
    connection.execute(
        """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,
           status,created_at) VALUES(?,?,'CONFIGURATION','OPERATION',?,?,'OPEN',?)""",
        (waiting, task['id'], identity, source['role'], at),
    )
    receipt = {
        'task_id': task['id'],
        'operation_id': identity,
        'operation_status': 'RUNNING',
        'task_status': 'WAITING',
        'state_version': version,
    }
    return Success({'code': 'OPERATION_ACCEPTED', 'data': receipt, 'details': None}, 202)


def _current(connection, identity):
    operation = connection.execute(
        "SELECT * FROM code_operations WHERE id=? AND operation_type='APPLY_CONFIGURATION' AND session_id IS NOT NULL AND status IN ('RUNNING','UNKNOWN')",
        (identity,),
    ).fetchone()
    if operation is None:
        return None
    _, application, steps, source = live_configuration_records(connection, operation)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (source['session_id'], operation['task_id']),
    ).fetchone()
    if (
        task is None
        or session is None
        or task['stop_requested_at'] is not None
        or (
            'published_candidate_id' in source
            and task['current_candidate_id'] != source['published_candidate_id']
        )
        or task['status'] != 'WAITING'
        or task['phase'] != source['role']
        or task['resume_phase'] != source['role']
        or task['active_session_id'] != source['session_id']
        or task['control_generation'] != source['generation']
        or task['execution_profile_version_id'] != source['old_profile_version_id']
        or task['authorization_id'] != source['old_authorization_id']
        or task['state_version'] <= operation['expected_state_version']
        or session['model_window'] != canonical_input(source['model_window'])
        or session['native_session_id'] != source['native_session_id']
        or session['gateway_credential_ref'] != source['credential_ref']
    ):
        return None
    waits = connection.execute(
        "SELECT kind,source_kind,source_id FROM code_waiting_items WHERE task_id=? AND status='OPEN'",
        (task['id'],),
    ).fetchall()
    if len(waits) != 1 or tuple(waits[0]) != ('CONFIGURATION', 'OPERATION', identity):
        raise StorageUnavailable('Original configuration waiting scope differs')
    scope = original_active_session_scope(connection, task, session)
    if (
        scope.operation_id != source['start_operation_id']
        or scope.profile_id != source['launch_profile_id']
    ):
        raise StorageUnavailable('Original configuration native owner differs')
    return task, operation, application, steps, source, scope


def _verified_observation(connection, current, observation, at):
    from backend.app.infrastructure.guard_task_basis_protocol import _hex

    task, _, application, _, source, scope = current
    if (
        type(observation) is not ControlConfigurationObservation
        or type(observation.quiescence) is not CaptureTurnEvidence
        or type(observation.configuration) is not InitialConfigurationObservation
        or not _hex(observation.permission_sha256, 64)
    ):
        raise TaskExecutionError('ORIGINAL_CONTROL_CONFIGURATION_OBSERVATION_REQUIRED')
    quiet = observation.quiescence.scope_proof()
    _identifier(quiet['turn']['assistant_message_id'], 'msg')
    if (
        type(quiet['active_process_count']) is not int
        or quiet['workspace']['filesystem'] != 'NTFS'
        or quiet['workspace']['is_directory'] is not True
    ):
        raise TaskExecutionError('ORIGINAL_CONTROL_WORKSPACE_UNVERIFIED')
    configuration = observation.configuration
    turn = quiet['turn']
    instance = connection.execute(
        'SELECT * FROM code_instances WHERE id=? AND task_id=?', (source['instance_id'], task['id'])
    ).fetchone()
    if (
        turn['session_id'] != source['native_session_id']
        or turn['trigger_message_id'] != source['model_window']['native_trigger_message_id']
        or turn['outcome'] not in ('COMPLETED', 'CANCELLED')
        or quiet['guard_receipt_sha256'] != source['guard_receipt_sha256']
        or quiet['active_process_count'] != 1
        or instance is None
        or instance['status'] != 'READY'
        or strict_json_object(instance['runtime_binding'])['guard_run_ref']
        != source['runtime_binding_ref']
        or strict_json_object(instance['runtime_binding'])['manifest_ref']
        != configuration.source_sha256
        or strict_json_object(instance['process_identity'])['ownership_ref']
        != source['guard_receipt_sha256']
    ):
        raise TaskExecutionError('ORIGINAL_CONTROL_CONFIGURATION_SOURCE_DIFFERS')
    profile = connection.execute(
        'SELECT models FROM code_execution_profile_versions WHERE id=?',
        (application['new_profile_version_id'],),
    ).fetchone()
    models = strict_json_object(profile['models'])
    target_profile = connection.execute(
        'SELECT executor FROM code_execution_profile_versions WHERE id=?',
        (application['new_profile_version_id'],),
    ).fetchone()
    if (
        configuration.runtime_bundle_ref
        != strict_json_object(target_profile['executor'])['runtime_bundle_ref']
    ):
        raise TaskExecutionError('ORIGINAL_CONTROL_RUNTIME_BUNDLE_DIFFERS')
    effective = {
        'instance_id': scope.instance_id,
        'control_generation': source['generation'],
        'runtime_bundle_ref': configuration.runtime_bundle_ref,
        'configuration_policy_version': 'OC20-CONFIG-1',
        'source_refs': ['sha256:' + configuration.source_sha256],
        'nonsecret_config_ref': 'sha256:' + configuration.nonsecret_config_sha256,
        'role_model_refs': {
            'role': source['role'],
            'agent_ref': configuration.agent_ref,
            'primary_profile_ref': models['primary_profile_ref'],
            'auxiliary_profile_refs': models['auxiliary_profile_refs'],
        },
        'observed_at': at,
        'result': 'VERIFIED',
        'difference_kinds': [],
    }
    return quiet, effective


def _observe_record(connection, current, at, *, result, proof=None):
    task, operation, _, _, source, _ = current
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    digest = hashlib.sha256(
        canonical_input(proof if proof is not None else source).encode()
    ).hexdigest()
    step = 2 if proof is not None else 1
    connection.execute(
        """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,control_generation,
           runtime_binding_ref,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,'QUIESCE',?,?,?,?,?)""",
        (
            identity,
            task['id'],
            source['instance_id'],
            operation['id'],
            source['generation'],
            source['runtime_binding_ref'],
            result,
            '[]'
            if proof is not None
            else json.dumps(['EXTERNAL_RESULT_UNKNOWN'], separators=(',', ':')),
            1 if proof is not None else None,
            at,
            f'sqlite:code_operation_steps/{operation["id"]}/{step}#sha256={digest}',
        ),
    )
    return identity


def _control_stage(current):
    steps = current[3]
    if steps[1]['status'] != 'SUCCEEDED':
        return 2
    if steps[2]['status'] != 'SUCCEEDED':
        return 3
    return 4


def _unknown(connection, current, at):
    _, operation, application, _, _, _ = current
    stage = _control_stage(current)
    if stage == 2:
        _observe_record(connection, current, at, result='UNKNOWN')
    connection.execute(
        "UPDATE code_operation_steps SET status='UNKNOWN',started_at=coalesce(started_at,?),last_observed_at=? WHERE operation_id=? AND step_no=? AND status IN ('PENDING','RUNNING','UNKNOWN')",
        (at, at, operation['id'], stage),
    )
    connection.execute(
        "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
        (operation['id'],),
    )
    connection.execute(
        "UPDATE code_configuration_applications SET status='UNKNOWN' WHERE id=?",
        (application['id'],),
    )
    connection.execute(
        "UPDATE code_authorizations SET status='APPLY_UNKNOWN' WHERE id=? AND status IN ('BOUND_PENDING_APPLY','APPLY_UNKNOWN')",
        (application['authorization_id'],),
    )


def _validate_control_target(connection, current, *, catalog, check_admissions):
    task, _, application, _, source, _ = current
    if 'model_authorization' in source:
        from .task_configuration_models import compile_model_authorization

        profile = connection.execute(
            'SELECT models FROM code_execution_profile_versions WHERE id=?',
            (application['new_profile_version_id'],),
        ).fetchone()
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (application['authorization_id'],)
            ).fetchone()
        )
        compiled = compile_model_authorization(
            connection, task['id'], strict_json_object(profile['models']), grant['scope']
        )
        if canonical_input(compiled) != canonical_input(source['model_authorization']):
            raise TaskExecutionError('ORIGINAL_MODEL_AUTHORIZATION_COMPILATION_DIFFERS')
    if 'delivery_authorization' in source:
        from .task_configuration_delivery import compile_delivery_authorization

        profile = connection.execute(
            'SELECT delivery FROM code_execution_profile_versions WHERE id=?',
            (application['new_profile_version_id'],),
        ).fetchone()
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (application['authorization_id'],)
            ).fetchone()
        )
        delivery = None if profile['delivery'] is None else strict_json_object(profile['delivery'])
        compiled = compile_delivery_authorization(connection, task['id'], delivery, grant['scope'])
        if canonical_input(compiled) != canonical_input(source['delivery_authorization']):
            raise TaskExecutionError('ORIGINAL_DELIVERY_AUTHORIZATION_COMPILATION_DIFFERS')
    if 'check_configuration' in source:
        from .task_configuration_checks import observe_check_configuration

        latest_checks = observe_check_configuration(
            connection,
            catalog,
            task,
            application['new_profile_version_id'],
            application['authorization_id'],
            check_admissions,
            include_output='max_output_bytes' in source['check_configuration'],
        )
        if latest_checks != source['check_configuration']:
            raise TaskExecutionError('ORIGINAL_CHECK_CONFIGURATION_ADMISSION_DIFFERS')


def _adopt(connection, current, observation, at, *, catalog, check_admissions):
    task, operation, application, steps, source, _ = current
    if (
        steps[2]['status'] != 'SUCCEEDED'
        or strict_json_object(steps[2]['result_ref'])
        != {'configuration_application_id': application['id']}
        or steps[3]['status'] not in ('RUNNING', 'UNKNOWN')
    ):
        raise StorageUnavailable('Original effective control preparation differs')
    _validate_control_target(
        connection, current, catalog=catalog, check_admissions=check_admissions
    )
    quiet, effective = _verified_observation(connection, current, observation, at)
    from .task_configuration_control import (
        retained_control_application,
        verify_control_observation,
    )

    identity = retained_control_application(operation, application, steps, source)
    if identity is None:
        raise StorageUnavailable('Original control application identity is required')
    verify_control_observation(identity, observation, quiet)
    results = {
        4: {
            'configuration_application_id': application['id'],
            'start_operation_id': source['start_operation_id'],
            'effective_evidence': effective,
            'native_permission_sha256': observation.permission_sha256,
        },
    }
    for number, result in results.items():
        connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=coalesce(started_at,?),
               ended_at=?,last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=?""",
            (at, at, at, canonical_input(result), operation['id'], number),
        )
    new_grant = connection.execute(
        "UPDATE code_authorizations SET status='EFFECTIVE' WHERE id=? AND task_id=? AND status IN ('BOUND_PENDING_APPLY','APPLY_UNKNOWN')",
        (application['authorization_id'], task['id']),
    )
    old_grant = connection.execute(
        "UPDATE code_authorizations SET status='RETIRED' WHERE id=? AND task_id=? AND status='EFFECTIVE'",
        (source['old_authorization_id'], task['id']),
    )
    adopted = connection.execute(
        """UPDATE code_tasks SET execution_profile_version_id=?,authorization_id=?,status='VERIFYING',
           resume_phase=NULL,state_version=?,updated_at=?,last_observed_at=?,current_test_report_id=NULL,current_delivery_plan_id=NULL
           WHERE id=? AND state_version=? AND status='WAITING' AND stop_requested_at IS NULL""",
        (
            application['new_profile_version_id'],
            application['authorization_id'],
            increment(task['state_version']),
            at,
            at,
            task['id'],
            task['state_version'],
        ),
    )
    if new_grant.rowcount != 1 or old_grant.rowcount != 1 or adopted.rowcount != 1:
        raise StorageUnavailable('Original verified control adoption was fenced')
    connection.execute(
        "UPDATE code_configuration_applications SET status='APPLIED',applied_at=?,effective_evidence=? WHERE id=?",
        (at, canonical_input(effective), application['id']),
    )
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',failure_code=NULL,ended_at=? WHERE id=?",
        (at, operation['id']),
    )
    connection.execute(
        """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE task_id=? AND source_kind='OPERATION' AND source_id=? AND kind='CONFIGURATION' AND status='OPEN'""",
        (
            at,
            canonical_input({'operation_id': operation['id'], 'outcome': 'CONFIGURATION_APPLIED'}),
            task['id'],
            operation['id'],
        ),
    )


def _prepare_effective_control(connection, current, observation, at, *, catalog, check_admissions):
    from .task_configuration_control import (
        retained_control_application,
        verify_control_observation,
    )

    _, operation, application, steps, source, _ = current
    identity = retained_control_application(operation, application, steps, source)
    if (
        identity is None
        or steps[2]['status'] not in ('RUNNING', 'UNKNOWN')
        or steps[3]['status'] != 'PENDING'
    ):
        raise StorageUnavailable('Original control verification preparation differs')
    _validate_control_target(
        connection, current, catalog=catalog, check_admissions=check_admissions
    )
    quiet, _ = _verified_observation(connection, current, observation, at)
    verify_control_observation(identity, observation, quiet)
    prepared = connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=?,
           result_ref=? WHERE operation_id=? AND step_no=3 AND status IN ('RUNNING','UNKNOWN')""",
        (
            at,
            at,
            canonical_input({'configuration_application_id': application['id']}),
            operation['id'],
        ),
    )
    state = 'UNKNOWN' if operation['status'] == 'UNKNOWN' else 'RUNNING'
    verifying = connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=4 AND status='PENDING' AND result_ref IS NULL""",
        (state, at, at, operation['id']),
    )
    if prepared.rowcount != 1 or verifying.rowcount != 1:
        raise StorageUnavailable('Original effective control preparation was fenced')


def _observe_control(
    runtime, driver, current, cancelled, *, native_dispatch=False, check_admissions=()
):
    identity = current[1]['id']

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_CONFIGURATION_CANCELLED')
        with runtime.database.transaction() as connection:
            if _current(connection, identity) != current:
                raise TaskExecutionError('ORIGINAL_CONFIGURATION_FENCED')

    source = current[4]
    window = ModelWindow(
        current[0]['id'],
        source['instance_id'],
        source['generation'],
        source['session_id'],
        source['native_session_id'],
        source['model_window']['operation_id'],
        source['model_window']['native_trigger_message_id'],
    )
    from .task_native_policy import NativePolicyCompilationError

    try:
        checkpoint()
        if 'native_read_authorization' in source:
            from .task_configuration_control import retained_control_application
            from .task_configuration_live_records import stored_profile_content

            with runtime.database.transaction() as connection:
                if _control_stage(current) == 2 or native_dispatch:
                    _validate_control_target(
                        connection,
                        current,
                        catalog=runtime.catalog,
                        check_admissions=check_admissions,
                    )
                profile = connection.execute(
                    'SELECT * FROM code_execution_profile_versions WHERE id=?',
                    (current[2]['new_profile_version_id'],),
                ).fetchone()
                grant = connection.execute(
                    'SELECT * FROM code_authorizations WHERE id=?',
                    (current[2]['authorization_id'],),
                ).fetchone()
                content = stored_profile_content(profile)
                target_scope = project_grant(grant)['scope']
            if _control_stage(current) == 2:
                return driver.prepare_native_configuration(
                    current[5], window, source['credential_ref'], content, target_scope, checkpoint
                )
            application_identity = retained_control_application(
                current[1], current[2], current[3], source
            )
            return driver.apply_native_configuration(
                current[5],
                window,
                source['credential_ref'],
                content,
                target_scope,
                application_identity,
                checkpoint,
                dispatch=native_dispatch,
            )
        return driver.observe_control_configuration(
            current[5], window, source['credential_ref'], checkpoint
        )
    except (
        TaskExecutionError,
        LaunchOutcomeUnknown,
        OSError,
        NativePolicyCompilationError,
        ConfigInvalid,
        CodingCheckPlanError,
        TaskBasisUnavailable,
    ):
        return None


def _control_observation_time(current):
    task, operation, _, steps, _, _ = current
    recorded = (
        step[field]
        for step in steps
        for field in ('started_at', 'ended_at', 'last_observed_at')
        if step[field] is not None
    )
    return max(operation_time(None), task['updated_at'], operation['created_at'], *recorded)


def advance_live_configuration(runtime, driver, *, cancelled, check_admissions=()):
    from .task_configuration_control import reserve_control_application
    from .task_native_policy import NativePolicyCompilationError

    if cancelled():
        return False
    runtime.commands().process_lock.assert_owned()
    before = (
        (datetime.fromisoformat(operation_time(None)) - timedelta(seconds=_OBSERVE_RECHECK_SECONDS))
        .isoformat(timespec='milliseconds')
        .replace('+00:00', 'Z')
    )
    with runtime.database.transaction() as connection:
        row = connection.execute(
            """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               JOIN code_operation_steps q ON q.operation_id=o.id AND q.step_no=2
               JOIN code_operation_steps a ON a.operation_id=o.id AND a.step_no=3
               JOIN code_operation_steps s ON s.operation_id=o.id
                 AND s.step_no=CASE WHEN q.status<>'SUCCEEDED' THEN 2
                     WHEN a.status='SUCCEEDED' THEN 4 ELSE 3 END
               WHERE o.operation_type='APPLY_CONFIGURATION' AND o.session_id IS NOT NULL
               AND o.status IN ('RUNNING','UNKNOWN') AND t.status='WAITING' AND t.stop_requested_at IS NULL
               AND s.status IN ('PENDING','RUNNING','UNKNOWN')
               AND (s.step_no=2 OR (s.status IN ('RUNNING','UNKNOWN')
                    AND json_extract(a.external_identity,'$.mode') IN ('CONTROL_ONLY','NATIVE_PERMISSION')))
               AND (s.last_observed_at IS NULL OR s.last_observed_at<=?) ORDER BY o.id LIMIT 1""",
            (before,),
        ).fetchone()
        if row is None:
            return False
        current = _current(connection, row['id'])
        if current is None:
            return False
    identity = row['id']
    native_dispatch = False
    # Each successful phase is committed before observing its successor.
    # Retained application/verification phases never acquire a native send slot.
    for _ in range(3):
        from .task_instance_driver import NativeConfigurationPreparation

        observation = _observe_control(
            runtime,
            driver,
            current,
            cancelled,
            native_dispatch=native_dispatch,
            check_admissions=check_admissions,
        )
        native_dispatch = False
        native_preparation = (
            observation if type(observation) is NativeConfigurationPreparation else None
        )
        if native_preparation is not None:
            observation = native_preparation.observation
        if cancelled():
            return False
        with runtime.database.transaction(write=True) as connection:
            if _current(connection, identity) != current:
                return False
            at = _control_observation_time(current)
            if observation is None:
                _unknown(connection, current, at)
                return True
            stage = _control_stage(current)
            try:
                if stage == 2:
                    reserve_control_application(
                        connection, current, observation, at, native_preparation=native_preparation
                    )
                elif stage == 3:
                    _prepare_effective_control(
                        connection,
                        current,
                        observation,
                        at,
                        catalog=runtime.catalog,
                        check_admissions=check_admissions,
                    )
                else:
                    _adopt(
                        connection,
                        current,
                        observation,
                        at,
                        catalog=runtime.catalog,
                        check_admissions=check_admissions,
                    )
            except (
                TaskExecutionError,
                CodingCheckPlanError,
                ConfigInvalid,
                TaskBasisUnavailable,
                NativePolicyCompilationError,
            ):
                _unknown(connection, current, at)
                return True
        if stage == 4:
            return True
        if stage == 2 and native_preparation is not None:
            # Only this successful reservation turn may attempt the original publisher.
            # A later turn, including a missing private intent, reconciles read-only.
            native_dispatch = True
        with runtime.database.transaction() as connection:
            current = _current(connection, identity)
            if current is None:
                return True
    raise StorageUnavailable('Original control application stage did not complete')


def interrupt_live_configurations(connection, task_id, at):
    rows = connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION' AND session_id IS NOT NULL AND status IN ('RUNNING','UNKNOWN')",
        (task_id,),
    ).fetchall()
    for operation in rows:
        _, application, _, _ = live_configuration_records(connection, operation)
        connection.execute(
            """UPDATE code_operation_steps SET status='CANCELLED',started_at=coalesce(started_at,?),
               ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no>1 AND status<>'SUCCEEDED'""",
            (at, at, at, operation['id']),
        )
        connection.execute(
            "UPDATE code_operations SET status='CANCELLED',failure_code='TASK_ENDED',ended_at=? WHERE id=?",
            (at, operation['id']),
        )
        connection.execute(
            "UPDATE code_configuration_applications SET status='FAILED' WHERE id=?",
            (application['id'],),
        )
        connection.execute(
            "UPDATE code_authorizations SET status='APPLY_FAILED' WHERE id=?",
            (application['authorization_id'],),
        )


def project_live_configuration_activity(connection, task, data, ready):
    if task['status'] == 'PENDING':
        return
    active = connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION' AND session_id IS NOT NULL AND status IN ('RUNNING','UNKNOWN') ORDER BY id LIMIT 2",
        (task['id'],),
    ).fetchall()
    if len(active) > 1:
        raise StorageUnavailable('More than one original live configuration is active')
    related = None
    if active and task['status'] == 'WAITING':
        public_live_configuration_operation(connection, active[0])
        if data['active_operations']:
            raise StorageUnavailable('Original live configuration conflicts with another operation')
        related = active[0]['id']
        data['active_operations'] = [
            {key: active[0][key] for key in ('id', 'operation_type', 'status')}
        ]
        reason = 'OPERATION_IN_PROGRESS'
    elif data['active_operations']:
        reason = 'OPERATION_IN_PROGRESS'
    elif task['status'] in ('VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE') and not active:
        try:
            source = idle_configuration_source(connection, task)
        except TaskExecutionError:
            source = None
        reason = 'WRITER_ACTIVE' if source is None else None if ready else 'CONFIG_NOT_READY'
    else:
        reason = 'INVALID_STATE'
    if task['status'] not in ('STOPPING', 'TERMINATED', 'COMPLETED'):
        for action in data['available_actions']:
            if action['action'] == 'APPLY_CONFIGURATION':
                action.update(enabled=reason is None, reason_code=reason, related_id=related)
