"""Resolve and save a validated route on the caller's shared SQLite transaction."""

from copy import deepcopy
from dataclasses import replace

from backend.app.infrastructure.identifiers import increment, require_write_transaction
from backend.app.shared.command_execution import Rejected

from .artifact_links import create_links
from .graph import validate_graph
from .repository import FormationRepository
from .types import reference


def resolve_route(plan, mapping, next_results):
    """Convert only identity fields; confirmed titles/descriptions/source text remain exact."""
    changes, routes = plan.scope.resolve(list(plan.changes), list(plan.result_routes), mapping)

    def mapped(ref):
        return mapping.get(ref, ref)

    head = deepcopy(plan.head)
    for key in ('current_step_ref', 'active_branch_ref'):
        head[key] = mapped(head[key])
    steps = {}
    for ref, value in plan.steps.items():
        row = deepcopy(value)
        real = mapped(ref)
        reference(real, 'resolved.step_ref', 'STEP')
        row['step_ref'] = real
        row['next_result_no'] = next_results.get(ref, row['next_result_no'])
        steps[real] = row
    results = {}
    for ref, value in plan.results.items():
        row = deepcopy(value)
        real = mapped(ref)
        reference(real, 'resolved.result_ref', 'RESULT')
        row['step_ref'] = mapped(row['step_ref'])
        row['result_ref'] = real
        if real.split('.o')[0] != row['step_ref']:
            raise ValueError('Resolved result has a different real owner')
        results[real] = row
    branches, issues = deepcopy(plan.branches), deepcopy(plan.issues)
    for row in branches.values():
        for key in ('origin_step_ref', 'return_step_ref'):
            row[key] = mapped(row[key])
    for row in issues.values():
        row['step_ref'] = mapped(row['step_ref'])
    dependencies = frozenset(
        (mapped(origin), mapped(target)) for origin, target in plan.dependencies
    )
    replacements = frozenset(
        (mapped(origin), mapped(target)) for origin, target in plan.replacements
    )
    validate_graph(
        steps,
        branches,
        issues,
        current_step_ref=head['current_step_ref'],
        active_branch_ref=head['active_branch_ref'],
        dependencies=dependencies,
        replacements=replacements,
    )
    return replace(
        plan,
        head=head,
        steps=steps,
        results=results,
        branches=branches,
        issues=issues,
        dependencies=dependencies,
        replacements=replacements,
        changes=tuple(changes),
        result_routes=tuple(routes),
        links=tuple(change for change in changes if change['type'] == 'LINK_CONTENT'),
    )


def apply_disposition_events(plan, event_ids):
    """Bind lifecycle/disposition facts to the actual already allocated event batch."""
    branches, issues = deepcopy(plan.branches), deepcopy(plan.issues)
    for change in plan.disposition_actions:
        if change['type'] == 'DISPOSE_BRANCH':
            ref = change['branch_ref']
            event_id = event_ids[('BRANCH_DISPOSITION_CHANGED', ref)]
            branches[ref]['state_event_id'] = event_id
            branches[ref]['disposition_event_id'] = event_id
        elif change['type'] == 'DISPOSE_ISSUE':
            ref = change['issue_ref']
            issues[ref]['disposition_event_id'] = event_ids[('ISSUE_DISPOSITION_CHANGED', ref)]
        elif change['type'] == 'RESUME_ISSUE':
            issues[change['issue_ref']]['disposition_event_id'] = None
        else:
            raise ValueError('Unknown route disposition effect')
    return replace(plan, branches=branches, issues=issues)


def _update(connection, table, identity, document_id, ref, fields):
    allowed = {
        'formation_steps': {
            'definition_version',
            'next_result_no',
            'position',
            'title',
            'status',
            'closure_event_id',
        },
        'formation_branches': {
            'question',
            'relevance',
            'result_summary',
            'result_sources_json',
            'return_step_ref',
            'status',
            'state_event_id',
            'disposition_event_id',
        },
        'formation_issues': {
            'description',
            'blocking',
            'source_refs_json',
            'resolution_sources_json',
            'step_ref',
            'disposition',
            'disposition_reason',
            'disposition_event_id',
        },
        'formation_results': {'description'},
    }
    if not fields or set(fields) - allowed[table]:
        raise ValueError('Route storage accepts only its registered mutable fields')
    changed = connection.execute(
        f'UPDATE {table} SET '
        + ','.join(key + '=?' for key in fields)
        + f' WHERE document_id=? AND {identity}=?',
        (*fields.values(), document_id, ref),
    )
    if changed.rowcount != 1:
        raise ValueError('Route entity changed inside its shared transaction')


