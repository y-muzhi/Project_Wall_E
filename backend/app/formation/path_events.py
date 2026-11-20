"""Immutable manual route event batches over original audit identities."""

from collections import Counter

from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_integer

from .events import EVENT_ACTIONS, record_change
from .types import reference


def allocate_event_ids(connection, keys):
    require_write_transaction(connection)
    if not keys or len(set(keys)) != len(keys):
        raise ValueError('A route batch requires unique actual event keys')
    if any(action not in EVENT_ACTIONS for action, _ in keys):
        raise ValueError('Unregistered route event action')
    return {key: entity_id(connection, EntityKind.DOCUMENT_AUDIT) for key in keys}


def write_headers(
    connection,
    *,
    root,
    command,
    event_ids,
    facts,
    extra_counts,
    message_id,
    key,
    at,
    reason,
    version_before,
    version_after,
    head_before,
    head_after,
    closures=None,
    reasons=None,
    actor='USER',
    source_run_id=None,
    sources=None,
    content_effect=None,
):
    require_write_transaction(connection)
    document_id = root['assistant_document_id']
    message = connection.execute(
        'SELECT * FROM conversation_messages WHERE id=? AND requirement_id=? AND document_id=?',
        (message_id, root['id'], document_id),
    ).fetchone()
    if actor not in ('USER', 'AI'):
        raise ValueError('Route event actor must be a real user input or audited assistant')
    if source_run_id is None:
        if (
            actor != 'USER'
            or message is None
            or message['role'] != 'USER'
            or message['guide_run_id'] is not None
            or message['idempotency_key'] != key
            or message['created_at'] != at
        ):
            raise ValueError('A manual route requires its actual newly recorded user action')
    else:
        run = connection.execute(
            'SELECT * FROM guide_runs WHERE id=? AND requirement_id=? AND document_id=?',
            (source_run_id, root['id'], document_id),
        ).fetchone()
        if (
            run is None
            or message is None
            or message['guide_run_id'] != source_run_id
            or message['role'] != ('USER' if actor == 'USER' else 'ASSISTANT')
            or run['idempotency_key'] != key
            or run['function_type'] != 'collaboration_v1'
            or run['status'] != 'RUNNING'
            or message['created_at'] != at
            or actor == 'USER'
            and run['trigger_message_id'] != message_id
        ):
            raise ValueError('Formation event must bind its real accepted round and source message')
    expected_f = (
        1
        if version_before['formation_version'] is None
        else version_before['formation_version'] + 1
    )
    content_unchanged = (
        version_after['content_version'] == version_before['content_version']
        and version_after['document_revision_id'] == version_before['document_revision_id']
    )
    if content_effect is not None and not content_unchanged:
        actual = connection.execute(
            "SELECT 1 FROM document_change_audits WHERE document_id=? AND revision_id=? AND source_type='CARD_RESPONSE' AND source_id=? AND event_type='CONTENT_COMMITTED' AND before_content_version=? AND after_content_version=?",
            (
                document_id,
                version_after['document_revision_id'],
                message_id,
                version_before['content_version'],
                version_after['content_version'],
            ),
        ).fetchone()
        if (
            actor != 'USER'
            or source_run_id is not None
            or message['message_type'] != 'CARD_RESPONSE'
            or actual is None
            or (
                content_effect['document_id'],
                content_effect['revision_id'],
                content_effect['after_content_version'],
            )
            != (
                document_id,
                version_after['document_revision_id'],
                version_after['content_version'],
            )
        ):
            raise ValueError(
                'Content events require their real same-transaction exact card adoption'
            )
    elif not content_unchanged:
        raise ValueError('A route-only batch cannot change document content')
    if (
        version_after['discussion_version'] != version_before['discussion_version'] + 1
        or version_after['formation_version'] != expected_f
    ):
        raise ValueError('One formation transaction changes D and F exactly once')
    identities = [(fact.kind, fact.ref) for fact in facts]
    if len(set(identities)) != len(identities):
        raise ValueError('A route batch must freeze each final scalar/member fact once')
    for count in extra_counts.values():
        strict_integer(count, 'extra_fact_count', minimum=0)
    closures = {} if closures is None else closures
    reasons = {} if reasons is None else reasons
    counts = Counter(fact.owner for fact in facts)
    counts.update(extra_counts)
    if set(counts) - set(event_ids):
        raise ValueError('Every actual fact must belong to this event batch')
    batch_ref = next(iter(event_ids.values()))
    views = []
    for ordinal, (event_key, event_id) in enumerate(event_ids.items(), 1):
        action, _ = event_key
        view = {
            'event_id': event_id,
            'action': action,
            'actor': actor,
            'reason': reasons.get(event_key, reason),
            'created_at': at,
            'schema': 'formation_event_v1',
            'document_id': document_id,
            'batch_ref': batch_ref,
            'ordinal': ordinal,
            'batch_size': len(event_ids),
            'version_before': version_before,
            'version_after': version_after,
            'change_count': counts[event_key],
            'closure': closures.get(event_key),
        }
        payload = {
            'formation_event_type': action,
            'event': view,
            'command_message_id': message_id,
            'idempotency_key': key,
            'command': command if ordinal == 1 else None,
            'focus_before': {
                name: head_before[name] for name in ('current_step_ref', 'active_branch_ref')
            },
            'focus_after': {
                name: head_after[name] for name in ('current_step_ref', 'active_branch_ref')
            },
        }
        if sources is not None:
            from .types import sources as source_values

            payload['source_refs'] = source_values(sources.get(event_key, []), 'event.source_refs')
        connection.execute(
            'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,'
            'before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) '
            "VALUES(?,?,?,?,?,?,NULL,NULL,?,'DISCUSSION_UPDATED',NULL,?,?)",
            (
                event_id,
                root['id'],
                document_id,
                'AI_MESSAGE' if actor == 'AI' else 'USER_ACTION',
                message_id,
                action,
                at,
                source_run_id,
                canonical_input(payload),
            ),
        )
        views.append(view)
    return tuple(views)


