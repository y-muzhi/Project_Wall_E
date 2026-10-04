"""Approved C06 internal input and complete result contract."""
from backend.app.shared.validation import object_fields, strict_integer
from backend.app.infrastructure.idempotency import canonical_input
from dataclasses import dataclass
import json
from backend.app.shared.validation import MISSING, strict_enum, strict_json_object, comment_content
from backend.app.shared.pagination import page_number, page_metadata
from backend.app.documents.anchors import validate_anchor, locate
from backend.app.documents.snapshot import _time
from backend.app.infrastructure.idempotency import request_key
from backend.app.shared.validation import selected_text, prefix_text, suffix_text, reject

COMMENT_FIELDS = ('id', 'requirement_id', 'content', 'anchor_type', 'block_id', 'anchor_ref', 'anchor_status', 'status', 'resolved_at', 'deleted_at', 'created_at', 'updated_at')


def get_comment_input(value: object = MISSING) -> int:
    return strict_integer(value, 'comment_id')


def get_comment_index_input(value: object = MISSING) -> int:
    return strict_integer(value, 'requirement_id')


@dataclass(frozen=True)
class ListCommentsInput:
    requirement_id: int
    page: int


def list_comments_input(payload: object) -> ListCommentsInput:
    data = object_fields(payload, 'query', ('requirement_id', 'page'), ('requirement_id',))
    return ListCommentsInput(strict_integer(data['requirement_id'], 'requirement_id'), page_number(data.get('page', 1)))


def _detached(value):
    return json.loads(canonical_input(value))


def comment_read_model(data: object) -> dict:
    value = object_fields(data, 'comment', COMMENT_FIELDS, COMMENT_FIELDS)
    strict_integer(value['id'], 'id'); strict_integer(value['requirement_id'], 'requirement_id')
    if comment_content(value['content']) != value['content']:
        raise ValueError('Stored comment text must already be normalized')
    validate_anchor(value['anchor_type'], value['block_id'], value['anchor_ref'])
    strict_enum(value['status'], 'status', ('OPEN', 'RESOLVED')); strict_enum(value['anchor_status'], 'anchor_status', ('ATTACHED', 'ORPHANED'))
    created, updated = _time(value['created_at']), _time(value['updated_at'])
    if created > updated or (value['status'] == 'RESOLVED') != (value['resolved_at'] is not None):
        raise ValueError('Stored comment event chronology is inconsistent')
    for field in ('resolved_at', 'deleted_at'):
        if value[field] is not None and not created <= _time(value[field]) <= updated:
            raise ValueError('Stored comment event is outside its lifetime')
    return _detached(value)


def get_comment_result(row) -> dict:
    value = {field: row[field] for field in COMMENT_FIELDS if field != 'anchor_ref'}
    value['anchor_ref'] = strict_json_object(row['anchor_ref_json'], 'anchor_ref_json')
    return comment_read_model(value)


def location_model(data: object) -> dict:
    fields = ('status', 'block_id', 'start_offset', 'end_offset')
    value = object_fields(data, 'location', fields, fields)
    strict_enum(value['status'], 'location.status', ('ATTACHED', 'ORPHANED'))
    if value['status'] == 'ORPHANED':
        if any(value[field] is not None for field in fields[1:]):
            raise ValueError('Orphaned locations have no target or offsets')
    else:
        strict_integer(value['block_id'], 'location.block_id')
        if (value['start_offset'] is None) != (value['end_offset'] is None):
            raise ValueError('Selection offsets must occur together')
        if value['start_offset'] is not None:
            strict_integer(value['start_offset'], 'start_offset', minimum=0); strict_integer(value['end_offset'], 'end_offset', minimum=0)
            if value['start_offset'] >= value['end_offset']:
                raise ValueError('Selection offsets must describe a nonempty half-open range')
    return _detached(value)


def comment_list_item(data: object) -> dict:
    value = object_fields(data, 'item', (*COMMENT_FIELDS, 'location'), (*COMMENT_FIELDS, 'location'))
    core = comment_read_model({field: value[field] for field in COMMENT_FIELDS})
    location = location_model(value['location'])
    if core['deleted_at'] is not None:
        raise ValueError('Deleted comments cannot occur in a live list')
    if location['status'] == 'ATTACHED':
        if location['block_id'] != core['block_id']:
            raise ValueError('A location must use the original block identity')
        if core['anchor_type'] == 'BLOCK' and location['start_offset'] is not None:
            raise ValueError('BLOCK comments have no selection offsets')
        if core['anchor_type'] == 'SELECTION' and (location['start_offset'] is None or location['end_offset']-location['start_offset'] != len(core['anchor_ref']['selected_text'])):
            raise ValueError('Selection offsets must use Unicode code points')
    return {**core, 'location': location}


