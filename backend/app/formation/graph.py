"""Full-graph invariants shared by previews and transactional commits."""

from collections import deque
from collections.abc import Mapping

from backend.app.shared.validation import reject


def acyclic(nodes, edges, field):
    """Iterative Kahn traversal: history depth does not consume Python's recursion stack."""
    nodes = set(nodes)
    outgoing = {node: set() for node in nodes}
    indegrees = dict.fromkeys(nodes, 0)
    for origin, target in edges:
        if origin not in nodes or target not in nodes or origin == target:
            reject(field, 'INVALID_FORMAT', '关系端点必须是不同的同文档步骤')
        if target not in outgoing[origin]:
            outgoing[origin].add(target)
            indegrees[target] += 1
    queue = deque(sorted(node for node, degree in indegrees.items() if degree == 0))
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for target in sorted(outgoing[node]):
            indegrees[target] -= 1
            if indegrees[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        reject(field, 'INVALID_FORMAT', '步骤关系不能形成循环')


def validate_graph(
    steps: Mapping,
    branches: Mapping,
    issues: Mapping,
    *,
    current_step_ref,
    active_branch_ref,
    dependencies,
    replacements,
):
    """Every collection must come from a complete projection of the current transaction."""
    acyclic(steps, dependencies, 'dependencies')
    acyclic(steps, replacements, 'replacements')
    positions = []
    for step in steps.values():
        if step['status'] != 'CANCELLED':
            positions.append(step['position'])
    if sorted(positions) != list(range(1, len(positions) + 1)):
        reject('steps', 'INVALID_FORMAT', '有效步骤顺序必须完整且唯一')
    if current_step_ref is not None and current_step_ref not in steps:
        reject('current_step_ref', 'INVALID_FORMAT', '当前步骤必须属于同文档')
    for branch in branches.values():
        if branch['origin_step_ref'] not in steps or branch['return_step_ref'] not in steps:
            reject('branches', 'INVALID_FORMAT', '支线来源及返回步骤必须属于同文档')
        if branch['status'] == 'OPEN' and steps[branch['return_step_ref']]['status'] == 'CANCELLED':
            reject('branches', 'INVALID_FORMAT', '开放支线不能返回已放弃步骤')
    if active_branch_ref is not None:
        active = branches.get(active_branch_ref)
        if (
            active is None
            or active['status'] != 'OPEN'
            or active['return_step_ref'] != current_step_ref
        ):
            reject('active_branch_ref', 'INVALID_FORMAT', '活动支线必须开放且返回当前步骤')
    for issue in issues.values():
        if issue['step_ref'] not in steps:
            reject('issues', 'INVALID_FORMAT', '问题所属步骤必须属于同文档')
        if issue['disposition'] == 'OPEN' and steps[issue['step_ref']]['status'] == 'CANCELLED':
            reject('issues', 'INVALID_FORMAT', '开放问题不能留在已放弃步骤')
        branch_ref = issue['branch_ref']
        if branch_ref is None:
            continue
        branch = branches.get(branch_ref)
        if branch is None:
            reject('issues', 'INVALID_FORMAT', '关联支线必须属于同文档')
        if (
            issue['disposition'] == 'OPEN'
            and branch['status'] == 'OPEN'
            and issue['step_ref'] != branch['return_step_ref']
        ):
            reject('issues', 'INVALID_FORMAT', '开放问题与开放关联支线必须在同一处理步骤')
