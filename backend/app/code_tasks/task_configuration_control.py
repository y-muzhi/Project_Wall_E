"""Retained C39 control/native identity; only the native original publisher may dispatch."""

import hashlib
from dataclasses import asdict
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

FIELDS = (
    'mode',
    'operation_id',
    'application_id',
    'step_no',
    'generation',
    'nonce',
    'source_sha256',
    'quiescence_sha256',
    'configuration_sha256',
    'permission_sha256',
)


def _digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


def retained_control_application(operation, application, steps, source):
    raw = steps[2]['external_identity']
    if raw is None:
        return None
    value = strict_json_object(raw)
    native = 'native_read_authorization' in source
    extra = ('target_policy', 'target_permission_sha256', 'session_scope', 'previous_applications')
    identity = exact(value, (*FIELDS, *extra) if native else FIELDS)
    for key in ('operation_id', 'application_id', 'step_no', 'generation'):
        strict_integer(identity[key], key)
    strict_integer(operation['id'], 'operation.id')
    strict_integer(operation['control_generation'], 'operation.control_generation')
    strict_integer(application['id'], 'application.id')
    quiet = strict_json_object(steps[1]['result_ref'])
    if (
        raw != canonical_input(identity)
        or identity['mode'] != ('NATIVE_PERMISSION' if native else 'CONTROL_ONLY')
        or identity['operation_id'] != operation['id']
        or identity['application_id'] != application['id']
        or identity['step_no'] != 3
        or identity['generation'] != operation['control_generation']
        or not _hex(identity['nonce'], 32)
        or any(not _hex(identity[key], 64) for key in FIELDS if key.endswith('_sha256'))
        or steps[1]['status'] != 'SUCCEEDED'
        or steps[2]['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED', 'CANCELLED')
        or identity['source_sha256'] != _digest(source)
        or identity['quiescence_sha256'] != _digest(quiet['proof'])
    ):
        raise StorageUnavailable('Original control application identity differs')
    if native:
        from backend.app.infrastructure.runtime_launch_journal import LaunchScope

        try:
            creation = LaunchScope(**identity['session_scope'])
            previous = [LaunchScope(**row) for row in identity['previous_applications']]
        except (ValueError, TypeError, RuntimeError) as error:
            raise StorageUnavailable('Original native permission scope is invalid') from error
        if (
            not _hex(identity['target_permission_sha256'], 64)
            or creation.step_no not in (1, 4)
            or creation.operation_id == operation['id']
            or type(identity['previous_applications']) is not list
            or len({row.operation_id for row in previous}) != len(previous)
            or any(
                row.controller_ref != creation.controller_ref
                or row.step_no != 3
                or row.operation_id in (creation.operation_id, operation['id'])
                or not _hex(row.nonce, 32)
                for row in previous
            )
        ):
            raise StorageUnavailable('Original native permission scope differs')
    return identity


def reserve_control_application(connection, current, observation, at, *, native_preparation=None):
    from .task_live_configuration import _observe_record, _verified_observation

    _, operation, application, steps, source, _ = current
    if steps[1]['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN') or (
        steps[2]['status'] != 'PENDING'
        or steps[2]['external_identity'] is not None
        or steps[2]['result_ref'] is not None
        or steps[3]['status'] != 'PENDING'
    ):
        raise StorageUnavailable('Original control application preparation differs')
    quiet, _ = _verified_observation(connection, current, observation, at)
    identity = {
        'mode': 'CONTROL_ONLY',
        'operation_id': operation['id'],
        'application_id': application['id'],
        'step_no': 3,
        'generation': operation['control_generation'],
        'nonce': uuid4().hex,
        'source_sha256': _digest(source),
        'quiescence_sha256': _digest(quiet),
        'configuration_sha256': _digest(asdict(observation.configuration)),
        'permission_sha256': observation.permission_sha256,
    }
    if 'native_read_authorization' in source:
        from .authorizations import project_grant
        from .task_configuration_live_records import stored_profile_content
        from .task_instance_driver import NativeConfigurationPreparation
        from .task_native_policy import validate_managed_policy_evidence

        if (
            type(native_preparation) is not NativeConfigurationPreparation
            or native_preparation.observation != observation
            or not _hex(native_preparation.target_permission_sha256, 64)
        ):
            raise TaskExecutionError('ORIGINAL_NATIVE_CONFIGURATION_PREPARATION_REQUIRED')
        profile = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (application['new_profile_version_id'],),
        ).fetchone()
        grant = connection.execute(
            'SELECT * FROM code_authorizations WHERE id=?', (application['authorization_id'],)
        ).fetchone()
        policy = validate_managed_policy_evidence(
            strict_json_object(native_preparation.policy_evidence_json),
            stored_profile_content(profile),
            project_grant(grant)['scope'],
            quiet['workspace'],
            observation.configuration.agent_ref,
        )
        identity.update(
            mode='NATIVE_PERMISSION',
            target_policy=policy,
            target_permission_sha256=native_preparation.target_permission_sha256,
            session_scope=asdict(native_preparation.session_scope),
            previous_applications=[asdict(row) for row in native_preparation.previous_applications],
        )
    elif native_preparation is not None:
        raise TaskExecutionError('ORIGINAL_CONTROL_ONLY_PREPARATION_REQUIRED')
    quiet_id = _observe_record(connection, current, at, result='VERIFIED', proof=quiet)
    completed = connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=coalesce(started_at,?),
           ended_at=?,last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=2
           AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (
            at,
            at,
            at,
            canonical_input({'quiesce_observation_id': quiet_id, 'proof': quiet}),
            operation['id'],
        ),
    )
    state = 'UNKNOWN' if operation['status'] == 'UNKNOWN' else 'RUNNING'
    prepared = connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=?,last_observed_at=?,
           external_identity=? WHERE operation_id=? AND step_no=3 AND status='PENDING'
           AND external_identity IS NULL AND result_ref IS NULL""",
        (state, at, at, canonical_input(identity), operation['id']),
    )
    if completed.rowcount != 1 or prepared.rowcount != 1:
        raise StorageUnavailable('Original control application preparation was fenced')


def verify_control_observation(identity, observation, quiet):
    if (
        identity['quiescence_sha256'] != _digest(quiet)
        or identity['configuration_sha256'] != _digest(asdict(observation.configuration))
        or identity.get('target_permission_sha256', identity['permission_sha256'])
        != observation.permission_sha256
    ):
        raise TaskExecutionError('ORIGINAL_CONTROL_APPLICATION_GROUP_DIFFERS')


def verify_control_result(identity, result):
    if identity is None:
        return
    evidence = result['effective_evidence']
    configuration = {
        'runtime_bundle_ref': evidence['runtime_bundle_ref'],
        'source_sha256': evidence['source_refs'][0][7:],
        'nonsecret_config_sha256': evidence['nonsecret_config_ref'][7:],
        'agent_ref': evidence['role_model_refs']['agent_ref'],
    }
    if (
        result['native_permission_sha256']
        != identity.get('target_permission_sha256', identity['permission_sha256'])
        or _digest(configuration) != identity['configuration_sha256']
        or identity['mode'] == 'NATIVE_PERMISSION'
        and identity['target_policy']['agent'] != configuration['agent_ref']
    ):
        raise StorageUnavailable('Original control application result differs')
