"""Maintain all affected active artifacts in the real content transaction, including closed steps."""

from contextlib import contextmanager

from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.json_canonical import canonical_input

from .artifact_links import block_digest
from .events import record_change
from .path_facts import artifact_snapshot
from .transaction import FormationTransaction

TEMP = '_formation_content_changed_blocks'


@contextmanager
def changed_block_index(connection, prior, candidate):
    changed = (
        identity
        for identity, (block, _) in prior.by_id.items()
        if identity not in candidate.by_id
        or block.markdown != candidate.by_id[identity][0].markdown
    )
    connection.execute(
        'CREATE TEMP TABLE ' + TEMP + '(block_id INTEGER PRIMARY KEY NOT NULL) STRICT'
    )
    try:
        batch = []
        for identity in changed:
            batch.append((identity,))
            if len(batch) == 100:
                connection.executemany('INSERT INTO ' + TEMP + ' VALUES(?)', batch)
                batch.clear()
        if batch:
            connection.executemany('INSERT INTO ' + TEMP + ' VALUES(?)', batch)
        yield
    finally:
        # The caller also closes the connection on failure; no temporary state
        # or partially maintained artifact is ever committed separately.
        connection.execute('DROP TABLE IF EXISTS temp.' + TEMP)


def range_delta(before, after):
    def indexed(rows):
        return {
            f'CURRENT:{row["revision_id"]}:{row["block_id"]}': {
                'kind': 'RANGE',
                **{name: row[name] for name in ('revision_id', 'block_id', 'block_digest')},
            }
            for row in rows
        }

    old, new = indexed(before), indexed(after)
    ordinal = 0
    for key in sorted(old.keys() | new.keys(), key=lambda value: value.encode('utf-8')):
        if old.get(key) != new.get(key):
            ordinal += 1
            yield {
                'ordinal': ordinal,
                'collection': 'CURRENT_RANGE',
                'member_key': key,
                'before': old.get(key),
                'after': new.get(key),
            }


