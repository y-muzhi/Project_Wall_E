"""Verify actual current blocks and persist original artifact ranges without writing content."""

import hashlib
from dataclasses import dataclass

from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.identifiers import increment, require_write_transaction
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object


def block_digest(markdown):
    return hashlib.sha256(markdown.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class VerifiedLink:
    connection: object
    requirement_id: int
    document_id: int
    step_ref: str
    result_refs: tuple[str, ...]
    revision_id: int
    ranges: tuple[tuple[int, str], ...]
    content_digest: str


def verify_links(connection, root, links, resources):
    """Read-only calculation; COMMIT must run this again on its actual transaction."""
    document_id = root['assistant_document_id']
    current = connection.execute(
        'SELECT d.*,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? '
        "AND d.requirement_id=? AND d.document_type='CURRENT' AND d.archived_at IS NULL",
        (document_id, root['id']),
    ).fetchone()
    if current is None:
        raise Rejected('NOT_FOUND')
    try:
        snapshot = validate_snapshot(
            current['markdown_content'],
            strict_json_object(current['block_state_json']),
            DocumentSources(connection, root['id'], resources, document_id=document_id),
        )
    except DocumentInvalid:
        raise Rejected('SOURCE_INVALID') from None
    blocks = snapshot.by_id
    order = {identity: index for index, identity in enumerate(blocks)}
    verified = []
    for link in links:
        if link['revision_id'] != current['revision_id'] or any(
            identity not in blocks for identity in link['block_ids']
        ):
            raise Rejected(
                'STATE_CONFLICT',
                details={
                    'reason': 'SOURCE_UNAVAILABLE',
                    'step_ref': link['step_ref'] if link['step_ref'].startswith('s') else None,
                    'proposal': None,
                },
            )
        ranges = tuple(
            (identity, block_digest(blocks[identity][0].markdown))
            for identity in sorted(link['block_ids'], key=order.__getitem__)
        )
        digest = hashlib.sha256(
            canonical_input(
                {
                    'ranges': [
                        {'block_id': identity, 'block_digest': digest}
                        for identity, digest in ranges
                    ]
                }
            ).encode('utf-8')
        ).hexdigest()
        verified.append(
            VerifiedLink(
                connection,
                root['id'],
                document_id,
                link['step_ref'],
                tuple(link['result_refs']),
                current['revision_id'],
                ranges,
                digest,
            )
        )
    return tuple(verified)


def create_links(connection, document_id, verified, event_ids, summaries):
    """The caller owns event/message/versions/receipt and their single shared COMMIT."""
    require_write_transaction(connection)
    if len(verified) != len(event_ids):
        raise ValueError('Each real association requires its actual audit event')
    head = connection.execute(
        'SELECT * FROM formation_heads WHERE document_id=?', (document_id,)
    ).fetchone()
    if head is None:
        raise ValueError('Verified links require a real existing formation')
    for link, event_id in zip(verified, event_ids, strict=True):
        if not 1 <= len(link.result_refs) <= 20:
            raise ValueError('An artifact requires 1 to 20 actual results')
        if link.connection is not connection or link.document_id != document_id:
            raise ValueError('Artifact verification cannot be transferred between transactions')
        current = connection.execute(
            'SELECT r.id FROM requirement_documents d JOIN revisions r ON r.document_id=d.id '
            'AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
            (document_id, link.requirement_id),
        ).fetchone()
        event = connection.execute(
            'SELECT 1 FROM document_change_audits WHERE id=? AND document_id=? AND requirement_id=? '
            "AND json_extract(payload_json,'$.formation_event_type')='CONTENT_ASSOCIATED'",
            (event_id, document_id, link.requirement_id),
        ).fetchone()
        if current is None or current[0] != link.revision_id or event is None:
            raise ValueError(
                'Artifact must use the actual current revision and same-document audit'
            )
    next_number = head['next_artifact_no']
    created = []
    for link, event_id in zip(verified, event_ids, strict=True):
        ref = f'a{next_number}'
        next_number = increment(next_number)
        summary = summaries[link.step_ref]
        from .types import text

        summary = text(summary, 'artifact.summary', 240)
        row = {
            'document_id': document_id,
            'artifact_ref': ref,
            'step_ref': link.step_ref,
            'source_event_id': event_id,
            'origin_revision_id': link.revision_id,
            'origin_digest': link.content_digest,
            'summary': summary,
            'checked_against_revision_id': link.revision_id,
            'freshness': 'CURRENT',
            'review_reason': None,
        }
        connection.execute(
            'INSERT INTO formation_artifacts('
            + ','.join(row)
            + ') VALUES('
            + ','.join('?' for _ in row)
            + ')',
            tuple(row.values()),
        )
        connection.executemany(
            'INSERT INTO formation_artifact_results(document_id,artifact_ref,result_ref) VALUES(?,?,?)',
            [(document_id, ref, result) for result in link.result_refs],
        )
        connection.executemany(
            'INSERT INTO formation_artifact_ranges(document_id,artifact_ref,role,ordinal,revision_id,'
            'block_id,block_digest) VALUES(?,?,?,?,?,?,?)',
            [
                (document_id, ref, role, ordinal, link.revision_id, identity, digest)
                for role in ('ORIGIN', 'CURRENT')
                for ordinal, (identity, digest) in enumerate(link.ranges, 1)
            ],
        )
        created.append(row)
    changed = connection.execute(
        'UPDATE formation_heads SET next_artifact_no=? WHERE document_id=? AND next_artifact_no=?',
        (next_number, document_id, head['next_artifact_no']),
    )
    if changed.rowcount != 1:
        raise ValueError('Artifact allocator changed inside the shared transaction')
    return tuple(created)


def current_artifact_matches(connection, document_id, artifact, current_blocks):
    """One shared proof for closure/preview: same live identities, actual block bytes and at least one range."""
    if artifact['freshness'] != 'CURRENT' or current_blocks is None:
        return False
    found = False
    for item in connection.execute(
        "SELECT block_id,block_digest FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT' ORDER BY ordinal",
        (document_id, artifact['artifact_ref']),
    ):
        found = True
        actual = current_blocks.get(item['block_id'])
        if actual is None or block_digest(actual[0].markdown) != item['block_digest']:
            return False
    return found
