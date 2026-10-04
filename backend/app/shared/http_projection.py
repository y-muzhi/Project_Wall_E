"""Strict response white lists, independent of persistence relationship checks.

The application already validates actual sources in its read transaction. This
layer checks the projected structure and pair; it never supplies a fake source
verifier or opens a second database snapshot during response conversion.
"""
import re

from backend.app.documents.markdown import parse_markdown
from backend.app.documents.snapshot import FIELDS, Provenance, _time
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.requirements.contracts import READ_FIELDS, LIST_FIELDS, STATUSES, REQUIREMENT_TYPES, requirement_read_model
from backend.app.revisions.contracts import SUMMARY_FIELDS, revision_summary
from .validation import strict_integer, strict_enum, title


def exact(value: object, fields) -> dict:
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('Response fields differ from the registered schema')
    return dict(value)


def requirement(value: object) -> dict:
    return requirement_read_model(exact(value, READ_FIELDS))


def requirement_summary(value: object) -> dict:
    data = exact(value, LIST_FIELDS)
    strict_integer(data['id'], 'id')
    if type(data['requirement_no']) is not str or re.fullmatch(r'REQ[0-9]{6}', data['requirement_no']) is None:
        raise ValueError('Invalid requirement number')
    if title(data['title']) != data['title']:
        raise ValueError('Invalid title')
    strict_enum(data['requirement_type'], 'requirement_type', REQUIREMENT_TYPES)
    strict_enum(data['status'], 'status', STATUSES)
    _time(data['updated_at'])
    return data


def snapshot_pair(markdown: object, value: object) -> dict:
    state = exact(value, ('schema_version', 'next_block_id', 'blocks'))
    if type(state['schema_version']) is not int or state['schema_version'] != 1:
        raise ValueError('Invalid block state version')
    next_id = strict_integer(state['next_block_id'], 'next_block_id')
    parsed = parse_markdown(markdown)
    if type(state['blocks']) is not list or len(state['blocks']) != len(parsed.blocks):
        raise ValueError('Invalid paired block count')
    if len(canonical_input(state).encode('utf-8')) > 4*1024*1024:
        raise ValueError('Block state exceeds capacity')
    identities = set()
    blocks = []
    for value, block in zip(state['blocks'], parsed.blocks):
        metadata = exact(value, FIELDS)
        identity = strict_integer(metadata['block_id'], 'block_id')
        if identity >= next_id or identity in identities:
            raise ValueError('Invalid block identity')
        identities.add(identity)
        if metadata['block_type'] != block.block_type or type(metadata['section_path']) is not list or metadata['section_path'] != list(block.section_path):
            raise ValueError('Block derivatives differ from actual Markdown')
        for prefix in ('created', 'last_modified'):
            origin = Provenance(metadata[prefix+'_by_type'], metadata[prefix+'_source_type'], metadata[prefix+'_source_id'])
            actors = {'TEMPLATE': {'SYSTEM'}, 'GUIDE_RUN': {'AI'}, 'SUGGESTION_BATCH': {'AI', 'USER'}, 'MANUAL_EDIT': {'USER'}}
            if origin.actor not in actors[origin.source_type]:
                raise ValueError('Invalid provenance combination')
        if _time(metadata['created_at']) > _time(metadata['last_modified_at']):
            raise ValueError('Invalid block chronology')
        blocks.append(metadata)
    return {**state, 'blocks': blocks}


def document(value: object, kind: str) -> dict:
    from backend.app.documents.contracts import DOCUMENT_FIELDS
    data = exact(value, DOCUMENT_FIELDS)
    for field in ('id', 'requirement_id', 'content_version'):
        strict_integer(data[field], field)
    if data['document_type'] != kind:
        raise ValueError('Wrong document kind')
    if _time(data['created_at']) > _time(data['updated_at']):
        raise ValueError('Invalid document chronology')
    data['block_state_json'] = snapshot_pair(data['markdown_content'], data['block_state_json'])
    return data


def revision(value: object, *, full: bool = False) -> dict:
    fields = (*SUMMARY_FIELDS, 'markdown_content', 'block_state_json') if full else SUMMARY_FIELDS
    data = exact(value, fields)
    summary = revision_summary({field: data[field] for field in SUMMARY_FIELDS})
    if not full:
        return summary
    return {**summary, 'markdown_content': data['markdown_content'], 'block_state_json': snapshot_pair(data['markdown_content'], data['block_state_json'])}


def page(value: object, item_projection, requested_page: int) -> tuple[dict, dict]:
    data = exact(value, ('items', 'page', 'page_size', 'total', 'total_pages'))
    strict_integer(data['page'], 'page', maximum=100000)
    strict_integer(data['page_size'], 'page_size')
    strict_integer(data['total'], 'total', minimum=0)
    strict_integer(data['total_pages'], 'total_pages', minimum=0)
    if data['page'] != requested_page or data['page_size'] != 20 or data['total_pages'] != (data['total']+19)//20 or type(data['items']) is not list or len(data['items']) != min(20, max(0, data['total']-(data['page']-1)*20)):
        raise ValueError('Pagination contradicts the actual read result')
    return {'items': [item_projection(item) for item in data['items']]}, {field: data[field] for field in ('page', 'page_size', 'total', 'total_pages')}
