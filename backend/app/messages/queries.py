"""Same-snapshot immutable messages and D-004 card availability facts."""
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.resources import ResourceCatalog, ProtocolInvalid
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.validation import InvalidInput, strict_json_object, strict_integer, object_fields
from .cards import CardsInvalid, decode_cards, decode_responses
from .contracts import MESSAGE_FIELDS, list_messages_input, list_messages_result, message_read_model


def _same_run_root(repository, row, requirement_id):
    if row['guide_run_id'] is not None:
        run = repository.guide_binding(row['guide_run_id'])
        if run is None or run['requirement_id'] != requirement_id: raise ValueError('Message run belongs to another requirement')


def card_state(repository, root, row, protocol, catalog=None):
    replies = repository.formal_responses(row['id'])
    if len(replies) > 1 or any(reply['requirement_id'] != root['id'] or reply['sequence_no'] <= row['sequence_no'] or reply['created_at'] < row['created_at'] for reply in replies):
        raise ValueError('Formal answer ownership/chronology is inconsistent')
    for reply in replies:
        _same_run_root(repository, reply, root['id'])
    if replies:
        return 'ANSWERED'
    if repository.latest_card_id(root['id']) != row['id'] or repository.newer_input_exists(row) or row['guide_run_id'] is None:
        return 'EXPIRED'
    source = repository.guide(row['guide_run_id'])
    if source is None or source['requirement_id'] != root['id'] or source['function_type'] != 'collaboration_v1':
        raise ValueError('Card source is not its actual collaboration round')
    if source['status'] != 'COMPLETED' or repository.newer_run_exists(root['id'], source['id']):
        return 'EXPIRED'
    cards = decode_cards(row['structured_content_json'], protocol)
    binding = cards['program_binding']
    if root['discussion_version'] != binding['discussion_version']:
        return 'EXPIRED'
    if root['document_work_state'] != 'IDLE':
        return 'EXPIRED'
    if root['active_operation_type'] is not None or root['active_operation_id'] is not None or any(repository.activities(root['id']).values()):
        raise ValueError('Card availability requires actual idle ownership')
    target_version = binding['target_content_version']
    if target_version is not None:
        if cards['purpose'] == 'DOCUMENT_ACTION':
            target = cards['action_payload']['target']
            target_id = target['document_id'] if target['kind'] == 'EXISTING' else None
        else:
            target_id = source['target_document_id']
        from backend.app.infrastructure.document_repository import DocumentRepository
        current = None if target_id is None else DocumentRepository(repository.connection).get_current(root['id'], target_id)
        if current is None or current['content_version'] != target_version or current['archived_at'] is not None:
            return 'EXPIRED'
    return 'AVAILABLE'


def project_message(repository, root, row, protocol, catalog=None):
    data = {field: row[field] for field in MESSAGE_FIELDS if field not in ('structured_content', 'card_state', 'topic_refs', 'document_ids', 'program_receipt')}
    if row['requirement_id'] != root['id']: raise ValueError('Message belongs to another requirement')
    _same_run_root(repository, row, root['id'])
    import json
    data.update(structured_content=None, card_state=None, topic_refs=json.loads(row['topic_refs']), document_ids=json.loads(row['document_ids']), program_receipt=repository.program_receipt(row))
    if row['message_type'] == 'INTERACTION_CARDS':
        try: data['structured_content'] = decode_cards(row['structured_content_json'], protocol)
        except (CardsInvalid, InvalidInput, ProtocolInvalid): pass
        if data['structured_content'] is not None: data['card_state'] = card_state(repository, root, row, protocol, catalog)
    elif row['message_type'] == 'CARD_RESPONSE':
        original = repository.get(row['reply_to_message_id'])
        if original is None or original['requirement_id'] != root['id'] or original['role'] != 'ASSISTANT' or original['message_type'] != 'INTERACTION_CARDS' or original['sequence_no'] >= row['sequence_no']:
            raise ValueError('Response source is not a prior card of this requirement')
        _same_run_root(repository, original, root['id'])
        try: data['structured_content'] = decode_responses(row['structured_content_json'], decode_cards(original['structured_content_json'], protocol), protocol)
        except (CardsInvalid, InvalidInput, ProtocolInvalid): pass
    return message_read_model(data)


def list_messages(database, payload, *, catalog=None):
    try: request = list_messages_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            root = RequirementRepository(connection).get(request.requirement_id)
            if root is None: result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                repository = MessageRepository(connection)
                rows = repository.window(root['id'], request.before_sequence_no)
                protocol = (catalog if catalog is not None else ResourceCatalog()).collaboration if any(row['message_type'] != 'TEXT' for row in rows) else None
                items = [project_message(repository, root, row, protocol, catalog) for row in rows]
                more = bool(rows) and repository.older_exists(root['id'], rows[0]['sequence_no'])
                result = {'code': 'READ_OK', 'data': list_messages_result(items, request, more), 'details': None}
        return result
    except StorageUnavailable: return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
