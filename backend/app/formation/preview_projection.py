"""Deterministic preview facts from the validated complete symbolic route."""

from backend.app.shared.validation import strict_json_object

from .artifact_links import current_artifact_matches


def result_groups(results, declared=()):
    order = {ref: index for index, ref in enumerate(declared)}
    groups = {}
    for ref, row in results.items():
        groups.setdefault(row['step_ref'], []).append(
            {
                'result_ref': ref,
                'description': row['description'],
                'kind': row['kind'],
            }
        )

    def position(row):
        ref = row['result_ref']
        return (1, order[ref]) if ref.startswith('new_') else (0, int(ref.split('.o')[1]))

    for rows in groups.values():
        rows.sort(key=position)
    return groups


def step(row, groups):
    if row is None:
        return None
    return {
        'kind': 'STEP',
        'step_ref': row['step_ref'],
        'title': row['title'],
        'status': row['status'],
        'position': row['position'],
        'expected_results': groups[row['step_ref']],
    }


def result(row):
    return (
        None
        if row is None
        else {
            'kind': 'RESULT',
            'result_ref': row['result_ref'],
            'description': row['description'],
            'result_kind': row['kind'],
        }
    )


def issue(row):
    return {
        'kind': 'ISSUE',
        'issue_ref': row['issue_ref'],
        'step_ref': row['step_ref'],
        'disposition': row['disposition'],
    }


def branch(row):
    return {
        'kind': 'BRANCH',
        'branch_ref': row['branch_ref'],
        'origin_step_ref': row['origin_step_ref'],
        'return_step_ref': row['return_step_ref'],
        'status': row['status'],
    }


def affected_items(before, plan):
    old_head, old_steps, old_results, old_branches, old_issues, old_dependencies, _ = before
    old_groups, new_groups = (
        result_groups(old_results),
        result_groups(plan.results, plan.scope.declared_results),
    )
    ordinal = 0
    covered_order = set()
    for change in plan.changes:
        kind = change['type']
        identity = None
        previous = current = None
        if kind == 'SET_GOAL' and old_head['goal_version'] != plan.head['goal_version']:
            identity = 'goal'
            previous, current = (
                {'kind': 'GOAL', 'text': old_head['goal_text']},
                {'kind': 'GOAL', 'text': plan.head['goal_text']},
            )
        elif kind in ('ADD_STEP', 'RENAME_STEP', 'MOVE_STEP', 'CANCEL_STEP'):
            ref = change.get('temp_step_ref', change.get('step_ref'))
            if kind in ('ADD_STEP', 'MOVE_STEP', 'CANCEL_STEP'):
                covered_order.add(ref)
            old, new = old_steps.get(ref), plan.steps[ref]
            field = {
                'ADD_STEP': None,
                'RENAME_STEP': 'title',
                'MOVE_STEP': 'position',
                'CANCEL_STEP': 'status',
            }[kind]
            if old is None or old[field] != new[field]:
                identity, previous, current = ref, step(old, old_groups), step(new, new_groups)
        elif kind == 'SET_DEPENDENCIES':
            ref = change['step_ref']
            old = sorted(target for origin, target in old_dependencies if origin == ref)
            new = sorted(target for origin, target in plan.dependencies if origin == ref)
            if old != new:
                identity = ref
                previous = {'kind': 'DEPENDENCIES', 'step_ref': ref, 'dependencies': old}
                current = {'kind': 'DEPENDENCIES', 'step_ref': ref, 'dependencies': new}
        elif kind in ('UPDATE_RESULT', 'ADD_RESULT'):
            ref = change.get('result_ref', change.get('temp_result_ref'))
            old, new = old_results.get(ref), plan.results[ref]
            if old is None or old['description'] != new['description']:
                identity, previous, current = ref, result(old), result(new)
        elif kind == 'LINK_CONTENT':
            identity = change['step_ref']
            current = {
                'kind': 'ARTIFACT_LINK',
                **{
                    name: change[name]
                    for name in ('step_ref', 'result_refs', 'revision_id', 'block_ids')
                },
            }
        elif kind in ('MOVE_ISSUE', 'DISPOSE_ISSUE', 'RESUME_ISSUE'):
            ref = change['issue_ref']
            old, new = issue(old_issues[ref]), issue(plan.issues[ref])
            if old != new:
                identity, previous, current = ref, old, new
        elif kind in ('SET_BRANCH_RETURN', 'DISPOSE_BRANCH'):
            ref = change['branch_ref']
            old, new = branch(old_branches[ref]), branch(plan.branches[ref])
            if old != new:
                identity, previous, current = ref, old, new
        if identity is not None:
            ordinal += 1
            yield {
                'ordinal': ordinal,
                'change_type': kind,
                'entity_ref': identity,
                'before': previous,
                'after': current,
            }
    # Inserting/moving one node can shift arbitrarily many existing nodes.
    for ref, old in sorted(old_steps.items(), key=lambda item: (item[1]['position'], item[0])):
        new = plan.steps[ref]
        if (
            ref in covered_order
            or old['status'] == 'CANCELLED'
            or new['status'] == 'CANCELLED'
            or old['position'] == new['position']
        ):
            continue
        ordinal += 1
        yield {
            'ordinal': ordinal,
            'change_type': 'MOVE_STEP',
            'entity_ref': ref,
            'before': step(old, old_groups),
            'after': step(new, new_groups),
        }


