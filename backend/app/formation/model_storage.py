"""Commit a prepared ordinary AI unit on its actual C07 connection and audited source."""

from collections import Counter

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.json_canonical import canonical_input

from .artifact_links import create_links
from .content_maintenance import range_delta
from .json_arrays import json_array
from .model_facts import bind_events, event_keys, graph_facts
from .model_reviews import classify_associations
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact, artifact_fact, artifact_snapshot
from .read_context import ReadContext
from .recommendations import capture_basis
from .repository import FormationRepository
from .route_storage import persist_graph
from .transaction import FormationTransaction


def _insert(connection, table, row):
    connection.execute(
        'INSERT INTO '
        + table
        + '('
        + ','.join(row)
        + ') VALUES('
        + ','.join('?' for _ in row)
        + ')',
        tuple(row.values()),
    )


def _topics(connection, document_id, table, field, values):
    for ref, wanted in values.items():
        previous = {
            row[0]
            for row in connection.execute(
                'SELECT topic_ref FROM ' + table + ' WHERE document_id=? AND ' + field + '=?',
                (document_id, ref),
            )
        }
        connection.executemany(
            'DELETE FROM ' + table + ' WHERE document_id=? AND ' + field + '=? AND topic_ref=?',
            [(document_id, ref, topic) for topic in sorted(previous - wanted)],
        )
        connection.executemany(
            'INSERT INTO ' + table + '(document_id,' + field + ',topic_ref) VALUES(?,?,?)',
            [(document_id, ref, topic) for topic in sorted(wanted - previous)],
        )


