"""Read-only ADJUST_PATH preview: same full graph/source preparation, no allocations or writes."""

import re

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import (
    InvalidInput,
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
)

from .artifact_links import verify_links
from .cursors import decode, encode
from .native_contracts import native_command
from .path_commands import load_input
from .preview_contracts import validate
from .preview_projection import affected_items, reference_labels, warnings
from .proposal_binding import digest
from .read_context import ReadContext
from .read_queries import path_changed


def preview_input(payload):
    fields = ('expected_discussion_version', 'discussion_command', 'section', 'limit', 'cursor')
    item = object_fields(payload, 'body', fields, fields[:2])
    command = native_command(item['discussion_command'])
    if command['action'] != 'ADJUST_PATH':
        reject('discussion_command.action', 'INVALID_ENUM', '预览只接受完整路线调整')
    result = {
        'expected_discussion_version': strict_integer(
            item['expected_discussion_version'], 'expected_discussion_version'
        ),
        'discussion_command': command,
        'limit': strict_integer(item.get('limit', 20), 'limit', maximum=100),
        'section': None
        if 'section' not in item
        else strict_enum(item['section'], 'section', ('AFFECTED', 'WARNINGS')),
    }
    if 'cursor' in item:
        if result['section'] is None:
            reject('section', 'REQUIRED', '使用分页游标时必须指定影响或提示区域')
        result['cursor'] = raw_text(item['cursor'], 'cursor', 1, 4096)
    return result


def input_digest(request):
    return digest(
        {key: request[key] for key in ('expected_discussion_version', 'discussion_command')}
    )


def read_anchor(request, document_id):
    if 'cursor' not in request:
        return None
    section = request['section']
    anchor = decode(request['cursor'], document_id, 'path-preview', {'section': section})
    fields = (
        'discussion_version',
        'formation_version',
        'content_version',
        'input_digest',
        'after_ordinal',
    )
    object_fields(anchor, 'cursor.anchor', fields, fields)
    for name in ('discussion_version', 'formation_version', 'content_version', 'after_ordinal'):
        strict_integer(anchor[name], 'cursor.' + name)
    if (
        type(anchor['input_digest']) is not str
        or re.fullmatch(r'[0-9a-f]{64}', anchor['input_digest']) is None
    ):
        reject('cursor', 'INVALID_FORMAT', '预览游标摘要不合法')
    return anchor


def slice_rows(produce, section, request, document_id, versions, anchor):
    after = anchor['after_ordinal'] if anchor is not None and request['section'] == section else 0
    selected, total = [], 0
    for row in produce():
        total += 1
        if row['ordinal'] != total:
            raise ValueError('Preview ordinals must be complete and deterministic')
        if total > after and len(selected) < request['limit']:
            selected.append(row)
    has_more = bool(selected) and selected[-1]['ordinal'] < total
    cursor = (
        encode(
            document_id,
            'path-preview',
            {'section': section},
            {
                **versions,
                'input_digest': input_digest(request),
                'after_ordinal': selected[-1]['ordinal'],
            },
        )
        if has_more
        else None
    )
    return {'items': selected, 'total': total, 'has_more': has_more, 'next_cursor': cursor}


def prepare_preview(connection, root, request, resources, anchor):
    command = request['discussion_command']
    if anchor is not None and anchor['input_digest'] != input_digest(request):
        path_changed()
    if root['discussion_version'] != request['expected_discussion_version']:
        if anchor is not None:
            path_changed()
        raise Rejected(
            'DISCUSSION_VERSION_CONFLICT',
            details={
                'expected_version': request['expected_discussion_version'],
                'actual_version': root['discussion_version'],
                'resource_kind': 'RequirementDocument',
                'resource_id': root['assistant_document_id'],
            },
        )
    try:
        document, before, _, plan = load_input(connection, root, command)
    except Rejected as error:
        if anchor is not None and error.code in (
            'DISCUSSION_VERSION_CONFLICT',
            'CONTENT_VERSION_CONFLICT',
        ):
            path_changed()
        raise
    versions = {
        'discussion_version': root['discussion_version'],
        'formation_version': before[0]['version'],
        'content_version': document['content_version'],
    }
    if anchor is not None and any(anchor[name] != value for name, value in versions.items()):
        path_changed()
    for change in plan.changes:
        if change['type'] == 'SET_GOAL':
            verify_source_refs(
                connection, root['id'], change['source_refs'], resources=resources.collaboration
            )
    if plan.links:
        verify_links(connection, root, plan.links, resources)
    context = ReadContext(connection, root, resources)
    value = {
        'document_id': root['assistant_document_id'],
        **versions,
        'changes_digest': digest(
            {'changes': command['changes'], 'result_routes': command['result_routes']}
        ),
        'affected_items': slice_rows(
            lambda: affected_items(before, plan),
            'AFFECTED',
            request,
            context.document_id,
            versions,
            anchor,
        ),
        'warnings': slice_rows(
            lambda: warnings(context, before, plan, command['based_on_proposal']),
            'WARNINGS',
            request,
            context.document_id,
            versions,
            anchor,
        ),
        'result_routes': command['result_routes'],
        'reference_map': reference_labels(plan),
    }
    return validate(value)


def preview_path(database, requirement_id, document_id, payload, *, catalog=None):
    try:
        strict_integer(requirement_id, 'requirement_id')
        strict_integer(document_id, 'document_id')
        request = preview_input(payload)
        anchor = read_anchor(request, document_id)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        resources = ResourceCatalog() if catalog is None else catalog
        with database.transaction() as connection:
            root = RequirementRepository(connection).get_for_document(requirement_id, document_id)
            if root is None:
                raise Rejected('NOT_FOUND')
            value = prepare_preview(connection, root, request, resources, anchor)
        return {'code': 'READ_OK', 'data': value, 'details': None}
    except InvalidInput:
        return {'code': 'FORMATION_INVALID', 'data': None, 'details': None}
    except Rejected as error:
        return {
            'code': 'FORMATION_INVALID' if error.code == 'SOURCE_INVALID' else error.code,
            'data': None,
            'details': None if error.code == 'SOURCE_INVALID' else error.details,
        }
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except (ValueError, TypeError, LookupError, RuntimeError):
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
