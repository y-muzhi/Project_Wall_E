"""The fourteen exact PathChange alternatives; unrelated fields are rejected."""

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import object_fields, reject, strict_enum, strict_integer

from .types import (
    MAX_CHANGE_BYTES,
    MAX_CHANGES,
    MAX_RESULTS,
    RESULT_KINDS,
    array,
    nullable,
    path_reference,
    reference,
    sources,
    text,
)

PATH_FIELDS = {
    'SET_GOAL': ('text', 'source_refs'),
    'ADD_STEP': (
        'temp_step_ref',
        'title',
        'expected_results',
        'dependencies',
        'replaces_step_refs',
        'before_step_ref',
    ),
    'RENAME_STEP': ('step_ref', 'title'),
    'MOVE_STEP': ('step_ref', 'before_step_ref'),
    'SET_DEPENDENCIES': ('step_ref', 'dependencies'),
    'UPDATE_RESULT': ('result_ref', 'description'),
    'ADD_RESULT': ('step_ref', 'temp_result_ref', 'description', 'kind'),
    'CANCEL_STEP': ('step_ref', 'replacement_step_refs'),
    'LINK_CONTENT': ('step_ref', 'result_refs', 'revision_id', 'block_ids'),
    'MOVE_ISSUE': ('issue_ref', 'to_step_ref'),
    'SET_BRANCH_RETURN': ('branch_ref', 'return_step_ref'),
    'DISPOSE_ISSUE': ('issue_ref', 'disposition', 'reason'),
    'DISPOSE_BRANCH': ('branch_ref', 'disposition', 'reason'),
    'RESUME_ISSUE': ('issue_ref',),
}


def ref_array(value, field, kind, *, path=False, minimum=0):
    parse = path_reference if path else reference
    return array(
        value, field, lambda v, f: parse(v, f, kind), minimum=minimum, maximum=None, unique=True
    )


def expected_result(value, field):
    fields = ('temp_result_ref', 'description', 'kind')
    item = object_fields(value, field, fields, fields)
    return {
        'temp_result_ref': reference(
            item['temp_result_ref'], field + '.temp_result_ref', 'TEMP_RESULT'
        ),
        'description': text(item['description'], field + '.description'),
        'kind': strict_enum(item['kind'], field + '.kind', RESULT_KINDS),
    }


def path_change(value, field):
    keys = ('type', *(key for keys in PATH_FIELDS.values() for key in keys))
    header = object_fields(value, field, keys, ('type',))
    kind = strict_enum(header['type'], field + '.type', PATH_FIELDS)
    fields = ('type', *PATH_FIELDS[kind])
    item = object_fields(header, field, fields, fields)
    result = {'type': kind}
    for key in PATH_FIELDS[kind]:
        value, name = item[key], field + '.' + key
        if key in ('text', 'description', 'reason'):
            parsed = text(value, name)
        elif key == 'title':
            parsed = text(value, name, 120)
        elif key == 'source_refs':
            parsed = sources(value, name)
        elif key in ('temp_step_ref', 'temp_result_ref'):
            parsed = reference(
                value, name, 'TEMP_STEP' if key == 'temp_step_ref' else 'TEMP_RESULT'
            )
        elif key == 'expected_results':
            parsed = array(value, name, expected_result, minimum=1, maximum=MAX_RESULTS)
        elif key in ('dependencies', 'replacement_step_refs'):
            parsed = ref_array(value, name, 'STEP', path=True)
        elif key == 'replaces_step_refs':
            parsed = ref_array(value, name, 'STEP')
        elif key == 'before_step_ref':
            parsed = nullable(value, name, lambda v, f: path_reference(v, f, 'STEP'))
        elif key in ('to_step_ref', 'return_step_ref'):
            parsed = path_reference(value, name, 'STEP')
        elif key == 'step_ref':
            parser = path_reference if kind in ('ADD_RESULT', 'LINK_CONTENT') else reference
            parsed = parser(value, name, 'STEP')
        elif key in ('result_ref', 'issue_ref', 'branch_ref'):
            parsed = reference(value, name, key.removesuffix('_ref').upper())
        elif key == 'result_refs':
            parsed = ref_array(value, name, 'RESULT', path=True, minimum=1)
        elif key == 'kind':
            parsed = strict_enum(value, name, RESULT_KINDS)
        elif key == 'disposition':
            parsed = strict_enum(value, name, ('DEFERRED', 'DROPPED'))
        elif key == 'revision_id':
            parsed = strict_integer(value, name)
        elif key == 'block_ids':
            parsed = array(value, name, strict_integer, minimum=1, unique=True)
        else:
            raise AssertionError('Unimplemented PathChange field: ' + key)
        result[key] = parsed
    return result


def result_route(value, field):
    fields = ('from_result_ref', 'disposition', 'target_result_refs', 'reason')
    item = object_fields(value, field, fields, fields)
    result = {
        'from_result_ref': reference(item['from_result_ref'], field + '.from_result_ref', 'RESULT'),
        'disposition': strict_enum(
            item['disposition'], field + '.disposition', ('REPLACED', 'NOT_REQUIRED')
        ),
        'target_result_refs': ref_array(
            item['target_result_refs'], field + '.target_result_refs', 'RESULT', path=True
        ),
        'reason': text(item['reason'], field + '.reason'),
    }
    if (result['disposition'] == 'REPLACED') != bool(result['target_result_refs']):
        reject(field, 'INVALID_FORMAT', '成果承接必须有目标，不再需要必须无目标并说明原因')
    return result


def route_batch(changes, result_routes, field='discussion_command'):
    parsed = array(changes, field + '.changes', path_change, minimum=1, maximum=MAX_CHANGES)
    routes = array(result_routes, field + '.result_routes', result_route, maximum=None)
    size = len(canonical_input({'changes': parsed, 'result_routes': routes}).encode('utf-8'))
    if size > MAX_CHANGE_BYTES:
        reject(field, 'TOO_LONG', '本次路线调整超过64KiB')
    refs = [route['from_result_ref'] for route in routes]
    if len(refs) != len(set(refs)):
        reject(field + '.result_routes', 'INVALID_FORMAT', '同一原成果只能处置一次')
    return parsed, routes