def maintain_content(
    connection, current, prior, candidate, revision_id, content_event_id, *, transaction, key, at
):
    require_write_transaction(connection)
    if transaction is None:
        return
    if (
        type(transaction) is not FormationTransaction
        or transaction.connection is not connection
        or (
            transaction.document_id != current['id']
            or transaction.requirement_id != current['requirement_id']
        )
    ):
        raise ValueError('Artifact maintenance requires this exact transaction and document')
    source = connection.execute(
        'SELECT 1 FROM document_change_audits WHERE id=? AND requirement_id=? AND document_id=? '
        "AND revision_id=? AND event_type='CONTENT_COMMITTED'",
        (content_event_id, current['requirement_id'], current['id'], revision_id),
    ).fetchone()
    if source is None:
        raise ValueError('Artifact maintenance must follow the actual immutable content event')
    with changed_block_index(connection, prior, candidate):
        affected = (
            'SELECT DISTINCT a.artifact_ref FROM formation_artifacts a '
            'JOIN formation_artifact_ranges ranges ON ranges.document_id=a.document_id AND ranges.artifact_ref=a.artifact_ref '
            'JOIN temp.'
            + TEMP
            + " changed ON changed.block_id=ranges.block_id WHERE a.document_id=? AND ranges.role='CURRENT' "
            'AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews review WHERE review.document_id=a.document_id '
            "AND review.reviewed_artifact_ref=a.artifact_ref AND review.result='REASSOCIATED')"
        )
        total = connection.execute(
            'SELECT count(*) FROM (' + affected + ')', (current['id'],)
        ).fetchone()[0]
        if total == 0:
            return
        after_versions = transaction.touch(at)
        event_id = entity_id(connection, EntityKind.DOCUMENT_AUDIT)
        head = connection.execute(
            'SELECT * FROM formation_heads WHERE document_id=?', (current['id'],)
        ).fetchone()
        view = {
            'event_id': event_id,
            'action': 'ARTIFACT_CHECKED',
            'actor': 'PROGRAM',
            'reason': '正文已保存，更新相关成果的内容核对状态',
            'created_at': at,
            'schema': 'formation_event_v1',
            'document_id': current['id'],
            'batch_ref': event_id,
            'ordinal': 1,
            'batch_size': 1,
            'version_before': transaction.before,
            'version_after': after_versions,
            'change_count': total,
            'closure': None,
        }
        focus = {name: head[name] for name in ('current_step_ref', 'active_branch_ref')}
        payload = {
            'formation_event_type': 'ARTIFACT_CHECKED',
            'event': view,
            'content_event_id': content_event_id,
            'idempotency_key': key,
            'focus_before': transaction.focus_before,
            'focus_after': focus,
        }
        connection.execute(
            'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,'
            'before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) '
            "VALUES(?,?,?,'PROGRAM',?,'ARTIFACT_CHECKED',NULL,NULL,?,'DISCUSSION_UPDATED',NULL,NULL,?)",
            (
                event_id,
                current['requirement_id'],
                current['id'],
                content_event_id,
                at,
                canonical_input(payload),
            ),
        )
        order = {identity: index for index, identity in enumerate(candidate.by_id)}
        actual = 0
        identities = connection.execute(
            'SELECT artifact_ref FROM ('
            + affected
            + ') ORDER BY CAST(substr(artifact_ref,2) AS INTEGER)',
            (current['id'],),
        )
        try:
            for artifact_record in identities:
                artifact_ref = artifact_record[0]
                actual += 1
                artifact = dict(
                    connection.execute(
                        'SELECT * FROM formation_artifacts WHERE document_id=? AND artifact_ref=?',
                        (current['id'], artifact_ref),
                    ).fetchone()
                )
                before_ranges = [
                    dict(row)
                    for row in connection.execute(
                        'SELECT ordinal,revision_id,block_id,block_digest FROM formation_artifact_ranges '
                        "WHERE document_id=? AND artifact_ref=? AND role='CURRENT' ORDER BY ordinal",
                        (current['id'], artifact_ref),
                    )
                ]
                survivors = sorted(
                    (
                        row['block_id']
                        for row in before_ranges
                        if row['block_id'] in candidate.by_id
                    ),
                    key=order.__getitem__,
                )
                after_ranges = [
                    {
                        'ordinal': ordinal,
                        'revision_id': revision_id,
                        'block_id': identity,
                        'block_digest': block_digest(candidate.by_id[identity][0].markdown),
                    }
                    for ordinal, identity in enumerate(survivors, 1)
                ]
                updated = {
                    **artifact,
                    'checked_against_revision_id': revision_id,
                    'freshness': 'NEEDS_REVIEW' if survivors else 'REMOVED',
                    'review_reason': 'CHANGED' if survivors else None,
                }
                connection.execute(
                    'UPDATE formation_artifacts SET checked_against_revision_id=?,freshness=?,review_reason=? '
                    'WHERE document_id=? AND artifact_ref=?',
                    (
                        revision_id,
                        updated['freshness'],
                        updated['review_reason'],
                        current['id'],
                        artifact_ref,
                    ),
                )
                connection.execute(
                    "DELETE FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT'",
                    (current['id'], artifact_ref),
                )
                connection.executemany(
                    'INSERT INTO formation_artifact_ranges(document_id,artifact_ref,role,ordinal,revision_id,block_id,block_digest) '
                    "VALUES(?,?,'CURRENT',?,?,?,?)",
                    [
                        (
                            current['id'],
                            artifact_ref,
                            row['ordinal'],
                            row['revision_id'],
                            row['block_id'],
                            row['block_digest'],
                        )
                        for row in after_ranges
                    ],
                )
                record_change(
                    connection,
                    current['id'],
                    event_id,
                    actual,
                    'ARTIFACT',
                    artifact_ref,
                    artifact_snapshot(artifact),
                    artifact_snapshot(updated),
                    lambda old=before_ranges, new=after_ranges: range_delta(old, new),
                )
                references = {('ARTIFACT', artifact_ref), ('STEP', artifact['step_ref'])}
                references.update(
                    ('RESULT', row[0])
                    for row in connection.execute(
                        'SELECT result_ref FROM formation_artifact_results WHERE document_id=? AND artifact_ref=?',
                        (current['id'], artifact_ref),
                    )
                )
                connection.executemany(
                    'INSERT OR IGNORE INTO formation_event_refs(document_id,event_id,kind,ref) VALUES(?,?,?,?)',
                    [(current['id'], event_id, kind, ref) for kind, ref in sorted(references)],
                )
        finally:
            identities.close()
        if actual != total:
            raise ValueError(
                'Artifact maintenance lost affected rows while updating current ranges'
            )
