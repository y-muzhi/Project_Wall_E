"""Freeze bounded real formation material on the existing accepted execution basis."""

from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_loads

from .read_context import ReadContext
from .read_projection import artifact_view, latest_assessment
from .recommendations import latest_recommendation
from .repository import FormationRepository


def _rows(connection, sql, args):
    return [dict(row) for row in connection.execute(sql, args)]


def capture_material(
    connection,
    root,
    selection,
    catalog,
    *,
    previous_branch=None,
    required_steps=(),
    required_entities=(),
):
    document_id = root['assistant_document_id']
    repository = FormationRepository(connection)
    head = repository.head(document_id)
    current = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
        (document_id, root['id']),
    ).fetchone()
    if current is None:
        raise Rejected('SOURCE_INVALID')
    result = {
        'basis': {
            'formation_version': None if head is None else head['version'],
            'goal_version': None if head is None else head['goal_version'],
            'document_revision_id': current['revision_id'],
            'content_version': current['content_version'],
        },
        'goal': None,
        'selected_step': None,
        'selected_branch': None,
        'related_issues': [],
        'artifacts': [],
        'assessment': None,
        'recommendation': None,
        'coverage': {'limit': 100, 'included': [], 'omitted': []},
    }
    if head is None:
        return result
    result['goal'] = {
        'version': head['goal_version'],
        'text': head['goal_text'],
        'source_refs': strict_json_loads(head['goal_sources_json']),
    }
    context = ReadContext(connection, root, catalog)
    included = result['coverage']['included']
    selected_step = selection['discussion_step_ref']
    if selected_step is not None:
        row = connection.execute(
            'SELECT * FROM formation_steps WHERE document_id=? AND step_ref=?',
            (document_id, selected_step),
        ).fetchone()
        if row is None:
            raise Rejected('SOURCE_INVALID')
        value = step_material(connection, document_id, row)
        result['selected_step'] = value
        included.append({'kind': 'STEP', 'ref': selected_step})
        assessment = latest_assessment(context, dict(row))
        if assessment is not None:
            result['assessment'] = {
                key: assessment[key]
                for key in (
                    'verdict',
                    'reason',
                    'goal_version',
                    'evaluated_step_version',
                    'evaluated_revision_id',
                    'coverage_block_ids',
                    'source_refs',
                    'assistant_message_id',
                    'validity',
                    'stale_reason',
                )
            }
        recommendation = latest_recommendation(context, selected_step)
        if recommendation is not None:
            result['recommendation'] = {
                key: recommendation[key]
                for key in (
                    'action',
                    'step_ref',
                    'reason',
                    'source_refs',
                    'assistant_message_id',
                    'validity',
                    'stale_reason',
                )
            }
    for ref in required_steps:
        if any(item['kind'] == 'STEP' and item['ref'] == ref for item in included):
            continue
        if len(included) >= 100:
            raise Rejected('CAPACITY_EXHAUSTED')
        row = connection.execute(
            'SELECT * FROM formation_steps WHERE document_id=? AND step_ref=?', (document_id, ref)
        ).fetchone()
        if row is None:
            raise Rejected('SOURCE_INVALID')
        included.append(
            {'kind': 'STEP', 'ref': ref, 'definition': step_material(connection, document_id, row)}
        )
    selected_branch = selection['discussion_branch_ref']
    if selected_branch is not None:
        row = connection.execute(
            'SELECT * FROM formation_branches WHERE document_id=? AND branch_ref=?',
            (document_id, selected_branch),
        ).fetchone()
        if row is None:
            raise Rejected('SOURCE_INVALID')
        if len(included) >= 100:
            raise Rejected('CAPACITY_EXHAUSTED')
        result['selected_branch'] = branch_material(connection, document_id, row, previous_branch)
        included.append({'kind': 'BRANCH', 'ref': selected_branch})

    def include(kind, row, *, hard):
        identity = {'BRANCH': 'branch_ref', 'ISSUE': 'issue_ref', 'ARTIFACT': 'artifact_ref'}[kind]
        ref = row[identity]
        if any(item['kind'] == kind and item['ref'] == ref for item in included):
            return
        if len(included) >= 100:
            if hard:
                raise Rejected('CAPACITY_EXHAUSTED')
            return
        if kind == 'ISSUE':
            value = issue_material(row)
            result['related_issues'].append(value)
        elif kind == 'ARTIFACT':
            value = artifact_material(context, row)
            result['artifacts'].append(value)
        else:
            value = branch_material(connection, document_id, row)
        included.append(
            {'kind': kind, 'ref': ref, **({'definition': value} if kind == 'BRANCH' else {})}
        )

    for item in required_entities:
        kind, ref = item['kind'], item['ref']
        if kind not in ('BRANCH', 'ISSUE', 'ARTIFACT'):
            continue
        table, identity = {
            'BRANCH': ('formation_branches', 'branch_ref'),
            'ISSUE': ('formation_issues', 'issue_ref'),
            'ARTIFACT': ('formation_artifacts', 'artifact_ref'),
        }[kind]
        row = connection.execute(
            'SELECT * FROM ' + table + ' WHERE document_id=? AND ' + identity + '=?',
            (document_id, ref),
        ).fetchone()
        if row is None:
            raise Rejected('SOURCE_INVALID')
        include(kind, row, hard=True)

    hard_steps = tuple(
        dict.fromkeys(([selected_step] if selected_step is not None else []) + list(required_steps))
    )
    for hard_step in hard_steps:
        issues = connection.execute(
            "SELECT * FROM formation_issues WHERE document_id=? AND step_ref=? AND disposition='OPEN' ORDER BY blocking DESC,CAST(substr(issue_ref,2) AS INTEGER) LIMIT 101",
            (document_id, hard_step),
        ).fetchall()
        artifacts = connection.execute(
            'SELECT a.* FROM formation_artifacts a WHERE a.document_id=? AND a.step_ref=? AND NOT EXISTS('
            'SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
            "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED') ORDER BY CAST(substr(a.artifact_ref,2) AS INTEGER) LIMIT 101",
            (document_id, hard_step),
        ).fetchall()
        for row in issues:
            if row['blocking']:
                include('ISSUE', row, hard=True)
        for row in artifacts:
            include('ARTIFACT', row, hard=True)
    if selected_step is not None:
        issues = connection.execute(
            "SELECT * FROM formation_issues WHERE document_id=? AND step_ref=? AND disposition='OPEN' AND blocking=0 ORDER BY CAST(substr(issue_ref,2) AS INTEGER) LIMIT 101",
            (document_id, selected_step),
        ).fetchall()
        for row in connection.execute(
            "SELECT * FROM formation_branches WHERE document_id=? AND return_step_ref=? AND status='OPEN' ORDER BY CAST(substr(branch_ref,2) AS INTEGER) LIMIT 100",
            (document_id, selected_step),
        ):
            include('BRANCH', row, hard=False)
        for row in issues:
            if not row['blocking']:
                include('ISSUE', row, hard=False)
        remaining = 100 - len(included)
        for row in connection.execute(
            "SELECT s.* FROM formation_steps s WHERE s.document_id=? AND s.status='PLANNED' AND s.step_ref<>? "
            'AND EXISTS(SELECT 1 FROM formation_step_edges e WHERE e.document_id=s.document_id '
            'AND ((e.from_step_ref=s.step_ref AND e.to_step_ref=?) OR (e.to_step_ref=s.step_ref AND e.from_step_ref=?))) '
            'ORDER BY s.position,CAST(substr(s.step_ref,2) AS INTEGER) LIMIT ?',
            (document_id, selected_step, selected_step, selected_step, remaining),
        ):
            if not any(
                item['kind'] == 'STEP' and item['ref'] == row['step_ref'] for item in included
            ):
                included.append(
                    {
                        'kind': 'STEP',
                        'ref': row['step_ref'],
                        'definition': step_material(connection, document_id, row),
                    }
                )
    for kind, table in (
        ('STEP', 'formation_steps'),
        ('BRANCH', 'formation_branches'),
        ('ISSUE', 'formation_issues'),
        ('ARTIFACT', 'formation_artifacts'),
    ):
        total = connection.execute(
            'SELECT count(*) FROM ' + table + ' WHERE document_id=?', (document_id,)
        ).fetchone()[0]
        omitted = total - sum(item['kind'] == kind for item in included)
        if omitted:
            result['coverage']['omitted'].append(
                {
                    'kind': kind,
                    'count': omitted,
                    'reason': 'ENTITY_LIMIT' if len(included) >= 100 else 'NOT_RELATED',
                }
            )
    return catalog.collaboration.validate('CanonicalFormation', result)


