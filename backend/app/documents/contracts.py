"""APP-DOC-QUERY-C01/C02 exact document read models and snapshot gates."""
from typing import Mapping, Any

from backend.app.shared.validation import MISSING, strict_enum, strict_integer, strict_json_object
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


def get_manual_draft_result(row: Mapping[str, Any], source_verifier: SourceVerifier) -> dict:
    data = document_read_model(row, source_verifier)
    if data['document_type'] != 'MANUAL_DRAFT':
        raise ValueError('Draft read must not project current content')
    return data
