"""Real audit identities and immutable scalar/member history in one caller transaction."""

import hashlib

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_loads

from .digests import ArrayDigest

EVENT_ACTIONS = frozenset(
    [
        'PATH_INITIALIZED',
        'GOAL_CHANGED',
        'STEP_ADDED',
        'STEP_UPDATED',
        'STEP_MOVED',
        'STEP_STARTED',
        'STEP_PAUSED',
        'STEP_RESUMED',
        'STEP_REOPENED',
        'STEP_COMPLETED',
        'STEP_CANCELLED',
        'DISCUSSION_STEP_SELECTED',
        'RESULT_ROUTE',
        'ISSUE_ADDED',
        'ISSUE_UPDATED',
        'ISSUE_RESOLVED',
        'ISSUE_MOVED',
        'ISSUE_DISPOSITION_CHANGED',
        'ISSUE_RESUMED',
        'BRANCH_ADDED',
        'BRANCH_UPDATED',
        'BRANCH_RESULT_RECORDED',
        'BRANCH_ENTERED',
        'BRANCH_RETURNED',
        'BRANCH_RETURN_CHANGED',
        'BRANCH_DISPOSITION_CHANGED',
        'BRANCH_RESUMED',
        'BRANCH_REOPENED',
        'ASSESSMENT_RECORDED',
        'RECOMMENDATION_RECORDED',
        'CONTENT_ASSOCIATED',
        'ARTIFACT_CHECKED',
        'ARTIFACT_REASSOCIATED',
        'PROPOSAL_DEFERRED',
        'PROPOSAL_RESUMED',
        'PROPOSAL_ADJUSTMENT_REQUESTED',
        'PROPOSAL_ADJUSTMENT_WITHDRAWN',
        'PROPOSAL_SUPERSEDED',
        'PROPOSAL_APPLIED',
    ]
)


def scalar_snapshot(kind, row):
    if row is None:
        return None
    if kind == 'STEP':
        fields = ('step_ref', 'definition_version', 'title', 'status', 'position', 'next_result_no')
        return {**{key: row[key] for key in fields}, 'closure_event_ref': row['closure_event_id']}
    if kind == 'BRANCH':
        fields = (
            'branch_ref',
            'origin_step_ref',
            'return_step_ref',
            'question',
            'relevance',
            'status',
            'result_summary',
        )
        return {
            **{key: row[key] for key in fields},
            'origin_event_ref': row['origin_event_id'],
            'state_event_ref': row['state_event_id'],
            'disposition_event_ref': row['disposition_event_id'],
        }
    if kind == 'ISSUE':
        fields = (
            'issue_ref',
            'step_ref',
            'branch_ref',
            'description',
            'disposition',
            'disposition_reason',
        )
        return {
            **{key: row[key] for key in fields},
            'blocking': bool(row['blocking']),
            'disposition_event_ref': row['disposition_event_id'],
        }
    raise ValueError('Unsupported native scalar snapshot kind')


def source_members(collection, before_json, after_json):
    def indexed(raw):
        result = {}
        for source in strict_json_loads(raw):
            key = hashlib.sha256(canonical_input(source).encode('utf-8')).hexdigest()
            result[key] = {'kind': 'SOURCE', 'source_ref': source}
        return result

    before, after = indexed(before_json), indexed(after_json)
    ordinal = 0
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old != new:
            ordinal += 1
            yield {
                'ordinal': ordinal,
                'collection': collection,
                'member_key': key,
                'before': old,
                'after': new,
            }


MEMBER_COLLECTIONS = (
    'DEPENDENCY',
    'REPLACES',
    'TOPIC',
    'GOAL_SOURCE',
    'ISSUE_SOURCE',
    'ISSUE_RESOLUTION_SOURCE',
    'BRANCH_TOPIC',
    'BRANCH_RESULT_SOURCE',
    'ARTIFACT_RESULT',
    'ORIGIN_RANGE',
    'CURRENT_RANGE',
)


def ordered_members(rows):
    previous = None
    for ordinal, item in enumerate(rows, 1):
        key = (MEMBER_COLLECTIONS.index(item['collection']), item['member_key'].encode('utf-8'))
        if item['ordinal'] != ordinal or previous is not None and key <= previous:
            raise ValueError(
                'Member ordinals and collection/key order must be consecutive and stable'
            )
        previous = key
        yield item