def reference_labels(plan):
    labels = []
    count = 0
    for change in plan.changes:
        if change['type'] == 'ADD_STEP':
            labels.append({'temp_ref': change['temp_step_ref'], 'preview_label': change['title']})
            for expected in change['expected_results']:
                count += 1
                labels.append(
                    {
                        'temp_ref': expected['temp_result_ref'],
                        'preview_label': '新增成果' + str(count),
                    }
                )
        elif change['type'] == 'ADD_RESULT':
            count += 1
            labels.append(
                {'temp_ref': change['temp_result_ref'], 'preview_label': '新增成果' + str(count)}
            )
    return labels


def semantic_steps(before, plan):
    old_head, old_steps, _old_results, old_branches, old_issues, old_dependencies, old_replaces = (
        before
    )
    if old_head['goal_version'] != plan.head['goal_version']:
        return set(plan.steps)
    touched = {
        ref
        for ref, row in plan.steps.items()
        if (
            ref not in old_steps
            or row['definition_version'] != old_steps[ref]['definition_version']
            or row['status'] != old_steps[ref]['status']
        )
    }
    changed_edges = (set(old_dependencies) ^ set(plan.dependencies)) | (
        set(old_replaces) ^ set(plan.replacements)
    )
    for origin, target in changed_edges:
        touched.update((origin, target))
    for old_rows, new_rows, owner in (
        (old_issues, plan.issues, 'step_ref'),
        (old_branches, plan.branches, 'return_step_ref'),
    ):
        for ref, new in new_rows.items():
            if new != old_rows[ref]:
                touched.update((new[owner], old_rows[ref][owner]))
    for link in plan.links:
        touched.add(link['step_ref'])
    return touched


