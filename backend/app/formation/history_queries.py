"""Bounded immutable history reads on one database snapshot, with frozen event upper bounds."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import (
    InvalidInput,
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .cursors import decode, encode
from .history_contracts import validate
from .types import reference


def read_input(view, payload):
    fields = {
        'events': ('limit', 'cursor', 'step_ref', 'branch_ref'),
        'changes': ('event_id', 'limit', 'cursor'),
        'members': ('event_id', 'change_ordinal', 'limit', 'cursor'),
        'closure': ('event_id', 'kind', 'limit', 'cursor'),
        'evidence': ('event_id', 'owner_kind', 'item_ref', 'limit', 'cursor'),
    }
    if view not in fields:
        raise ValueError('Unregistered immutable read')
    required = tuple(
        key for key in fields[view] if key not in ('limit', 'cursor', 'step_ref', 'branch_ref')
    )
    item = object_fields(payload, 'query', fields[view], required)
    result = {'limit': strict_integer(item.get('limit', 20), 'limit', maximum=100)}
    if 'cursor' in item:
        result['cursor'] = raw_text(item['cursor'], 'cursor', 1, 4096)
    for name in ('event_id', 'change_ordinal'):
        if name in item:
            result[name] = strict_integer(item[name], name)
    for name in ('step_ref', 'branch_ref'):
        if name in item:
            result[name] = reference(item[name], name, name.removesuffix('_ref').upper())
    if view == 'closure':
        result['kind'] = strict_enum(item['kind'], 'kind', ('RESULT', 'ISSUE', 'BRANCH'))
    if view == 'evidence':
        result['owner_kind'] = strict_enum(
            item['owner_kind'], 'owner_kind', ('RESULT', 'ISSUE', 'BRANCH')
        )
        result['item_ref'] = reference(item['item_ref'], 'item_ref', result['owner_kind'])
    return result


def _event(connection, document_id, event_id):
    row = connection.execute(
        'SELECT payload_json FROM document_change_audits WHERE document_id=? AND id=?',
        (document_id, event_id),
    ).fetchone()
    if row is None:
        raise Rejected('NOT_FOUND')
    payload = strict_json_object(row[0])
    if 'formation_event_type' not in payload:
        raise Rejected('NOT_FOUND')
    event = validate('EventView', payload['event'])
    if (
        event['document_id'] != document_id
        or event['event_id'] != event_id
        or event['action'] != payload['formation_event_type']
    ):
        raise ValueError('Stored history event identity differs')
    return event


def closure_head(connection, document_id, event_id):
    row = connection.execute(
        'SELECT * FROM formation_closures WHERE document_id=? AND event_id=?',
        (document_id, event_id),
    ).fetchone()
    if row is None:
        raise Rejected('NOT_FOUND')
    return validate(
        'ClosureHead', {key: value for key, value in dict(row).items() if key != 'document_id'}
    )


def _filters(request):
    return {key: value for key, value in request.items() if key not in ('limit', 'cursor')}


def _anchor(request, document_id, view):
    if 'cursor' not in request:
        return None
    anchor = decode(request['cursor'], document_id, view, _filters(request))
    fields = ('upper_event_id', 'before_event_id') if view == 'events' else ('after_ordinal',)
    object_fields(anchor, 'cursor.anchor', fields, fields)
    for name in fields:
        strict_integer(anchor[name], 'cursor.anchor.' + name)
    if view == 'events' and anchor['before_event_id'] > anchor['upper_event_id']:
        reject('cursor', 'INVALID_FORMAT', '事件游标超出冻结上界')
    return anchor


def _result(document_id, view, request, rows, data, schema, anchor):
    has_more = len(rows) > request['limit']
    data['items'] = rows[: request['limit']]
    cursor = (
        encode(document_id, view, _filters(request), anchor(data['items'][-1]))
        if has_more
        else None
    )
    return {
        'value': validate(schema, data),
        'pagination': {'page_size': request['limit'], 'has_more': has_more, 'next_cursor': cursor},
    }


def _events(connection, document_id, request, anchor):
    clauses = ['e.document_id=?', "json_type(e.payload_json,'$.formation_event_type')='text'"]
    parameters = [document_id]
    for name, kind in (('step_ref', 'STEP'), ('branch_ref', 'BRANCH')):
        if name in request:
            clauses.append(
                'EXISTS(SELECT 1 FROM formation_event_refs r JOIN document_change_audits related '
                'ON related.id=r.event_id AND related.document_id=r.document_id '
                'WHERE r.document_id=e.document_id AND r.kind=? AND r.ref=? AND '
                "json_extract(related.payload_json,'$.event.batch_ref')=json_extract(e.payload_json,'$.event.batch_ref'))"
            )
            parameters.extend((kind, request[name]))
    where = ' AND '.join(clauses)
    upper = (
        connection.execute(
            'SELECT max(e.id) FROM document_change_audits e WHERE ' + where, parameters
        ).fetchone()[0]
        if anchor is None
        else anchor['upper_event_id']
    )
    total = (
        connection.execute(
            'SELECT count(*) FROM document_change_audits e WHERE ' + where + ' AND e.id<=?',
            (*parameters, upper),
        ).fetchone()[0]
        if upper is not None
        else 0
    )
    before = None if anchor is None else anchor['before_event_id']
    rows = []
    if upper is not None:
        restriction = '' if before is None else ' AND e.id<?'
        values = (*parameters, upper) if before is None else (*parameters, upper, before)
        identities = connection.execute(
            'SELECT e.id FROM document_change_audits e WHERE '
            + where
            + ' AND e.id<=?'
            + restriction
            + ' ORDER BY e.id DESC LIMIT ?',
            (*values, request['limit'] + 1),
        )
        rows = [_event(connection, document_id, row[0]) for row in identities]
    return _result(
        document_id,
        'events',
        request,
        rows,
        {'document_id': document_id, 'upper_event_id': upper, 'total': total},
        'EventPage',
        lambda row: {'upper_event_id': upper, 'before_event_id': row['event_id']},
    )


def _changes(connection, document_id, request, after):
    event_id = request['event_id']
    total = connection.execute(
        'SELECT count(*) FROM formation_event_changes WHERE document_id=? AND event_id=?',
        (document_id, event_id),
    ).fetchone()[0]
    rows = []
    for row in connection.execute(
        'SELECT * FROM formation_event_changes WHERE document_id=? AND event_id=? AND ordinal>? ORDER BY ordinal LIMIT ?',
        (document_id, event_id, after, request['limit'] + 1),
    ):
        rows.append(
            {
                'ordinal': row['ordinal'],
                'entity_kind': row['entity_kind'],
                'entity_ref': row['entity_ref'],
                'before': None
                if row['before_json'] is None
                else strict_json_loads(row['before_json']),
                'after': None
                if row['after_json'] is None
                else strict_json_loads(row['after_json']),
                'member_changes': {'count': row['member_count'], 'digest': row['member_digest']},
            }
        )
    return rows, {'document_id': document_id, 'event_id': event_id, 'total': total}, 'ChangePage'


def _members(connection, document_id, request, after):
    event_id, change = request['event_id'], request['change_ordinal']
    owner = connection.execute(
        'SELECT member_count,member_digest FROM formation_event_changes WHERE document_id=? AND event_id=? AND ordinal=?',
        (document_id, event_id, change),
    ).fetchone()
    if owner is None:
        raise Rejected('NOT_FOUND')
    rows = [
        {
            'ordinal': row['ordinal'],
            'collection': row['collection'],
            'member_key': row['member_key'],
            'before': None if row['before_json'] is None else strict_json_loads(row['before_json']),
            'after': None if row['after_json'] is None else strict_json_loads(row['after_json']),
        }
        for row in connection.execute(
            'SELECT * FROM formation_event_members WHERE document_id=? AND event_id=? AND change_ordinal=? '
            'AND ordinal>? ORDER BY ordinal LIMIT ?',
            (document_id, event_id, change, after, request['limit'] + 1),
        )
    ]
    return (
        rows,
        {
            'document_id': document_id,
            'event_id': event_id,
            'change_ordinal': change,
            'total': owner['member_count'],
            'digest': owner['member_digest'],
        },
        'MemberChangePage',
    )


def _closure(connection, document_id, request, after):
    event_id, kind = request['event_id'], request['kind']
    head = closure_head(connection, document_id, event_id)
    rows = [
        strict_json_object(row[0])
        for row in connection.execute(
            'SELECT payload_json FROM formation_closure_items WHERE event_id=? AND kind=? AND ordinal>? ORDER BY ordinal LIMIT ?',
            (event_id, kind, after, request['limit'] + 1),
        )
    ]
    return (
        rows,
        {
            'document_id': document_id,
            'event_id': event_id,
            'closure': head,
            'kind': kind,
            'total': head[kind.lower() + '_count'],
        },
        'ClosureItemPage',
    )


def _evidence(connection, document_id, request, after):
    event_id, kind, ref = request['event_id'], request['owner_kind'], request['item_ref']
    closure_head(connection, document_id, event_id)
    owner = connection.execute(
        'SELECT payload_json FROM formation_closure_items WHERE event_id=? AND kind=? AND item_ref=?',
        (event_id, kind, ref),
    ).fetchone()
    if owner is None:
        raise Rejected('NOT_FOUND')
    owner = strict_json_object(owner[0])
    rows = [
        strict_json_object(row[0])
        for row in connection.execute(
            'SELECT payload_json FROM formation_closure_evidence WHERE event_id=? AND owner_kind=? AND item_ref=? '
            'AND ordinal>? ORDER BY ordinal LIMIT ?',
            (event_id, kind, ref, after, request['limit'] + 1),
        )
    ]
    if kind != 'RESULT' and any(row['kind'] != 'SOURCE' for row in rows):
        raise ValueError('Non-result closure evidence cannot contain artifact ranges')
    return (
        rows,
        {
            'document_id': document_id,
            'event_id': event_id,
            'owner_kind': kind,
            'item_ref': ref,
            'total': owner['evidence_count'],
            'digest': owner['evidence_digest'],
        },
        'ClosureEvidencePage',
    )


def read_history(database, requirement_id, document_id, view, payload):
    try:
        strict_integer(requirement_id, 'requirement_id')
        strict_integer(document_id, 'document_id')
        request = read_input(view, payload)
        anchor = _anchor(request, document_id, view)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            if (
                RequirementRepository(connection).get_for_document(requirement_id, document_id)
                is None
            ):
                raise Rejected('NOT_FOUND')
            from .repository import FormationRepository

            FormationRepository(connection).head(document_id, required=True)
            if view == 'events':
                data = _events(connection, document_id, request, anchor)
            else:
                _event(connection, document_id, request['event_id'])
                after = 0 if anchor is None else anchor['after_ordinal']
                handler = {
                    'changes': _changes,
                    'members': _members,
                    'closure': _closure,
                    'evidence': _evidence,
                }[view]
                rows, value, schema = handler(connection, document_id, request, after)
                data = _result(
                    document_id,
                    view,
                    request,
                    rows,
                    value,
                    schema,
                    lambda row: {'after_ordinal': row['ordinal']},
                )
        return {'code': 'READ_OK', 'data': data, 'details': None}
    except Rejected as error:
        return {'code': error.code, 'data': None, 'details': error.details}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except (ValueError, TypeError, LookupError, RuntimeError):
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
