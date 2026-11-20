"""Public entity projections on one read snapshot; no complete history is embedded."""

from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.shared.validation import strict_json_loads, strict_json_object

from .artifact_links import block_digest
from .availability import branch_actions, issue_actions, step_actions
from .history_contracts import validate as history_value
from .history_queries import closure_head
from .read_contracts import validate
from .recommendations import latest_recommendation


def last_event(context, kind, ref):
    row = context.connection.execute(
        'SELECT e.payload_json FROM formation_event_refs r JOIN document_change_audits e ON e.id=r.event_id '
        'WHERE r.document_id=? AND r.kind=? AND r.ref=? ORDER BY r.event_id DESC LIMIT 1',
        (context.document_id, kind, ref),
    ).fetchone()
    if row is None:
        return None
    event = strict_json_object(row[0])['event']
    return history_value(
        'EventSummary',
        {name: event[name] for name in ('event_id', 'action', 'actor', 'reason', 'created_at')},
    )


def latest_assessment(context, step):
    row = context.connection.execute(
        'SELECT * FROM formation_assessments WHERE document_id=? AND step_ref=? ORDER BY event_id DESC,id DESC LIMIT 1',
        (context.document_id, step['step_ref']),
    ).fetchone()
    if row is None:
        return None
    coverage = strict_json_loads(row['coverage_json'])
    value = {
        'verdict': row['verdict'],
        'reason': row['reason'],
        'goal_version': row['goal_version'],
        'evaluated_step_version': row['definition_version'],
        'evaluated_revision_id': row['evaluated_revision_id'],
        'coverage_block_ids': coverage,
        'source_refs': strict_json_loads(row['source_refs_json']),
        'assistant_message_id': row['assistant_message_id'],
    }
    history_value('AssessmentSnapshot', value)
    reason = None
    if row['goal_version'] != context.head['goal_version']:
        reason = 'GOAL_CHANGED'
    elif row['definition_version'] != step['definition_version']:
        reason = 'DEFINITION_CHANGED'
    elif coverage:
        original = context.connection.execute(
            'SELECT markdown_snapshot,block_state_snapshot_json FROM revisions WHERE id=? AND document_id=?',
            (row['evaluated_revision_id'], context.document_id),
        ).fetchone()
        if original is None:
            raise ValueError('Assessment lost its immutable Revision')
        snapshot = validate_snapshot(
            original['markdown_snapshot'],
            strict_json_object(original['block_state_snapshot_json']),
            DocumentSources(
                context.connection,
                context.root['id'],
                context.resources,
                document_id=context.document_id,
            ),
        )
        if any(
            identity not in snapshot.by_id
            or identity not in context.blocks
            or block_digest(snapshot.by_id[identity][0].markdown)
            != block_digest(context.blocks[identity][0].markdown)
            for identity in coverage
        ):
            reason = 'COVERAGE_CHANGED'
    return validate(
        'AssessmentView',
        {**value, 'validity': 'CURRENT' if reason is None else 'STALE', 'stale_reason': reason},
    )


def relation_counts(context, step_ref):
    statements = {
        'dependencies': "SELECT count(*) FROM formation_step_edges WHERE document_id=? AND from_step_ref=? AND kind='DEPENDENCY'",
        'replaces': "SELECT count(*) FROM formation_step_edges WHERE document_id=? AND from_step_ref=? AND kind='REPLACES'",
        'topics': 'SELECT count(*) FROM formation_step_topics WHERE document_id=? AND step_ref=?',
        'issues': 'SELECT count(*) FROM formation_issues WHERE document_id=? AND step_ref=?',
        'branches': 'SELECT count(*) FROM formation_branches WHERE document_id=? AND return_step_ref=?',
        'artifacts': 'SELECT count(*) FROM formation_artifacts a WHERE a.document_id=? AND a.step_ref=? AND NOT EXISTS('
        'SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
        "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED')",
    }
    return {
        name: context.connection.execute(sql, (context.document_id, step_ref)).fetchone()[0]
        for name, sql in statements.items()
    }


def step_view(context, row, *, detail=False):
    step = dict(row)
    ref = step['step_ref']
    result = {
        'step_ref': ref,
        'definition_version': step['definition_version'],
        'title': step['title'],
        'status': step['status'],
        'position': context.repository.display_position(context.document_id, ref, step['position']),
        'expected_results': [
            dict(item)
            for item in context.connection.execute(
                'SELECT result_ref,description,kind FROM formation_results WHERE document_id=? AND step_ref=? '
                "ORDER BY CAST(substr(result_ref,instr(result_ref,'.o')+2) AS INTEGER)",
                (context.document_id, ref),
            )
        ],
        'relation_counts': relation_counts(context, ref),
        'last_event': last_event(context, 'STEP', ref),
        'assessment': latest_assessment(context, step),
        'recommendation': latest_recommendation(context, ref),
        'availability': step_actions(step, context.busy),
    }
    if detail:
        result['closure'] = (
            closure_head(context.connection, context.document_id, step['closure_event_id'])
            if (step['status'] == 'COMPLETED' and step['closure_event_id'] is not None)
            else None
        )
        source_map = {}
        groups = [strict_json_loads(context.head['goal_sources_json'])]
        groups.extend(
            value['source_refs']
            for value in (result['assessment'], result['recommendation'])
            if value is not None
        )
        from backend.app.shared.json_canonical import canonical_input

        for group in groups:
            for source in group:
                source_map[canonical_input(source)] = source
        result['sources'] = [context.source_status(source_map[key]) for key in sorted(source_map)]
    return validate('StepDetail' if detail else 'StepView', result)