def locate_comment(row, snapshot) -> dict:
    value = get_comment_result(row)
    found = locate(snapshot, value['anchor_type'], value['block_id'], value['anchor_ref'])
    return comment_list_item({**value, 'location': {'status': 'ATTACHED' if found.attached else 'ORPHANED', **found.as_dict()}})


def list_comments_result(items: list[dict], request: ListCommentsInput, total: int) -> dict:
    if type(items) is not list or len(items) > 20:
        raise ValueError('Comment list must contain at most one fixed page')
    values = [comment_list_item(item) for item in items]
    if any(item['requirement_id'] != request.requirement_id for item in values):
        raise ValueError('Comment list contains another requirement')
    return {'items': values, **page_metadata(request.page, total)}


def comment_index_model(data: object) -> dict:
    fields = ('requirement_id', 'document_id', 'content_version', 'total_count', 'open_count', 'blocks', 'comments')
    value = object_fields(data, 'index', fields, fields)
    for field in fields[:3]: strict_integer(value[field], field)
    for field in ('total_count', 'open_count'): strict_integer(value[field], field, minimum=0)
    if type(value['comments']) is not list or type(value['blocks']) is not list:
        raise ValueError('Comment index collections must be arrays')
    identities, open_count, expected = set(), 0, {}
    for comment in value['comments']:
        object_fields(comment, 'comment', ('id', 'status', 'anchor_status', 'location'), ('id', 'status', 'anchor_status', 'location'))
        strict_integer(comment['id'], 'id'); strict_enum(comment['status'], 'status', ('OPEN', 'RESOLVED')); strict_enum(comment['anchor_status'], 'anchor_status', ('ATTACHED', 'ORPHANED'))
        if comment['id'] in identities: raise ValueError('Index comment identities must be unique')
        identities.add(comment['id']); location_model(comment['location'])
        if comment['status'] == 'OPEN':
            open_count += 1
            if comment['location']['status'] == 'ATTACHED':
                expected.setdefault(comment['location']['block_id'], []).append(comment['id'])
    actual = {}
    for block in value['blocks']:
        object_fields(block, 'block', ('block_id', 'open_count', 'comment_ids'), ('block_id', 'open_count', 'comment_ids'))
        strict_integer(block['block_id'], 'block_id'); strict_integer(block['open_count'], 'open_count')
        if block['block_id'] in actual or type(block['comment_ids']) is not list or block['open_count'] != len(block['comment_ids']):
            raise ValueError('Index block counts must match their unique targets')
        for identity in block['comment_ids']: strict_integer(identity, 'comment_id')
        actual[block['block_id']] = block['comment_ids']
    if value['total_count'] != len(identities) or value['open_count'] != open_count or actual != expected:
        raise ValueError('Index counts and markers must derive from the complete same collection')
    return _detached(value)


def get_comment_index_result(requirement_id: int, document, snapshot, items: list[dict]) -> dict:
    by_block = {}
    comments = []
    for item in items:
        if item['requirement_id'] != requirement_id or item['deleted_at'] is not None:
            raise ValueError('Index only contains the requirement complete live collection')
        comments.append({field: item[field] for field in ('id', 'status', 'anchor_status', 'location')})
        if item['status'] == 'OPEN' and item['location']['status'] == 'ATTACHED':
            by_block.setdefault(item['block_id'], []).append(item['id'])
    blocks = [{'block_id': metadata['block_id'], 'open_count': len(by_block[metadata['block_id']]), 'comment_ids': by_block[metadata['block_id']]} for metadata in snapshot.state['blocks'] if metadata['block_id'] in by_block]
    return comment_index_model({'requirement_id': requirement_id, 'document_id': document['id'], 'content_version': document['content_version'],
        'total_count': len(comments), 'open_count': sum(item['status'] == 'OPEN' for item in comments), 'blocks': blocks, 'comments': comments})


