"""V1.5 APP-REQ-C01/C02: user-owned creation and metadata transactions."""

from datetime import datetime
import sqlite3
from typing import Callable

from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, requirement_number
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput, object_fields
from .contracts import (
    create_requirement_input,
    create_requirement_result,
    update_requirement_input,
    update_requirement_result,
)
from .discussion import empty_discussion


def update_discussion(executor, payload, *, catalog=None, clock=None):
    from .contracts import discussion_command_input, discussion_command_result
    from .discussion import apply_user_command
    from backend.app.documents.guards import assert_idle

    try:
        request = discussion_command_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        repository = RequirementRepository(connection)
        root = repository.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['discussion_version'] != request.expected_discussion_version:
            raise Rejected(
                'DISCUSSION_VERSION_CONFLICT',
                details={
                    'expected_version': request.expected_discussion_version,
                    'actual_version': root['discussion_version'],
                    'resource_kind': 'Requirement',
                    'resource_id': root['id'],
                },
            )
        assert_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
        message_id = entity_id(connection, EntityKind.MESSAGE)
        state, closed_phase = apply_user_command(
            connection, root, request.discussion_command, message_id, catalog or ResourceCatalog()
        )
        if state == root['discussion_state_json']:
            return Success(
                {'code': 'NO_CHANGE', 'data': discussion_command_result(root), 'details': None}, 200
            )
        at = operation_time(clock)
        if at < root['updated_at']:
            raise ValueError('Discussion event cannot precede persisted activity')
        command = request.discussion_command
        labels = {
            'SET_BINDING': '调整讨论目标与参考来源',
            'SET_FOCUS': '切换讨论主题',
            'CHANGE_PHASE': '确认切换讨论阶段',
            'SET_DISPOSITION': '记录讨论处置',
        }
        from backend.app.infrastructure.idempotency import canonical_input

        content = (
            labels[command['type']]
            + '：'
            + canonical_input({key: value for key, value in command.items() if key != 'type'})
        )
        target = state['binding']['target_document_id']
        MessageRepository(connection).create_user_text(
            message_id,
            root['id'],
            None,
            content,
            request.idempotency_key,
            at,
            phase_ref=root['discussion_state_json']['phase']['phase_ref'],
            topic_refs=() if state['focus_topic_ref'] is None else (state['focus_topic_ref'],),
            document_ids=() if target is None else (target,),
        )
        updated = repository.update_discussion(root, state, at)
        AuditRepository(connection).record_discussion_update(
            root, updated, command, message_id, closed_phase, request.idempotency_key, at
        )
        return Success(
            {'code': 'UPDATED', 'data': discussion_command_result(updated), 'details': None}, 200
        )

    return execute_idempotent(
        executor,
        'APP-REQ-CMD-C06',
        request,
        operation,
        allowed_failures=frozenset(
            {
                'NOT_FOUND',
                'DISCUSSION_VERSION_CONFLICT',
                'STATE_CONFLICT',
                'WORK_STATE_CONFLICT',
                'WORK_STATE_INCONSISTENT',
                'SOURCE_INVALID',
                'SCOPE_INVALID',
            }
        ),
    )


def create_requirement(
    executor: Idempotency,
    payload: object,
    *,
    catalog: ResourceCatalog | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict:
    try:
        request = create_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection: sqlite3.Connection) -> Success:
        try:
            resources = catalog.collaboration if catalog is not None else None
            discussion = empty_discussion(resources)
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        at = operation_time(clock)
        identity = entity_id(connection, EntityKind.REQUIREMENT)
        message_id = entity_id(connection, EntityKind.MESSAGE)
        root = RequirementRepository(connection).create(
            identity, requirement_number(connection), request, message_id, discussion, at
        )
        MessageRepository(connection).create_user_text(
            message_id, identity, None, request.initial_idea, request.idempotency_key, at
        )
        return Success(
            {
                'code': 'CREATED',
                'data': create_requirement_result(root, message_id),
                'details': None,
            },
            201,
        )

    return execute_idempotent(
        executor,
        'APP-REQ-CMD-C01',
        request,
        operation,
        allowed_failures=frozenset({'CONFIG_INVALID'}),
        target_identity='Requirements',
    )


def update_requirement(
    executor: Idempotency, payload: object, *, clock: Callable[[], datetime] | None = None
) -> dict:
    try:
        request = update_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        repository = RequirementRepository(connection)
        current = repository.get(request.requirement_id)
        if current is None:
            raise Rejected('NOT_FOUND')
        if current['metadata_version'] != request.expected_metadata_version:
            raise Rejected(
                'METADATA_VERSION_CONFLICT',
                details={
                    'expected_version': request.expected_metadata_version,
                    'actual_version': current['metadata_version'],
                    'resource_kind': 'Requirement',
                    'resource_id': current['id'],
                },
            )
        changes = {
            field: value for field, value in request.changes.items() if current[field] != value
        }
        if not changes:
            return Success(
                {'code': 'NO_CHANGE', 'data': update_requirement_result(current), 'details': None},
                200,
            )
        at = operation_time(clock)
        if at < current['updated_at']:
            raise ValueError('Metadata event cannot precede persisted activity')
        updated = repository.update_attributes(current, changes, at)
        AuditRepository(connection).record_requirement_update(
            current, updated, changes, request.idempotency_key, at
        )
        return Success(
            {'code': 'UPDATED', 'data': update_requirement_result(updated), 'details': None}, 200
        )

    return execute_idempotent(
        executor,
        'APP-REQ-CMD-C02',
        request,
        operation,
        allowed_failures=frozenset({'NOT_FOUND', 'METADATA_VERSION_CONFLICT'}),
    )


def complete_initialization(*args, **kwargs):
    # The V1.5 HTTP boundary validates the empty request and rejects the removed
    # initialization operation. No schema, baseline or provider work is done.
    return {'code': 'STATE_CONFLICT', 'data': None, 'details': None}


def _set_status(executor, payload, status, clock):
    try:
        fields = ('requirement_id', 'expected_metadata_version', 'idempotency_key')
        data = object_fields(payload, 'body', fields, fields)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    return update_requirement(executor, {**data, 'changes': {'status': status}}, clock=clock)


def complete_requirement(executor, payload, *, clock=None):
    return _set_status(executor, payload, 'COMPLETED', clock)


def reactivate_requirement(executor, payload, *, clock=None):
    return _set_status(executor, payload, 'PLANNING', clock)