def branch_view(context, row):
    fields = (
        'branch_ref',
        'origin_step_ref',
        'return_step_ref',
        'question',
        'relevance',
        'status',
        'result_summary',
    )
    value = {name: row[name] for name in fields}
    value.update(
        origin_event_ref=row['origin_event_id'],
        state_event_ref=row['state_event_id'],
        disposition_event_ref=row['disposition_event_id'],
        result_source_refs=strict_json_loads(row['result_sources_json']),
        topic_count=context.connection.execute(
            'SELECT count(*) FROM formation_branch_topics WHERE document_id=? AND branch_ref=?',
            (context.document_id, row['branch_ref']),
        ).fetchone()[0],
        availability=branch_actions(
            context.connection, context.document_id, row, context.head, context.busy
        ),
    )
    return validate('BranchView', value)


def issue_view(context, row):
    fields = (
        'issue_ref',
        'step_ref',
        'branch_ref',
        'description',
        'disposition',
        'disposition_reason',
    )
    value = {name: row[name] for name in fields}
    value.update(
        blocking=bool(row['blocking']),
        source_refs=strict_json_loads(row['source_refs_json']),
        resolution_source_refs=strict_json_loads(row['resolution_sources_json']),
        disposition_event_ref=row['disposition_event_id'],
        availability=issue_actions(context.connection, context.document_id, row, context.busy),
    )
    return validate('IssueView', value)


def lineage_item(context, row):
    parameters = (context.document_id, row['artifact_ref'])
    predecessor = context.connection.execute(
        'SELECT reviewed_artifact_ref,event_id FROM formation_artifact_reviews WHERE document_id=? '
        "AND replacement_artifact_ref=? AND result='REASSOCIATED'",
        parameters,
    ).fetchone()
    successor = context.connection.execute(
        'SELECT replacement_artifact_ref,event_id FROM formation_artifact_reviews WHERE document_id=? '
        "AND reviewed_artifact_ref=? AND result='REASSOCIATED'",
        parameters,
    ).fetchone()
    return validate(
        'LineageItem',
        {
            'artifact_ref': row['artifact_ref'],
            'predecessor_ref': None if predecessor is None else predecessor[0],
            'predecessor_review_event_id': None if predecessor is None else predecessor[1],
            'successor_ref': None if successor is None else successor[0],
            'successor_review_event_id': None if successor is None else successor[1],
            'is_active': successor is None,
            'freshness': row['freshness'],
            'review_reason': row['review_reason'],
        },
    )


def artifact_view(context, row):
    fields = (
        'artifact_ref',
        'step_ref',
        'origin_revision_id',
        'summary',
        'checked_against_revision_id',
        'freshness',
        'review_reason',
    )
    value = {name: row[name] for name in fields}
    value.update(
        source_event_ref=row['source_event_id'],
        origin_content_digest=row['origin_digest'],
        **{
            name: item
            for name, item in lineage_item(context, row).items()
            if name not in ('artifact_ref', 'freshness', 'review_reason')
        },
    )
    value['result_refs'] = [
        item[0]
        for item in context.connection.execute(
            'SELECT result_ref FROM formation_artifact_results WHERE document_id=? AND artifact_ref=? ORDER BY result_ref',
            (context.document_id, row['artifact_ref']),
        )
    ]
    counts = {'ORIGIN': 0, 'CURRENT': 0}
    for item in context.connection.execute(
        'SELECT role,count(*) FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? GROUP BY role',
        (context.document_id, row['artifact_ref']),
    ):
        counts[item[0]] = item[1]
    value.update(origin_block_count=counts['ORIGIN'], current_block_count=counts['CURRENT'])
    sources = context.connection.execute(
        'SELECT source_refs_json FROM revisions WHERE id=? AND document_id=?',
        (row['origin_revision_id'], context.document_id),
    ).fetchone()
    if sources is None:
        raise ValueError('Artifact lost its immutable origin Revision')
    source_refs = strict_json_loads(sources[0])
    event = context.connection.execute(
        'SELECT source_type,source_id,payload_json FROM document_change_audits WHERE document_id=? AND id=?',
        (context.document_id, row['source_event_id']),
    ).fetchone()
    if event is None:
        raise ValueError('Artifact lost its original source event')
    source_refs.extend(strict_json_object(event['payload_json']).get('source_refs', []))
    if event['source_type'] in ('USER_ACTION', 'AI_MESSAGE'):
        source_refs.append({'kind': 'MESSAGE', 'message_id': event['source_id']})
    from backend.app.shared.json_canonical import canonical_input

    distinct = {canonical_input(source): source for source in source_refs}
    value['sources'] = [context.source_status(distinct[key]) for key in sorted(distinct)]
    return validate('ArtifactView', value)
