"""Exact I20 batch/suggestion projections, without fresh-target mutation."""
from functools import lru_cache
import json
from backend.app.documents.snapshot import _time
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import MISSING, object_fields, strict_integer, strict_enum, strict_json_object, raw_text
from dataclasses import dataclass
from backend.app.infrastructure.idempotency import request_key

METADATA_FIELDS = ('id', 'requirement_id', 'guide_run_id', 'source_type', 'source_id', 'title', 'summary', 'status', 'completion_result', 'error_message', 'base_content_version', 'applied_content_version', 'created_at', 'completed_at', 'updated_at')
SUGGESTION_FIELDS = ('id', 'batch_id', 'order_no', 'title', 'explanation', 'impact', 'patch_operation', 'target_ref', 'selector', 'original_content', 'proposed_markdown', 'proposed_data', 'user_edited_content', 'status', 'validation_status', 'validation_error', 'created_at', 'decided_at', 'updated_at')
DECISIONS = ('PENDING', 'ACCEPTED', 'REJECTED', 'EDITED')


def get_batch_input(value: object = MISSING) -> int:
    return strict_integer(value, 'batch_id')


def _detached(value):
    return json.loads(canonical_input(value))


@lru_cache(maxsize=1)
def _protocol():
    # Only immutable signed program resources are cached, never business rows.
    return ResourceCatalog().freeze('MODIFY', 'USER_INSTRUCTION')


def batch_metadata(data: object) -> dict:
    value = object_fields(data, 'batch', METADATA_FIELDS, METADATA_FIELDS)
    for field in ('id', 'requirement_id', 'guide_run_id', 'base_content_version'): strict_integer(value[field], field)
    strict_enum(value['source_type'], 'source_type', ('USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT'))
    if value['source_type'] == 'USER_INSTRUCTION':
        if value['source_id'] is not None: raise ValueError('USER_INSTRUCTION has no source identity')
    else: strict_integer(value['source_id'], 'source_id')
    raw_text(value['title'], 'title', 1); raw_text(value['summary'], 'summary', 1)
    strict_enum(value['status'], 'status', ('PENDING', 'COMPLETED', 'DISCARDED'))
    created, updated = _time(value['created_at']), _time(value['updated_at'])
    if created > updated or (value['status'] != 'PENDING') != (value['completed_at'] is not None):
        raise ValueError('Batch event chronology is inconsistent')
    if value['completed_at'] is not None and not created <= _time(value['completed_at']) <= updated:
        raise ValueError('Batch completion time is outside its lifetime')
    if value['status'] == 'COMPLETED': strict_enum(value['completion_result'], 'completion_result', ('CHANGES_APPLIED', 'NO_CHANGE'))
    elif value['completion_result'] is not None: raise ValueError('Only completed batches have a completion result')
    if value['completion_result'] == 'CHANGES_APPLIED':
        if strict_integer(value['applied_content_version'], 'applied_content_version') != value['base_content_version']+1:
            raise ValueError('One batch application increments its baseline version once')
    elif value['applied_content_version'] is not None: raise ValueError('Unchanged/unapplied batches have no adopted version')
    if value['error_message'] is not None: raw_text(value['error_message'], 'error_message', 1)
    return _detached(value)


def suggestion_read_model(data: object, *, protocol=None) -> dict:
    value = object_fields(data, 'suggestion', SUGGESTION_FIELDS, SUGGESTION_FIELDS)
    for field in ('id', 'batch_id', 'order_no'): strict_integer(value[field], field)
    resource = _protocol() if protocol is None else protocol
    resource.validate_patch({field: value[field] for field in ('title', 'explanation', 'impact', 'patch_operation', 'target_ref', 'original_content', 'proposed_markdown')} |
        {'selector_json': value['selector'], 'proposed_data_json': value['proposed_data']})
    strict_enum(value['status'], 'status', DECISIONS); strict_enum(value['validation_status'], 'validation_status', ('VALID', 'INVALID'))
    if value['validation_status'] == 'INVALID': raw_text(value['validation_error'], 'validation_error', 1)
    elif value['validation_error'] is not None: raise ValueError('Valid suggestions have no validation error')
    if value['status'] == 'EDITED':
        raw_text(value['user_edited_content'], 'user_edited_content', 1, 100000)
        if value['patch_operation'] == 'DELETE_BLOCK': raise ValueError('Delete suggestions cannot be edited')
    elif value['user_edited_content'] is not None: raise ValueError('Other decisions clear edited content')
    created, updated = _time(value['created_at']), _time(value['updated_at'])
    if created > updated or (value['status'] != 'PENDING') != (value['decided_at'] is not None):
        raise ValueError('Suggestion decision chronology is inconsistent')
    if value['decided_at'] is not None and not created <= _time(value['decided_at']) <= updated:
        raise ValueError('Suggestion decision time is outside its lifetime')
    return _detached(value)


