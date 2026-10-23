"""APP-DOC-QUERY-C01/C02 exact document read models and snapshot gates."""
from typing import Mapping, Any
from dataclasses import dataclass

from backend.app.shared.validation import MISSING, strict_enum, strict_integer, strict_json_object
from backend.app.shared.validation import object_fields
from .snapshot import SourceVerifier, _time, validate_snapshot

DOCUMENT_FIELDS = ('id', 'requirement_id', 'document_type', 'markdown_content', 'block_state_json',
                   'content_version', 'created_at', 'updated_at')


def get_current_document_input(value: object = MISSING) -> int:
    return strict_integer(value, 'requirement_id')


def get_manual_draft_input(value: object = MISSING) -> int:
    return strict_integer(value, 'requirement_id')


def document_read_model(row: Mapping[str, Any], source_verifier: SourceVerifier) -> dict:
    data = {field: row[field] for field in DOCUMENT_FIELDS}
    for field in ('id', 'requirement_id', 'content_version'):
        strict_integer(data[field], field)
    strict_enum(data['document_type'], 'document_type', ('CURRENT', 'MANUAL_DRAFT'))
    _time(data['created_at'])
    _time(data['updated_at'])
    # SQLite json_valid alone permits duplicate keys and does not prove a pair.
    state = strict_json_object(data['block_state_json'], 'block_state_json')
    data['block_state_json'] = validate_snapshot(data['markdown_content'], state, source_verifier).state
    return data


def get_current_document_result(row: Mapping[str, Any], source_verifier: SourceVerifier) -> dict:
    data = document_read_model(row, source_verifier)
    if data['document_type'] != 'CURRENT':
        raise ValueError('Current read must not project a draft')
    return data


DRAFT_FIELDS = (*DOCUMENT_FIELDS, 'target_document_id', 'base_content_version', 'template_ref')


def get_manual_draft_result(row: Mapping[str, Any], source_verifier: SourceVerifier) -> dict:
    data = document_read_model(row, source_verifier)
    if data['document_type'] != 'MANUAL_DRAFT':
        raise ValueError('Draft read must not project current content')
    for field in ('target_document_id', 'base_content_version'):
        data[field] = strict_integer(row[field], field)
    data['template_ref'] = None if row['template_ref'] is None else strict_json_object(row['template_ref'])
    return data


@dataclass(frozen=True)
class StartManualDraftInput:
    requirement_id: int
    document_id: int
    expected_version: int
    idempotency_key: str
    restore_revision_id: int | None = None

    def business_input(self):
        return {'requirement_id': self.requirement_id, 'document_id': self.document_id, 'expected_version': self.expected_version,
            **({} if self.restore_revision_id is None else {'restore_revision_id': self.restore_revision_id})}


def start_manual_draft_input(payload):
    from backend.app.infrastructure.idempotency import request_key
    fields = ('requirement_id', 'document_id', 'expected_version', 'restore_revision_id', 'idempotency_key')
    data = object_fields(payload, 'body', fields, tuple(field for field in fields if field != 'restore_revision_id'))
    return StartManualDraftInput(strict_integer(data['requirement_id'], 'requirement_id'),
        strict_integer(data['document_id'], 'document_id'), strict_integer(data['expected_version'], 'expected_version'),
        request_key(data['idempotency_key']), None if 'restore_revision_id' not in data else strict_integer(data['restore_revision_id'], 'restore_revision_id'))


def start_manual_draft_result(draft, root, source_verifier):
    from backend.app.requirements.contracts import requirement_read_model
    return {'manual_draft': get_manual_draft_result(draft, source_verifier), 'requirement': requirement_read_model(root)}


@dataclass(frozen=True)
class DraftCommandInput:
    requirement_id: int
    document_id: int
    draft_id: int
    expected_version: int
    idempotency_key: str

    def business_input(self):
        return {field: getattr(self, field) for field in ('requirement_id', 'document_id', 'draft_id', 'expected_version')}


