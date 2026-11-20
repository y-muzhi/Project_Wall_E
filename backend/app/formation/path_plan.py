"""Complete symbolic route calculation shared by read-only preview and COMMIT."""

import json
from copy import deepcopy
from dataclasses import dataclass

from backend.app.infrastructure.identifiers import increment
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import reject

from .graph import validate_graph
from .path_contracts import path_change, route_batch
from .path_scope import PathScope, path_scope


def invalid_transition(step_ref=None):
    raise Rejected(
        'STATE_CONFLICT',
        details={
            'reason': 'INVALID_TRANSITION',
            'step_ref': step_ref,
            'proposal': None,
        },
    )


@dataclass(frozen=True)
class RoutePlan:
    head: dict
    steps: dict
    results: dict
    branches: dict
    issues: dict
    dependencies: frozenset
    replacements: frozenset
    links: tuple
    scope: PathScope
    changes: tuple
    result_routes: tuple
    disposition_actions: tuple
    changed: bool


def prepare_route(
    head,
    steps,
    results,
    branches,
    issues,
    dependencies,
    replacements,
    changes,
    result_routes,
    *,
    expanded_model_changes=False,
):
    """No SQL, persistent allocation, timestamps or hidden model calls are performed."""
    if expanded_model_changes:
        # The model's original 20/64KiB batch has already been checked. Internal
        # expansion (e.g. one UPDATE_STEP with 20 added results) is not another user batch.
        if result_routes:
            raise ValueError('Ordinary model expansion cannot route existing results')
        changes = [path_change(value, f'changes[{index}]') for index, value in enumerate(changes)]
    else:
        changes, result_routes = route_batch(changes, result_routes)
    scope = path_scope(
        changes,
        result_routes,
        step_refs=steps,
        result_owners={ref: row['step_ref'] for ref, row in results.items()},
        branch_refs=branches,
        issue_refs=issues,
    )
    original = (head, steps, results, branches, issues, set(dependencies), set(replacements))
    head, steps, results, branches, issues, dependencies, replacements = deepcopy(original)
    order = [
        ref
        for ref, row in sorted(steps.items(), key=lambda item: (item[1]['position'], item[0]))
        if row['status'] != 'CANCELLED'
    ]
    # All local declarations exist in the symbolic graph before any reference is evaluated.
    for change in changes:
        if change['type'] == 'ADD_STEP':
            ref = change['temp_step_ref']
            steps[ref] = {
                'document_id': head['document_id'],
                'step_ref': ref,
                'definition_version': 1,
                'next_result_no': 1 + len(change['expected_results']),
                'position': len(order) + 1,
                'title': change['title'],
                'status': 'PLANNED',
                'closure_event_id': None,
            }
            order.append(ref)
            for result in change['expected_results']:
                result_ref = result['temp_result_ref']
                results[result_ref] = {
                    'document_id': head['document_id'],
                    'step_ref': ref,
                    'result_ref': result_ref,
                    'description': result['description'],
                    'kind': result['kind'],
                }
            dependencies.update((ref, target) for target in change['dependencies'])
            replacements.update((ref, target) for target in change['replaces_step_refs'])
        elif change['type'] == 'ADD_RESULT':
            ref = change['temp_result_ref']
            results[ref] = {
                'document_id': head['document_id'],
                'step_ref': change['step_ref'],
                'result_ref': ref,
                'description': change['description'],
                'kind': change['kind'],
            }

    links, dispositions = [], []
    for change in changes:
        kind = change['type']
        if kind == 'SET_GOAL':
            head['goal_text'] = change['text']
            head['goal_sources_json'] = json.dumps(
                change['source_refs'], ensure_ascii=False, sort_keys=True, separators=(',', ':')
            )
        elif kind in ('ADD_STEP', 'MOVE_STEP'):
            ref = change.get('temp_step_ref', change.get('step_ref'))
            if (
                ref not in order
                or change['before_step_ref'] is not None
                and change['before_step_ref'] not in order
            ):
                invalid_transition(ref)
            order.remove(ref)
            before = change['before_step_ref']
            index = len(order) if before is None else order.index(before)
            order.insert(index, ref)
        elif kind == 'RENAME_STEP':
            steps[change['step_ref']]['title'] = change['title']
        elif kind == 'SET_DEPENDENCIES':
            ref = change['step_ref']
            dependencies = {edge for edge in dependencies if edge[0] != ref}
            dependencies.update((ref, target) for target in change['dependencies'])
        elif kind == 'UPDATE_RESULT':
            results[change['result_ref']]['description'] = change['description']
        elif kind == 'ADD_RESULT':
            pass  # Declaration was incorporated above, including forward references.
        elif kind == 'CANCEL_STEP':
            ref = change['step_ref']
            if steps[ref]['status'] not in ('PLANNED', 'IN_PROGRESS', 'PAUSED'):
                invalid_transition(ref)
            steps[ref]['status'] = 'CANCELLED'
            order.remove(ref)
            replacements.update((target, ref) for target in change['replacement_step_refs'])
            if head['current_step_ref'] == ref:
                head['current_step_ref'] = None
                head['active_branch_ref'] = None
        elif kind == 'LINK_CONTENT':
            links.append(deepcopy(change))
        elif kind == 'MOVE_ISSUE':
            issues[change['issue_ref']]['step_ref'] = change['to_step_ref']
        elif kind == 'SET_BRANCH_RETURN':
            branches[change['branch_ref']]['return_step_ref'] = change['return_step_ref']
            if (
                head['active_branch_ref'] == change['branch_ref']
                and head['current_step_ref'] != change['return_step_ref']
            ):
                head['active_branch_ref'] = None
        elif kind == 'DISPOSE_ISSUE':
            issue = issues[change['issue_ref']]
            if issue['disposition'] != 'OPEN':
                invalid_transition(issue['step_ref'])
            issue['disposition'] = change['disposition']
            issue['disposition_reason'] = change['reason']
            dispositions.append(deepcopy(change))
        elif kind == 'DISPOSE_BRANCH':
            branch = branches[change['branch_ref']]
            if branch['status'] != 'OPEN':
                invalid_transition(branch['return_step_ref'])
            branch['status'] = change['disposition']
            if head['active_branch_ref'] == change['branch_ref']:
                head['active_branch_ref'] = None
            dispositions.append(deepcopy(change))
        elif kind == 'RESUME_ISSUE':
            issue = issues[change['issue_ref']]
            if issue['disposition'] not in ('DEFERRED', 'OPEN'):
                invalid_transition(issue['step_ref'])
            if issue['disposition'] == 'DEFERRED':
                issue['disposition'] = 'OPEN'
                issue['disposition_reason'] = None
                issue['disposition_event_id'] = None
                dispositions.append(deepcopy(change))
        else:
            raise AssertionError('Unimplemented PathChange alternative: ' + kind)

    for position, ref in enumerate(order, 1):
        steps[ref]['position'] = position
    cancelled = {ref for ref, row in steps.items() if row['status'] == 'CANCELLED'}
    for origin, target in dependencies:
        if origin not in cancelled and target in cancelled:
            reject('changes', 'INVALID_FORMAT', '有效步骤的依赖必须明确转交，不能仍指向放弃步骤')
    for route in result_routes:
        source_kind = results[route['from_result_ref']]['kind']
        for target in route['target_result_refs']:
            if results[target]['kind'] != source_kind:
                reject('result_routes', 'INVALID_FORMAT', '预期成果承接不能改变种类')
    for change in changes:
        if change['type'] == 'CANCEL_STEP':
            for target in change['replacement_step_refs']:
                if target in cancelled:
                    reject('changes', 'INVALID_FORMAT', '替代步骤不能同时被放弃')

    if (head['goal_text'], head['goal_sources_json']) != (
        original[0]['goal_text'],
        original[0]['goal_sources_json'],
    ):
        head['goal_version'] = increment(original[0]['goal_version'])
    from collections import defaultdict

    def definitions_by_step(rows):
        grouped = defaultdict(list)
        for result_ref, row in rows.items():
            grouped[row['step_ref']].append((result_ref, row['description'], row['kind']))
        return {ref: sorted(values) for ref, values in grouped.items()}

    def dependencies_by_step(edges):
        grouped = defaultdict(set)
        for origin, target in edges:
            grouped[origin].add(target)
        return grouped

    previous_definitions = definitions_by_step(original[2])
    definitions = definitions_by_step(results)
    previous_dependencies = dependencies_by_step(original[5])
    current_dependencies = dependencies_by_step(dependencies)
    for ref in original[1]:
        definition_changed = previous_definitions.get(ref) != definitions.get(ref)
        dependency_changed = previous_dependencies[ref] != current_dependencies[ref]
        if definition_changed or dependency_changed:
            steps[ref]['definition_version'] = increment(original[1][ref]['definition_version'])
    validate_graph(
        steps,
        branches,
        issues,
        current_step_ref=head['current_step_ref'],
        active_branch_ref=head['active_branch_ref'],
        dependencies=dependencies,
        replacements=replacements,
    )
    calculated = (head, steps, results, branches, issues, dependencies, replacements)
    changed = calculated != original or bool(links)
    return RoutePlan(
        head,
        steps,
        results,
        branches,
        issues,
        frozenset(dependencies),
        frozenset(replacements),
        tuple(links),
        scope,
        tuple(changes),
        tuple(result_routes),
        tuple(dispositions),
        changed,
    )