def suggestion_from_row(row, *, protocol=None) -> dict:
    value = {field: row[field] for field in SUGGESTION_FIELDS if field not in ('target_ref', 'selector', 'proposed_data')}
    for public, stored in (('target_ref', 'target_ref_json'), ('selector', 'selector_json'), ('proposed_data', 'proposed_data_json')):
        value[public] = None if row[stored] is None else strict_json_object(row[stored], stored)
    return suggestion_read_model(value, protocol=protocol)


def suggestion_counts(items: list[dict]) -> dict:
    result = {status.lower(): sum(item['status'] == status for item in items) for status in DECISIONS}
    return {'total': len(items), **result}


def counts_model(data: object) -> dict:
    fields = ('total', 'pending', 'accepted', 'rejected', 'edited')
    value = object_fields(data, 'counts', fields, fields)
    for field in fields: strict_integer(value[field], field, minimum=0)
    if not 1 <= value['total'] <= 100 or value['total'] != sum(value[field] for field in fields[1:]):
        raise ValueError('Aggregate counts must include every suggestion exactly once')
    return dict(value)


def batch_read_model(data: object, *, protocol=None) -> dict:
    fields = (*METADATA_FIELDS, 'suggestions', 'counts')
    value = object_fields(data, 'batch', fields, fields)
    metadata = batch_metadata({field: value[field] for field in METADATA_FIELDS})
    if type(value['suggestions']) is not list or not 1 <= len(value['suggestions']) <= 100:
        raise ValueError('A stored batch must contain all 1..100 suggestions')
    items = [suggestion_read_model(item, protocol=protocol) for item in value['suggestions']]
    if any(item['batch_id'] != value['id'] or item['created_at'] < value['created_at'] or item['updated_at'] > value['updated_at'] for item in items):
        raise ValueError('Suggestion ownership or aggregate activity time is inconsistent')
    order = [(item['order_no'], item['id']) for item in items]
    if order != sorted(order) or len({item['id'] for item in items}) != len(items) or len({item['order_no'] for item in items}) != len(items):
        raise ValueError('Suggestions must be distinct in stable order')
    counts = counts_model(value['counts'])
    if counts != suggestion_counts(items): raise ValueError('Batch counts must reflect its complete same-snapshot suggestions')
    return {**metadata, 'suggestions': items, 'counts': dict(counts)}


def get_batch_result(row, suggestions, *, protocol) -> dict:
    metadata = batch_metadata({field: row[field] for field in METADATA_FIELDS})
    items = [suggestion_from_row(item, protocol=protocol) for item in suggestions]
    return batch_read_model({**metadata, 'suggestions': items, 'counts': suggestion_counts(items)}, protocol=protocol)


@dataclass(frozen=True)
class BatchActionInput:
    batch_id: int
    idempotency_key: str

    def business_input(self) -> dict:
        return {'batch_id': self.batch_id}


def discard_batch_input(payload: object) -> BatchActionInput:
    fields = ('batch_id', 'idempotency_key')
    value = object_fields(payload, 'body', fields, fields)
    return BatchActionInput(strict_integer(value['batch_id'], 'batch_id'), request_key(value['idempotency_key'], 'idempotency_key'))


def discard_batch_result(row, items) -> dict:
    metadata = batch_metadata({field: row[field] for field in METADATA_FIELDS})
    if metadata['status'] != 'DISCARDED': raise ValueError('Discard result must reflect the actual batch transition')
    for item in items: strict_enum(item['status'], 'status', DECISIONS)
    return {'code': 'BATCH_DISCARDED', 'data': {'batch': metadata, 'counts': counts_model(suggestion_counts(items))}, 'details': None}