def material_sources(value):
    """Collect addressed SourceRefs only, without claiming database rows were sent."""
    found = {}

    def visit(item):
        if isinstance(item, dict):
            for name, child in item.items():
                if name in (
                    'source_refs',
                    'origin_source_refs',
                    'result_source_refs',
                    'resolution_source_refs',
                ):
                    from backend.app.shared.json_canonical import canonical_input

                    for source in child:
                        found.setdefault(canonical_input(source), source)
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return list(found.values())


def previous_branch_result(connection, document_id, branch_ref):
    row = connection.execute(
        "SELECT event_id,before_json FROM formation_event_changes WHERE document_id=? AND entity_kind='BRANCH' "
        "AND entity_ref=? AND json_extract(before_json,'$.result_summary') IS NOT NULL ORDER BY event_id DESC,ordinal DESC LIMIT 1",
        (document_id, branch_ref),
    ).fetchone()
    if row is None:
        return None
    previous = strict_json_loads(row['before_json'])
    sources = [
        strict_json_loads(member[0])['source_ref']
        for member in connection.execute(
            "SELECT before_json FROM formation_event_members WHERE event_id=? AND collection='BRANCH_RESULT_SOURCE' "
            'AND before_json IS NOT NULL ORDER BY ordinal LIMIT 101',
            (row['event_id'],),
        )
    ]
    if len(sources) > 100:
        raise Rejected('CAPACITY_EXHAUSTED')
    return {
        'summary': previous['result_summary'],
        'source_refs': sources,
        'event_id': previous['state_event_ref'],
    }