def record_change(connection, document_id, event_id, ordinal, kind, ref, before, after, members=()):
    require_write_transaction(connection)
    if callable(members):
        produce = members
    elif isinstance(members, (list, tuple)):
        produce = lambda: iter(members)
    else:
        raise TypeError('Large member changes require a repeatable generator factory')

    def measured(rows):
        digest = ArrayDigest()
        count = 0
        for item in rows:
            count += 1
            if item['ordinal'] != count:
                raise ValueError('Member ordinals must be consecutive and stable')
            digest.append(item)
        return count, digest.hexdigest()

    count, digest = measured(ordered_members(produce()))
    connection.execute(
        'INSERT INTO formation_event_changes(event_id,ordinal,document_id,entity_kind,entity_ref,'
        'before_json,after_json,member_count,member_digest) VALUES(?,?,?,?,?,?,?,?,?)',
        (
            event_id,
            ordinal,
            document_id,
            kind,
            ref,
            None if before is None else canonical_input(before),
            None if after is None else canonical_input(after),
            count,
            digest,
        ),
    )
    actual_digest = ArrayDigest()
    actual_count = 0
    batch = []

    def flush():
        connection.executemany(
            'INSERT INTO formation_event_members(event_id,change_ordinal,ordinal,document_id,collection,'
            'member_key,before_json,after_json) VALUES(?,?,?,?,?,?,?,?)',
            batch,
        )
        batch.clear()

    for item in ordered_members(produce()):
        actual_count += 1
        if item['ordinal'] != actual_count:
            raise ValueError('Member ordinals changed between validation and storage')
        actual_digest.append(item)
        batch.append(
            (
                event_id,
                ordinal,
                item['ordinal'],
                document_id,
                item['collection'],
                item['member_key'],
                None if item['before'] is None else canonical_input(item['before']),
                None if item['after'] is None else canonical_input(item['after']),
            )
        )
        if len(batch) == 100:
            flush()
    if batch:
        flush()
    if actual_count != count or actual_digest.hexdigest() != digest:
        raise ValueError('Member facts changed during their immutable publication')


def record_state_event(
    connection,
    *,
    event_id,
    root,
    before,
    mutation,
    message_id,
    key,
    at,
    reason,
    version_before,
    version_after,
    command,
    source_run_id=None,
    source=None,
):
    require_write_transaction(connection)
    if not mutation.changed or mutation.action not in EVENT_ACTIONS:
        raise ValueError('Only a real registered transition can create a native event')
    document_id = root['assistant_document_id']
    changes = []
    references = set()
    for kind, identity, previous, current in (
        ('STEP', 'step_ref', before[1], mutation.steps),
        ('BRANCH', 'branch_ref', before[2], mutation.branches),
        ('ISSUE', 'issue_ref', before[3], mutation.issues),
    ):
        for ref in sorted(current):
            if previous[ref] == current[ref]:
                continue
            old, new = previous[ref], current[ref]
            members = []
            if kind == 'BRANCH' and old['result_sources_json'] != new['result_sources_json']:
                members = list(
                    source_members(
                        'BRANCH_RESULT_SOURCE',
                        old['result_sources_json'],
                        new['result_sources_json'],
                    )
                )
            changes.append(
                (kind, ref, scalar_snapshot(kind, old), scalar_snapshot(kind, new), members)
            )
            references.add((kind, ref))
            if kind == 'BRANCH':
                references.update(('STEP', row['return_step_ref']) for row in (old, new))
            if kind == 'ISSUE':
                references.update(('STEP', row['step_ref']) for row in (old, new))
    for head in (before[0], mutation.head):
        if head['current_step_ref'] is not None:
            references.add(('STEP', head['current_step_ref']))
        if head['active_branch_ref'] is not None:
            references.add(('BRANCH', head['active_branch_ref']))
    from .path_events import write_headers, write_facts
    from .path_facts import RouteFact

    event_key = (mutation.action, str(event_id))
    event_ids = {event_key: event_id}
    facts = [
        RouteFact(kind, ref, old, new, event_key, members)
        for kind, ref, old, new, members in changes
    ]
    views = write_headers(
        connection,
        root=root,
        command=command,
        event_ids=event_ids,
        facts=facts,
        extra_counts={},
        message_id=message_id,
        key=key,
        at=at,
        reason=reason,
        version_before=version_before,
        version_after=version_after,
        head_before=before[0],
        head_after=mutation.head,
        actor='AI' if source_run_id is not None else 'USER',
        source_run_id=source_run_id,
        sources={event_key: [source]} if source is not None else None,
    )
    write_facts(
        connection,
        document_id,
        event_ids,
        views,
        facts,
        references=[(event_id, kind, ref) for kind, ref in references],
    )
    return views[0]
