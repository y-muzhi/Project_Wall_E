"""Preserve launch observations and read verified effective control groups."""

from dataclasses import dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_runtime_bundle import is_opencode_runtime_bundle_ref
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_operations import _time


@dataclass(frozen=True)
class InitialConfigurationObservation:
    runtime_bundle_ref: str
    source_sha256: str
    nonsecret_config_sha256: str
    agent_ref: str

    def __post_init__(self):
        if (
            not is_opencode_runtime_bundle_ref(self.runtime_bundle_ref)
            or not _hex(self.source_sha256, 64)
            or not _hex(self.nonsecret_config_sha256, 64)
            or type(self.agent_ref) is not str
            or not self.agent_ref
        ):
            raise ValueError('Original initial configuration observation differs')


@dataclass(frozen=True)
class InitialNativeSession:
    native_id: str
    configuration: InitialConfigurationObservation


def record_initial_configuration(connection, scope, observation, *, at):
    profile = connection.execute(
        'SELECT models FROM code_execution_profile_versions WHERE id=?', (scope.profile_id,)
    ).fetchone()
    instance = connection.execute(
        "SELECT runtime_binding FROM code_instances WHERE id=? AND task_id=? AND status='READY'",
        (scope.instance_id, scope.task_id),
    ).fetchone()
    if (
        type(observation) is not InitialConfigurationObservation
        or profile is None
        or instance is None
        or strict_json_object(instance['runtime_binding'])['manifest_ref']
        != observation.source_sha256
        or connection.execute(
            'SELECT 1 FROM code_configuration_applications WHERE operation_id=?',
            (scope.operation_id,),
        ).fetchone()
        is not None
    ):
        raise StorageUnavailable('Original initial configuration scope differs')
    models = strict_json_object(profile['models'])
    effective = {
        'instance_id': scope.instance_id,
        'control_generation': scope.control_generation,
        'runtime_bundle_ref': observation.runtime_bundle_ref,
        'configuration_policy_version': 'OC20-CONFIG-1',
        'source_refs': ['sha256:' + observation.source_sha256],
        'nonsecret_config_ref': 'sha256:' + observation.nonsecret_config_sha256,
        'role_model_refs': {
            'role': 'BACKEND',
            'agent_ref': observation.agent_ref,
            'primary_profile_ref': models['primary_profile_ref'],
            'auxiliary_profile_refs': models['auxiliary_profile_refs'],
        },
        'observed_at': at,
        'result': 'VERIFIED',
        'difference_kinds': [],
    }
    from .task_configuration_progress import finish_staged_configuration

    if finish_staged_configuration(connection, scope, effective, at):
        return
    connection.execute(
        """INSERT INTO code_configuration_applications(
               id,task_id,new_profile_version_id,authorization_id,operation_id,
               status,created_at,effective_evidence)
           VALUES(?,?,?,?,?,'APPLYING',?,?)""",
        (
            entity_id(connection, EntityKind.TASK_CONFIGURATION_APPLICATION),
            scope.task_id,
            scope.profile_id,
            scope.authorization_id,
            scope.operation_id,
            at,
            canonical_input(effective),
        ),
    )