@dataclass(frozen=True)
class CreateCommentInput:
    requirement_id: int
    expected_content_version: int
    content: str
    anchor_type: str
    block_id: int
    selection: dict | None
    idempotency_key: str

    def business_input(self) -> dict:
        return {field: getattr(self, field) for field in ('requirement_id', 'expected_content_version', 'content', 'anchor_type', 'block_id', 'selection')}


def _unicode(value: str, field: str):
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        reject(field, 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')


def create_comment_input(payload: object) -> CreateCommentInput:
    fields = ('requirement_id', 'expected_content_version', 'content', 'anchor_type', 'block_id', 'selection', 'idempotency_key')
    data = object_fields(payload, 'body', fields, tuple(field for field in fields if field != 'selection'))
    content = comment_content(data['content']); _unicode(content, 'content')
    kind = strict_enum(data['anchor_type'], 'anchor_type', ('BLOCK', 'SELECTION'))
    selection = data.get('selection')
    if kind == 'BLOCK':
        if selection is not None: reject('selection', 'INVALID_TYPE', 'BLOCK评论不提交选区')
    else:
        fields = ('selected_text', 'prefix_text', 'suffix_text')
        object_fields(selection, 'selection', fields, fields)
        selected_text(selection['selected_text']); prefix_text(selection['prefix_text']); suffix_text(selection['suffix_text'])
        for field in fields: _unicode(selection[field], 'selection.'+field)
        selection = _detached(selection)
    return CreateCommentInput(strict_integer(data['requirement_id'], 'requirement_id'), strict_integer(data['expected_content_version'], 'expected_content_version'),
        content, kind, strict_integer(data['block_id'], 'block_id'), selection, request_key(data['idempotency_key'], 'idempotency_key'))


def create_comment_result(row) -> dict:
    return {'code': 'COMMENT_CREATED', 'data': get_comment_result(row), 'details': None}


@dataclass(frozen=True)
class CommentActionInput:
    comment_id: int
    idempotency_key: str
    content: str | None = None

    def business_input(self) -> dict:
        return {'comment_id': self.comment_id, **({} if self.content is None else {'content': self.content})}


def _action_input(payload: object, *, editing: bool) -> CommentActionInput:
    fields = ('comment_id', 'idempotency_key', 'content') if editing else ('comment_id', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    content = comment_content(data['content']) if editing else None
    if content is not None: _unicode(content, 'content')
    return CommentActionInput(strict_integer(data['comment_id'], 'comment_id'), request_key(data['idempotency_key'], 'idempotency_key'), content)


def edit_comment_input(payload: object) -> CommentActionInput:
    return _action_input(payload, editing=True)


def resolve_comment_input(payload: object) -> CommentActionInput:
    return _action_input(payload, editing=False)


reopen_comment_input = resolve_comment_input
delete_comment_input = resolve_comment_input


def edit_comment_result(row) -> dict:
    return {'code': 'COMMENT_UPDATED', 'data': get_comment_result(row), 'details': None}


resolve_comment_result = edit_comment_result
reopen_comment_result = edit_comment_result
delete_comment_result = edit_comment_result


def revalidate_anchors_input(payload: object) -> tuple[int, dict]:
    data = object_fields(payload, 'body', ('requirement_id', 'new_document'), ('requirement_id', 'new_document'))
    document = object_fields(data['new_document'], 'new_document', ('markdown_content', 'block_state_json'), ('markdown_content', 'block_state_json'))
    return strict_integer(data['requirement_id'], 'requirement_id'), document


def revalidate_anchors_result(requirement_id: int, document_id: int, version: int,
                              attached: list[int], orphaned: list[int]) -> dict:
    for field, value in (('requirement_id', requirement_id), ('document_id', document_id), ('content_version', version)):
        strict_integer(value, field)
    identities = attached + orphaned
    if len(set(identities)) != len(identities):
        raise ValueError('Every nondeleted comment must appear exactly once')
    for identity in identities:
        strict_integer(identity, 'comment_id')
    data = {'requirement_id': requirement_id, 'document_id': document_id, 'content_version': version,
            'attached_comment_ids': list(attached), 'orphaned_comment_ids': list(orphaned)}
    canonical_input(data)
    return {'code': 'ANCHORS_UPDATED', 'data': data, 'details': None}