def freeze_message_effects(connection, basis):
    rows = [*basis['recent_messages'], basis['user_message']]
    rows.extend(
        item['value']['message']
        for item in basis['source_snapshots']
        if item['source_ref']['kind'] in ('MESSAGE', 'CARD_ANSWER')
    )
    result = {}
    for message in rows:
        effect = None
        if message['role'] == 'ASSISTANT' and message.get('guide_run_id') is not None:
            run = connection.execute(
                'SELECT status,final_result_json FROM guide_runs WHERE id=? AND requirement_id=?',
                (message['guide_run_id'], message['requirement_id']),
            ).fetchone()
            if run is not None:
                if run['status'] in ('FAILED', 'CANCELLED'):
                    effect = run['status']
                elif run['status'] == 'COMPLETED' and run['final_result_json'] is not None:
                    saved = strict_json_loads(run['final_result_json'])
                    effect = saved.get('effect_state')
                    if effect is None and 'validation_error' in saved:
                        effect = (
                            'STRUCTURED_REJECTED'
                            if saved['validation_error'] is not None
                            or saved.get('progress_error') is not None
                            else 'APPLIED'
                        )
        result[str(message['id'])] = effect
    return result


def step_material(connection, document_id, row):
    value = {name: row[name] for name in ('step_ref', 'definition_version', 'title', 'status')}
    value['expected_results'] = _rows(
        connection,
        "SELECT result_ref,description,kind FROM formation_results WHERE document_id=? AND step_ref=? ORDER BY CAST(substr(result_ref,instr(result_ref,'.o')+2) AS INTEGER)",
        (document_id, row['step_ref']),
    )
    for name, kind in (('dependencies', 'DEPENDENCY'), ('replaces_step_refs', 'REPLACES')):
        value[name] = [
            item[0]
            for item in connection.execute(
                'SELECT to_step_ref FROM formation_step_edges WHERE document_id=? AND from_step_ref=? AND kind=? ORDER BY CAST(substr(to_step_ref,2) AS INTEGER)',
                (document_id, row['step_ref'], kind),
            )
        ]
    value['topic_refs'] = [
        item[0]
        for item in connection.execute(
            'SELECT topic_ref FROM formation_step_topics WHERE document_id=? AND step_ref=? ORDER BY topic_ref',
            (document_id, row['step_ref']),
        )
    ]
    return value


def issue_material(row):
    return {
        **{
            name: row[name]
            for name in ('issue_ref', 'step_ref', 'branch_ref', 'description', 'disposition')
        },
        'blocking': bool(row['blocking']),
        'source_refs': strict_json_loads(row['source_refs_json']),
        'resolution_source_refs': strict_json_loads(row['resolution_sources_json']),
    }


def branch_material(connection, document_id, row, previous=None):
    value = {
        name: row[name]
        for name in (
            'branch_ref',
            'origin_step_ref',
            'return_step_ref',
            'question',
            'relevance',
            'status',
            'result_summary',
        )
    }
    value.update(
        state_event_ref=row['state_event_id'],
        result_source_refs=strict_json_loads(row['result_sources_json']),
        topic_refs=[
            item[0]
            for item in connection.execute(
                'SELECT topic_ref FROM formation_branch_topics WHERE document_id=? AND branch_ref=? ORDER BY topic_ref',
                (document_id, row['branch_ref']),
            )
        ],
        previous_result=previous_branch_result(connection, document_id, row['branch_ref']),
    )
    if previous is not None and previous['result_summary'] is not None:
        value['previous_result'] = {
            'summary': previous['result_summary'],
            'source_refs': strict_json_loads(previous['result_sources_json']),
            'event_id': previous['state_event_id'],
        }
    event = connection.execute(
        'SELECT source_type,source_id,payload_json FROM document_change_audits WHERE document_id=? AND id=?',
        (document_id, row['origin_event_id']),
    ).fetchone()
    if event is None:
        raise Rejected('SOURCE_INVALID')
    origin = strict_json_loads(event['payload_json']).get('source_refs', [])
    if event['source_type'] in ('USER_ACTION', 'AI_MESSAGE'):
        origin = [*origin, {'kind': 'MESSAGE', 'message_id': event['source_id']}]
    from backend.app.shared.json_canonical import canonical_input

    value['origin_source_refs'] = list(
        {canonical_input(source): source for source in origin}.values()
    )
    return value


def artifact_material(context, row):
    public = artifact_view(context, row)
    value = {
        name: public[name]
        for name in (
            'artifact_ref',
            'step_ref',
            'summary',
            'freshness',
            'review_reason',
            'origin_revision_id',
            'checked_against_revision_id',
            'result_refs',
            'current_block_count',
        )
    }
    value['current_block_ids'] = [
        item[0]
        for item in context.connection.execute(
            "SELECT block_id FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT' ORDER BY ordinal LIMIT 100",
            (context.document_id, row['artifact_ref']),
        )
    ]
    value['source_refs'] = [entry['source_ref'] for entry in public['sources']]
    return value