def current_effective_configuration(connection, task, *, start_scope):
    from .task_configuration_effective import effective_control_application

    applied = effective_control_application(
        connection,
        task,
        instance_id=start_scope.instance_id,
        launch_profile_id=start_scope.profile_id,
    )
    if applied is not None:
        return applied
    row = connection.execute(
        """SELECT a.*,o.operation_type FROM code_configuration_applications a
           JOIN code_operations o ON o.id=a.operation_id AND o.task_id=a.task_id
           WHERE a.task_id=? AND a.new_profile_version_id=? AND a.authorization_id=?
             AND a.status='APPLIED' AND o.status='SUCCEEDED' AND o.control_generation=?
             AND (
                 (o.id=? AND o.operation_type='START')
                 OR (o.operation_type='APPLY_CONFIGURATION' AND EXISTS(
                     SELECT 1 FROM code_operation_steps s WHERE s.operation_id=o.id AND s.step_no=4
                     AND s.status='SUCCEEDED' AND json_extract(s.result_ref,'$.start_operation_id')=?
                 ))
             )
             AND EXISTS(SELECT 1 FROM code_operation_steps s WHERE s.operation_id=? AND s.step_no=4
                AND s.status='SUCCEEDED' AND json_extract(s.result_ref,'$.instance_id')=?)""",
        (
            task['id'],
            task['execution_profile_version_id'],
            task['authorization_id'],
            start_scope.launch_generation,
            start_scope.operation_id,
            start_scope.operation_id,
            start_scope.operation_id,
            start_scope.instance_id,
        ),
    ).fetchone()
    if row is None:
        return None
    evidence = strict_json_object(row['effective_evidence'])
    if (
        evidence['result'] != 'VERIFIED'
        or evidence['instance_id'] != start_scope.instance_id
        or evidence['control_generation'] != start_scope.launch_generation
        or evidence['role_model_refs']['role'] != 'BACKEND'
        or evidence['observed_at']
        != (row['created_at'] if row['operation_type'] == 'START' else row['applied_at'])
        or row['applied_at'] < row['created_at']
    ):
        raise StorageUnavailable('Original applied initial configuration differs')
    if row['operation_type'] == 'APPLY_CONFIGURATION':
        from .task_configuration_progress import (
            public_configuration_operation,
            staged_configuration,
        )

        original = staged_configuration(connection, task['id'])
        if original is None or original['id'] != row['operation_id']:
            raise StorageUnavailable('Original staged configuration is unavailable')
        public_configuration_operation(connection, original)
    return row


def initial_configuration_view(connection, task_id):
    row = connection.execute(
        """SELECT id,status,new_profile_version_id,authorization_id,effective_evidence
           FROM code_configuration_applications WHERE task_id=? ORDER BY created_at DESC,id DESC
           LIMIT 1""",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    effective = (
        None if row['effective_evidence'] is None else strict_json_object(row['effective_evidence'])
    )
    return validate_initial_configuration_view(
        {
            'id': row['id'],
            'status': row['status'],
            'new_profile_version_id': row['new_profile_version_id'],
            'authorization_id': row['authorization_id'],
            'evidence_result': None if effective is None else effective['result'],
            'difference_kinds': [] if effective is None else effective['difference_kinds'],
            'observed_at': None if effective is None else effective['observed_at'],
        }
    )


def validate_initial_configuration_view(data):
    if data is None:
        return None
    value = exact(
        data,
        (
            'id',
            'status',
            'new_profile_version_id',
            'authorization_id',
            'evidence_result',
            'difference_kinds',
            'observed_at',
        ),
    )
    for key in ('id', 'new_profile_version_id', 'authorization_id'):
        strict_integer(value[key], key)
    differences = value['difference_kinds']
    if (
        value['status'] not in ('PENDING', 'APPLYING', 'APPLIED', 'FAILED', 'UNKNOWN')
        or value['evidence_result'] not in (None, 'VERIFIED', 'UNAVAILABLE', 'UNKNOWN')
        or (value['evidence_result'] is None) != (value['observed_at'] is None)
        or (value['status'] == 'APPLIED' and value['evidence_result'] != 'VERIFIED')
        or type(differences) is not list
        or (value['evidence_result'] in (None, 'VERIFIED') and differences)
        or any(
            kind
            not in (
                'SOURCE_SET',
                'PATH_BINDING',
                'EXTENSIONS',
                'DEPENDENCIES',
                'MODEL_ROUTE',
                'PERMISSIONS',
                'PROCESS_BOUNDARY',
            )
            for kind in differences
        )
        or len(set(differences)) != len(differences)
    ):
        raise ValueError('Original configuration projection differs')
    _time(value['observed_at'])
    return value
