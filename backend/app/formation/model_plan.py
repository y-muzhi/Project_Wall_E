"""Prepare one ordinary formation delta against a complete real graph, without writes."""

from copy import deepcopy
from dataclasses import dataclass, replace

from backend.app.guide.progress_application import ProgressInvalid

from .artifact_links import verify_links
from .graph import validate_graph
from .json_arrays import json_array
from .model_contracts import formation_delta
from .model_evidence import ModelEvidence
from .path_plan import RoutePlan, prepare_route
from .path_scope import path_scope, planned_references
from .repository import FormationRepository
from .route_storage import resolve_route


@dataclass(frozen=True)
class ModelPlan:
    before: tuple
    route: RoutePlan
    mapping: dict
    changes: tuple
    step_topics: dict
    branch_topics: dict
    assessments: tuple
    recommendations: tuple
    associations: tuple
    evidence: ModelEvidence
    initializing: bool
    changed: bool


def prepare_model(connection, root, context, value, catalog):
    delta = formation_delta(value)
    frozen = context.canonical['formation']['basis']
    if delta['basis'] != frozen:
        raise ProgressInvalid('Formation delta differs from the actual frozen basis')
    document_id = root['assistant_document_id']
    repository = FormationRepository(connection)
    real_head = repository.head(document_id)
    if (None if real_head is None else real_head['version']) != frozen['formation_version']:
        raise ProgressInvalid('Formation changed after the accepted round')
    current = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=?',
        (document_id,),
    ).fetchone()
    if current is None or (current['revision_id'], current['content_version']) != (
        frozen['document_revision_id'],
        frozen['content_version'],
    ):
        raise ProgressInvalid('Content changed after the actual frozen Revision')
    evidence = ModelEvidence(connection, root, context, catalog)
    changes = deepcopy(delta['changes'])
    _resolve_sources(changes, evidence)
    initial = next((change for change in changes if change['type'] == 'INITIALIZE_PATH'), None)
    if (real_head is None) != (initial is not None):
        raise ProgressInvalid('Initialize exactly once, and only an actual missing formation')
    if real_head is None:
        head = {
            'document_id': document_id,
            'version': 1,
            'goal_version': 1,
            'goal_text': initial['goal']['text'],
            'goal_sources_json': json_array(initial['goal']['source_refs']),
            'current_step_ref': None,
            'active_branch_ref': None,
            'next_step_no': 1,
            'next_branch_no': 1,
            'next_issue_no': 1,
            'next_artifact_no': 1,
        }
        steps, branches, issues, edges = {}, {}, {}, {'DEPENDENCY': [], 'REPLACES': []}
    else:
        head, steps, branches, issues, edges = repository.graph(document_id)
    results = {
        row['result_ref']: dict(row)
        for row in connection.execute(
            'SELECT * FROM formation_results WHERE document_id=?', (document_id,)
        )
    }
    before = (
        deepcopy(head),
        deepcopy(steps),
        deepcopy(results),
        deepcopy(branches),
        deepcopy(issues),
        set(edges['DEPENDENCY']),
        set(edges['REPLACES']),
    )
    additions = []
    for change in changes:
        if change['type'] == 'INITIALIZE_PATH':
            additions.extend(deepcopy(change['steps']))
        elif change['type'] == 'ADD_STEP':
            additions.append(
                {
                    key: deepcopy(change[key])
                    for key in (
                        'temp_ref',
                        'title',
                        'expected_results',
                        'dependencies',
                        'topic_refs',
                    )
                }
            )
    if len({row['temp_ref'] for row in additions}) != len(additions):
        raise ProgressInvalid('Step declarations must be unique across the entire unit')
    drafts = {row['temp_ref']: row for row in additions}
    route_changes = []
    topic_changes = {}
    for entry in additions:
        original = next(
            change
            for change in changes
            if change.get('temp_ref') == entry['temp_ref']
            or change['type'] == 'INITIALIZE_PATH'
            and any(step['temp_ref'] == entry['temp_ref'] for step in change['steps'])
        )
        topic_changes[entry['temp_ref']] = list(entry['topic_refs'])
        route_changes.append(
            {
                'type': 'ADD_STEP',
                'temp_step_ref': entry['temp_ref'],
                'title': entry['title'],
                'expected_results': [
                    {
                        'temp_result_ref': result['temp_ref'],
                        'description': result['description'],
                        'kind': result['kind'],
                    }
                    for result in entry['expected_results']
                ],
                'dependencies': entry['dependencies'],
                'replaces_step_refs': [],
                'before_step_ref': original.get('before_step_ref'),
            }
        )
    temporary_moves = []
    for change in changes:
        kind = change['type']
        if kind == 'UPDATE_STEP':
            ref = change['step_ref']
            evidence.require_visible('STEP', ref, newly_declared=drafts)
            if ref not in drafts and steps[ref]['status'] != 'PLANNED':
                raise ProgressInvalid('Ordinary maintenance only changes not-yet-started details')
            if ref in drafts:
                entry = next(row for row in route_changes if row.get('temp_step_ref') == ref)
                if change['title'] is not None:
                    entry['title'] = change['title']
                if change['dependencies'] is not None:
                    entry['dependencies'] = change['dependencies']
                entry['expected_results'].extend(
                    {
                        'temp_result_ref': result['temp_ref'],
                        'description': result['description'],
                        'kind': result['kind'],
                    }
                    for result in change['add_results']
                )
            else:
                if change['title'] is not None:
                    route_changes.append(
                        {'type': 'RENAME_STEP', 'step_ref': ref, 'title': change['title']}
                    )
                if change['dependencies'] is not None:
                    route_changes.append(
                        {
                            'type': 'SET_DEPENDENCIES',
                            'step_ref': ref,
                            'dependencies': change['dependencies'],
                        }
                    )
                for result in change['add_results']:
                    route_changes.append(
                        {
                            'type': 'ADD_RESULT',
                            'step_ref': ref,
                            'temp_result_ref': result['temp_ref'],
                            'description': result['description'],
                            'kind': result['kind'],
                        }
                    )
            if change['topic_refs'] is not None:
                topic_changes[ref] = change['topic_refs']
        elif kind == 'MOVE_STEP':
            evidence.require_visible('STEP', change['step_ref'], newly_declared=drafts, full=False)
            temporary_moves.append(change)
    if route_changes:
        symbolic = prepare_route(*before, route_changes, [], expanded_model_changes=True)
    else:
        scope = path_scope(
            [],
            [],
            step_refs=steps,
            result_owners={ref: row['step_ref'] for ref, row in results.items()},
            branch_refs=branches,
            issue_refs=issues,
        )
        symbolic = RoutePlan(
            head,
            steps,
            results,
            branches,
            issues,
            frozenset(edges['DEPENDENCY']),
            frozenset(edges['REPLACES']),
            (),
            scope,
            (),
            (),
            (),
            False,
        )
    if temporary_moves:
        order = [
            ref
            for ref, row in sorted(symbolic.steps.items(), key=lambda pair: pair[1]['position'])
            if row['status'] != 'CANCELLED'
        ]
        for change in temporary_moves:
            ref, target = change['step_ref'], change['before_step_ref']
            if ref not in order or target == ref or target is not None and target not in order:
                raise ProgressInvalid('Move requires distinct active planned identities')
            if target is not None:
                evidence.require_visible('STEP', target, newly_declared=drafts, full=False)
            order.remove(ref)
            order.insert(len(order) if target is None else order.index(target), ref)
        for position, ref in enumerate(order, 1):
            symbolic.steps[ref]['position'] = position
    mapping, result_counters, next_step = planned_references(head, symbolic.scope, steps)
    route = resolve_route(symbolic, mapping, result_counters)
    route.head['next_step_no'] = next_step
    if initial is not None:
        first = mapping[initial['steps'][0]['temp_ref']]
        route.head['current_step_ref'] = first
        route.steps[first]['status'] = 'IN_PROGRESS'
    topics = {row['topic_ref'] for row in context.canonical['discussion']['topics']}
    step_topics = {ref: set() for ref in route.steps}
    for row in connection.execute(
        'SELECT step_ref,topic_ref FROM formation_step_topics WHERE document_id=?', (document_id,)
    ):
        step_topics[row['step_ref']].add(row['topic_ref'])
    for ref, selected in topic_changes.items():
        if not set(selected) <= topics:
            raise ProgressInvalid('Step topics must be actual frozen document topics')
        step_topics[mapping.get(ref, ref)] = set(selected)
    # Every dependency/move target must be seen or locally declared; full DB
    # existence/cycle validation is independent and still uses the whole graph.
    for change in route_changes:
        for ref in change.get('dependencies', []):
            evidence.require_visible('STEP', ref, newly_declared=drafts, full=False)
        target = change.get('before_step_ref')
        if target is not None:
            evidence.require_visible('STEP', target, newly_declared=drafts, full=False)
    from .model_entities import apply_entities

    route, mapping, branch_topics, assessments, recommendations, associations = apply_entities(
        connection,
        root,
        context,
        evidence,
        changes,
        route,
        mapping,
        catalog,
    )
    validate_graph(
        route.steps,
        route.branches,
        route.issues,
        current_step_ref=route.head['current_step_ref'],
        active_branch_ref=route.head['active_branch_ref'],
        dependencies=route.dependencies,
        replacements=route.replacements,
    )
    associations = tuple(
        {**item, 'verified': verify_links(connection, root, [item['link']], catalog)[0]}
        for item in associations
    )
    old_topics = {
        (row['step_ref'], row['topic_ref'])
        for row in connection.execute(
            'SELECT step_ref,topic_ref FROM formation_step_topics WHERE document_id=?',
            (document_id,),
        )
    }
    changed_topics = old_topics != {
        (ref, topic) for ref, values in step_topics.items() for topic in values
    }
    old_branch_topics = {
        (row['branch_ref'], row['topic_ref'])
        for row in connection.execute(
            'SELECT branch_ref,topic_ref FROM formation_branch_topics WHERE document_id=?',
            (document_id,),
        )
    }
    changed_topics = changed_topics or old_branch_topics != {
        (ref, topic) for ref, values in branch_topics.items() for topic in values
    }
    declared = []
    for change in changes:
        kind = change['type']
        if kind == 'INITIALIZE_PATH':
            for step in change['steps']:
                declared.append(step['temp_ref'])
                declared.extend(result['temp_ref'] for result in step['expected_results'])
        elif kind == 'ADD_STEP':
            declared.append(change['temp_ref'])
            declared.extend(result['temp_ref'] for result in change['expected_results'])
        elif kind == 'UPDATE_STEP':
            declared.extend(result['temp_ref'] for result in change['add_results'])
        elif kind in ('ADD_ISSUE', 'ADD_BRANCH'):
            declared.append(change['temp_ref'])
    mapping = {ref: mapping[ref] for ref in declared}
    changed = (
        (
            route.head,
            route.steps,
            route.results,
            route.branches,
            route.issues,
            set(route.dependencies),
            set(route.replacements),
        )
        != before
        or changed_topics
        or bool(assessments or recommendations or associations)
    )
    return ModelPlan(
        before,
        replace(route, changed=changed),
        mapping,
        tuple(changes),
        step_topics,
        branch_topics,
        tuple(assessments),
        tuple(recommendations),
        associations,
        evidence,
        real_head is None,
        changed,
    )


def _resolve_sources(value, evidence):
    if isinstance(value, dict):
        for name, child in value.items():
            if name == 'source_refs':
                value[name] = evidence.sources(child)
            else:
                _resolve_sources(child, evidence)
    elif isinstance(value, list):
        for child in value:
            _resolve_sources(child, evidence)
