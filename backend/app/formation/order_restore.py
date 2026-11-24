"""Restore only positions from the last eligible order batch; never rewind content or discussion."""

from backend.app.shared.validation import strict_json_loads


def previous_order(connection, document_id):
    row = connection.execute(
        "SELECT json_extract(payload_json,'$.event.batch_ref') FROM document_change_audits "
        "WHERE document_id=? AND reason_code IN ('STEP_MOVED','PATH_INITIALIZED','STEP_ADDED','STEP_CANCELLED') ORDER BY id DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    batch = row[0]
    events = connection.execute(
        "SELECT id,reason_code FROM document_change_audits WHERE document_id=? AND json_extract(payload_json,'$.event.batch_ref')=? ORDER BY id",
        (document_id, batch),
    ).fetchall()
    if any(
        e['reason_code'] in ('STEP_ADDED', 'STEP_CANCELLED', 'PATH_INITIALIZED') for e in events
    ):
        return None
    rows = connection.execute(
        'SELECT c.entity_ref,c.before_json,c.after_json FROM formation_event_changes c JOIN document_change_audits e ON e.id=c.event_id AND e.document_id=c.document_id '
        "WHERE c.document_id=? AND c.entity_kind='ORDER' AND json_extract(e.payload_json,'$.event.batch_ref')=?",
        (document_id, batch),
    ).fetchall()
    actual = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT step_ref,position FROM formation_steps WHERE document_id=? AND status<>'CANCELLED' ORDER BY position",
            (document_id,),
        )
    }
    if not rows or len(rows) > 100:
        return None
    prior = dict(actual)
    affected = []
    for row in rows:
        if row['before_json'] is None or row['after_json'] is None:
            return None
        ref = row['entity_ref']
        before, after = (
            strict_json_loads(row[k])['position'] for k in ('before_json', 'after_json')
        )
        if actual.get(ref) != after:
            return None
        prior[ref] = before
        affected.append({'step_ref': ref, 'before': before, 'after': after})
    if set(prior.values()) != set(actual.values()):
        return None
    return {'batch_id': batch, 'moves': sorted(affected, key=lambda x: x['after'])}


def restore_changes(connection, document_id, candidate):
    """Restore the recorded order using the fewest existing-step moves."""
    current = previous_order(connection, document_id)
    if current is None or current != candidate:
        raise ValueError('The previous order no longer matches the document')
    original_positions = {row['step_ref']: row['before'] for row in current['moves']}
    order = sorted(
        (
            (row[0], original_positions.get(row[0], row[1]))
            for row in connection.execute(
                "SELECT step_ref,position FROM formation_steps WHERE document_id=? AND status<>'CANCELLED'",
                (document_id,),
            )
        ),
        key=lambda row: row[1],
    )
    # The recorded MOVE events identify their subject in the owning STEP fact. A batch
    # may also own displaced neighbors, so compute a minimum set from the actual order.
    from bisect import bisect_left

    ranks = {ref: i for i, (ref, _) in enumerate(order)}
    sequence = [
        row[0]
        for row in connection.execute(
            "SELECT step_ref FROM formation_steps WHERE document_id=? AND status<>'CANCELLED' ORDER BY position",
            (document_id,),
        )
    ]
    tails, end_refs, predecessor = [], [], {}
    for ref in sequence:
        rank = ranks[ref]
        i = bisect_left(tails, rank)
        predecessor[ref] = end_refs[i - 1] if i else None
        if i == len(tails):
            tails.append(rank)
            end_refs.append(ref)
        else:
            tails[i] = rank
            end_refs[i] = ref
    keep = set()
    ref = end_refs[-1]
    while ref is not None:
        keep.add(ref)
        ref = predecessor[ref]
    return [
        {
            'type': 'MOVE_STEP',
            'step_ref': ref,
            'before_step_ref': order[i + 1][0] if i + 1 < len(order) else None,
        }
        for i in reversed(range(len(order)))
        if (ref := order[i][0]) not in keep
    ]
