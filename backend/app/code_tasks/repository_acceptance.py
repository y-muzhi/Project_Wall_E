"""Original repository registration, observation and baseline acceptance.

The immutable 202 receipt and real operation/steps are committed together.
Registration reserves an ID, without a placeholder repository or task.
"""

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.code_errors import empty_conflict, validation_details
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.validation import MAX_SAFE_INTEGER, InvalidInput, strict_json_object

from .command_registry import REPOSITORY_OPERATIONS, registered_command, validate_registered_success
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_baseline_input import (
    BASELINE_INPUT_FIELDS,
    baseline_fixed_input,
    baseline_profile,
    check_baseline_input,
)


def verify_saved_repository_acceptance(connection, operation):
    kind = operation['operation_type']
    if operation['resource_kind'] != 'REPOSITORY' or kind not in REPOSITORY_OPERATIONS.values():
        raise StorageUnavailable('Original repository operation required')
    path = '/api/v1/code-repositories'
    if kind == 'REFRESH_REPOSITORY':
        path += f'/{operation["resource_id"]}/refresh'
    elif kind == 'REGISTER_BASE':
        path += f'/{operation["resource_id"]}/snapshots'
    try:
        original_input = operation['fixed_input']
        if kind == 'REGISTER_BASE':
            fixed = strict_json_object(original_input)
            business_input = {field: fixed[field] for field in BASELINE_INPUT_FIELDS}
            repository_id = operation['resource_id']
            repository = connection.execute(
                'SELECT object_format FROM code_repositories WHERE id=?', (repository_id,)
            ).fetchone()
            if repository is None or business_input['repository_id'] != repository_id:
                raise ValueError('Original baseline repository differs')
            check_baseline_input(business_input, repository['object_format'])
            if fixed != baseline_fixed_input(
                business_input, fixed['snapshot_id'], repository['object_format']
            ):
                raise ValueError('Original baseline reservation differs')
            original_input = canonical_input(business_input)
        command = registered_command('POST', path, operation['idempotency_key'])
        receipt = connection.execute(
            'SELECT status,success_result_json,http_status,business_input_json '
            'FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?',
            command.scope.identity,
        ).fetchone()
        if receipt is None or receipt['status'] != 'SUCCEEDED':
            raise ValueError('Original accepted receipt required')
        accepted = strict_json_object(receipt['success_result_json'])
        if set(accepted) != {'code', 'data', 'details'} or accepted['details'] is not None:
            raise ValueError('Original accepted receipt fields differ')
        validate_registered_success(
            command, accepted['data'], accepted['code'], receipt['http_status']
        )
        if (
            accepted['data']['operation_id'] != operation['id']
            or accepted['data']['resource_id'] != operation['resource_id']
            or receipt['business_input_json'] != original_input
        ):
            raise ValueError('Original receipt resource or input differs')
    except (ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable('Stored original repository acceptance is invalid') from error


def accept_repository_operation(runtime, request, *, queue_available=None):
    require_schema(runtime)
    capability = request.command.route.capability_id
    action = REPOSITORY_OPERATIONS.get(capability)
    if action is None:
        raise ValueError('Original repository command required')
    registration = action == 'REGISTER_REPOSITORY'
    baseline = action == 'REGISTER_BASE'
    original = request.business_input()
    if (
        not registration
        and request.command.route.match(request.command.path)['id'] != request.repository_id
    ):
        raise ValueError('Original repository path owner differs')

    def accept(connection):
        require_write_transaction(connection)
        if queue_available is not None and not queue_available():
            raise ConfigurationNotReady('Q20-WINDOWS', 'Q20-GIT')
        if not registration:
            repo = connection.execute(
                'SELECT object_format FROM code_repositories WHERE id=?', (request.repository_id,)
            ).fetchone()
            if repo is None:
                return Rejection('NOT_FOUND', None)
            if baseline:
                try:
                    check_baseline_input(original, repo['object_format'])
                except InvalidInput as error:
                    return Rejection('INVALID_INPUT', validation_details(error))
                if original['repository_id'] != request.repository_id:
                    raise ValueError('Original baseline repository differs')
                if (
                    baseline_profile(
                        connection, runtime.catalog, original['execution_profile_version_id']
                    )
                    is None
                ):
                    return Rejection('NOT_FOUND', None)
            elif original != {'repository_id': request.repository_id}:
                raise ValueError('Original refresh input differs')
        kinds = [EntityKind.OPERATION_RECORD]
        if registration:
            kinds.append(EntityKind.REPOSITORY)
        elif baseline:
            kinds.append(EntityKind.CODE_SNAPSHOT)
        for kind in kinds:
            current = connection.execute(
                'SELECT last_value FROM sequences WHERE entity_kind=?', (kind.value,)
            ).fetchone()
            if current is not None and current[0] >= MAX_SAFE_INTEGER:
                return Rejection('PRECONDITION_FAILED', empty_conflict())
        repository_id = (
            entity_id(connection, EntityKind.REPOSITORY) if registration else request.repository_id
        )
        operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
        fixed_input = original
        if baseline:
            snapshot_id = entity_id(connection, EntityKind.CODE_SNAPSHOT)
            fixed_input = baseline_fixed_input(original, snapshot_id, repo['object_format'])
        fixed = canonical_input(fixed_input)
        at = operation_time(None)
        connection.execute(
            "INSERT INTO code_operations VALUES(?,NULL,NULL,'REPOSITORY',?,NULL,?,?,NULL,?,NULL,'PENDING',?,NULL,NULL,NULL)",
            (operation_id, repository_id, action, request.idempotency_key, fixed, at),
        )
        for number, step in enumerate(operation_steps('RESOURCE', action), 1):
            connection.execute(
                "INSERT INTO code_operation_steps VALUES(?,?,?,'PENDING',NULL,?,NULL,NULL,NULL,NULL)",
                (operation_id, number, step, fixed),
            )
        return Success(
            {
                'code': 'OPERATION_ACCEPTED',
                'data': {
                    'resource_kind': 'REPOSITORY',
                    'resource_id': repository_id,
                    'operation_id': operation_id,
                    'operation_status': 'PENDING',
                },
                'details': None,
            },
            202,
        )

    return execute_idempotent(
        runtime.commands(),
        capability,
        request,
        accept,
        business_input=original,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(
            {'INVALID_INPUT', 'NOT_FOUND', 'PRECONDITION_FAILED', 'CONFIG_NOT_READY'}
        ),
    )
