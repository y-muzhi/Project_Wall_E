"""Document-scoped progress from the same read transaction as the discussion."""

from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import (
    InvalidInput,
    object_fields,
    strict_integer,
    strict_json_loads,
)
from .cursors import decode, encode


def page_start(cursor, document, group, filters, version):
    if cursor is None:
        return 0
    try:
        anchor = decode(cursor, document, group, filters)
        object_fields(anchor, 'progress_cursor', ('offset', 'version'), ('offset', 'version'))
        offset = strict_integer(anchor['offset'], 'progress_cursor.offset')
    except InvalidInput as error:
        raise Rejected('INVALID_INPUT', details=error.details) from error
    if anchor['version'] != version:
        raise Rejected(
            'STATE_CONFLICT', details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None}
        )
    return offset


def progress_brief(
    connection,
    root,
    summary,
    limit=3,
    *,
    group=None,
    cursor=None,
    catalog=None,
    display=True,
    viewed_step=None,
    whole_document=False,
):
    document_id = root['assistant_document_id']
    discussion = root['discussion_state_json']
    step = (
        None
        if whole_document
        else viewed_step
        if viewed_step is not None
        else summary['current_step_ref']
    )
    revision = connection.execute(
        'SELECT r.id FROM revisions r JOIN requirement_documents d ON r.document_id=d.id '
        'AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
        (document_id, root['id']),
    ).fetchone()[0]
    version = [root['discussion_version'], summary['formation_version'], revision]
    filters = {
        'requirement_id': root['id'],
        'order': 'latest_evidence_or_blocking_issue',
        'viewed_step': viewed_step,
        'whole_document': whole_document,
    }
    offset = page_start(cursor, document_id, group, filters, version)
    decision_start = offset if group == 'decisions' else 0
    issue_start = offset if group == 'issues' else 0
    decision_limit = 3 if group == 'issues' else limit
    issue_limit = 3 if group == 'decisions' else limit

    def next_cursor(kind, start, size, total):
        return (
            encode(document_id, kind, filters, {'offset': start + size, 'version': version})
            if start + size < total
            else None
        )

    focus = None
    topics = set()
    if step is not None:
        record = connection.execute(
            'SELECT title FROM formation_steps WHERE document_id=? AND step_ref=?',
            (document_id, step),
        ).fetchone()
        if record is None:
            raise Rejected('NOT_FOUND')
        title = record[0]
        topics = {
            row[0]
            for row in connection.execute(
                'SELECT topic_ref FROM formation_step_topics WHERE document_id=? AND step_ref=?',
                (document_id, step),
            )
        }
        focus = {'step_ref': step, 'title': title}
        if display:
            focus['purpose'] = [
                r[0]
                for r in connection.execute(
                    "SELECT description FROM formation_results WHERE document_id=? AND step_ref=? ORDER BY CAST(substr(result_ref,instr(result_ref,'.o')+2) AS INTEGER) LIMIT 3",
                    (document_id, step),
                )
            ]

    topic_evidence = {
        ref
        for topic in discussion['topics']
        if topic['topic_ref'] in topics
        for ref in topic['evidence_refs']
    }
    if step is not None:
        from .decision_links import linked_evidence

        topic_evidence.update(linked_evidence(connection, root['id'], document_id, step))
    # An explicit user replacement inherits a prior topic association of equal applicability.
    for item in discussion['evidence']:
        if item.get('supersedes') and topic_evidence.intersection(item['supersedes']):
            topic_evidence.add(item['evidence_ref'])
    decisions = []
    for item in reversed(discussion['evidence']):
        if item['state'] != 'ACTIVE' or item['origin'] not in ('USER_STATEMENT', 'USER_DECISION'):
            continue
        if item['nature'] == 'PROPOSAL' or not item['source_refs']:
            continue
        linked = set(item['topic_refs'])
        if item['applies_to'] != 'GLOBAL':
            linked.update(item['applies_to'])
        if step is None:
            if item['applies_to'] != 'GLOBAL':
                continue
        elif item['evidence_ref'] not in topic_evidence and not topics.intersection(linked):
            continue
        decisions.append(
            {
                'evidence_ref': item['evidence_ref'],
                'text': item['assertion'],
                'source_refs': item['source_refs'],
            }
        )

    where = " FROM formation_issues i JOIN formation_steps s USING(document_id,step_ref) WHERE i.document_id=? AND i.disposition='OPEN'"
    args = [document_id]
    if step is not None:
        where += ' AND i.step_ref=?'
        args.append(step)
    else:
        where += " AND s.status<>'CANCELLED'"
    ordered = ' ORDER BY i.blocking DESC, CAST(substr(i.issue_ref,2) AS INTEGER)'
    columns = 'SELECT i.issue_ref,i.description,i.source_refs_json,i.step_ref'
    total = connection.execute('SELECT count(*)' + where, args).fetchone()[0]
    issues = [
        {
            'issue_ref': row[0],
            'question': row[1],
            'source_refs': strict_json_loads(row[2]),
            **({'step_ref': row[3]} if display else {}),
        }
        for row in connection.execute(
            columns + where + ordered + ' LIMIT ? OFFSET ?', (*args, issue_limit, issue_start)
        )
    ]
    decision_page = decisions[decision_start : decision_start + decision_limit]
    next_item = None
    if display:
        if catalog is None:
            from backend.app.infrastructure.resources import ResourceCatalog

            catalog = ResourceCatalog()
        for row in decision_page:
            row.update(step_ref=step, writing=None)
        from .decision_writing import writing_for_page

        writing_for_page(connection, root, decision_page, revision, catalog)
        if total:
            first = connection.execute(columns + where + ordered + ' LIMIT 1', args).fetchone()
            next_item = {
                'kind': 'ISSUE',
                'ref': first[0],
                'reason': first[1],
                'source_refs': strict_json_loads(first[2]),
            }
        elif step:
            from .read_context import ReadContext
            from .recommendations import latest_recommendation

            rec = latest_recommendation(ReadContext(connection, root, catalog), step)
            if rec and rec['validity'] == 'CURRENT':
                next_item = {
                    'kind': 'RECOMMENDATION',
                    'ref': rec['step_ref'] or step,
                    'reason': rec['reason'],
                    'source_refs': rec['source_refs'],
                }
    return {
        'next': next_item,
        'document_id': document_id,
        'discussion_version': root['discussion_version'],
        'formation_version': summary['formation_version'],
        'revision_id': revision,
        'goal': summary['goal']['text'] if summary['goal'] else None,
        'focus': focus,
        'decisions': decision_page,
        'decision_next_cursor': next_cursor(
            'decisions', decision_start, decision_limit, len(decisions)
        ),
        'issue_next_cursor': next_cursor('issues', issue_start, issue_limit, total),
        'decision_total': len(decisions),
        'issues': issues,
        'issue_total': total,
    }