def store_model(
    connection, root_before, plan, run, assistant_id, llm_use_id, at, *, transaction=None
):
    require_write_transaction(connection)
    if plan.evidence.connection is not connection:
        raise ValueError('Model preparation cannot cross transaction/connection boundaries')
    source = connection.execute(
        'SELECT guide_run_id,ended_at,call_status,parse_status,finish_reason FROM llm_uses WHERE id=?',
        (llm_use_id,),
    ).fetchone()
    if (
        source is None
        or source['guide_run_id'] != run['id']
        or source['ended_at'] is None
        or source['call_status'] != 'SUCCEEDED'
        or source['parse_status'] != 'SUCCEEDED'
        or source['finish_reason'] != 'stop'
    ):
        raise ValueError('Formation application requires its actual completed audited model return')
    if not plan.changed:
        return {
            'result': 'NO_CHANGE',
            'event_ids': [],
            'reference_map': [],
            'formation_changed': False,
        }
    document_id = root_before['assistant_document_id']
    original_head = None if plan.initializing else plan.before[0]
    transaction = transaction or FormationTransaction(connection, root_before, original_head)
    associations = classify_associations(plan)
    keys = event_keys(plan, associations)
    if not keys:
        raise ValueError('A changed model plan requires real event facts')
    event_ids = allocate_event_ids(connection, keys)
    route = bind_events(plan, event_ids)
    facts = list(graph_facts(plan, route, keys))
    if plan.initializing:
        if FormationRepository(connection).head(document_id) is not None:
            raise ValueError('A formation cannot initialize twice')
        _insert(connection, 'formation_heads', route.head)
    else:
        actual = FormationRepository(connection).head(document_id, required=True)
        if any(
            actual[name] != plan.before[0][name]
            for name in (
                'version',
                'next_step_no',
                'next_branch_no',
                'next_issue_no',
                'next_artifact_no',
            )
        ):
            raise ValueError('Formation allocation changed inside the C07 owner transaction')
    persist_graph(connection, before=plan.before, resolved=route)
    _topics(connection, document_id, 'formation_step_topics', 'step_ref', plan.step_topics)
    _topics(connection, document_id, 'formation_branch_topics', 'branch_ref', plan.branch_topics)
    changed = connection.execute(
        'UPDATE formation_heads SET next_step_no=?,next_branch_no=?,next_issue_no=?,current_step_ref=?,active_branch_ref=? WHERE document_id=? AND version=?',
        (
            route.head['next_step_no'],
            route.head['next_branch_no'],
            route.head['next_issue_no'],
            route.head['current_step_ref'],
            route.head['active_branch_ref'],
            document_id,
            route.head['version'],
        ),
    )
    if changed.rowcount != 1:
        raise ValueError('Formation graph lost its actual version while committing')
    after = transaction.touch(at)
    extras = Counter()
    extras.update(('ASSESSMENT_RECORDED', row['step_ref']) for row in plan.assessments)
    extras.update(('RECOMMENDATION_RECORDED', row['step_ref']) for row in plan.recommendations)
    sources = _event_sources(plan, associations, keys)
    for index, item in enumerate(associations):
        owner = item['link']['step_ref'] + ':' + str(index)
        if item['reviewed'] is None or item['review_result'] == 'REASSOCIATED':
            extras[('CONTENT_ASSOCIATED', owner)] += 1
        if item['reviewed'] is not None:
            action = (
                'ARTIFACT_REASSOCIATED'
                if item['review_result'] == 'REASSOCIATED'
                else 'ARTIFACT_CHECKED'
            )
            extras[(action, item['reviewed']['artifact_ref'])] += 1
            if (
                item['review_result'] == 'MATCHED'
                and item['reviewed']['checked_against_revision_id'] != item['link']['revision_id']
            ):
                extras[(action, item['reviewed']['artifact_ref'])] += 1
    command = {
        'type': 'FORMATION_DELTA_APPLIED',
        'llm_use_id': llm_use_id,
        'reference_map': [
            {'temp_ref': ref, 'resolved_ref': real} for ref, real in plan.mapping.items()
        ],
    }
    views = write_headers(
        connection,
        root=root_before,
        command=command,
        event_ids=event_ids,
        facts=facts,
        extra_counts=extras,
        message_id=assistant_id,
        key=run['idempotency_key'],
        at=at,
        reason='接收文档形成讨论的结构化更新',
        version_before=transaction.before,
        version_after=after,
        head_before=transaction.focus_before,
        head_after=route.head,
        actor='AI',
        source_run_id=run['id'],
        sources=sources,
    )
    facts.extend(
        _store_associations(connection, root_before, plan, associations, event_ids, assistant_id)
    )
    facts.extend(_store_assessments(connection, plan, event_ids, assistant_id))
    facts.extend(_store_recommendations(connection, root_before, plan, event_ids, assistant_id))
    references = set()
    for event_id in event_ids.values():
        for ref in (transaction.focus_before['current_step_ref'], route.head['current_step_ref']):
            if ref is not None:
                references.add((event_id, 'STEP', ref))
        for ref in (transaction.focus_before['active_branch_ref'], route.head['active_branch_ref']):
            if ref is not None:
                references.add((event_id, 'BRANCH', ref))
    write_facts(connection, document_id, event_ids, views, facts, references=references)
    return {
        'result': 'APPLIED',
        'event_ids': list(event_ids.values()),
        'reference_map': [
            {'temp_ref': ref, 'resolved_ref': real} for ref, real in plan.mapping.items()
        ],
        'formation_changed': True,
    }


def _store_assessments(connection, plan, events, assistant_id):
    facts = []
    document_id = plan.route.head['document_id']
    revision = plan.evidence.context.canonical['formation']['basis']['document_revision_id']
    for item in plan.assessments:
        owner = ('ASSESSMENT_RECORDED', item['step_ref'])
        event_id = events[owner]
        snapshot = {
            'verdict': item['verdict'],
            'reason': item['reason'],
            'goal_version': plan.route.head['goal_version'],
            'evaluated_step_version': plan.route.steps[item['step_ref']]['definition_version'],
            'evaluated_revision_id': revision,
            'coverage_block_ids': item['coverage_block_ids'],
            'source_refs': item['source_refs'],
            'assistant_message_id': assistant_id,
        }
        _insert(
            connection,
            'formation_assessments',
            {
                'id': event_id,
                'document_id': document_id,
                'step_ref': item['step_ref'],
                'event_id': event_id,
                'assistant_message_id': assistant_id,
                'goal_version': snapshot['goal_version'],
                'definition_version': snapshot['evaluated_step_version'],
                'evaluated_revision_id': revision,
                'verdict': item['verdict'],
                'reason': item['reason'],
                'coverage_json': json_array(item['coverage_block_ids']),
                'source_refs_json': json_array(item['source_refs']),
            },
        )
        facts.append(RouteFact('ASSESSMENT', item['step_ref'], None, snapshot, owner))
    return facts


