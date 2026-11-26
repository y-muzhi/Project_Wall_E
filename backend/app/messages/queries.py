"""Same-snapshot immutable messages and D-004 card availability facts."""

import json
from functools import lru_cache

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ProtocolInvalid, ResourceCatalog
from backend.app.shared.validation import (
    InvalidInput,
    strict_integer,
)

from .cards import CardsInvalid, decode_cards, decode_responses
from .contracts import MESSAGE_FIELDS, list_messages_input, list_messages_result, message_read_model


def _same_run_root(repository, row, requirement_id):
    if row['guide_run_id'] is not None:
        run = repository.guide_binding(row['guide_run_id'])
        if (
            run is None
            or run['requirement_id'] != requirement_id
            or run['document_id'] != row['document_id']
        ):
            raise ValueError('Message run belongs to another requirement')


@lru_cache(maxsize=1)
def _formation_reading_protocol():
    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE

    return ResourceCatalog().for_formation_profile(DEFAULT_PROFILE).collaboration


def reading_protocol(raw, protocol):
    if raw and json.loads(raw).get('purpose') in ('STAGED_WRITE', 'FORMATION_PATH_CHANGE'):
        if protocol is None or not protocol.formation_driven:
            return _formation_reading_protocol()
    if raw and json.loads(raw).get('purpose') == 'PHASE_CHANGE':
        from backend.app.infrastructure.collaboration_resources import ROOT, CollaborationResources

        return CollaborationResources.load(ROOT.parent / 'v15')
    return protocol


def card_state(repository, root, row, protocol, catalog=None):
    replies = repository.formal_responses(row['id'])
    if len(replies) > 1 or any(
        reply['requirement_id'] != root['id']
        or reply['document_id'] != row['document_id']
        or reply['sequence_no'] <= row['sequence_no']
        or reply['created_at'] < row['created_at']
        for reply in replies
    ):
        raise ValueError('Formal answer ownership/chronology is inconsistent')
    for reply in replies:
        _same_run_root(repository, reply, root['id'])
    if replies:
        return 'ANSWERED'
    if json.loads(row['structured_content_json']).get('purpose') in (
        'STAGED_WRITE',
        'FORMATION_PATH_CHANGE',
    ):
        from backend.app.formation.proposal_availability import message_card_state

        return message_card_state(repository, root, row, catalog or ResourceCatalog())
    if json.loads(row['structured_content_json']).get('purpose') == 'PHASE_CHANGE':
        return 'EXPIRED'
    if (
        repository.latest_card_id(root['id'], row['document_id']) != row['id']
        or repository.newer_input_exists(row)
        or row['guide_run_id'] is None
    ):
        return 'EXPIRED'
    source = repository.guide(row['guide_run_id'])
    if (
        source is None
        or source['requirement_id'] != root['id']
        or source['function_type'] != 'collaboration_v1'
    ):
        raise ValueError('Card source is not its actual collaboration round')
    if source['status'] != 'COMPLETED' or repository.newer_run_exists(
        root['id'], source['id'], row['document_id']
    ):
        return 'EXPIRED'
    cards = decode_cards(
        row['structured_content_json'], reading_protocol(row['structured_content_json'], protocol)
    )
    binding = cards['program_binding']
    if root['discussion_version'] != binding['discussion_version']:
        return 'EXPIRED'
    if root['document_work_state'] != 'IDLE':
        return 'EXPIRED'
    if (
        root['active_operation_type'] is not None
        or root['active_operation_id'] is not None
        or any(repository.activities(root['id']).values())
    ):
        raise ValueError('Card availability requires actual idle ownership')
    target_version = binding['target_content_version']
    if target_version is not None:
        if cards['purpose'] == 'DOCUMENT_ACTION':
            target = cards['action_payload']['target']
            target_id = target['document_id'] if target['kind'] == 'EXISTING' else None
        else:
            target_id = source['target_document_id']
        from backend.app.infrastructure.document_repository import DocumentRepository

        current = (
            None
            if target_id is None
            else DocumentRepository(repository.connection).get_current(root['id'], target_id)
        )
        if (
            current is None
            or current['content_version'] != target_version
            or current['archived_at'] is not None
        ):
            return 'EXPIRED'
    return 'AVAILABLE'


