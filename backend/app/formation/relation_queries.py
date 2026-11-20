"""Bounded relationship, artifact range and lineage queries sharing the current F snapshot."""

from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import (
    object_fields,
    raw_text,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .cursors import encode
from .read_contracts import validate
from .read_projection import artifact_view, branch_view, issue_view, lineage_item
from .read_queries import filters, pack, page_anchor, read_current
from .types import BRANCH_STATUSES, reference


def common_input(payload, allowed, mandatory=()):
    item = object_fields(payload, 'query', allowed, mandatory)
    result = {'limit': strict_integer(item.get('limit', 20), 'limit', maximum=100)}
    if 'cursor' in item:
        result['cursor'] = raw_text(item['cursor'], 'cursor', 1, 4096)
    if 'known_f' in item:
        result['known_f'] = strict_integer(item['known_f'], 'known_f')
    return result


def require_entity(context, table, identity, ref):
    row = context.connection.execute(
        'SELECT * FROM ' + table + ' WHERE document_id=? AND ' + identity + '=?',
        (context.document_id, ref),
    ).fetchone()
    if row is None:
        raise Rejected('NOT_FOUND')
    return row


def relation_input(step_ref, payload):
    reference(step_ref, 'step_ref', 'STEP')
    header = object_fields(
        payload,
        'query',
        (
            'relation_kind',
            'limit',
            'cursor',
            'known_f',
            'state',
            'branch_ref',
            'include_superseded',
        ),
        ('relation_kind',),
    )
    kind = strict_enum(
        header['relation_kind'],
        'relation_kind',
        ('DEPENDENCY', 'REPLACES', 'TOPIC', 'ISSUE', 'BRANCH', 'ARTIFACT'),
    )
    fields = ['relation_kind', 'limit', 'cursor', 'known_f']
    if kind in ('ISSUE', 'BRANCH', 'ARTIFACT'):
        fields.append('state')
    if kind == 'ISSUE':
        fields.append('branch_ref')
    if kind == 'ARTIFACT':
        fields.append('include_superseded')
    result = common_input(header, fields, ('relation_kind',))
    result.update(relation_kind=kind, step_ref=step_ref)
    if 'state' in fields:
        states = ('CURRENT', 'NEEDS_REVIEW', 'REMOVED') if kind == 'ARTIFACT' else BRANCH_STATUSES
        result['state'] = (
            None if 'state' not in header else strict_enum(header['state'], 'state', states)
        )
    if kind == 'ISSUE':
        result['branch_ref'] = (
            None
            if 'branch_ref' not in header
            else reference(header['branch_ref'], 'branch_ref', 'BRANCH')
        )
    if kind == 'ARTIFACT':
        result['include_superseded'] = strict_boolean(
            header.get('include_superseded', False), 'include_superseded'
        )
    return result


def relations(context, request):
    step = request['step_ref']
    require_entity(context, 'formation_steps', 'step_ref', step)
    kind = request['relation_kind']
    after = page_anchor(context, 'relations', request, text_order=kind == 'TOPIC')
    parameters = [context.document_id, step]
    if kind in ('DEPENDENCY', 'REPLACES'):
        table, identity = 'formation_step_edges', 'to_step_ref'
        clauses = ['s.document_id=?', 's.from_step_ref=?', 's.kind=?']
        parameters.append(kind)
        projector = lambda context, row: {
            'relation_kind': kind,
            'from_step_ref': row['from_step_ref'],
            'to_step_ref': row['to_step_ref'],
        }
    elif kind == 'TOPIC':
        table, identity = 'formation_step_topics', 'topic_ref'
        clauses = ['s.document_id=?', 's.step_ref=?']
        projector = lambda context, row: {
            'relation_kind': kind,
            'step_ref': step,
            'topic_ref': row['topic_ref'],
        }
    else:
        table, identity, owner, state = {
            'ISSUE': ('formation_issues', 'issue_ref', 'step_ref', 'disposition'),
            'BRANCH': ('formation_branches', 'branch_ref', 'return_step_ref', 'status'),
            'ARTIFACT': ('formation_artifacts', 'artifact_ref', 'step_ref', 'freshness'),
        }[kind]
        clauses = ['s.document_id=?', 's.' + owner + '=?']
        if request['state'] is not None:
            clauses.append('s.' + state + '=?')
            parameters.append(request['state'])
        if kind == 'ISSUE' and request['branch_ref'] is not None:
            clauses.append('s.branch_ref=?')
            parameters.append(request['branch_ref'])
        if kind == 'ARTIFACT' and not request['include_superseded']:
            clauses.append(
                'NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=s.document_id '
                "AND r.reviewed_artifact_ref=s.artifact_ref AND r.result='REASSOCIATED')"
            )
        nested = {'ISSUE': issue_view, 'BRANCH': branch_view, 'ARTIFACT': artifact_view}[kind]
        projector = lambda context, row: {
            'relation_kind': kind,
            'step_ref': step,
            kind.lower(): nested(context, row),
        }
    where = ' AND '.join(clauses)
    total = context.connection.execute(
        'SELECT count(*) FROM ' + table + ' s WHERE ' + where, parameters
    ).fetchone()[0]
    order = 's.' + identity if kind == 'TOPIC' else 'CAST(substr(s.' + identity + ',2) AS INTEGER)'
    restriction = '' if after is None else ' AND ' + order + '>?'
    values = parameters if after is None else [*parameters, after]
    rows = context.connection.execute(
        'SELECT s.* FROM '
        + table
        + ' s WHERE '
        + where
        + restriction
        + ' ORDER BY '
        + order
        + ' LIMIT ?',
        (*values, request['limit'] + 1),
    ).fetchall()
    key = lambda row: row[identity] if kind == 'TOPIC' else int(row[identity][1:])
    return pack(context, 'relations', request, rows, total, projector, key)


def range_input(artifact_ref, payload):
    reference(artifact_ref, 'artifact_ref', 'ARTIFACT')
    result = common_input(payload, ('role', 'limit', 'cursor', 'known_f'), ('role',))
    result.update(
        artifact_ref=artifact_ref,
        role=strict_enum(payload['role'], 'role', ('ORIGIN', 'CURRENT')),
    )
    return result


def ranges(context, request):
    artifact = request['artifact_ref']
    require_entity(context, 'formation_artifacts', 'artifact_ref', artifact)
    after = page_anchor(context, 'ranges', request)
    parameters = (context.document_id, artifact, request['role'])
    total = context.connection.execute(
        'SELECT count(*) FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role=?',
        parameters,
    ).fetchone()[0]
    rows = [
        dict(row)
        for row in context.connection.execute(
            'SELECT ordinal,revision_id,block_id,block_digest FROM formation_artifact_ranges '
            'WHERE document_id=? AND artifact_ref=? AND role=? AND ordinal>? ORDER BY ordinal LIMIT ?',
            (*parameters, 0 if after is None else after, request['limit'] + 1),
        )
    ]
    return artifact_page(
        context,
        'ranges',
        request,
        rows,
        total,
        lambda row: row,
        lambda row: row['ordinal'],
        'RangePage',
        {'artifact_ref': artifact, 'role': request['role']},
    )


def artifact_page(context, kind, request, rows, total, projector, after, schema, extra):
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
            schema,
            {
                'document_id': context.document_id,
                'formation_version': context.head['version'],
                **extra,
                'total': total,
                'items': [projector(row) for row in selected],
            },
        ),
        'pagination': {'page_size': request['limit'], 'has_more': has_more, 'next_cursor': cursor},
    }


