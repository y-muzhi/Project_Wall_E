"""Deterministic route event keys and scalar/member deltas, without nested graph snapshots."""

from dataclasses import dataclass

from .events import scalar_snapshot, source_members


@dataclass(frozen=True)
class RouteFact:
    kind: str
    ref: str
    before: dict | None
    after: dict | None
    owner: tuple[str, str]
    members: object = ()


def event_keys(before, plan):
    old_head, old_steps, old_results, old_branches, old_issues, old_dependencies, _ = before
    keys = []
    for change in plan.changes:
        kind = change['type']
        key = None
        if kind == 'SET_GOAL':
            if (old_head['goal_version'], old_head['goal_text']) != (
                plan.head['goal_version'],
                plan.head['goal_text'],
            ):
                key = ('GOAL_CHANGED', 'goal')
        elif kind == 'ADD_STEP':
            key = ('STEP_ADDED', change['temp_step_ref'])
        elif kind == 'RENAME_STEP':
            ref = change['step_ref']
            if old_steps[ref]['title'] != plan.steps[ref]['title']:
                key = ('STEP_UPDATED', ref)
        elif kind == 'MOVE_STEP':
            ref = change['step_ref']
            if (
                plan.steps[ref]['status'] != 'CANCELLED'
                and old_steps[ref]['position'] != plan.steps[ref]['position']
            ):
                key = ('STEP_MOVED', ref)
        elif kind == 'SET_DEPENDENCIES':
            ref = change['step_ref']
            old = {target for origin, target in old_dependencies if origin == ref}
            current = {target for origin, target in plan.dependencies if origin == ref}
            if old != current:
                key = ('STEP_UPDATED', ref)
        elif kind == 'UPDATE_RESULT':
            ref = change['result_ref']
            if old_results[ref]['description'] != plan.results[ref]['description']:
                key = ('STEP_UPDATED', plan.results[ref]['step_ref'])
        elif kind == 'ADD_RESULT':
            ref = change['step_ref']
            key = ('STEP_ADDED' if ref not in old_steps else 'STEP_UPDATED', ref)
        elif kind == 'CANCEL_STEP':
            key = ('STEP_CANCELLED', change['step_ref'])
        elif kind == 'LINK_CONTENT':
            key = ('CONTENT_ASSOCIATED', change['step_ref'])
        elif kind == 'MOVE_ISSUE':
            ref = change['issue_ref']
            if old_issues[ref]['step_ref'] != plan.issues[ref]['step_ref']:
                key = ('ISSUE_MOVED', ref)
        elif kind == 'SET_BRANCH_RETURN':
            ref = change['branch_ref']
            if old_branches[ref]['return_step_ref'] != plan.branches[ref]['return_step_ref']:
                key = ('BRANCH_RETURN_CHANGED', ref)
        elif kind in ('DISPOSE_ISSUE', 'RESUME_ISSUE'):
            ref = change['issue_ref']
            if old_issues[ref]['disposition'] != plan.issues[ref]['disposition']:
                key = (
                    'ISSUE_RESUMED' if kind == 'RESUME_ISSUE' else 'ISSUE_DISPOSITION_CHANGED',
                    ref,
                )
        elif kind == 'DISPOSE_BRANCH':
            key = ('BRANCH_DISPOSITION_CHANGED', change['branch_ref'])
        else:
            raise ValueError('Unregistered route change')
        if key is not None and key not in keys:
            keys.append(key)
    for route in plan.result_routes:
        keys.append(('RESULT_ROUTE', route['from_result_ref']))
    return tuple(keys)


def reference_members(collection, before, after):
    before, after = frozenset(before), frozenset(after)
    for ref in sorted(before ^ after):
        yield {
            'collection': collection,
            'member_key': ref,
            'before': {'kind': 'REF', 'ref': ref} if ref in before else None,
            'after': {'kind': 'REF', 'ref': ref} if ref in after else None,
        }


def step_members(before_dependencies, after_dependencies, before_replacements, after_replacements):
    groups = (
        ('DEPENDENCY', frozenset(before_dependencies), frozenset(after_dependencies)),
        ('REPLACES', frozenset(before_replacements), frozenset(after_replacements)),
    )

    def produce():
        ordinal = 0
        for collection, old, current in groups:
            for item in reference_members(collection, old, current):
                ordinal += 1
                yield {'ordinal': ordinal, **item}

    return produce