def _store_recommendations(connection, root, plan, events, assistant_id):
    facts = []
    context = ReadContext(connection, root, plan.evidence.catalog)
    current_ids = {
        block['block_id']
        for document in plan.evidence.context.input['documents']
        if document['document_id'] == root['assistant_document_id']
        and document['revision_id'] == context.current['revision_id']
        for block in document['blocks']
    }
    entities = [
        item
        for item in plan.evidence.context.canonical['formation']['coverage']['included']
        if item['kind'] in ('BRANCH', 'ISSUE', 'ARTIFACT')
    ]
    for item in plan.recommendations:
        owner = ('RECOMMENDATION_RECORDED', item['step_ref'])
        coverage = {
            block_id
            for association in plan.associations
            if association['link']['step_ref'] == item['step_ref']
            for block_id in association['link']['block_ids']
        }
        coverage.update(
            block_id
            for assessment in plan.assessments
            if assessment['step_ref'] == item['step_ref']
            for block_id in assessment['coverage_block_ids']
        )
        if not coverage:
            for artifact in plan.evidence.context.canonical['formation']['artifacts']:
                if artifact['step_ref'] == item['step_ref']:
                    coverage.update(artifact['current_block_ids'])
        if not coverage and item['action'] in ('WRITE', 'REVIEW_CONTENT', 'COMPLETE_STEP'):
            coverage.update(current_ids)
        coverage &= current_ids
        basis = capture_basis(
            context,
            item['step_ref'],
            item['target_step_ref'],
            sorted(coverage),
            item['source_refs'],
            entities,
            carried_block_ids=current_ids,
        )
        event_id = events[owner]
        _insert(
            connection,
            'formation_recommendations',
            {
                'id': event_id,
                'document_id': root['assistant_document_id'],
                'step_ref': item['step_ref'],
                'event_id': event_id,
                'assistant_message_id': assistant_id,
                'action': item['action'],
                'reason': item['reason'],
                'target_step_ref': item['target_step_ref'],
                'source_refs_json': json_array(item['source_refs']),
                'basis_json': canonical_input(basis),
            },
        )
        snapshot = {
            'action': item['action'],
            'step_ref': item['target_step_ref'],
            'reason': item['reason'],
            'source_refs': item['source_refs'],
            'assistant_message_id': assistant_id,
            'basis': basis,
        }
        facts.append(RouteFact('RECOMMENDATION', item['step_ref'], None, snapshot, owner))
    return facts