def lineage_input(artifact_ref, payload):
    reference(artifact_ref, 'artifact_ref', 'ARTIFACT')
    return {**common_input(payload, ('limit', 'cursor', 'known_f')), 'artifact_ref': artifact_ref}


def lineage(context, request):
    anchor_ref = request['artifact_ref']
    require_entity(context, 'formation_artifacts', 'artifact_ref', anchor_ref)
    after = page_anchor(context, 'lineage', request)
    roots = context.connection.execute(
        """WITH RECURSIVE ancestors(ref) AS (
            VALUES(?) UNION
            SELECT r.reviewed_artifact_ref FROM formation_artifact_reviews r JOIN ancestors a
            ON r.replacement_artifact_ref=a.ref WHERE r.document_id=? AND r.result='REASSOCIATED'
        ) SELECT ref FROM ancestors a WHERE NOT EXISTS(
            SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=?
            AND r.replacement_artifact_ref=a.ref AND r.result='REASSOCIATED')""",
        (anchor_ref, context.document_id, context.document_id),
    ).fetchall()
    if len(roots) != 1:
        raise ValueError('Artifact lineage must have exactly one acyclic root')
    chain = """WITH RECURSIVE chain(ref,ordinal) AS (
        VALUES(?,1) UNION ALL SELECT r.replacement_artifact_ref,c.ordinal+1
        FROM chain c JOIN formation_artifact_reviews r ON r.reviewed_artifact_ref=c.ref
        WHERE r.document_id=? AND r.result='REASSOCIATED'
    ) """
    parameters = (roots[0][0], context.document_id)
    total = context.connection.execute(chain + 'SELECT count(*) FROM chain', parameters).fetchone()[
        0
    ]
    rows = context.connection.execute(
        chain + 'SELECT a.*,c.ordinal AS chain_ordinal FROM chain c JOIN formation_artifacts a '
        'ON a.artifact_ref=c.ref AND a.document_id=? WHERE c.ordinal>? ORDER BY c.ordinal LIMIT ?',
        (*parameters, context.document_id, 0 if after is None else after, request['limit'] + 1),
    ).fetchall()
    return artifact_page(
        context,
        'lineage',
        request,
        rows,
        total,
        lambda row: lineage_item(context, row),
        lambda row: row['chain_ordinal'],
        'LineagePage',
        {'anchor_ref': anchor_ref},
    )


def read_relations(database, requirement_id, document_id, step_ref, payload, *, catalog=None):
    return read_current(
        database,
        requirement_id,
        document_id,
        lambda: relation_input(step_ref, payload),
        relations,
        catalog=catalog,
    )


def read_ranges(database, requirement_id, document_id, artifact_ref, payload, *, catalog=None):
    return read_current(
        database,
        requirement_id,
        document_id,
        lambda: range_input(artifact_ref, payload),
        ranges,
        catalog=catalog,
    )


def read_lineage(database, requirement_id, document_id, artifact_ref, payload, *, catalog=None):
    return read_current(
        database,
        requirement_id,
        document_id,
        lambda: lineage_input(artifact_ref, payload),
        lineage,
        catalog=catalog,
    )
