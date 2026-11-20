"""Resolve a whole route's symbol domain before allocating any persistent identity."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backend.app.shared.validation import reject

from .types import MAX_RESULTS


@dataclass(frozen=True)
class PathScope:
    step_refs: frozenset[str]
    result_owners: Mapping[str, str]
    declared_steps: tuple[str, ...]
    declared_results: tuple[str, ...]

    def resolve(self, changes, result_routes, reference_map):
        """Use only a complete transaction-owned allocation; never rewrite a published card."""
        expected = set(self.declared_steps) | set(self.declared_results)
        if set(reference_map) != expected:
            raise ValueError('A complete, exact transaction allocation is required')
        if len(set(reference_map.values())) != len(reference_map):
            raise ValueError('Allocated formation identities must be unique')
        from .types import reference

        for temporary in self.declared_steps:
            reference(reference_map[temporary], 'reference_map', 'STEP')
        for temporary in self.declared_results:
            real = reference(reference_map[temporary], 'reference_map', 'RESULT')
            owner = self.result_owners[temporary]
            if real.split('.o')[0] != reference_map.get(owner, owner):
                raise ValueError('Allocated result does not belong to its declared step')
        existing = self.step_refs - set(self.declared_steps)
        existing_results = set(self.result_owners) - set(self.declared_results)
        if set(reference_map.values()) & (existing | existing_results):
            raise ValueError('Allocation reuses an existing identity')

        def mapped(value):
            if type(value) is str:
                return reference_map.get(value, value)
            if type(value) is list:
                return [mapped(part) for part in value]
            if type(value) is dict:
                # Text and sources are never recursively interpreted as local symbols.
                return {key: map_field(key, part) for key, part in value.items()}
            return value

        reference_fields = {
            'step_ref',
            'temp_step_ref',
            'temp_result_ref',
            'result_ref',
            'dependencies',
            'replaces_step_refs',
            'before_step_ref',
            'replacement_step_refs',
            'result_refs',
            'to_step_ref',
            'return_step_ref',
            'from_result_ref',
            'target_result_refs',
        }

        def map_field(key, value):
            if key in reference_fields:
                return mapped(value)
            if key == 'expected_results':
                return [mapped(item) for item in value]
            from copy import deepcopy

            return deepcopy(value)

        return [mapped(change) for change in changes], [mapped(route) for route in result_routes]


def path_scope(changes, result_routes, *, step_refs, result_owners, branch_refs, issue_refs):
    """Inputs are the complete same-document graph, never a browser's first page."""
    existing_steps = frozenset(step_refs)
    owners = dict(result_owners)
    declared_steps = []
    declared_results = []

    def declare_result(ref, owner, field):
        if ref in owners:
            reject(field, 'INVALID_FORMAT', '临时成果引用只能声明一次')
        owners[ref] = owner
        declared_results.append(ref)

    for index, change in enumerate(changes):
        field = f'changes[{index}]'
        if change['type'] == 'ADD_STEP':
            ref = change['temp_step_ref']
            if ref in existing_steps or ref in declared_steps:
                reject(field + '.temp_step_ref', 'INVALID_FORMAT', '临时步骤引用只能声明一次')
            declared_steps.append(ref)
            for result in change['expected_results']:
                declare_result(result['temp_result_ref'], ref, field + '.expected_results')
        elif change['type'] == 'ADD_RESULT':
            declare_result(
                change['temp_result_ref'], change['step_ref'], field + '.temp_result_ref'
            )

    all_steps = existing_steps | set(declared_steps)
    counts = dict.fromkeys(all_steps, 0)
    for owner in owners.values():
        if owner not in all_steps:
            reject('changes', 'INVALID_FORMAT', '成果所属步骤不在当前文档或本批声明中')
        counts[owner] += 1
    if any(not 1 <= count <= MAX_RESULTS for count in counts.values()):
        reject('changes', 'OUT_OF_RANGE', '每个步骤必须有1至20项预期成果')

    def require(ref, allowed, field):
        if ref is not None and ref not in allowed:
            reject(field, 'INVALID_FORMAT', '引用不属于当前文档或本批声明')

    writes = set()
    write_fields = {
        'SET_GOAL': ('GOAL', 'text'),
        'RENAME_STEP': ('step_ref', 'title'),
        'MOVE_STEP': ('step_ref', 'position'),
        'SET_DEPENDENCIES': ('step_ref', 'dependencies'),
        'UPDATE_RESULT': ('result_ref', 'description'),
        'CANCEL_STEP': ('step_ref', 'status'),
        'MOVE_ISSUE': ('issue_ref', 'step_ref'),
        'SET_BRANCH_RETURN': ('branch_ref', 'return_step_ref'),
        'DISPOSE_ISSUE': ('issue_ref', 'disposition'),
        'RESUME_ISSUE': ('issue_ref', 'disposition'),
        'DISPOSE_BRANCH': ('branch_ref', 'status'),
    }
    for index, change in enumerate(changes):
        field = f'changes[{index}]'
        kind = change['type']
        if kind in write_fields:
            identity, attribute = write_fields[kind]
            key = (change.get(identity, identity), attribute)
            if key in writes:
                reject(field, 'INVALID_FORMAT', '同一批次不能重复写入同一对象字段')
            writes.add(key)
        for key in ('step_ref', 'before_step_ref', 'to_step_ref', 'return_step_ref'):
            if key in change:
                require(change[key], all_steps, field + '.' + key)
        for key in ('dependencies', 'replaces_step_refs', 'replacement_step_refs'):
            for ref in change.get(key, []):
                require(ref, all_steps, field + '.' + key)
        for key, allowed in (
            ('issue_ref', issue_refs),
            ('branch_ref', branch_refs),
            ('result_ref', owners),
        ):
            if key in change:
                require(change[key], allowed, field + '.' + key)
        for ref in change.get('result_refs', []):
            require(ref, owners, field + '.result_refs')
            if owners[ref] != change['step_ref']:
                reject(field + '.result_refs', 'INVALID_FORMAT', '内容关联成果必须属于指定步骤')
        if kind in ('ADD_STEP', 'MOVE_STEP'):
            ref = change.get('temp_step_ref', change.get('step_ref'))
            if ref == change['before_step_ref']:
                reject(field + '.before_step_ref', 'INVALID_FORMAT', '步骤不能移动到自身之前')

    cancelled = {change['step_ref'] for change in changes if change['type'] == 'CANCEL_STEP'}
    expected_routes = {ref for ref, owner in result_owners.items() if owner in cancelled}
    if {route['from_result_ref'] for route in result_routes} != expected_routes:
        reject('result_routes', 'INVALID_FORMAT', '必须逐项明确被取消步骤的全部原成果去向')
    for index, route in enumerate(result_routes):
        for ref in route['target_result_refs']:
            require(ref, owners, f'result_routes[{index}].target_result_refs')
            if owners[ref] in cancelled:
                reject('result_routes', 'INVALID_FORMAT', '成果不能承接到被取消步骤')
    return PathScope(
        frozenset(all_steps),
        MappingProxyType(owners),
        tuple(declared_steps),
        tuple(declared_results),
    )


def planned_references(head, scope, steps):
    """Pure numbering calculation; only the caller's later successful COMMIT consumes numbers."""
    from backend.app.infrastructure.identifiers import increment

    mapping = {}
    next_step = head['next_step_no']
    for temporary in scope.declared_steps:
        mapping[temporary] = f's{next_step}'
        next_step = increment(next_step)
    next_results = {}
    for temporary in scope.declared_results:
        owner = scope.result_owners[temporary]
        if owner not in next_results:
            next_results[owner] = 1 if owner in mapping else steps[owner]['next_result_no']
        number = next_results[owner]
        mapping[temporary] = f'{mapping.get(owner, owner)}.o{number}'
        next_results[owner] = increment(number)
    return mapping, next_results, next_step