def _store_associations(connection, root, plan, associations, events, assistant_id):
    facts = []
    for index, item in enumerate(associations):
        ref = item['link']['step_ref']
        create_owner = ('CONTENT_ASSOCIATED', ref + ':' + str(index))
        created = None
        if item['reviewed'] is None or item['review_result'] == 'REASSOCIATED':
            created = create_links(
                connection,
                root['assistant_document_id'],
                (item['verified'],),
                (events[create_owner],),
                {ref: '关联内容：' + plan.route.steps[ref]['title']},
            )[0]
            facts.append(
                artifact_fact(
                    created, item['link']['result_refs'], item['verified'].ranges, create_owner
                )
            )
        old = item['reviewed']
        if old is None:
            continue
        action = (
            'ARTIFACT_REASSOCIATED'
            if item['review_result'] == 'REASSOCIATED'
            else 'ARTIFACT_CHECKED'
        )
        owner = (action, old['artifact_ref'])
        if (
            item['review_result'] == 'MATCHED'
            and old['checked_against_revision_id'] != item['link']['revision_id']
        ):
            before_ranges = [
                dict(row)
                for row in connection.execute(
                    "SELECT ordinal,revision_id,block_id,block_digest FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT' ORDER BY ordinal",
                    (root['assistant_document_id'], old['artifact_ref']),
                )
            ]
            after_ranges = [
                {
                    'ordinal': ordinal,
                    'revision_id': item['link']['revision_id'],
                    'block_id': block_id,
                    'block_digest': block_digest,
                }
                for ordinal, (block_id, block_digest) in enumerate(item['verified'].ranges, 1)
            ]
            connection.execute(
                'UPDATE formation_artifacts SET checked_against_revision_id=? WHERE document_id=? AND artifact_ref=?',
                (item['link']['revision_id'], root['assistant_document_id'], old['artifact_ref']),
            )
            connection.execute(
                "DELETE FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT'",
                (root['assistant_document_id'], old['artifact_ref']),
            )
            connection.executemany(
                "INSERT INTO formation_artifact_ranges VALUES(?,?,'CURRENT',?,?,?,?)",
                [
                    (
                        root['assistant_document_id'],
                        old['artifact_ref'],
                        row['ordinal'],
                        row['revision_id'],
                        row['block_id'],
                        row['block_digest'],
                    )
                    for row in after_ranges
                ],
            )
            changed = {**old, 'checked_against_revision_id': item['link']['revision_id']}
            facts.append(
                RouteFact(
                    'ARTIFACT',
                    old['artifact_ref'],
                    artifact_snapshot(old),
                    artifact_snapshot(changed),
                    owner,
                    lambda old=before_ranges, new=after_ranges: range_delta(old, new),
                )
            )
        snapshot = {
            'reviewed_artifact_ref': old['artifact_ref'],
            'replacement_artifact_ref': None if created is None else created['artifact_ref'],
            'result': item['review_result'],
            'checked_against_revision_id': item['link']['revision_id'],
            'assistant_message_id': assistant_id,
            'source_refs': item['source_refs'],
        }
        _insert(
            connection,
            'formation_artifact_reviews',
            {
                'event_id': events[owner],
                'document_id': root['assistant_document_id'],
                **{key: value for key, value in snapshot.items() if key != 'source_refs'},
                'source_refs_json': json_array(snapshot['source_refs']),
            },
        )
        facts.append(RouteFact('ARTIFACT_REVIEW', old['artifact_ref'], None, snapshot, owner))
    return facts


def _event_sources(plan, associations, keys):
    sources = {key: [] for key in keys}
    for item in plan.changes:
        kind = item['type']
        refs = item.get('source_refs', [])
        if kind == 'INITIALIZE_PATH':
            sources[('PATH_INITIALIZED', 'formation')] = item['goal']['source_refs']
        elif kind in ('ADD_ISSUE', 'ADD_BRANCH'):
            ref = plan.mapping[item['temp_ref']]
            sources[('ISSUE_ADDED' if kind == 'ADD_ISSUE' else 'BRANCH_ADDED', ref)] = refs
    for item in plan.assessments:
        sources[('ASSESSMENT_RECORDED', item['step_ref'])] = item['source_refs']
    for item in plan.recommendations:
        sources[('RECOMMENDATION_RECORDED', item['step_ref'])] = item['source_refs']
    for index, item in enumerate(associations):
        key = ('CONTENT_ASSOCIATED', item['link']['step_ref'] + ':' + str(index))
        if key in sources:
            sources[key] = item['source_refs']
        if item['reviewed'] is not None:
            action = (
                'ARTIFACT_REASSOCIATED'
                if item['review_result'] == 'REASSOCIATED'
                else 'ARTIFACT_CHECKED'
            )
            sources[(action, item['reviewed']['artifact_ref'])] = item['source_refs']
    return sources