def cancel_manual_draft_input(payload):
    from backend.app.infrastructure.idempotency import request_key
    fields = ('requirement_id', 'document_id', 'draft_id', 'expected_version', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    return DraftCommandInput(*(strict_integer(data[field], field) for field in fields[:-1]), request_key(data['idempotency_key']))


complete_manual_draft_input = cancel_manual_draft_input


def cancel_manual_draft_result(requirement_id, document_id, manual_draft_id):
    return {'requirement_id': strict_integer(requirement_id, 'requirement_id'),
        'document_id': strict_integer(document_id, 'document_id'),
        'manual_draft_id': strict_integer(manual_draft_id, 'manual_draft_id'), 'cancelled': True}


@dataclass(frozen=True)
class SaveManualDraftInput(DraftCommandInput):
    markdown_content: str
    block_state_json: dict

    def business_input(self):
        return {**super().business_input(), 'markdown_content': self.markdown_content, 'block_state_json': self.block_state_json}


def save_manual_draft_input(payload):
    from backend.app.shared.validation import text_value, reject
    from backend.app.infrastructure.idempotency import request_key, canonical_input
    fields = ('requirement_id', 'document_id', 'draft_id', 'expected_version', 'idempotency_key', 'markdown_content', 'block_state_json')
    data = object_fields(payload, 'body', fields, fields)
    markdown = text_value(data['markdown_content'], 'markdown_content')
    if type(data['block_state_json']) is not dict:
        reject('block_state_json', 'INVALID_TYPE', '必须是JSON对象')
    try:
        canonical_input({'markdown_content': markdown, 'block_state_json': data['block_state_json']})
    except (ValueError, UnicodeError, RecursionError):
        reject('block_state_json', 'INVALID_FORMAT', '正文与快照必须使用合法JSON和Unicode')
    return SaveManualDraftInput(*(strict_integer(data[field], field) for field in fields[:4]), request_key(data['idempotency_key']), markdown, data['block_state_json'])


save_manual_draft_result = get_manual_draft_result


def document_effect(value):
    fields = ('document_id', 'before_content_version', 'after_content_version', 'revision_id', 'result')
    data = object_fields(value, 'document_effect', fields, fields)
    for field in ('document_id', 'after_content_version', 'revision_id'):
        strict_integer(data[field], field)
    if data['before_content_version'] is not None:
        strict_integer(data['before_content_version'], 'before_content_version')
    kind = strict_enum(data['result'], 'result', ('CREATED', 'UPDATED', 'NO_CHANGE'))
    before, after = data['before_content_version'], data['after_content_version']
    if (kind == 'CREATED' and (before is not None or after != 1)) or (kind == 'UPDATED' and (before is None or after != before + 1)) or (kind == 'NO_CHANGE' and before != after):
        raise ValueError('Contradictory document effect')
    return dict(data)


complete_manual_draft_result = document_effect

DOCUMENT_SUMMARY_FIELDS = ('id', 'requirement_id', 'name', 'document_kind', 'document_type',
    'metadata_version', 'content_version', 'current_revision_id', 'confirmed_revision_id',
    'archived_at', 'updated_at', 'source_status')


def document_summary(value):
    from backend.app.shared.validation import strict_integer, strict_enum, raw_text
    from backend.app.documents.snapshot import _time
    if type(value) is not dict or set(value) != set(DOCUMENT_SUMMARY_FIELDS):
        raise ValueError('Invalid document summary fields')
    data = dict(value)
    for field in ('id', 'requirement_id', 'metadata_version', 'content_version', 'current_revision_id'):
        strict_integer(data[field], field)
    if data['confirmed_revision_id'] is not None:
        strict_integer(data['confirmed_revision_id'], 'confirmed_revision_id')
    raw_text(data['name'], 'name', 1, 80)
    strict_enum(data['document_kind'], 'document_kind', ('REQUIREMENT_BRIEF', 'DESIGN', 'SPECIFICATION'))
    strict_enum(data['document_type'], 'document_type', ('CURRENT',))
    strict_enum(data['source_status'], 'source_status', ('UNCHANGED', 'UPDATED', 'UNAVAILABLE'))
    _time(data['updated_at'])
    if data['archived_at'] is not None:
        _time(data['archived_at'])
    return data


DOCUMENT_KINDS = ('REQUIREMENT_BRIEF', 'DESIGN', 'SPECIFICATION')


def document_name(value):
    from backend.app.shared.validation import ordinary_text, reject
    name = ordinary_text(value, 'name', 1, 80, multiline=False)
    try:
        name.encode('utf-8')
    except UnicodeEncodeError:
        reject('name', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return name


@dataclass(frozen=True)
class CreateDocumentInput:
    requirement_id: int
    name: str
    document_kind: str
    template_ref: dict | None
    idempotency_key: str

    def business_input(self):
        return {field: getattr(self, field) for field in ('requirement_id', 'name', 'document_kind', 'template_ref')}


def create_document_input(payload):
    from backend.app.infrastructure.idempotency import request_key
    from backend.app.shared.validation import raw_text, reject
    import re
    fields = ('requirement_id', 'name', 'document_kind', 'template_ref', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    reference = data['template_ref']
    if reference is not None:
        reference = object_fields(reference, 'template_ref', ('key', 'version', 'digest'), ('key', 'version', 'digest'))
        for key in ('key', 'version'):
            raw_text(reference[key], 'template_ref.' + key, 1, 200)
            try:
                reference[key].encode('utf-8')
            except UnicodeEncodeError:
                reject('template_ref.' + key, 'INVALID_FORMAT', '必须使用有效Unicode文本')
        if type(reference['digest']) is not str or re.fullmatch('[0-9a-f]{64}', reference['digest']) is None:
            reject('template_ref.digest', 'INVALID_FORMAT', '必须使用资源的SHA-256摘要')
    return CreateDocumentInput(strict_integer(data['requirement_id'], 'requirement_id'), document_name(data['name']),
        strict_enum(data['document_kind'], 'document_kind', DOCUMENT_KINDS), reference, request_key(data['idempotency_key']))


@dataclass(frozen=True)
class DocumentMetadataInput:
    document_id: int
    expected_metadata_version: int
    change: dict
    idempotency_key: str

    def business_input(self):
        return {field: getattr(self, field) for field in ('document_id', 'expected_metadata_version', 'change')}


def document_metadata_input(payload):
    from backend.app.infrastructure.idempotency import request_key
    fields = ('document_id', 'expected_metadata_version', 'change', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    change = object_fields(data['change'], 'change', ('type', 'name', 'expected_content_version', 'revision_id'), ('type',))
    kind = strict_enum(change['type'], 'change.type', ('RENAME', 'ARCHIVE', 'RESTORE', 'CONFIRM'))
    allowed = {'RENAME': ('type', 'name'), 'ARCHIVE': ('type',), 'RESTORE': ('type',), 'CONFIRM': ('type', 'expected_content_version', 'revision_id')}[kind]
    change = dict(object_fields(change, 'change', allowed, allowed))
    if kind == 'RENAME':
        change['name'] = document_name(change['name'])
    elif kind == 'CONFIRM':
        for field in ('expected_content_version', 'revision_id'):
            change[field] = strict_integer(change[field], 'change.' + field)
    return DocumentMetadataInput(strict_integer(data['document_id'], 'document_id'),
        strict_integer(data['expected_metadata_version'], 'expected_metadata_version'), change,
        request_key(data['idempotency_key']))


def document_view(value):
    fields = (*DOCUMENT_SUMMARY_FIELDS, 'markdown_content', 'block_state_json', 'template_ref', 'created_at')
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('Invalid DocumentView fields')
    from backend.app.shared.http_projection import snapshot_pair
    summary = document_summary({key: value[key] for key in DOCUMENT_SUMMARY_FIELDS})
    _time(value['created_at'])
    if value['created_at'] > summary['updated_at']:
        raise ValueError('Invalid document chronology')
    state = snapshot_pair(value['markdown_content'], value['block_state_json'])
    if value['template_ref'] is not None:
        from backend.app.requirements.discussion import discussion_resources
        discussion_resources().validate('ResourceRef', value['template_ref'])
    return {**value, **summary, 'block_state_json': state}
