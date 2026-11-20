"""Success-only idempotency wraps native formation operations on the original database."""

from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput, reject

from .contracts import command_input
from .state_commands import STATE_ACTIONS
from .state_commands import apply as apply_state


def _execute(executor, request, handler, *, clock):
    def operation(connection):
        root = RequirementRepository(connection).get_for_document(
            request.requirement_id, request.document_id
        )
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['discussion_version'] != request.expected_discussion_version:
            raise Rejected(
                'DISCUSSION_VERSION_CONFLICT',
                details={
                    'expected_version': request.expected_discussion_version,
                    'actual_version': root['discussion_version'],
                    'resource_kind': 'RequirementDocument',
                    'resource_id': request.document_id,
                },
            )
        try:
            data = handler(
                connection,
                root,
                request.discussion_command,
                request.idempotency_key,
                operation_time(clock),
            )
        except InvalidInput:
            raise Rejected('FORMATION_INVALID') from None
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        return Success(
            {
                'code': 'NO_CHANGE' if data['result'] == 'NO_CHANGE' else 'UPDATED',
                'data': data,
                'details': None,
            },
            200,
        )

    return execute_idempotent(
        executor,
        'formation.command',
        request,
        operation,
        target_identity=f'Requirement:{request.requirement_id}:Document:{request.document_id}',
        allowed_failures=frozenset(
            {
                'FORMATION_INVALID',
                'NOT_FOUND',
                'DISCUSSION_VERSION_CONFLICT',
                'CONTENT_VERSION_CONFLICT',
                'STATE_CONFLICT',
                'WORK_STATE_CONFLICT',
                'WORK_STATE_INCONSISTENT',
                'SOURCE_INVALID',
                'CARD_ALREADY_ANSWERED',
                'CONFIG_INVALID',
            }
        ),
    )


def update_state(executor, payload, *, clock=None):
    """State-only unit; the complete HTTP dispatcher is composed after all action units."""
    try:
        request = command_input(payload)
        if request.discussion_command['action'] not in STATE_ACTIONS:
            reject('discussion_command.action', 'INVALID_ENUM', '此入口只处理步骤及支线状态操作')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    return _execute(executor, request, apply_state, clock=clock)


def update_path(executor, payload, *, catalog=None, clock=None):
    from .path_commands import apply as apply_path

    try:
        request = command_input(payload)
        if request.discussion_command['action'] != 'ADJUST_PATH':
            reject('discussion_command.action', 'INVALID_ENUM', '此入口只处理完整路线调整')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        resources = ResourceCatalog() if catalog is None else catalog
    except ConfigInvalid:
        return {'code': 'CONFIG_INVALID', 'data': None, 'details': None}

    def apply(connection, root, command, key, at):
        return apply_path(connection, root, command, key, at, resources=resources)

    return _execute(executor, request, apply, clock=clock)


def complete_step(executor, payload, *, catalog=None, clock=None):
    from .completion_commands import apply as apply_completion

    try:
        request = command_input(payload)
        if request.discussion_command['action'] != 'COMPLETE_STEP':
            reject('discussion_command.action', 'INVALID_ENUM', '此入口只处理用户结束步骤')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        resources = ResourceCatalog() if catalog is None else catalog
    except ConfigInvalid:
        return {'code': 'CONFIG_INVALID', 'data': None, 'details': None}

    def apply(connection, root, command, key, at):
        return apply_completion(connection, root, command, key, at, resources=resources)

    return _execute(executor, request, apply, clock=clock)


def update_proposal(executor, payload, *, catalog=None, clock=None):
    from .proposal_commands import ACTIONS
    from .proposal_commands import apply as apply_proposal

    try:
        request = command_input(payload)
        if request.discussion_command['action'] not in ACTIONS:
            reject('discussion_command.action', 'INVALID_ENUM', '此入口只处理提案处置')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        resources = ResourceCatalog() if catalog is None else catalog
    except ConfigInvalid:
        return {'code': 'CONFIG_INVALID', 'data': None, 'details': None}

    def apply(connection, root, command, key, at):
        return apply_proposal(connection, root, command, key, at, resources=resources)

    return _execute(executor, request, apply, clock=clock)


def update(executor, payload, *, catalog=None, clock=None):
    # Reuse the transaction units; their strict parser rejects every unknown
    # action/field before any allocation or successful idempotency record.
    command = payload.get('discussion_command') if type(payload) is dict else None
    action = command.get('action') if type(command) is dict else None
    if action in STATE_ACTIONS:
        return update_state(executor, payload, clock=clock)
    if action == 'ADJUST_PATH':
        return update_path(executor, payload, catalog=catalog, clock=clock)
    if action == 'COMPLETE_STEP':
        return complete_step(executor, payload, catalog=catalog, clock=clock)
    return update_proposal(executor, payload, catalog=catalog, clock=clock)
