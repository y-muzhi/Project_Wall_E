"""Strict public program receipt projection; private publication proofs never escape."""

from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_boolean, strict_enum, strict_integer

from .types import array, nullable, reference

RECEIPT_FIELDS = (
    'schema',
    'processing',
    'requirement_id',
    'document_id',
    'discussion_version',
    'formation_version',
    'content_version',
    'operation',
    'result',
    'user_message_id',
    'effects',
    'event_ids',
    'reference_map',
)


def program_receipt(value):
    item = exact(value, RECEIPT_FIELDS)
    strict_enum(item['schema'], 'schema', ('formation_program_receipt_v21_1',))
    strict_enum(item['processing'], 'processing', ('PROGRAM',))
    for name in (
        'requirement_id',
        'document_id',
        'discussion_version',
        'formation_version',
        'content_version',
    ):
        strict_integer(item[name], name)
    operation = strict_enum(
        item['operation'],
        'operation',
        ('NATIVE_FORMATION', 'STAGED_WRITE', 'FORMATION_PATH_CHANGE'),
    )
    result = strict_enum(item['result'], 'result', ('APPLIED', 'NO_CHANGE'))
    nullable(item['user_message_id'], 'user_message_id', strict_integer)
    effects = exact(
        item['effects'],
        ('content_changed', 'revision_id', 'formation_changed', 'proposal_disposition'),
    )
    for name in ('content_changed', 'formation_changed'):
        strict_boolean(effects[name], name)
    nullable(effects['revision_id'], 'revision_id', strict_integer)
    nullable(
        effects['proposal_disposition'],
        'proposal_disposition',
        lambda v, f: strict_enum(v, f, ('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED')),
    )
    if effects['content_changed'] != (effects['revision_id'] is not None):
        raise ValueError('Only an actual content effect returns its Revision')
    event_ids = array(item['event_ids'], 'event_ids', strict_integer, maximum=None)
    if len(set(event_ids)) != len(event_ids):
        raise ValueError('Receipt repeats an event')
    mappings = []
    seen = set()
    resolved = set()
    for row in array(
        item['reference_map'],
        'reference_map',
        lambda v, f: exact(v, ('temp_ref', 'resolved_ref')),
        maximum=None,
    ):
        kind = 'STEP' if row['temp_ref'].startswith('new_step_') else 'RESULT'
        reference(row['temp_ref'], 'temp_ref', 'TEMP_' + kind)
        reference(row['resolved_ref'], 'resolved_ref', kind)
        if row['temp_ref'] in seen or row['resolved_ref'] in resolved:
            raise ValueError('Receipt reference mapping is not one to one')
        seen.add(row['temp_ref'])
        resolved.add(row['resolved_ref'])
        mappings.append(row)
    if result == 'NO_CHANGE' and (
        item['user_message_id'] is not None
        or event_ids
        or mappings
        or effects['content_changed']
        or effects['formation_changed']
        or effects['proposal_disposition'] is not None
    ):
        raise ValueError('No-change receipt cannot invent effects')
    if result == 'APPLIED' and item['user_message_id'] is None:
        raise ValueError('Applied program commands require their actual user message')
    if operation == 'NATIVE_FORMATION' and effects['content_changed']:
        raise ValueError('Native commands do not write body content')
    return {**item, 'effects': effects, 'event_ids': event_ids, 'reference_map': mappings}
