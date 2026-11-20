"""Transaction-local exact content authorization minted after a real formal answer."""

from dataclasses import dataclass

from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input

from .card_source import card_source
from .proposal_binding import digest

_TOKEN = object()


@dataclass(frozen=True)
class CardWriteAuthority:
    token: object
    connection: object
    requirement_id: int
    document_id: int
    response_id: int
    key: str
    payload_digest: str
    snapshot_digest: str


def prepare_authorized_write(connection, root, response_id, key, catalog, at):
    from backend.app.documents.markdown import parse_markdown
    from backend.app.documents.patch_application import apply_confirmed_facts
    from backend.app.documents.snapshot import Provenance, assign_identities
    from backend.app.documents.sources import DocumentSources
    from backend.app.infrastructure.identifiers import block_id

    from .write_preview import prepare_write

    descriptor, payload = card_source(
        connection, root['id'], root['assistant_document_id'], response_id, catalog
    )
    actual_key = connection.execute(
        'SELECT idempotency_key FROM conversation_messages WHERE id=?', (response_id,)
    ).fetchone()[0]
    if actual_key != key:
        raise Rejected('SOURCE_INVALID')
    current, prior, scope, markdown = prepare_write(connection, root, payload, catalog)
    sources = DocumentSources(connection, root['id'], catalog, document_id=current['id'])
    provenance = Provenance('USER', 'CARD_RESPONSE', response_id)
    if payload['write_mode'] == 'FILL_EMPTY':
        identities = []
        next_id = prior.next_block_id
        for _ in parse_markdown(markdown).blocks:
            identity, next_id = block_id(next_id)
            identities.append(identity)
        candidate = assign_identities(markdown, identities, next_id, prior, provenance, at, sources)
    else:
        candidate = apply_confirmed_facts(
            prior, payload['patches'], scope, None, at, sources, provenance=provenance
        )
    if candidate.parsed.markdown != markdown:
        raise ValueError('Exact adoption differs from its program-validated preview')
    references = [
        *payload['source_refs'],
        {'kind': 'MESSAGE', 'message_id': descriptor['conversation_message_id']},
        {'kind': 'CARD_ANSWER', 'message_id': response_id, 'card_key': descriptor['card_key']},
    ]
    references = list({canonical_input(source): source for source in references}.values())
    covered = set(candidate.by_id) - set(prior.by_id)
    covered.update(patch['target_ref']['block_id'] for patch in payload['patches'])
    covered.update(
        identity
        for identity in candidate.by_id
        if identity in prior.by_id
        and candidate.by_id[identity][0].markdown != prior.by_id[identity][0].markdown
    )
    covered &= set(candidate.by_id)
    authority = CardWriteAuthority(
        _TOKEN,
        connection,
        root['id'],
        root['assistant_document_id'],
        response_id,
        key,
        digest(payload),
        digest({'markdown': candidate.parsed.markdown, 'state': candidate.state}),
    )
    return (
        authority,
        current,
        candidate,
        references,
        sorted(covered, key=list(candidate.by_id).index),
    )


def require_authority(
    value, connection, current, response_id, snapshot, key, source_refs, summary, catalog
):
    if (
        type(value) is not CardWriteAuthority
        or value.token is not _TOKEN
        or value.connection is not connection
    ):
        raise Rejected('SOURCE_INVALID')
    if (value.requirement_id, value.document_id, value.response_id, value.key) != (
        current['requirement_id'],
        current['id'],
        response_id,
        key,
    ) or value.snapshot_digest != digest(
        {'markdown': snapshot.parsed.markdown, 'state': snapshot.state}
    ):
        raise Rejected('SOURCE_INVALID')
    descriptor, payload = card_source(
        connection, current['requirement_id'], current['id'], response_id, catalog
    )
    if digest(payload) != value.payload_digest or summary != payload['change_summary']:
        raise Rejected('SOURCE_INVALID')
    wanted = [
        *payload['source_refs'],
        {'kind': 'MESSAGE', 'message_id': descriptor['conversation_message_id']},
        {'kind': 'CARD_ANSWER', 'message_id': response_id, 'card_key': descriptor['card_key']},
    ]
    wanted = list({canonical_input(source): source for source in wanted}.values())
    if canonical_input({'sources': source_refs}) != canonical_input({'sources': wanted}):
        raise Rejected('SOURCE_INVALID')
    root = connection.execute(
        'SELECT document_work_state,active_operation_type,active_operation_id FROM requirements WHERE id=?',
        (current['requirement_id'],),
    ).fetchone()
    if tuple(root) != ('IDLE', None, None):
        raise Rejected('WORK_STATE_CONFLICT')
    return descriptor