def warnings(context, before, plan, based_on):
    touched = semantic_steps(before, plan)
    ordinal = 0

    def warning(code, step_ref, related_ref, message):
        nonlocal ordinal
        ordinal += 1
        return {
            'ordinal': ordinal,
            'code': code,
            'step_ref': step_ref,
            'related_ref': related_ref,
            'message': message,
        }

    linked = {ref for link in plan.links for ref in link['result_refs']}
    results = sorted(
        plan.results.values(),
        key=lambda row: (
            int(row['step_ref'].removeprefix('new_step_').removeprefix('s')),
            row['result_ref'],
        ),
    )
    for row in results:
        if (
            row['step_ref'] not in touched
            or row['kind'] != 'CONTENT'
            or row['result_ref'] in linked
        ):
            continue
        proven = False
        if not row['result_ref'].startswith('new_'):
            for artifact in context.connection.execute(
                'SELECT a.* FROM formation_artifacts a JOIN formation_artifact_results ar '
                'ON ar.document_id=a.document_id AND ar.artifact_ref=a.artifact_ref WHERE a.document_id=? '
                "AND ar.result_ref=? AND a.freshness='CURRENT' AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r "
                "WHERE r.document_id=a.document_id AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED')",
                (context.document_id, row['result_ref']),
            ):
                if current_artifact_matches(
                    context.connection, context.document_id, artifact, context.blocks
                ):
                    proven = True
                    break
        if not proven:
            yield warning(
                'OUTSTANDING_CONTENT',
                row['step_ref'],
                row['result_ref'],
                '该预期成果尚无已核实的正文关联。',
            )
    for row in sorted(plan.issues.values(), key=lambda row: int(row['issue_ref'][1:])):
        if row['step_ref'] in touched and row['disposition'] == 'OPEN':
            yield warning(
                'UNRESOLVED_ISSUE',
                row['step_ref'],
                row['issue_ref'],
                '该步骤仍有未解决问题。',
            )
    for row in sorted(plan.branches.values(), key=lambda row: int(row['branch_ref'][1:])):
        if row['return_step_ref'] in touched and row['status'] == 'OPEN':
            yield warning(
                'OPEN_BRANCH',
                row['return_step_ref'],
                row['branch_ref'],
                '该步骤仍有开放支线。',
            )
    for row in context.connection.execute(
        'SELECT p.message_id,p.card_key,p.binding_json FROM formation_proposal_index p WHERE p.document_id=? '
        "AND p.disposition IN ('PENDING','DEFERRED') ORDER BY p.message_id,p.card_key",
        (context.document_id,),
    ):
        binding = strict_json_object(row['binding_json'])
        owner_steps = {item['step_ref'] for item in binding['step_definitions']}
        is_source = based_on is not None and (row['message_id'], row['card_key']) == (
            based_on['message_id'],
            based_on['card_key'],
        )
        if is_source or owner_steps & touched:
            yield warning(
                'PROPOSAL_AFFECTED',
                None,
                None,
                '相关待处理提案的用途将受本次调整影响，请重新核对。',
            )
    for row in context.connection.execute(
        'SELECT a.step_ref,a.goal_version,a.definition_version FROM formation_assessments a WHERE a.document_id=? '
        'AND NOT EXISTS(SELECT 1 FROM formation_assessments newer WHERE newer.document_id=a.document_id '
        'AND newer.step_ref=a.step_ref AND (newer.event_id,newer.id)>(a.event_id,a.id)) ORDER BY a.step_ref',
        (context.document_id,),
    ):
        step_ref = row['step_ref']
        if (
            row['goal_version'] != plan.head['goal_version']
            or row['definition_version'] != plan.steps[step_ref]['definition_version']
        ):
            yield warning(
                'ASSESSMENT_STALE', step_ref, step_ref, '该步骤的原评估与调整后的目标或定义不一致。'
            )
    old_focus, new_focus = before[0], plan.head
    if old_focus['current_step_ref'] is not None and new_focus['current_step_ref'] is None:
        yield warning(
            'FOCUS_CLEARED',
            old_focus['current_step_ref'],
            old_focus['active_branch_ref'],
            '当前讨论目标将清除，可重新选择步骤继续。',
        )
    elif old_focus['active_branch_ref'] is not None and new_focus['active_branch_ref'] is None:
        yield warning(
            'FOCUS_CLEARED',
            old_focus['current_step_ref'],
            old_focus['active_branch_ref'],
            '当前活动支线将退出，继续步骤讨论。',
        )