def persist_route(connection, *, before, resolved, verified_links, link_event_ids, summaries):
    """Caller first records the real event batch; state, links, D and receipt commit together."""
    require_write_transaction(connection)
    if not resolved.changed:
        raise ValueError('An unchanged route must return its receipt without mutation')
    document_id = resolved.head['document_id']
    old_head = before[0]
    if old_head['document_id'] != document_id:
        raise ValueError('A route cannot change its document owner')
    for collection in (resolved.steps, resolved.results, resolved.branches, resolved.issues):
        if any(row['document_id'] != document_id for row in collection.values()):
            raise ValueError('Every resolved entity must belong to the same document')
    if len(verified_links) != len(resolved.links):
        raise ValueError('Every route content association must be verified in this transaction')
    for checked, link in zip(verified_links, resolved.links, strict=True):
        if (checked.step_ref, checked.result_refs) != (
            link['step_ref'],
            tuple(link['result_refs']),
        ):
            raise ValueError('Verified content association does not match the accepted route')
    current = FormationRepository(connection).head(document_id, required=True)
    if current['version'] != old_head['version']:
        raise Rejected(
            'STATE_CONFLICT', details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None}
        )
    persist_graph(connection, before=before, resolved=resolved)
    artifacts = create_links(connection, document_id, verified_links, link_event_ids, summaries)
    changed = connection.execute(
        'UPDATE formation_heads SET version=?,goal_version=?,goal_text=?,goal_sources_json=?,'
        'current_step_ref=?,active_branch_ref=? WHERE document_id=? AND version=?',
        (
            increment(old_head['version']),
            resolved.head['goal_version'],
            resolved.head['goal_text'],
            resolved.head['goal_sources_json'],
            resolved.head['current_step_ref'],
            resolved.head['active_branch_ref'],
            document_id,
            old_head['version'],
        ),
    )
    if changed.rowcount != 1:
        raise Rejected(
            'STATE_CONFLICT', details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None}
        )
    return artifacts


def persist_graph(connection, *, before, resolved):
    """Store one fully validated complete graph on the caller's connection; never touch D/F or commit."""
    require_write_transaction(connection)
    (
        old_head,
        old_steps,
        old_results,
        old_branches,
        old_issues,
        old_dependencies,
        old_replacements,
    ) = before
    document_id = resolved.head['document_id']
    if old_head['document_id'] != document_id:
        raise ValueError('A shared graph cannot change its document')
    # Vacate active ranks inside this same transaction. The partial unique index remains enabled.
    connection.execute(
        "UPDATE formation_steps SET position=-position WHERE document_id=? AND status<>'CANCELLED'",
        (document_id,),
    )
    for ref, row in resolved.steps.items():
        stored = dict(row)
        if row['status'] == 'CANCELLED':
            stored['position'] = -int(ref[1:])
        if ref not in old_steps:
            connection.execute(
                'INSERT INTO formation_steps('
                + ','.join(stored)
                + ') VALUES('
                + ','.join('?' for _ in stored)
                + ')',
                tuple(stored.values()),
            )
        else:
            fields = {
                key: stored[key]
                for key in (
                    'definition_version',
                    'next_result_no',
                    'position',
                    'title',
                    'status',
                    'closure_event_id',
                )
            }
            _update(connection, 'formation_steps', 'step_ref', document_id, ref, fields)
    for ref, row in resolved.results.items():
        if ref not in old_results:
            connection.execute(
                'INSERT INTO formation_results('
                + ','.join(row)
                + ') VALUES('
                + ','.join('?' for _ in row)
                + ')',
                tuple(row.values()),
            )
        elif row['description'] != old_results[ref]['description']:
            _update(
                connection,
                'formation_results',
                'result_ref',
                document_id,
                ref,
                {'description': row['description']},
            )
    for kind, previous, current_edges in (
        ('DEPENDENCY', set(old_dependencies), resolved.dependencies),
        ('REPLACES', set(old_replacements), resolved.replacements),
    ):
        connection.executemany(
            'DELETE FROM formation_step_edges WHERE document_id=? AND from_step_ref=? AND to_step_ref=? AND kind=?',
            [
                (document_id, origin, target, kind)
                for origin, target in sorted(previous - current_edges)
            ],
        )
        connection.executemany(
            'INSERT INTO formation_step_edges(document_id,from_step_ref,to_step_ref,kind) VALUES(?,?,?,?)',
            [
                (document_id, origin, target, kind)
                for origin, target in sorted(current_edges - previous)
            ],
        )
    for table, identity, previous, rows, mutable in (
        (
            'formation_branches',
            'branch_ref',
            old_branches,
            resolved.branches,
            (
                'return_step_ref',
                'question',
                'relevance',
                'status',
                'state_event_id',
                'result_summary',
                'result_sources_json',
                'disposition_event_id',
            ),
        ),
        (
            'formation_issues',
            'issue_ref',
            old_issues,
            resolved.issues,
            (
                'step_ref',
                'description',
                'blocking',
                'source_refs_json',
                'disposition',
                'disposition_reason',
                'resolution_sources_json',
                'disposition_event_id',
            ),
        ),
    ):
        for ref, row in rows.items():
            if ref not in previous:
                connection.execute(
                    'INSERT INTO '
                    + table
                    + '('
                    + ','.join(row)
                    + ') VALUES ('
                    + ','.join('?' for _ in row)
                    + ')',
                    tuple(row.values()),
                )
                continue
            fields = {key: row[key] for key in mutable if row[key] != previous[ref][key]}
            if fields:
                _update(connection, table, identity, document_id, ref, fields)
