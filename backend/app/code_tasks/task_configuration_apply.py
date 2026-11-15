"""Admit original C39 preparation or verified same-session control configuration."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    reject,
    strict_integer,
    text_value,
)

from .authorization_scope import profile_scope_error, resource_scope_error
from .authorizations import project_grant
from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .execution_profile_resources import reference_error
from .execution_profile_versions import _project as project_profile
from .operation_protocol import operation_steps
from .task_configuration_effective import fixed_content_changed

PATH = '/api/v1/code-tasks/{task_id}/configuration'
CAPABILITY = 'APP-CODE-CMD-C39'
TYPE = 'APPLY_CONFIGURATION'
STEPS = operation_steps('CODING', TYPE)
BODY = ('expected_state_version', 'execution_profile_version_id', 'authorization_id', 'reason')
RECEIPT = ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
configuration_apply_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class ApplyConfigurationRequest:
    task_id: int
    expected_state_version: int
    execution_profile_version_id: int
    authorization_id: int
    reason: str
    command: RegisteredCommand
    ready: bool = False
    check_admissions: tuple = ()
    native_ready: bool = False
    body_fields = BODY

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'task_id': self.task_id, **{field: getattr(self, field) for field in BODY}}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fields = object_fields(body, 'body', BODY, BODY)
        reason = text_value(fields['reason'], 'reason')
        if not reason.strip():
            reject('reason', 'TOO_SHORT', '配置应用说明必须为非空文本')
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        return cls(
            task_id,
            *(strict_integer(fields[key], key) for key in BODY[:-1]),
            reason,
            registered_command(
                'POST', PATH.format(task_id=task_id), idempotency_header(request, lowercase=True)
            ),
            bool(worker is not None and getattr(worker, 'accepts_live_configuration', False)),
            getattr(worker, 'project_check_admissions', ()),
            bool(
                worker is not None and getattr(worker, 'accepts_native_permission_updates', False)
            ),
        )


def configuration_receipt(command, value, status):
    data = exact(value, RECEIPT)
    for key in ('task_id', 'operation_id', 'state_version'):
        strict_integer(data[key], key)
    if (
        status != 202
        or data['task_id'] != command.route.match(command.path)['task_id']
        or data['task_status'] not in ('PENDING', 'WAITING')
        or data['operation_status'] != 'RUNNING'
    ):
        raise ValueError('Original configuration receipt differs')
    return data


def _authorize_pair(connection, catalog, task, request):
    old = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    target = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (request.execution_profile_version_id,),
    ).fetchone()
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (request.authorization_id,)
    ).fetchone()
    if target is None or grant_row is None:
        return Rejection('NOT_FOUND', None)
    if old is None:
        raise StorageUnavailable('Original configured profile is missing')
    grant = project_grant(grant_row)
    denied = Rejection(
        'AUTHORIZATION_NOT_APPLICABLE',
        {'task_id': task['id'], 'authorization_id': request.authorization_id},
    )
    if (
        grant['profile_version_id'] != target['id']
        or grant['task_id'] is not None
        or grant['status'] != 'APPROVED_UNBOUND'
    ):
        return denied
    snapshots = {}
    try:
        previous = project_profile(old, connection, catalog, snapshots)
        profile = project_profile(target, connection, catalog, snapshots)
        resources = snapshots['execution']
        if reference_error(connection, profile, resources) is not None:
            raise ConfigurationNotReady('Q20-CONFIG')
        if profile_scope_error(grant['scope'], profile) or resource_scope_error(
            grant['scope'], resources
        ):
            return denied
    except ConfigInvalid as error:
        raise ConfigurationNotReady('Q20-CONFIG') from error
    return previous, profile, grant['scope']


def _reserve_pair(connection, task, request):
    from .task_start import start_conflict

    if task['state_version'] >= MAX_SAFE_INTEGER - 3:
        return start_conflict('PRECONDITION_FAILED', task)
    if connection.execute(
        'SELECT 1 FROM sequences WHERE entity_kind IN (?,?) AND last_value=? LIMIT 1',
        (
            EntityKind.OPERATION_RECORD.value,
            EntityKind.TASK_CONFIGURATION_APPLICATION.value,
            MAX_SAFE_INTEGER,
        ),
    ).fetchone():
        return start_conflict('PRECONDITION_FAILED', task)
    operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
    application_id = entity_id(connection, EntityKind.TASK_CONFIGURATION_APPLICATION)
    at = max(operation_time(None), task['updated_at'])
    version = task['state_version'] + 1
    fixed = canonical_input(request.business_input())
    receipt = {
        'task_id': task['id'],
        'operation_id': operation_id,
        'operation_status': 'RUNNING',
        'task_status': 'PENDING',
        'state_version': version,
    }
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,'RUNNING',?,?)""",
        (
            operation_id,
            task['id'],
            task['id'],
            TYPE,
            request.command.key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
            at,
        ),
    )
    steps = (
        {'state_version': version},
        {'scope': 'NO_INSTANCE'},
        {'configuration_application_id': application_id},
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
           started_at,ended_at,last_observed_at,result_ref) VALUES(?,?,?,?,?,?,?,?,?)""",
        [
            (
                operation_id,
                number,
                name,
                'SUCCEEDED' if result is not None else 'PENDING',
                fixed,
                at if result is not None else None,
                at if result is not None else None,
                at if result is not None else None,
                canonical_input(result) if result is not None else None,
            )
            for number, (name, result) in enumerate(zip(STEPS, (*steps, None), strict=True), 1)
        ],
    )
    bound = connection.execute(
        """UPDATE code_authorizations SET task_id=?,status='BOUND_PENDING_APPLY'
           WHERE id=? AND task_id IS NULL AND status='APPROVED_UNBOUND' AND profile_version_id=?""",
        (task['id'], request.authorization_id, request.execution_profile_version_id),
    )
    retired = connection.execute(
        """UPDATE code_authorizations SET status='RETIRED'
           WHERE id=? AND task_id=? AND status='BOUND_PENDING_APPLY' AND profile_version_id=?""",
        (task['authorization_id'], task['id'], task['execution_profile_version_id']),
    )
    if bound.rowcount != 1 or retired.rowcount != 1:
        raise StorageUnavailable('Original unstarted configuration approval changed')
    connection.execute(
        """INSERT INTO code_configuration_applications(id,task_id,old_profile_version_id,
           new_profile_version_id,authorization_id,operation_id,status,created_at)
           VALUES(?,?,?,?,?,?,'PENDING',?)""",
        (
            application_id,
            task['id'],
            task['execution_profile_version_id'],
            request.execution_profile_version_id,
            request.authorization_id,
            operation_id,
            at,
        ),
    )
    updated = connection.execute(
        """UPDATE code_tasks SET execution_profile_version_id=?,authorization_id=?,state_version=?,updated_at=?
           WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL
           AND status='PENDING' AND phase='PREPARING' AND active_session_id IS NULL""",
        (
            request.execution_profile_version_id,
            request.authorization_id,
            version,
            at,
            task['id'],
            task['state_version'],
            task['control_generation'],
        ),
    )
    if updated.rowcount != 1:
        raise StorageUnavailable('Original unstarted configuration task changed')
    return Success({'code': 'OPERATION_ACCEPTED', 'data': receipt, 'details': None}, 202)


def accept_configuration(runtime, request):
    from .task_start import start_conflict
    from .task_stop import EXECUTION_TABLES, NO_ACTIVITY_FIELDS

    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['status'] == 'STOPPING' or task['stop_requested_at'] is not None:
            return start_conflict('INVALID_STATE', task)
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        previous = connection.execute(
            """SELECT id FROM code_operations WHERE task_id=?
               AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id LIMIT 1""",
            (task['id'],),
        ).fetchone()
        if previous is not None:
            return start_conflict('OPERATION_CONFLICT', task, previous['id'])
        pair = _authorize_pair(connection, runtime.catalog, task, request)
        if isinstance(pair, Rejection):
            return pair
        before, after, next_scope = pair
        if before['git'] != after['git'] or fixed_content_changed(before, after):
            return start_conflict('PRECONDITION_FAILED', task)
        if task['status'] != 'PENDING' or task['phase'] != 'PREPARING':
            if any(before[key] != after[key] for key in ('executor', 'models', 'environment')):
                return start_conflict('PRECONDITION_FAILED', task)
            from .task_live_configuration import (
                idle_configuration_source,
                reserve_live_configuration,
                supported_configuration_pair,
            )

            if not supported_configuration_pair(
                connection, task, before, after, request.authorization_id
            ):
                raise ConfigurationNotReady('Q20-CONFIG', 'Q20-OC')
            if task['state_version'] >= MAX_SAFE_INTEGER - 3:
                return start_conflict('PRECONDITION_FAILED', task)
            source = idle_configuration_source(connection, task)
            if source is None or not request.ready:
                raise ConfigurationNotReady('Q20-CONFIG', 'Q20-OC')
            from .task_configuration_checks import check_configuration_changes

            previous_grant = connection.execute(
                'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
                (task['authorization_id'], task['id']),
            ).fetchone()
            previous_scope = project_grant(previous_grant)['scope']
            if previous_scope['read_roots'] != next_scope['read_roots']:
                from .task_configuration_native import (
                    NativeReadAuthorizationError,
                    compile_native_read_authorization,
                )

                if not request.native_ready:
                    raise ConfigurationNotReady('Q20-CONFIG', 'Q20-WINDOWS')
                try:
                    source['native_read_authorization'] = compile_native_read_authorization(
                        connection, task['id'], previous_scope, next_scope
                    )
                except NativeReadAuthorizationError:
                    return Rejection(
                        'AUTHORIZATION_NOT_APPLICABLE',
                        {'task_id': task['id'], 'authorization_id': request.authorization_id},
                    )
            if previous_scope['model_profile_refs'] != next_scope['model_profile_refs']:
                from .task_configuration_models import (
                    ModelAuthorizationError,
                    compile_model_authorization,
                )

                try:
                    source['model_authorization'] = compile_model_authorization(
                        connection, task['id'], after['models'], next_scope
                    )
                except ModelAuthorizationError:
                    return Rejection(
                        'AUTHORIZATION_NOT_APPLICABLE',
                        {'task_id': task['id'], 'authorization_id': request.authorization_id},
                    )
            if previous_scope['allow_local_delivery'] != next_scope['allow_local_delivery']:
                from .task_configuration_delivery import (
                    DeliveryAuthorizationError,
                    compile_delivery_authorization,
                )

                try:
                    source['delivery_authorization'] = compile_delivery_authorization(
                        connection, task['id'], after['delivery'], next_scope
                    )
                except DeliveryAuthorizationError:
                    return Rejection(
                        'AUTHORIZATION_NOT_APPLICABLE',
                        {'task_id': task['id'], 'authorization_id': request.authorization_id},
                    )
            check_set_changed, output_changed = check_configuration_changes(
                before, after, previous_scope, next_scope
            )
            if check_set_changed or output_changed:
                from .coding_check_plan import CodingCheckPlanError
                from .task_basis import TaskBasisUnavailable
                from .task_configuration_checks import observe_check_configuration

                try:
                    from .task_testing_publication import published_check_task

                    check_task = published_check_task(connection, task, for_read=True)
                    source['check_configuration'] = observe_check_configuration(
                        connection,
                        runtime.catalog,
                        check_task,
                        request.execution_profile_version_id,
                        request.authorization_id,
                        request.check_admissions,
                        include_output=output_changed,
                    )
                except (CodingCheckPlanError, ConfigInvalid, TaskBasisUnavailable) as error:
                    raise ConfigurationNotReady('Q20-CHECKS') from error
            return reserve_live_configuration(connection, task, request, source)
        if (
            any(task[field] is not None for field in NO_ACTIVITY_FIELDS)
            or connection.execute(
                'SELECT 1 FROM code_operations WHERE task_id=? LIMIT 1', (task['id'],)
            ).fetchone()
            or any(
                connection.execute(
                    'SELECT 1 FROM ' + table + ' WHERE task_id=? LIMIT 1', (task['id'],)
                ).fetchone()
                for table in EXECUTION_TABLES
            )
        ):
            return start_conflict('PRECONDITION_FAILED', task)
        return _reserve_pair(connection, task, request)

    return execute_idempotent(
        runtime.commands(),
        CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


class ApplyConfigurationResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'AUTHORIZATION_NOT_APPLICABLE',
            'CONFIG_NOT_READY',
            'PRECONDITION_FAILED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'COMMAND_CLOSED',
        }
    )

    @staticmethod
    def project(data, request):
        data = configuration_receipt(request.command, data, 202)
        if data['state_version'] != request.expected_state_version + 1:
            raise ValueError('Original configuration version differs')
        return data, None


@configuration_apply_router.post(PATH)
async def apply_configuration_http(request: Request):
    result = await handle_http(
        request, ApplyConfigurationRequest, ApplyConfigurationResponse, accept_configuration
    )
    if result.status_code == 202:
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        if worker is not None:
            worker.wake()
    return result
