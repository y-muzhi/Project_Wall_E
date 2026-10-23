"""APP-REQ-QUERY-C01/C02; application result triads, no HTTP or write side effects."""
from collections.abc import Callable

from backend.app.infrastructure.database import Database, SchemaMismatch, StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.validation import InvalidInput, MISSING
from .contracts import get_requirement_input, get_requirement_result, list_requirements_input


def _query(database: Database, validate: Callable, read: Callable, *, not_found: bool = False) -> dict:
    try:
        request = validate()
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    # Validation of persisted fields must never be reported as caller input failure.
    try:
        with database.transaction() as connection:
            data = read(RequirementRepository(connection), request)
        return {'code': 'NOT_FOUND' if not_found and data is None else 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except SchemaMismatch:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def list_requirements(database: Database, payload: object = MISSING) -> dict:
    return _query(database, lambda: list_requirements_input({} if payload is MISSING else payload),
                  lambda repository, request: repository.list_page(request))


def get_requirement(database: Database, requirement_id: object = MISSING, *, expand=None) -> dict:
    from backend.app.shared.validation import strict_enum
    def validate():
        if expand is not None:
            strict_enum(expand, 'expand', ('discussion',))
        return get_requirement_input(requirement_id)
    def read(repository: RequirementRepository, identity: int) -> dict | None:
        from backend.app.infrastructure.document_repository import DocumentRepository
        root = repository.get(identity)
        if root is None:
            return None
        discussion = root['discussion_state_json']
        focus = next((item for item in discussion['topics'] if item['topic_ref'] == discussion['focus_topic_ref']), None)
        active = None
        if root['active_operation_id'] is not None:
            kind = root['active_operation_type']
            table = {'GUIDE_RUN': 'guide_runs', 'MANUAL_DRAFT': 'requirement_documents', 'SUGGESTION_BATCH': 'suggestion_batches'}[kind]
            row = repository.connection.execute('SELECT id,requirement_id,target_document_id FROM ' + table + ' WHERE id=?', (root['active_operation_id'],)).fetchone()
            if row is None or row['requirement_id'] != root['id']:
                raise ValueError('Active operation must reference a real owned object')
            labels = {'GUIDE_RUN': 'AI工作进行中', 'MANUAL_DRAFT': '人工编辑中', 'SUGGESTION_BATCH': '修改建议审阅中'}
            target = row['target_document_id']
            if target is not None and repository.connection.execute("SELECT 1 FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='CURRENT'", (target, root['id'])).fetchone() is None:
                raise ValueError('Active target must be an actual owned document')
            if kind in ('MANUAL_DRAFT', 'SUGGESTION_BATCH') and target is None:
                raise ValueError('A draft or batch requires its actual target')
            active = {'type': kind, 'id': row['id'], 'summary': labels[kind], 'target_document_id': target}
        result = {'requirement': get_requirement_result(root),
            'documents': DocumentRepository(repository.connection).list_current_summaries(identity),
            'discussion_summary': {'discussion_version': root['discussion_version'],
                'phase_ref': discussion['phase']['phase_ref'], 'phase_kind': discussion['phase']['kind'],
                'focus_topic_ref': discussion['focus_topic_ref'], 'focus_title': None if focus is None else focus['title'],
                'next_step': None if discussion['last_step'] is None else discussion['last_step']['value'],
                'pending_count': len(discussion['pending_user_message_ids'])},
            'discussion': discussion if expand == 'discussion' else None, 'active_operation': active}
        return project_detail(result, expand)
    return _query(database, validate, read, not_found=True)


def project_detail(value, expand):
    """The same exact detail contract at the application and HTTP boundaries."""
    from backend.app.shared.http_projection import exact, requirement
    from backend.app.shared.validation import strict_integer, strict_enum, raw_text
    from backend.app.documents.contracts import document_summary
    from .discussion import validate_discussion
    data = exact(value, ('requirement', 'documents', 'discussion_summary', 'discussion', 'active_operation'))
    root = requirement(data['requirement'])
    if type(data['documents']) is not list:
        raise ValueError('Document summaries must be an array')
    documents = [document_summary(item) for item in data['documents']]
    if len({item['id'] for item in documents}) != len(documents) or any(item['requirement_id'] != root['id'] for item in documents):
        raise ValueError('Document summary ownership or identities differ')
    summary = exact(data['discussion_summary'], ('discussion_version', 'phase_ref', 'phase_kind', 'focus_topic_ref', 'focus_title', 'next_step', 'pending_count'))
    if summary['discussion_version'] != root['discussion_version']:
        raise ValueError('Discussion summary version differs')
    strict_integer(summary['pending_count'], 'pending_count', minimum=0)
    raw_text(summary['phase_ref'], 'phase_ref', 1, 200)
    strict_enum(summary['phase_kind'], 'phase_kind', ('DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW'))
    if (summary['focus_topic_ref'] is None) != (summary['focus_title'] is None):
        raise ValueError('Focus summary is incomplete')
    if summary['focus_topic_ref'] is not None:
        raw_text(summary['focus_topic_ref'], 'focus_topic_ref', 1, 200)
        raw_text(summary['focus_title'], 'focus_title', 1, 1000)
    from .discussion import discussion_resources
    if summary['next_step'] is not None:
        discussion_resources().validate('NextStep', summary['next_step'])
    discussion = validate_discussion(data['discussion']) if expand == 'discussion' else None
    if expand != 'discussion' and data['discussion'] is not None:
        raise ValueError('Unrequested discussion must not be returned')
    active = data['active_operation']
    if active is not None:
        active = exact(active, ('type', 'id', 'summary', 'target_document_id'))
        strict_integer(active['id'], 'active_operation_id')
        if active['type'] != root['active_operation_type'] or active['id'] != root['active_operation_id']:
            raise ValueError('Active operation summary differs')
        raw_text(active['summary'], 'summary', 1, 1000)
        if active['target_document_id'] is not None:
            strict_integer(active['target_document_id'], 'target_document_id')
            if active['target_document_id'] not in {document['id'] for document in documents}:
                raise ValueError('Active operation target is absent from the owned document directory')
        elif active['type'] in ('MANUAL_DRAFT', 'SUGGESTION_BATCH'):
            raise ValueError('Active edit and batch targets cannot be missing')
    elif root['active_operation_id'] is not None:
        raise ValueError('Active operation summary is missing')
    return {**data, 'requirement': root, 'documents': documents, 'discussion_summary': summary, 'discussion': discussion, 'active_operation': active}
