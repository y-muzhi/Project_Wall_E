"""C03 read-only, same-snapshot inputs; no audit, draft or Provider access."""
import sqlite3

from backend.app.comments.contracts import get_comment_result
from backend.app.documents.anchors import locate
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.scopes import resolve_scope, restore_authority, ScopeInvalid
from backend.app.documents.snapshot import create_snapshot, validate_snapshot, validate_template_lock, Provenance
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, TemplateInvalid, ProtocolInvalid
from backend.app.messages.queries import project_message
from backend.app.requirements.contracts import requirement_read_model
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import MISSING, InvalidInput, strict_json_object
from .contracts import get_model_context_input, get_model_context_result, get_guide_run_result


def _message(repository, root, row, function, resources):
    if row is None: raise Rejected('SOURCE_INVALID')
    try: value = project_message(repository, root, row, function, resources)
    except (ValueError, InvalidInput, ProtocolInvalid): raise Rejected('SOURCE_INVALID') from None
    if value['message_type'] not in ('TEXT', 'CARD_RESPONSE'):
        raise Rejected('SOURCE_INVALID')
    if value['message_type'] == 'CARD_RESPONSE' and value['structured_content'] is None:
        raise Rejected('SOURCE_INVALID')
    return value


def _read_source(connection, run, root, snapshot, scope, resources):
    if run['source_type'] == 'USER_INSTRUCTION':
        if run['source_id'] is not None: raise Rejected('SOURCE_INVALID')
        return None
    if run['source_type'] == 'REVIEW_RESULT':
        guides = GuideRepository(connection)
        previous = guides.get(run['source_id'])
        if previous is None or previous['requirement_id'] != root['id'] or previous['action_type'] != 'REVIEW' or previous['status'] != 'COMPLETED':
            raise Rejected('SOURCE_INVALID')
        message, batches = guides.status_references(previous)
        get_guide_run_result(connection, previous, message, batches, catalog=resources)
        result = strict_json_object(previous['final_result_json'])
        protocol = resources.restore(previous['function_type'], previous['prompt_version'], prompt_version=previous['prompt_version'],
            context_template=previous['context_template_key']+'@'+previous['context_template_version'])
        manifest = protocol.validate_read_manifest(strict_json_object(previous['read_scope_manifest_json']))
        current_id = connection.execute("SELECT id,content_version FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (root['id'],)).fetchone()
        if protocol.action_type != 'REVIEW' or protocol.source_type != 'USER_INSTRUCTION' or manifest['function_type'] != protocol.function_type or manifest['source'] != {'source_type': 'USER_INSTRUCTION', 'source_id': None} or manifest['document_id'] != current_id['id'] or manifest['content_version'] > current_id['content_version']:
            raise Rejected('SOURCE_INVALID')
        if result.get('review_result') is None: raise Rejected('SOURCE_INVALID')
        review = protocol.validate_review_result(result['review_result'])
        return {'guide_run_id': previous['id'], 'reviewed_content_version': manifest['content_version'], 'review_result': review}
    row = connection.execute('SELECT * FROM comments WHERE id=?', (run['source_id'],)).fetchone()
    if row is None: raise Rejected('SOURCE_INVALID')
    comment = get_comment_result(row)
    if comment['requirement_id'] != root['id'] or comment['deleted_at'] is not None or comment['status'] != 'OPEN' or comment['anchor_status'] != 'ATTACHED':
        raise Rejected('SOURCE_INVALID')
    location = locate(snapshot, comment['anchor_type'], comment['block_id'], comment['anchor_ref'])
    if not location.attached: raise Rejected('COMMENT_ORPHANED')
    reference = {'block_id': comment['block_id']}
    if comment['anchor_type'] == 'SELECTION': reference.update(comment['anchor_ref'])
    if run['action_type'] != 'MODIFY' or scope.scope_type != comment['anchor_type'] or scope.input_ref != reference:
        raise Rejected('SCOPE_INVALID')
    return {'comment_id': comment['id'], 'content': comment['content'], 'anchor_type': comment['anchor_type'],
        'block_id': comment['block_id'], 'anchor_ref': comment['anchor_ref'],
        'current_location': None if location.start_offset is None else {'start_offset': location.start_offset, 'end_offset': location.end_offset}}


def _source(connection, run, root, snapshot, scope, resources):
    try: return _read_source(connection, run, root, snapshot, scope, resources)
    except (ValueError, InvalidInput, ProtocolInvalid): raise Rejected('SOURCE_INVALID') from None


def read_context(connection, identity, resources):
    """Keep every read on the caller's one SQLite snapshot, without repairing it."""
    guides = GuideRepository(connection)
    run = guides.get(identity)
    if run is None: raise Rejected('NOT_FOUND')
    root = RequirementRepository(connection).get(run['requirement_id'])
    if root is None: raise Rejected('SOURCE_INVALID')
    requirement = requirement_read_model(root)
    function = resources.restore(run['function_type'], run['prompt_version'], prompt_version=run['prompt_version'],
        context_template=run['context_template_key']+'@'+run['context_template_version'])
    if function.action_type != run['action_type'] or function.source_type != run['source_type']:
        raise Rejected('SOURCE_INVALID')
    message, batches = guides.status_references(run)
    get_guide_run_result(connection, run, message, batches, catalog=resources)
    stored = function.validate_read_manifest(strict_json_object(run['read_scope_manifest_json']))
    expected = {'function_type': function.function_type, 'source': {'source_type': run['source_type'], 'source_id': run['source_id']},
        'prompt': dict(zip(('key', 'version'), function.prompt_reference.split('@'))),
        'context_template': dict(zip(('key', 'version'), function.context_template.split('@'))),
        'template': {'key': root['template_key'], 'version': root['template_version']}}
    if any(stored[key] != value for key, value in expected.items()): raise Rejected('SOURCE_INVALID')
    rows = DocumentRepository(connection).by_requirement(root['id'], 'CURRENT')
    if len(rows) != 1: raise Rejected('SOURCE_INVALID')
    if rows[0]['id'] != stored['document_id'] or rows[0]['content_version'] != stored['content_version']:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    sources = DocumentSources(connection, root['id'], resources)
    current = get_current_document_result(rows[0], sources)
    snapshot = validate_snapshot(current['markdown_content'], current['block_state_json'], sources)
    reference = None if run['scope_ref_json'] is None else strict_json_object(run['scope_ref_json'])
    scope = resolve_scope(snapshot, run['action_type'], run['scope_type'], reference)
    authority = restore_authority(snapshot, run['action_type'], run['scope_type'], reference, run['allowed_targets_json'])
    if any(identity not in scope.read_ids for identity in stored['block_ids']): raise Rejected('SOURCE_INVALID')
    template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
    locked = ()
    if run['action_type'] == 'INITIALIZE':
        initial = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), current['created_at'], sources)
        locked = tuple(metadata['block_id'] for block, metadata in initial.by_id.values() if block.block_type == 'heading')
        validate_template_lock(snapshot, template, locked)
    messages = MessageRepository(connection)
    trigger = messages.get(run['trigger_message_id']) if run['trigger_message_id'] is not None else None
    user = _message(messages, root, trigger, function, resources)
    if user['role'] != 'USER': raise Rejected('SOURCE_INVALID')
    if trigger['guide_run_id'] != run['id']:
        previous = guides.get(run['retry_of_guide_run_id']) if run['retry_of_guide_run_id'] is not None else None
        if previous is None or previous['requirement_id'] != root['id'] or previous['status'] != 'FAILED' or previous['trigger_message_id'] != user['id']:
            raise Rejected('SOURCE_INVALID')
    # Card contents contain recommendations. Formal CARD_RESPONSE already
    # records the original question and only the user's chosen answers. Read
    # that immutable record, never the card's unchosen recommendation text.
    history_rows = connection.execute("SELECT * FROM conversation_messages WHERE requirement_id=? AND sequence_no<? AND message_type IN ('TEXT','CARD_RESPONSE') ORDER BY sequence_no DESC LIMIT ?",
        (root['id'], user['sequence_no'], function.context_policy['history_limit'])).fetchall()
    history = [_message(messages, root, row, function, resources) for row in reversed(history_rows)]
    source = _source(connection, run, root, snapshot, scope, resources)
    read_messages = {item['id'] for item in [*history, user]}
    read_messages.update(item['reply_to_message_id'] for item in [*history, user] if item['message_type'] == 'CARD_RESPONSE')
    ordered_messages = sorted(read_messages, key=lambda identity: messages.get(identity)['sequence_no'])
    actual = {**stored, 'block_ids': list(scope.read_ids), 'message_ids': ordered_messages}
    return get_model_context_result({'run': dict(run), 'requirement': requirement, 'current_document': current,
        'template': {'template_key': template.key, 'template_version': template.version, 'markdown_content': template.markdown, 'locked_heading_block_ids': list(locked)},
        'scope': {**scope.context_scope, 'focus_block_ids': list(scope.focus_ids), 'required_read_block_ids': list(scope.required_read_ids), 'read_block_ids': list(scope.read_ids)},
        'allowed_targets': [target.as_dict() for target in authority.allowed_targets],
        'user_input': user,
        'history': history, 'source': source, 'read_manifest': function.validate_read_manifest(actual)})


def get_model_context(database, guide_run_id=MISSING, *, catalog=None):
    try: identity = get_model_context_input(guide_run_id)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            resources = catalog if catalog is not None else ResourceCatalog()
            return read_context(connection, identity, resources)
    except Rejected as error: return {'code': error.code, 'data': None, 'details': None}
    except (ConfigInvalid, TemplateInvalid): code = 'CONFIG_INVALID'
    except (StorageUnavailable, sqlite3.Error): code = 'STORAGE_UNAVAILABLE'
    except (InvalidInput, ProtocolInvalid, ScopeInvalid): code = 'SOURCE_INVALID'
    except Exception: code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}
