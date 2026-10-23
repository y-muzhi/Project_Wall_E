"""Document-scoped immutable CONTENT history and separate user markers."""
from dataclasses import dataclass
import json
from backend.app.documents.snapshot import _time, validate_snapshot
from backend.app.infrastructure.idempotency import request_key, canonical_input
from backend.app.requirements.discussion import discussion_resources
from backend.app.shared.pagination import page_number, page_metadata
from backend.app.shared.validation import MISSING, object_fields, revision_description, strict_integer

SUMMARY_FIELDS = ('id', 'requirement_id', 'document_id', 'version_no', 'source_content_version', 'created_at', 'change_summary', 'source_refs', 'markers')

@dataclass(frozen=True)
class ListRevisionsInput:
    requirement_id: int
    document_id: int
    page: int

@dataclass(frozen=True)
class CreateManualRevisionInput:
    requirement_id: int
    document_id: int
    expected_version: int
    description: str | None
    idempotency_key: str

    def business_input(self):
        return {field: getattr(self, field) for field in ('requirement_id', 'document_id', 'expected_version', 'description')}

def create_manual_revision_input(payload):
    required = ('requirement_id', 'document_id', 'expected_version', 'idempotency_key')
    data = object_fields(payload, 'body', (*required, 'description'), required)
    description = revision_description(data.get('description'))
    if description is not None:
        from backend.app.comments.contracts import _unicode
        _unicode(description, 'description')
    return CreateManualRevisionInput(*(strict_integer(data[field], field) for field in required[:3]), description, request_key(data['idempotency_key']))

def create_manual_revision_result(value):
    fields = ('revision_id', 'event_id', 'marked')
    data = object_fields(value, 'marker', fields, fields)
    strict_integer(data['revision_id'], 'revision_id'); strict_integer(data['event_id'], 'event_id')
    if data['marked'] is not True:
        raise ValueError('A marker must reference a committed event')
    return dict(data)

def list_revisions_input(payload):
    data = object_fields(payload, 'query', ('requirement_id', 'document_id', 'page'), ('requirement_id', 'document_id'))
    return ListRevisionsInput(strict_integer(data['requirement_id'], 'requirement_id'), strict_integer(data['document_id'], 'document_id'), page_number(data.get('page', 1)))

def get_revision_input(value=MISSING):
    return strict_integer(value, 'revision_id')

def revision_summary(row):
    data = {field: row[field] for field in SUMMARY_FIELDS}
    for field in ('id', 'requirement_id', 'document_id', 'version_no', 'source_content_version'):
        strict_integer(data[field], field)
    if data['version_no'] != data['source_content_version']:
        raise ValueError('A CONTENT version must match its document content version')
    _time(data['created_at'])
    if data['change_summary'] is not None and type(data['change_summary']) is not str:
        raise ValueError('Invalid content change summary')
    if type(data['source_refs']) is not list or type(data['markers']) is not list:
        raise ValueError('History sources and markers must be arrays')
    for ref in data['source_refs']:
        discussion_resources().validate('SourceRef', ref)
    previous, identities = None, set()
    for marker in data['markers']:
        fields = ('event_id', 'description', 'created_at')
        object_fields(marker, 'marker', fields, fields)
        strict_integer(marker['event_id'], 'event_id')
        instant = _time(marker['created_at'])
        order = (instant, marker['event_id'])
        if marker['event_id'] in identities or instant < data['created_at'] or previous is not None and order <= previous:
            raise ValueError('History marker identities or chronology are inconsistent')
        if revision_description(marker['description']) != marker['description']:
            raise ValueError('Marker description must be normalized')
        previous = order
        identities.add(marker['event_id'])
    return json.loads(canonical_input(data))

def list_revisions_result(rows, page, total):
    return {'items': [revision_summary(row) for row in rows], **page_metadata(page, total)}

def get_revision_result(row, source_verifier):
    from backend.app.shared.validation import strict_json_object
    pair = validate_snapshot(row['markdown_snapshot'], strict_json_object(row['block_state_snapshot_json']), source_verifier)
    return {**revision_summary(row), 'markdown_content': pair.parsed.markdown, 'block_state_json': pair.state}