def project_message(
    repository, root, row, protocol, catalog=None, *, operations=None, suggestions=None
):
    data = {
        field: row[field]
        for field in MESSAGE_FIELDS
        if field
        not in ('structured_content', 'card_state', 'topic_refs', 'document_ids', 'program_receipt')
    }
    if row['requirement_id'] != root['id'] or row['document_id'] != root.get(
        'assistant_document_id'
    ):
        raise ValueError('Message belongs to another requirement')
    _same_run_root(repository, row, root['id'])
    import json

    data.update(
        structured_content=None,
        card_state=None,
        topic_refs=json.loads(row['topic_refs']),
        document_ids=json.loads(row['document_ids']),
        program_receipt=repository.program_receipt(row),
    )
    if row['message_type'] == 'INTERACTION_CARDS':
        try:
            data['structured_content'] = decode_cards(
                row['structured_content_json'],
                reading_protocol(row['structured_content_json'], protocol),
            )
        except (CardsInvalid, InvalidInput, ProtocolInvalid):
            pass
        if data['structured_content'] is not None:
            data['card_state'] = card_state(repository, root, row, protocol, catalog)
    elif row['message_type'] == 'CARD_RESPONSE':
        original = repository.get(row['reply_to_message_id'])
        if (
            original is None
            or original['requirement_id'] != root['id']
            or original['role'] != 'ASSISTANT'
            or original['message_type'] != 'INTERACTION_CARDS'
            or original['sequence_no'] >= row['sequence_no']
        ):
            raise ValueError('Response source is not a prior card of this requirement')
        _same_run_root(repository, original, root['id'])
        try:
            data['structured_content'] = decode_responses(
                row['structured_content_json'],
                decode_cards(
                    original['structured_content_json'],
                    reading_protocol(original['structured_content_json'], protocol),
                ),
                protocol,
            )
        except (CardsInvalid, InvalidInput, ProtocolInvalid):
            pass
    if operations is None:
        from backend.app.formation.chat_operations import chat_operations

        operations = chat_operations(
            repository.connection, root['id'], row['document_id'], [row['id']]
        )
    if row['id'] in operations:
        data['formation_operations'] = operations[row['id']]
    if (
        row['role'] == 'ASSISTANT'
        and row['message_type'] == 'TEXT'
        and row['guide_run_id'] is not None
    ):
        from backend.app.formation.initial_suggestion import audited_initials, public_initial

        if suggestions is None:
            suggestions = audited_initials(
                repository.connection, root['id'], row['document_id'], [row['id']]
            )
        if row['id'] in suggestions:
            data['initial_route_suggestion'] = public_initial(suggestions[row['id']])
    return message_read_model(data)


def list_messages(database, payload, *, catalog=None, include_operations=False):
    try:
        request = list_messages_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            root = RequirementRepository(connection).get_for_document(
                request.requirement_id, request.document_id
            )
            if root is None:
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                repository = MessageRepository(connection)
                rows = repository.window(
                    root['id'], request.before_sequence_no, request.document_id
                )
                protocol = (
                    (catalog if catalog is not None else ResourceCatalog()).collaboration
                    if any(row['message_type'] != 'TEXT' for row in rows)
                    else None
                )
                from backend.app.formation.chat_operations import chat_operations

                operations = chat_operations(
                    connection, root['id'], request.document_id, [row['id'] for row in rows]
                )
                from backend.app.formation.initial_suggestion import audited_initials

                suggestions = audited_initials(
                    connection,
                    root['id'],
                    request.document_id,
                    [
                        row['id']
                        for row in rows
                        if row['role'] == 'ASSISTANT'
                        and row['message_type'] == 'TEXT'
                        and row['guide_run_id'] is not None
                    ],
                )
                items = [
                    project_message(
                        repository,
                        root,
                        row,
                        protocol,
                        catalog,
                        operations=operations,
                        suggestions=suggestions,
                    )
                    for row in rows
                ]
                if include_operations:
                    from .operation_receipts import read_guide_operations

                    receipts, audited_runs = read_guide_operations(
                        connection, root['id'], request.document_id, {item['id'] for item in items}
                    )
                    for item in items:
                        if item['role'] == 'USER' and item['id'] in receipts:
                            item['guide_operations'] = receipts[item['id']]
                        if (
                            item['role'] == 'ASSISTANT'
                            and item['message_type'] == 'TEXT'
                            and item['guide_run_id'] in audited_runs
                        ):
                            item['audited_document_output'] = True
                            item['content'] = '文档操作结果已记录。'
                more = bool(rows) and repository.older_exists(
                    root['id'], rows[0]['sequence_no'], request.document_id
                )
                result = {
                    'code': 'READ_OK',
                    'data': list_messages_result(items, request, more),
                    'details': None,
                }
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def get_message(database, requirement_id, message_id, *, catalog=None):
    """Read one explicitly addressed source; never scan other conversations."""
    try:
        strict_integer(requirement_id, 'requirement_id')
        strict_integer(message_id, 'message_id')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            repository = MessageRepository(connection)
            row = repository.get(message_id)
            if row is None or row['requirement_id'] != requirement_id:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            roots = RequirementRepository(connection)
            root = (
                roots.get(requirement_id)
                if row['document_id'] is None
                else roots.get_for_document(requirement_id, row['document_id'])
            )
            if (
                root is None
                or row['document_id'] is None
                and row['id'] != root['initial_message_id']
            ):
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            data = project_message(
                repository, root, row, (catalog or ResourceCatalog()).collaboration, catalog
            )
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