def fact_references(fact):
    refs = set()

    def add(kind, ref):
        if ref is not None:
            reference(ref, 'event_reference', kind)
            refs.add((kind, ref))

    if fact.kind in ('STEP', 'ORDER'):
        add('STEP', fact.ref)
    elif fact.kind == 'RESULT':
        add('RESULT', fact.ref)
        add('STEP', fact.ref.split('.o')[0])
    elif fact.kind in ('ISSUE', 'BRANCH', 'ARTIFACT'):
        add(fact.kind, fact.ref)
    for snapshot in (fact.before, fact.after):
        if snapshot is None:
            continue
        for name in ('step_ref', 'origin_step_ref', 'return_step_ref'):
            if name in snapshot:
                add('STEP', snapshot[name])
        if 'branch_ref' in snapshot:
            add('BRANCH', snapshot['branch_ref'])
        if fact.kind == 'RESULT_ROUTE':
            for ref in (snapshot['from_result_ref'], *snapshot['target_result_refs']):
                add('RESULT', ref)
                add('STEP', ref.split('.o')[0])
    return refs


def write_facts(connection, document_id, event_ids, views, facts, *, references=()):
    require_write_transaction(connection)
    ordinals = Counter()
    references = set(references)
    allowed_ids = set(event_ids.values())
    for event_id, kind, ref in references:
        if event_id not in allowed_ids or kind not in (
            'STEP',
            'BRANCH',
            'ISSUE',
            'ARTIFACT',
            'RESULT',
        ):
            raise ValueError('Extra history references must belong to this real event batch')
        reference(ref, 'event_reference', kind)
    for fact in facts:
        if fact.owner not in event_ids:
            raise ValueError('A route fact cannot refer to another batch')
        event_id = event_ids[fact.owner]
        ordinals[event_id] += 1
        record_change(
            connection,
            document_id,
            event_id,
            ordinals[event_id],
            fact.kind,
            fact.ref,
            fact.before,
            fact.after,
            fact.members,
        )
        for kind, ref in fact_references(fact):
            references.add((event_id, kind, ref))
    for event_id, kind, ref in sorted(references):
        connection.execute(
            'INSERT INTO formation_event_refs(document_id,event_id,kind,ref) VALUES(?,?,?,?)',
            (document_id, event_id, kind, ref),
        )
    for view in views:
        if ordinals[view['event_id']] != view['change_count']:
            raise ValueError('Route event head and immutable scalar detail counts differ')
        actual = connection.execute(
            'SELECT count(*) FROM formation_event_changes WHERE document_id=? AND event_id=?',
            (document_id, view['event_id']),
        ).fetchone()[0]
        if actual != view['change_count']:
            raise ValueError('Route history is incomplete; the whole transaction must roll back')
