"""APP-REV-QUERY-C01/C02 input and immutable historical read projections."""
from dataclasses import dataclass
from typing import Any, Mapping

from backend.app.documents.snapshot import SourceVerifier, _time, validate_snapshot
from backend.app.shared.pagination import page_number, page_metadata
from backend.app.shared.validation import (
    MISSING, object_fields, revision_description, strict_enum, strict_integer, strict_json_object,
)

SUMMARY_FIELDS = ('id', 'requirement_id', 'version_no', 'revision_type', 'description', 'source_content_version', 'created_at')


@dataclass(frozen=True)
class ListRevisionsInput:
    requirement_id: int
    page: int


def list_revisions_input(payload: object) -> ListRevisionsInput:
    data = object_fields(payload, 'query', ('requirement_id', 'page'), ('requirement_id',))
    return ListRevisionsInput(strict_integer(data['requirement_id'], 'requirement_id'), page_number(data.get('page', 1)))


def get_revision_input(value: object = MISSING) -> int:
    return strict_integer(value, 'revision_id')


def revision_summary(row: Mapping[str, Any]) -> dict:
    data = {field: row[field] for field in SUMMARY_FIELDS}
    for field in ('id', 'requirement_id', 'version_no', 'source_content_version'):
        strict_integer(data[field], field)
    strict_enum(data['revision_type'], 'revision_type', ('BASELINE', 'MANUAL'))
    if data['revision_type'] == 'BASELINE' and data['version_no'] != 1:
        raise ValueError('Baseline must be version one')
    if data['revision_type'] == 'MANUAL' and data['version_no'] <= 1:
        raise ValueError('Manual revision must follow the baseline')
    if revision_description(data['description']) != data['description']:
        raise ValueError('Persisted revision description is not normalized')
    if data['description'] is not None:
        data['description'].encode('utf-8')
    _time(data['created_at'])
    return data


def list_revisions_result(rows: list[Mapping[str, Any]], page: int, total: int) -> dict:
    return {'items': [revision_summary(row) for row in rows], **page_metadata(page, total)}


def get_revision_result(row: Mapping[str, Any], source_verifier: SourceVerifier) -> dict:
    data = revision_summary(row)
    state = strict_json_object(row['block_state_snapshot_json'], 'block_state_json')
    pair = validate_snapshot(row['markdown_snapshot'], state, source_verifier)
    return {**data, 'markdown_content': pair.parsed.markdown, 'block_state_json': pair.state}
