"""Read committed route changes for a message window using historical event facts."""

from backend.app.shared.validation import strict_json_loads


def historical_title(connection, document, ref, batch):
    if not ref:
        return None
    row = connection.execute(
        "SELECT json_extract(after_json,'$.title') FROM formation_event_changes WHERE document_id=? AND entity_kind='STEP' AND entity_ref=? AND event_id<=? AND after_json IS NOT NULL ORDER BY event_id DESC LIMIT 1",
        (document, ref, batch),
    ).fetchone()
    if row is None:
        row = connection.execute(
            "SELECT json_extract(before_json,'$.title') FROM formation_event_changes WHERE document_id=? AND entity_kind='STEP' AND entity_ref=? AND event_id>? AND before_json IS NOT NULL ORDER BY event_id LIMIT 1",
            (document, ref, batch),
        ).fetchone()
    if row is None:
        row = connection.execute(
            'SELECT title FROM formation_steps WHERE document_id=? AND step_ref=?', (document, ref)
        ).fetchone()
    return row[0] if row else None


LIFECYCLE_LABELS = {
    'STEP_COMPLETED': '已结束步骤',
    'STEP_PAUSED': '已暂停步骤',
    'STEP_REOPENED': '已重新打开步骤',
    'STEP_RESUMED': '已恢复步骤',
    'BRANCH_DISPOSITION_CHANGED': '已更新支线',
    'BRANCH_ENTERED': '已进入支线',
    'BRANCH_RETURNED': '已返回主线',
    'BRANCH_RESUMED': '已继续支线',
    'BRANCH_REOPENED': '已重新打开支线',
    'ISSUE_RESUMED': '已恢复问题',
    'ISSUE_DISPOSITION_CHANGED': '已更新问题状态',
    'BRANCH_RETURN_CHANGED': '已修改支线返回步骤',
    'ISSUE_MOVED': '已转交问题',
    'RESULT_ROUTE': '已安排成果承接',
    'CONTENT_ASSOCIATED': '已关联正文成果',
}


