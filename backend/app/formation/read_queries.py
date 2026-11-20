"""Current entity pages bind cursors to real F and filters, without page-based totals."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import (
    InvalidInput,
    object_fields,
    raw_text,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .availability import action, work_reason
from .cursors import decode, encode
from .read_context import ReadContext
from .read_contracts import validate
from .read_projection import artifact_view, branch_view, issue_view, step_view
from .repository import FormationRepository
from .types import BRANCH_STATUSES, STEP_STATUSES, reference

STATES = {
    'steps': STEP_STATUSES,
    'branches': BRANCH_STATUSES,
    'issues': BRANCH_STATUSES,
    'artifacts': ('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
    'proposals': ('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'),
}
TABLES = {
    'steps': ('formation_steps', 'step_ref', 'status', None),
    'branches': ('formation_branches', 'branch_ref', 'status', 'return_step_ref'),
    'issues': ('formation_issues', 'issue_ref', 'disposition', 'step_ref'),
    'artifacts': ('formation_artifacts', 'artifact_ref', 'freshness', 'step_ref'),
}
PROJECT = {
    'steps': step_view,
    'branches': branch_view,
    'issues': issue_view,
    'artifacts': artifact_view,
}


def path_changed():
    raise Rejected(
        'STATE_CONFLICT', details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None}
    )


def page_input(kind, payload):
    strict_enum(kind, 'kind', STATES)
    fields = ['limit', 'cursor', 'known_f', 'state']
    if kind == 'steps':
        fields.append('include_cancelled')
    elif kind != 'proposals':
        fields.append('step_ref')
    if kind == 'issues':
        fields.append('branch_ref')
    if kind == 'artifacts':
        fields.append('include_superseded')
    item = object_fields(payload, 'query', fields)
    result = {
        'limit': strict_integer(item.get('limit', 20), 'limit', maximum=100),
        'state': None if 'state' not in item else strict_enum(item['state'], 'state', STATES[kind]),
    }
    for name in ('known_f',):
        if name in item:
            result[name] = strict_integer(item[name], name)
    if 'cursor' in item:
        result['cursor'] = raw_text(item['cursor'], 'cursor', 1, 4096)
    if kind == 'steps':
        result['include_cancelled'] = strict_boolean(
            item.get('include_cancelled', False), 'include_cancelled'
        )
    elif kind != 'proposals':
        result['step_ref'] = (
            None if 'step_ref' not in item else reference(item['step_ref'], 'step_ref', 'STEP')
        )
    if kind == 'issues':
        result['branch_ref'] = (
            None
            if 'branch_ref' not in item
            else reference(item['branch_ref'], 'branch_ref', 'BRANCH')
        )
    if kind == 'artifacts':
        result['include_superseded'] = strict_boolean(
            item.get('include_superseded', False), 'include_superseded'
        )
    return result


def filters(request):
    return {
        name: value for name, value in request.items() if name not in ('limit', 'cursor', 'known_f')
    }


def page_anchor(context, kind, request, *, step_order=False, text_order=False):
    if request.get('known_f', context.head['version']) != context.head['version']:
        path_changed()
    if 'cursor' not in request:
        return None
    anchor = decode(request['cursor'], context.document_id, kind, filters(request))
    object_fields(
        anchor, 'cursor.anchor', ('formation_version', 'after'), ('formation_version', 'after')
    )
    strict_integer(anchor['formation_version'], 'cursor.formation_version')
    if anchor['formation_version'] != context.head['version']:
        path_changed()
    if step_order:
        if type(anchor['after']) is not list or len(anchor['after']) != 2:
            reject('cursor', 'INVALID_FORMAT', '步骤游标缺少排序位置')
        strict_integer(anchor['after'][0], 'cursor.position')
        reference(anchor['after'][1], 'cursor.step_ref', 'STEP')
    elif text_order:
        raw_text(anchor['after'], 'cursor.after', 1, 200)
    else:
        strict_integer(anchor['after'], 'cursor.after')
    return anchor['after']


def pack(context, kind, request, rows, total, projector, after):
    has_more = len(rows) > request['limit']
    selected = rows[: request['limit']]
    cursor = (
        encode(
            context.document_id,
            kind,
            filters(request),
            {
                'formation_version': context.head['version'],
                'after': after(selected[-1]),
            },
        )
        if has_more
        else None
    )
    return {
        'value': validate(
            'EntityPage',
            {
                'document_id': context.document_id,
                'formation_version': context.head['version'],
                'kind': kind,
                'items': [projector(context, row) for row in selected],
                'total': total,
            },
        ),
        'pagination': {'page_size': request['limit'], 'has_more': has_more, 'next_cursor': cursor},
    }


def entity_page(context, kind, request):
    if kind == 'proposals':
        from .proposal_views import proposal_view

        after = page_anchor(context, kind, request, text_order=True)
        clauses, parameters = ['document_id=?'], [context.document_id]
        if request['state'] is not None:
            clauses.append('disposition=?')
            parameters.append(request['state'])
        where = ' AND '.join(clauses)
        total = context.connection.execute(
            'SELECT count(*) FROM formation_proposal_index WHERE ' + where, parameters
        ).fetchone()[0]
        if after is not None:
            from backend.app.shared.validation import decimal_integer

            parts = after.split(':', 1)
            if len(parts) != 2:
                reject('cursor', 'INVALID_FORMAT', '提案游标缺少原消息及卡片键')
            message_id = decimal_integer(parts[0], 'cursor.message_id')
            raw_text(parts[1], 'cursor.card_key', 1, 100)
            clauses.append('(message_id>? OR (message_id=? AND card_key>? COLLATE BINARY))')
            parameters.extend((message_id, message_id, parts[1]))
        rows = context.connection.execute(
            'SELECT * FROM formation_proposal_index WHERE '
            + ' AND '.join(clauses)
            + ' ORDER BY message_id,card_key COLLATE BINARY LIMIT ?',
            (*parameters, request['limit'] + 1),
        ).fetchall()
        return pack(
            context,
            kind,
            request,
            rows,
            total,
            proposal_view,
            lambda row: str(row['message_id']) + ':' + row['card_key'],
        )
    after = page_anchor(context, kind, request, step_order=kind == 'steps')
    table, identity, status, owner = TABLES[kind]
    clauses, parameters = ['s.document_id=?'], [context.document_id]
    if request['state'] is not None:
        clauses.append('s.' + status + '=?')
        parameters.append(request['state'])
    if kind == 'steps' and not request['include_cancelled']:
        clauses.append("s.status<>'CANCELLED'")
    if owner is not None and request['step_ref'] is not None:
        clauses.append('s.' + owner + '=?')
        parameters.append(request['step_ref'])
    if kind == 'issues' and request['branch_ref'] is not None:
        clauses.append('s.branch_ref=?')
        parameters.append(request['branch_ref'])
    if kind == 'artifacts' and not request['include_superseded']:
        clauses.append(
            'NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=s.document_id '
            "AND r.reviewed_artifact_ref=s.artifact_ref AND r.result='REASSOCIATED')"
        )
    where = ' AND '.join(clauses)
    total = context.connection.execute(
        'SELECT count(*) FROM ' + table + ' s WHERE ' + where, parameters
    ).fetchone()[0]
    if kind == 'steps':
        position = """CASE WHEN s.position>0 THEN s.position ELSE (
            SELECT json_extract(c.before_json,'$.position') FROM formation_event_changes c
            JOIN document_change_audits e ON e.id=c.event_id
            WHERE c.document_id=s.document_id AND c.entity_kind='STEP' AND c.entity_ref=s.step_ref
            AND json_extract(e.payload_json,'$.formation_event_type')='STEP_CANCELLED'
            ORDER BY c.event_id DESC LIMIT 1) END"""
        base = 'SELECT s.*,' + position + ' AS order_position FROM ' + table + ' s WHERE ' + where
        restriction = '' if after is None else ' WHERE (order_position,step_ref)>(?,?)'
        values = parameters if after is None else [*parameters, *after]
        rows = context.connection.execute(
            'WITH selected AS ('
            + base
            + ') SELECT * FROM selected'
            + restriction
            + ' ORDER BY order_position,step_ref LIMIT ?',
            (*values, request['limit'] + 1),
        ).fetchall()
        key = lambda row: [row['order_position'], row['step_ref']]
    else:
        number = 'CAST(substr(s.' + identity + ',2) AS INTEGER)'
        restriction = '' if after is None else ' AND ' + number + '>?'
        values = parameters if after is None else [*parameters, after]
        rows = context.connection.execute(
            'SELECT s.* FROM '
            + table
            + ' s WHERE '
            + where
            + restriction
            + ' ORDER BY '
            + number
            + ' LIMIT ?',
            (*values, request['limit'] + 1),
        ).fetchall()
        key = lambda row: int(row[identity][1:])
    return pack(context, kind, request, rows, total, PROJECT[kind], key)


def get_summary(connection, root):
    value = FormationRepository(connection).summary(root['assistant_document_id'])
    if value['exists']:
        busy = work_reason(connection, root)
        value['availability'] = [action(name, busy) for name in ('ADJUST_PATH', 'SWITCH_STEP')]
    return validate('Summary', value)


def read_current(database, requirement_id, document_id, parse, read, *, catalog=None):
    try:
        strict_integer(requirement_id, 'requirement_id')
        strict_integer(document_id, 'document_id')
        request = parse()
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        resources = ResourceCatalog() if catalog is None else catalog
        with database.transaction() as connection:
            root = RequirementRepository(connection).get_for_document(requirement_id, document_id)
            if root is None:
                raise Rejected('NOT_FOUND')
            data = read(ReadContext(connection, root, resources), request)
        return {'code': 'READ_OK', 'data': data, 'details': None}
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    except Rejected as error:
        return {'code': error.code, 'data': None, 'details': error.details}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except ConfigInvalid:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    except (ValueError, TypeError, LookupError, RuntimeError):
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def read_entities(database, requirement_id, document_id, kind, payload, *, catalog=None):
    return read_current(
        database,
        requirement_id,
        document_id,
        lambda: page_input(kind, payload),
        lambda context, request: entity_page(context, kind, request),
        catalog=catalog,
    )


def read_detail(database, requirement_id, document_id, kind, entity_ref, payload, *, catalog=None):
    def parse():
        strict_enum(kind, 'kind', ('steps', 'artifacts'))
        reference(entity_ref, 'entity_ref', 'STEP' if kind == 'steps' else 'ARTIFACT')
        request = object_fields(payload, 'query', ('known_f',))
        if 'known_f' in request:
            strict_integer(request['known_f'], 'known_f')
        return request

    def read(context, request):
        if request.get('known_f', context.head['version']) != context.head['version']:
            path_changed()
        table, identity, _, _ = TABLES[kind]
        row = context.connection.execute(
            'SELECT * FROM ' + table + ' WHERE document_id=? AND ' + identity + '=?',
            (document_id, entity_ref),
        ).fetchone()
        if row is None:
            raise Rejected('NOT_FOUND')
        value = (
            step_view(context, row, detail=True) if kind == 'steps' else artifact_view(context, row)
        )
        return {'value': value, 'pagination': None}

    return read_current(database, requirement_id, document_id, parse, read, catalog=catalog)
