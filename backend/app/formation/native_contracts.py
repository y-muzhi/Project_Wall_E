"""Exact native command union, independent from headers and database lookup."""

from backend.app.shared.validation import (
    object_fields,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .path_contracts import ref_array, route_batch
from .types import array, nullable, proposal, reference, sources, text

NATIVE_FIELDS = {
    'START_STEP': ('step_ref',),
    'PAUSE_STEP': ('step_ref',),
    'RESUME_STEP': ('step_ref',),
    'SWITCH_STEP': ('step_ref',),
    'REOPEN_STEP': ('step_ref',),
    'COMPLETE_STEP': (
        'step_ref',
        'expected_definition_version',
        'expected_goal_version',
        'expected_content_version',
        'result_dispositions',
        'issue_dispositions',
        'branch_dispositions',
        'next_step_ref',
    ),
    'ADJUST_PATH': (
        'expected_formation_version',
        'expected_content_version',
        'based_on_proposal',
        'changes',
        'result_routes',
        'reason',
    ),
    'ENTER_BRANCH': ('step_ref', 'branch_ref'),
    'RETURN_FROM_BRANCH': ('branch_ref',),
    'DISPOSE_BRANCH': ('branch_ref', 'disposition', 'reason'),
    'RESUME_BRANCH': (
        'step_ref',
        'branch_ref',
        'expected_branch_status',
        'expected_branch_event_id',
        'enter_after_resume',
    ),
    'RESUME_ISSUE': ('issue_ref',),
    'DEFER_WRITE_PROPOSAL': ('proposal', 'reason'),
    'RESUME_WRITE_PROPOSAL': ('proposal',),
    'WITHDRAW_PROPOSAL_ADJUSTMENT': ('proposal',),
}


def result_disposition(value, field):
    fields = ('result_ref', 'status', 'artifact_refs', 'source_refs')
    item = object_fields(value, field, fields, fields)
    return {
        'result_ref': reference(item['result_ref'], field + '.result_ref', 'RESULT'),
        'status': strict_enum(
            item['status'], field + '.status', ('OUTSTANDING', 'LANDED', 'ANALYZED')
        ),
        'artifact_refs': ref_array(item['artifact_refs'], field + '.artifact_refs', 'ARTIFACT'),
        'source_refs': sources(item['source_refs'], field + '.source_refs'),
    }


def remaining_disposition(value, field, kind):
    fields = ('ref', 'disposition', 'to_step_ref', 'reason')
    item = object_fields(value, field, fields, fields)
    disposition = strict_enum(
        item['disposition'],
        field + '.disposition',
        ('KEEP_OPEN', 'TRANSFER', 'DEFERRED', 'DROPPED'),
    )
    target = nullable(
        item['to_step_ref'], field + '.to_step_ref', lambda v, f: reference(v, f, 'STEP')
    )
    reason = nullable(item['reason'], field + '.reason', text)
    if (disposition == 'TRANSFER') != (target is not None):
        reject(field, 'INVALID_FORMAT', '只有转交处置可以且必须指定目标步骤')
    if disposition in ('DEFERRED', 'DROPPED') and reason is None:
        reject(field + '.reason', 'REQUIRED', '暂缓或放弃必须说明原因')
    return {
        'ref': reference(item['ref'], field + '.ref', kind),
        'disposition': disposition,
        'to_step_ref': target,
        'reason': reason,
    }


def native_command(value, field='discussion_command'):
    keys = ('type', 'action', *(key for fields in NATIVE_FIELDS.values() for key in fields))
    header = object_fields(value, field, keys, ('type', 'action'))
    strict_enum(header['type'], field + '.type', ('FORMATION',))
    action = strict_enum(header['action'], field + '.action', NATIVE_FIELDS)
    fields = ('type', 'action', *NATIVE_FIELDS[action])
    item = object_fields(header, field, fields, fields)
    result = {'type': 'FORMATION', 'action': action}
    for key in NATIVE_FIELDS[action]:
        value, name = item[key], field + '.' + key
        if key in ('changes', 'result_routes'):
            continue
        if key.startswith('expected_') and key != 'expected_branch_status':
            parsed = strict_integer(value, name)
        elif key in ('step_ref', 'next_step_ref'):
            parse = lambda v, f: reference(v, f, 'STEP')
            parsed = (
                nullable(value, name, parse)
                if action == 'SWITCH_STEP' or key == 'next_step_ref'
                else parse(value, name)
            )
        elif key in ('issue_ref', 'branch_ref'):
            parsed = reference(value, name, key.removesuffix('_ref').upper())
        elif key == 'result_dispositions':
            parsed = array(value, name, result_disposition, maximum=20)
        elif key in ('issue_dispositions', 'branch_dispositions'):
            kind = 'ISSUE' if key == 'issue_dispositions' else 'BRANCH'
            parsed = array(
                value, name, lambda v, f, kind=kind: remaining_disposition(v, f, kind), maximum=20
            )
        elif key == 'reason':
            parsed = text(value, name)
        elif key == 'enter_after_resume':
            parsed = strict_boolean(value, name)
        elif key == 'expected_branch_status':
            parsed = strict_enum(value, name, ('DEFERRED', 'RESOLVED'))
        elif key == 'disposition':
            parsed = strict_enum(value, name, ('DEFERRED', 'DROPPED'))
        elif key == 'based_on_proposal':
            parsed = nullable(value, name, proposal)
        elif key == 'proposal':
            parsed = proposal(value, name)
        else:
            raise AssertionError('Unimplemented native field: ' + key)
        result[key] = parsed
    if action == 'ADJUST_PATH':
        result['changes'], result['result_routes'] = route_batch(
            item['changes'], item['result_routes'], field
        )
    if action == 'COMPLETE_STEP':
        pairs = (
            ('result_dispositions', 'result_ref'),
            ('issue_dispositions', 'ref'),
            ('branch_dispositions', 'ref'),
        )
        for name, identity in pairs:
            refs = [item[identity] for item in result[name]]
            if len(refs) != len(set(refs)):
                reject(field + '.' + name, 'INVALID_FORMAT', '同一对象不能重复处置')
    return result
