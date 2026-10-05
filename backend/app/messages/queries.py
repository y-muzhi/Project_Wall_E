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
        raise ValueError('Formal response ownership or chronology is inconsistent')
    for reply in replies: _same_run_root(repository, reply, root['id'])
    if replies: return 'ANSWERED'
    if repository.latest_card_id(root['id']) != row['id'] or repository.newer_input_exists(row) or row['guide_run_id'] is None: return 'EXPIRED'
    run = repository.guide(row['guide_run_id'])
    if run is None or run['requirement_id'] != root['id'] or run['created_at'] > row['created_at']: raise ValueError('Card run ownership is inconsistent')
    if repository.newer_run_exists(root['id'], run['id']): return 'EXPIRED'
    initialize = run['action_type'] == 'INITIALIZE'
    if initialize:
        if root['status'] != 'INITIALIZING' or root['document_work_state'] != 'IDLE' or run['status'] != 'COMPLETED': return 'EXPIRED'
        if root['active_operation_type'] is not None or root['active_operation_id'] is not None or root['state_started_at'] is not None or any(repository.activities(root['id']).values()): raise ValueError('Idle root has a dangling activity')
        function = (catalog if catalog is not None else ResourceCatalog()).freeze(run['action_type'], run['source_type'])
        if function.function_type != run['function_type'] or run['source_id'] is not None: raise ValueError('Initialization card has an invalid function/source')
        final = strict_json_object(run['final_result_json'])
        fields = ('guide_run_id', 'status', 'assistant_message_id', 'current_document', 'suggestion_batch_id')
        object_fields(final, 'final_result', fields, fields)
        if final['guide_run_id'] != run['id'] or final['status'] != 'COMPLETED' or final['assistant_message_id'] != row['id'] or final['suggestion_batch_id'] is not None: raise ValueError('Initialization card has inconsistent committed effects')
        identity = object_fields(final['current_document'], 'current_document', ('id','content_version'), ('id','content_version'))
    else:
        lifecycle_allowed = root['status'] == 'ACTIVE' or root['status'] == 'COMPLETED' and run['action_type'] == 'ASK'
        if not lifecycle_allowed or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id'] or run['status'] != 'WAITING_USER': return 'EXPIRED'
        function = (catalog if catalog is not None else ResourceCatalog()).freeze(run['action_type'], run['source_type'])
        if function.function_type != run['function_type']: raise ValueError('Card run differs from its frozen function')
        if repository.activities(root['id']) != {'MANUAL_DRAFT': [], 'GUIDE_RUN': [run['id']], 'SUGGESTION_BATCH': []}: raise ValueError('Card availability requires the unique actual run activity')
        manifest = function.validate_read_manifest(strict_json_object(run['read_scope_manifest_json']))
        if manifest['function_type'] != run['function_type'] or manifest['source'] != {'source_type': run['source_type'], 'source_id': run['source_id']}: raise ValueError('Card context differs from its actual run function or source')
        identity = {'id': manifest['document_id'], 'content_version': manifest['content_version']}
    strict_integer(identity['id'], 'document_id');strict_integer(identity['content_version'], 'content_version')
    current = repository.current_identity(root['id'])
    if len(current) != 1: raise ValueError('Card availability requires a unique actual CURRENT')
    return 'AVAILABLE' if current[0]['id'] == identity['id'] and current[0]['content_version'] == identity['content_version'] else 'EXPIRED'


def project_message(repository, root, row, protocol, catalog=None):
    data = {field: row[field] for field in MESSAGE_FIELDS if field not in ('structured_content', 'card_state')}
    if row['requirement_id'] != root['id']: raise ValueError('Message belongs to another requirement')
    _same_run_root(repository, row, root['id'])
    data.update(structured_content=None, card_state=None)
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
                protocol = (catalog if catalog is not None else ResourceCatalog()).freeze('ASK','USER_INSTRUCTION') if any(row['message_type'] != 'TEXT' for row in rows) else None
                items = [project_message(repository, root, row, protocol, catalog) for row in rows]
                more = bool(rows) and repository.older_exists(root['id'], rows[0]['sequence_no'])
                result = {'code': 'READ_OK', 'data': list_messages_result(items, request, more), 'details': None}
        return result
    except StorageUnavailable: return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception: return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
