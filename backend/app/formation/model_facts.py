"""Bind actual AI event identities and freeze each final entity/member fact exactly once."""

from copy import deepcopy
from dataclasses import replace

from .events import scalar_snapshot, source_members
from .path_facts import RouteFact, reference_members, route_facts


def event_keys(plan, associations):
    keys = []
    before = plan.before
    route = plan.route
    if plan.initializing:
        keys.append(('PATH_INITIALIZED', 'formation'))
    for ref, row in route.steps.items():
        old = before[1].get(ref)
        if old is None:
            keys.append(('STEP_ADDED', ref))
        elif row != old or _topics(plan, 'STEP', ref) != plan.step_topics[ref]:
            action = (
                'STEP_MOVED'
                if all(row[name] == old[name] for name in row if name != 'position')
                and _topics(plan, 'STEP', ref) == plan.step_topics[ref]
                else 'STEP_UPDATED'
            )
            keys.append((action, ref))
    for ref, row in route.branches.items():
        old = before[3].get(ref)
        if old is None:
            keys.append(('BRANCH_ADDED', ref))
        if row['status'] == 'RESOLVED' and (
            old is None
            or old['status'] != 'RESOLVED'
            or old['result_summary'] != row['result_summary']
        ):
            keys.append(('BRANCH_RESULT_RECORDED', ref))
        elif old is not None and (
            row != old or _topics(plan, 'BRANCH', ref) != plan.branch_topics[ref]
        ):
            keys.append(('BRANCH_UPDATED', ref))
    for ref, row in route.issues.items():
        old = before[4].get(ref)
        if old is None:
            keys.append(('ISSUE_ADDED', ref))
        if row['disposition'] == 'RESOLVED' and (old is None or old['disposition'] != 'RESOLVED'):
            keys.append(('ISSUE_RESOLVED', ref))
        elif old is not None and row != old:
            keys.append(('ISSUE_UPDATED', ref))
    old_branch = before[0]['active_branch_ref']
    new_branch = route.head['active_branch_ref']
    if old_branch != new_branch:
        keys.append(
            ('BRANCH_ENTERED', new_branch)
            if new_branch is not None
            else ('BRANCH_RETURNED', old_branch)
        )
    keys.extend(('ASSESSMENT_RECORDED', row['step_ref']) for row in plan.assessments)
    keys.extend(('RECOMMENDATION_RECORDED', row['step_ref']) for row in plan.recommendations)
    for index, item in enumerate(associations):
        owner = item['link']['step_ref'] + ':' + str(index)
        if item['reviewed'] is None or item['review_result'] == 'REASSOCIATED':
            keys.append(('CONTENT_ASSOCIATED', owner))
        if item['reviewed'] is not None:
            keys.append(
                (
                    'ARTIFACT_REASSOCIATED'
                    if item['review_result'] == 'REASSOCIATED'
                    else 'ARTIFACT_CHECKED',
                    item['reviewed']['artifact_ref'],
                )
            )
    return tuple(dict.fromkeys(keys))


def bind_events(plan, event_ids):
    route = plan.route
    branches, issues = deepcopy(route.branches), deepcopy(route.issues)
    for ref, row in branches.items():
        if ref not in plan.before[3]:
            row['origin_event_id'] = event_ids[('BRANCH_ADDED', ref)]
            row['state_event_id'] = row['origin_event_id']
        if ('BRANCH_RESULT_RECORDED', ref) in event_ids:
            row['state_event_id'] = event_ids[('BRANCH_RESULT_RECORDED', ref)]
    for ref, row in issues.items():
        if ('ISSUE_RESOLVED', ref) in event_ids:
            row['disposition_event_id'] = event_ids[('ISSUE_RESOLVED', ref)]
    return replace(route, branches=branches, issues=issues)


def _topics(plan, kind, ref):
    table, column = (
        ('formation_step_topics', 'step_ref')
        if kind == 'STEP'
        else ('formation_branch_topics', 'branch_ref')
    )
    return {
        row[0]
        for row in plan.evidence.connection.execute(
            'SELECT topic_ref FROM ' + table + ' WHERE document_id=? AND ' + column + '=?',
            (plan.route.head['document_id'], ref),
        )
    }


def _members(base, groups):
    def produce():
        rows = list(base() if callable(base) else base)
        for collection, old, new in groups:
            if collection.endswith('_SOURCE'):
                rows.extend(source_members(collection, old, new))
            else:
                rows.extend(reference_members(collection, old, new))
        from .events import MEMBER_COLLECTIONS

        rows.sort(
            key=lambda row: (
                MEMBER_COLLECTIONS.index(row['collection']),
                row['member_key'].encode('utf-8'),
            )
        )
        for ordinal, row in enumerate(rows, 1):
            yield {**row, 'ordinal': ordinal}

    return produce


def graph_facts(plan, route, keys):
    facts = list(route_facts(plan.before, route, keys))
    by_entity = {(fact.kind, fact.ref): index for index, fact in enumerate(facts)}
    for kind, rows, previous, topics in (
        ('STEP', route.steps, plan.before[1], plan.step_topics),
        ('BRANCH', route.branches, plan.before[3], plan.branch_topics),
        ('ISSUE', route.issues, plan.before[4], None),
    ):
        for ref, row in rows.items():
            old = previous.get(ref)
            groups = []
            if topics is not None:
                collection = 'TOPIC' if kind == 'STEP' else 'BRANCH_TOPIC'
                groups.append((collection, _topics(plan, kind, ref), topics[ref]))
            if kind == 'BRANCH':
                groups.append(
                    (
                        'BRANCH_RESULT_SOURCE',
                        '[]' if old is None else old['result_sources_json'],
                        row['result_sources_json'],
                    )
                )
            elif kind == 'ISSUE':
                groups.extend(
                    (
                        (
                            'ISSUE_SOURCE',
                            '[]' if old is None else old['source_refs_json'],
                            row['source_refs_json'],
                        ),
                        (
                            'ISSUE_RESOLUTION_SOURCE',
                            '[]' if old is None else old['resolution_sources_json'],
                            row['resolution_sources_json'],
                        ),
                    )
                )
            preferred = (
                [('BRANCH_RESULT_RECORDED', ref), ('BRANCH_ADDED', ref), ('BRANCH_UPDATED', ref)]
                if kind == 'BRANCH'
                else [('ISSUE_RESOLVED', ref), ('ISSUE_ADDED', ref), ('ISSUE_UPDATED', ref)]
                if kind == 'ISSUE'
                else [('STEP_ADDED', ref), ('STEP_UPDATED', ref), ('STEP_MOVED', ref)]
            )
            owner = next((key for key in preferred if key in keys), None)
            index = by_entity.get((kind, ref))
            base = () if index is None else facts[index].members
            members = _members(base, groups)
            if index is not None:
                facts[index] = replace(
                    facts[index], owner=owner or facts[index].owner, members=members
                )
            elif owner is not None:
                facts.append(
                    RouteFact(
                        kind,
                        ref,
                        scalar_snapshot(kind, old),
                        scalar_snapshot(kind, row),
                        owner,
                        members,
                    )
                )
    if plan.initializing:
        members = _members((), [('GOAL_SOURCE', '[]', route.head['goal_sources_json'])])
        facts.insert(
            0,
            RouteFact(
                'GOAL',
                'goal',
                None,
                {'version': 1, 'text': route.head['goal_text']},
                ('PATH_INITIALIZED', 'formation'),
                members,
            ),
        )
    return tuple(facts)