def chat_operations(connection, requirement_id, document_id, message_ids):
    if not message_ids or document_id is None:
        return {}
    if not connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE name='formation_event_changes' AND type='table'"
    ).fetchone():
        return {}
    slots = ','.join('?' for _ in message_ids)
    rows = connection.execute(
        'SELECT a.source_id,a.reason_code,a.payload_json,c.entity_kind,c.before_json,c.after_json '
        'FROM document_change_audits a LEFT JOIN formation_event_changes c '
        "ON c.document_id=a.document_id AND c.event_id=a.id AND c.entity_kind IN ('STEP','GOAL') "
        "WHERE a.requirement_id=? AND a.document_id=? AND a.event_type='DISCUSSION_UPDATED' "
        "AND a.source_type IN ('AI_MESSAGE','USER_ACTION') AND a.source_id IN (" + slots + ') '
        "AND a.reason_code IN ('PATH_INITIALIZED','GOAL_CHANGED','STEP_ADDED','STEP_UPDATED',"
        "'STEP_CANCELLED','STEP_MOVED','DISCUSSION_STEP_SELECTED','STEP_STARTED','STEP_RESUMED',"
        "'STEP_COMPLETED','STEP_PAUSED','STEP_REOPENED','BRANCH_DISPOSITION_CHANGED','BRANCH_ENTERED','BRANCH_RETURNED','BRANCH_RESUMED','BRANCH_REOPENED','ISSUE_RESUMED','ISSUE_DISPOSITION_CHANGED','BRANCH_RETURN_CHANGED','ISSUE_MOVED','RESULT_ROUTE','CONTENT_ASSOCIATED') "
        'ORDER BY a.id,c.ordinal',
        (requirement_id, document_id, *message_ids),
    )
    groups = {}
    batch_commands = {}
    for row in rows:
        payload = strict_json_loads(row['payload_json'])
        event = payload.get('event', {})
        if (
            payload.get('command_message_id') != row['source_id']
            or event.get('document_id') != document_id
        ):
            continue
        action = row['reason_code']
        if action in (
            'CONTENT_ASSOCIATED',
            'ISSUE_DISPOSITION_CHANGED',
            'ISSUE_MOVED',
            'RESULT_ROUTE',
            'BRANCH_RETURN_CHANGED',
        ):
            batch = event['batch_ref']
            if batch not in batch_commands:
                command = connection.execute(
                    "SELECT json_extract(payload_json,'$.command.type') FROM document_change_audits WHERE document_id=? AND id=?",
                    (document_id, batch),
                ).fetchone()
                batch_commands[batch] = None if command is None else command[0]
            if batch_commands[batch] == 'FORMATION_DELTA_APPLIED':
                continue
        group = groups.setdefault(
            (row['source_id'], event['batch_ref']),
            {
                'actions': set(),
                'steps': {},
                'moves': {},
                'goal': None,
                'focus_changed': False,
                'focus_ref': None,
                'from_focus': payload['focus_before']['current_step_ref'],
                'labels': {},
                'last_event': event['event_id'],
            },
        )
        group['actions'].add(action)
        group['last_event'] = event['event_id']
        if (
            action == 'STEP_UPDATED'
            and row['before_json']
            and row['after_json']
            and row['entity_kind'] == 'STEP'
        ):
            old = strict_json_loads(row['before_json'])
            new = strict_json_loads(row['after_json'])
            if old['title'] != new['title']:
                group['labels'].setdefault('RENAME', '已修改步骤名称')
        if action in LIFECYCLE_LABELS:
            group['labels'].setdefault(action, LIFECYCLE_LABELS[action])
        group['focus_changed'] |= payload['focus_before'] != payload['focus_after']
        group['focus_ref'] = payload['focus_after']['current_step_ref']
        if row['after_json'] is None:
            continue
        value = strict_json_loads(row['after_json'])
        if row['entity_kind'] == 'GOAL':
            group['goal'] = value['text']
        elif row['entity_kind'] == 'STEP':
            ref = value['step_ref']
            group['steps'][ref] = value
            if row['reason_code'] == 'STEP_MOVED' and row['before_json'] is not None:
                previous = strict_json_loads(row['before_json'])
                if previous['position'] != value['position']:
                    group['moves'][ref] = {
                        'title': value['title'],
                        'before': previous['position'],
                        'after': value['position'],
                    }
    result = {}
    for (message, batch), group in groups.items():
        actions = group['actions']
        if 'PATH_INITIALIZED' in actions:
            kind = 'CREATED'
        elif actions.intersection(
            ('GOAL_CHANGED', 'STEP_ADDED', 'STEP_UPDATED', 'STEP_CANCELLED', 'STEP_MOVED')
        ):
            kind = 'UPDATED'
        elif any(action in actions for action in LIFECYCLE_LABELS if action != 'STEP_RESUMED'):
            kind = 'UPDATED'
        elif group['focus_changed']:
            kind = 'FOCUSED'
        else:
            continue
        if kind == 'UPDATED' and {'STEP_ADDED', 'STEP_CANCELLED'} <= actions:
            sources = {}
            targets = {}
            edges = connection.execute(
                "SELECT c.entity_ref,m.member_key FROM formation_event_members m JOIN formation_event_changes c ON c.event_id=m.event_id AND c.ordinal=m.change_ordinal JOIN document_change_audits a ON a.id=m.event_id WHERE m.document_id=? AND m.event_id BETWEEN ? AND ? AND json_extract(a.payload_json,'$.event.batch_ref')=? AND m.collection='REPLACES' AND m.before_json IS NULL AND m.after_json IS NOT NULL",
                (document_id, batch, group['last_event'], batch),
            )
            for new, old in edges:
                sources.setdefault(old, set()).add(new)
                targets.setdefault(new, set()).add(old)
            if any(len(refs) > 1 for refs in sources.values()):
                group['labels']['SPLIT'] = '已拆分步骤'
            if any(len(refs) > 1 for refs in targets.values()):
                group['labels']['MERGE'] = '已合并步骤'
        steps = sorted(group['steps'].values(), key=lambda step: step['position'])
        result.setdefault(message, []).append(
            {
                'batch_id': batch,
                'kind': kind,
                'goal': group['goal'],
                'steps': [step['title'] for step in steps],
                'moves': sorted(group['moves'].values(), key=lambda move: move['after']),
                'focus_title': group['steps'].get(group['focus_ref'], {}).get('title')
                or historical_title(
                    connection, document_id, group['focus_ref'], group['last_event']
                ),
                'previous_focus_title': historical_title(
                    connection, document_id, group['from_focus'], batch - 1
                )
                if group['focus_changed']
                else None,
                'actions': list(group['labels'].values()),
            }
        )
    return result