def route_facts(before, plan, keys):
    """Each final scalar/member fact is stored once; same-batch actions share versions."""
    (
        old_head,
        old_steps,
        old_results,
        old_branches,
        old_issues,
        old_dependencies,
        old_replacements,
    ) = before
    if not keys:
        if plan.changed:
            raise ValueError('A changed route requires an actual registered event')
        return ()
    facts = []
    from collections import defaultdict

    def grouped(edges):
        groups = defaultdict(set)
        for origin, target in edges:
            groups[origin].add(target)
        return groups

    previous_dependencies = grouped(old_dependencies)
    current_dependencies = grouped(plan.dependencies)
    previous_replacements = grouped(old_replacements)
    current_replacements = grouped(plan.replacements)

    def owner(ref, preferred=()):
        for action in preferred:
            if (action, ref) in keys:
                return action, ref
        for key in keys:
            if key[1] == ref:
                return key
        for key in keys:
            if key[0] in ('STEP_ADDED', 'STEP_CANCELLED', 'STEP_MOVED', 'STEP_UPDATED'):
                return key
        return keys[0]

    if (old_head['goal_version'], old_head['goal_text'], old_head['goal_sources_json']) != (
        plan.head['goal_version'],
        plan.head['goal_text'],
        plan.head['goal_sources_json'],
    ):

        def goal_members():
            yield from source_members(
                'GOAL_SOURCE', old_head['goal_sources_json'], plan.head['goal_sources_json']
            )

        facts.append(
            RouteFact(
                'GOAL',
                'goal',
                {'version': old_head['goal_version'], 'text': old_head['goal_text']},
                {'version': plan.head['goal_version'], 'text': plan.head['goal_text']},
                ('GOAL_CHANGED', 'goal'),
                goal_members,
            )
        )
    for ref in sorted(plan.steps):
        old, current = old_steps.get(ref), plan.steps[ref]
        previous_snapshot = scalar_snapshot('STEP', old)
        snapshot = scalar_snapshot('STEP', current)
        old_deps = previous_dependencies[ref]
        deps = current_dependencies[ref]
        old_replaces = previous_replacements[ref]
        replaces = current_replacements[ref]
        event = owner(ref, ('STEP_ADDED', 'STEP_CANCELLED', 'STEP_UPDATED', 'STEP_MOVED'))
        if previous_snapshot != snapshot or old_deps != deps or old_replaces != replaces:
            facts.append(
                RouteFact(
                    'STEP',
                    ref,
                    previous_snapshot,
                    snapshot,
                    event,
                    step_members(old_deps, deps, old_replaces, replaces),
                )
            )
        old_order = (
            None
            if old is None or old['status'] == 'CANCELLED'
            else {'step_ref': ref, 'position': old['position']}
        )
        order = (
            None
            if current['status'] == 'CANCELLED'
            else {'step_ref': ref, 'position': current['position']}
        )
        if old_order != order:
            facts.append(RouteFact('ORDER', ref, old_order, order, event))
    for ref in sorted(plan.results):
        old, current = old_results.get(ref), plan.results[ref]
        fields = ('result_ref', 'description', 'kind')
        previous = None if old is None else {key: old[key] for key in fields}
        snapshot = {key: current[key] for key in fields}
        if previous != snapshot:
            facts.append(
                RouteFact(
                    'RESULT',
                    ref,
                    previous,
                    snapshot,
                    owner(current['step_ref'], ('STEP_ADDED', 'STEP_UPDATED', 'STEP_CANCELLED')),
                )
            )
    for kind, old, current in (
        ('BRANCH', old_branches, plan.branches),
        ('ISSUE', old_issues, plan.issues),
    ):
        for ref in sorted(current):
            previous, snapshot = (
                scalar_snapshot(kind, old.get(ref)),
                scalar_snapshot(kind, current[ref]),
            )
            if previous != snapshot:
                facts.append(RouteFact(kind, ref, previous, snapshot, owner(ref)))
    for route in plan.result_routes:
        ref = route['from_result_ref']
        facts.append(RouteFact('RESULT_ROUTE', ref, None, dict(route), ('RESULT_ROUTE', ref)))
    return tuple(facts)


def artifact_snapshot(row):
    return {
        'artifact_ref': row['artifact_ref'],
        'step_ref': row['step_ref'],
        'source_event_ref': row['source_event_id'],
        'origin_revision_id': row['origin_revision_id'],
        'origin_content_digest': row['origin_digest'],
        'summary': row['summary'],
        'checked_against_revision_id': row['checked_against_revision_id'],
        'freshness': row['freshness'],
        'review_reason': row['review_reason'],
    }


def artifact_fact(row, result_refs, ranges, owner):
    snapshot = artifact_snapshot(row)
    result_refs = tuple(result_refs)
    ranges = tuple(sorted(ranges, key=lambda item: str(item[0]).encode('utf-8')))

    def produce():
        ordinal = 0
        for result in sorted(result_refs):
            ordinal += 1
            yield {
                'ordinal': ordinal,
                'collection': 'ARTIFACT_RESULT',
                'member_key': result,
                'before': None,
                'after': {'kind': 'REF', 'ref': result},
            }
        for role in ('ORIGIN', 'CURRENT'):
            for identity, digest in ranges:
                ordinal += 1
                yield {
                    'ordinal': ordinal,
                    'collection': role + '_RANGE',
                    'member_key': f'{role}:{row["origin_revision_id"]}:{identity}',
                    'before': None,
                    'after': {
                        'kind': 'RANGE',
                        'revision_id': row['origin_revision_id'],
                        'block_id': identity,
                        'block_digest': digest,
                    },
                }

    return RouteFact('ARTIFACT', row['artifact_ref'], None, snapshot, owner, produce)
