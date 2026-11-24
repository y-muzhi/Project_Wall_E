"""Proof of an exact discussion conclusion in a specific committed document block."""

from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.shared.validation import strict_json_loads
from .artifact_links import block_digest


def record_writes(connection, root, run, context, catalog, proposed, effect, application, new_refs):
    """An explicit existing-document write, a carried decision and exact paragraph must agree."""
    target = context.canonical.get('target') or {}
    if (
        not isinstance(proposed, dict)
        or run['operation'] != 'REVISE'
        or target.get('document_id') != root['assistant_document_id']
        or not isinstance(proposed.get('markdown_content'), str)
    ):
        return []
    refs = set(new_refs)
    refs.update(item['ref'] for item in context.input['goal_and_decisions'])
    decisions = [
        row
        for row in root['discussion_state_json']['evidence']
        if row['evidence_ref'] in refs
        and row['state'] == 'ACTIVE'
        and row['nature'] != 'PROPOSAL'
        and row['origin'] in ('USER_STATEMENT', 'USER_DECISION')
    ]
    if not decisions:
        return []
    from backend.app.documents.markdown import DocumentInvalid, parse_markdown

    try:
        attempted = {
            b.plain_text.strip() for b in parse_markdown(proposed['markdown_content']).blocks
        }
    except DocumentInvalid:
        return []
    candidates = [row for row in decisions if row['assertion'].strip() in attempted]
    if application == 'NOT_APPLIED':
        return [{'evidence_ref': row['evidence_ref'], 'state': 'FAILED'} for row in candidates]
    if (
        application != 'APPLIED'
        or not effect
        or effect['document_id'] != root['assistant_document_id']
    ):
        return []
    snapshot = connection.execute(
        "SELECT r.markdown_snapshot,r.block_state_snapshot_json FROM revisions r JOIN document_change_audits a ON a.revision_id=r.id AND a.document_id=r.document_id AND a.requirement_id=r.requirement_id WHERE r.id=? AND r.document_id=? AND a.guide_run_id=? AND a.event_type='CONTENT_COMMITTED'",
        (effect['revision_id'], effect['document_id'], run['id']),
    ).fetchone()
    if snapshot is None:
        return []
    blocks = validate_snapshot(
        snapshot[0],
        strict_json_loads(snapshot[1]),
        DocumentSources(connection, root['id'], catalog, document_id=effect['document_id']),
    ).by_id
    index = {}
    for identity, (block, metadata) in blocks.items():
        if (metadata['last_modified_source_type'], metadata['last_modified_source_id']) == (
            'GUIDE_RUN',
            run['id'],
        ):
            index.setdefault(block.plain_text.strip(), []).append(
                (identity, block_digest(block.markdown))
            )
    records = []
    for row in candidates:
        matches = index.get(row['assertion'].strip(), [])
        if len(matches) == 1:
            identity, digest = matches[0]
            records.append(
                {
                    'evidence_ref': row['evidence_ref'],
                    'state': 'WRITTEN',
                    'revision_id': effect['revision_id'],
                    'version': effect['after_content_version'],
                    'block_id': identity,
                    'block_digest': digest,
                }
            )
    return records


def writing_for_page(connection, root, rows, revision, catalog):
    if not rows:
        return
    document = root['assistant_document_id']
    wanted = {row['evidence_ref']: row for row in rows}
    bound = ','.join('?' for _ in rows)
    results = connection.execute(
        "SELECT r.id,r.final_result_json ->> '$.assistant_message_id',e.value FROM guide_runs r,json_each(r.final_result_json,'$.decision_writes') e WHERE r.document_id=? AND r.requirement_id=? AND r.status='COMPLETED' AND json_extract(e.value,'$.evidence_ref') IN ("
        + bound
        + ') ORDER BY r.id DESC',
        (document, root['id'], *wanted),
    )
    blocks = None
    latest_failures = {}
    for _, message, raw in results:
        fact = strict_json_loads(raw)
        row = wanted.get(fact['evidence_ref'])
        if row is None or row.get('writing') is not None:
            continue
        if fact['state'] == 'FAILED':
            latest_failures.setdefault(
                fact['evidence_ref'], {'kind': 'MESSAGE', 'message_id': message}
            )
            continue
        if blocks is None:
            from backend.app.documents.markdown import DocumentInvalid

            current = connection.execute(
                'SELECT markdown_snapshot,block_state_snapshot_json FROM revisions WHERE document_id=? AND id=?',
                (document, revision),
            ).fetchone()
            try:
                blocks = validate_snapshot(
                    current[0],
                    strict_json_loads(current[1]),
                    DocumentSources(connection, root['id'], catalog, document_id=document),
                ).by_id
            except DocumentInvalid:
                blocks = {}
        identity = fact['block_id']
        still_current = (
            identity in blocks
            and block_digest(blocks[identity][0].markdown) == fact['block_digest']
        )
        row['writing'] = {
            'state': 'CURRENT' if still_current else 'HISTORICAL',
            'version': fact['version'],
            'source_refs': [
                {
                    'kind': 'REVISION',
                    'document_id': document,
                    'revision_id': fact['revision_id'],
                    'block_ids': [identity],
                }
            ],
        }
    for ref, source in latest_failures.items():
        decision = wanted[ref]
        if decision.get('writing') is None:
            decision['writing'] = {'state': 'FAILED', 'version': None, 'source_refs': [source]}
        else:
            decision['writing']['source_refs'].append(source)
