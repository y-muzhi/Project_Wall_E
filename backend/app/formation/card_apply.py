"""Actual new-purpose C06 answers consume immutable payloads without another model call."""

from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.messages.cards import formal_answer_text, validate_responses
from backend.app.shared.command_execution import Rejected

from .http_projection import program_receipt
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact
from .proposal_binding import check_binding
from .proposal_contracts import proposal_group
from .proposal_sources import read_reference
from .repository import FormationRepository
from .transaction import FormationTransaction


def apply_card(connection, root, original, raw_cards, request, catalog, at):
    assert_idle(
        connection,
        root,
        remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
    )
    cards = proposal_group(raw_cards, catalog.collaboration, stored=True)
    answers = validate_responses(request.answers, cards, catalog.collaboration)
    if answers['execution_selection'] is not None or answers['responses'] != [
        {
            'card_key': cards['cards'][0]['card_key'],
            'selected_option_keys': ['apply'],
            'custom_answer': None,
            'skipped': False,
        }
    ]:
        raise Rejected('SOURCE_INVALID')
    reference = {'message_id': original['id'], 'card_key': cards['cards'][0]['card_key']}
    proposal = read_reference(connection, root, reference, purpose=cards['purpose'])
    if proposal.disposition != 'PENDING' or proposal.needs_revision:
        raise Rejected(
            'STATE_CONFLICT',
            details={'reason': 'PROPOSAL_BASIS_CHANGED', 'step_ref': None, 'proposal': reference},
        )
    check_binding(connection, root, proposal, cards['purpose'], catalog)
    if at < max(root['updated_at'], original['created_at']):
        raise ValueError('Formal adoption cannot precede its original source')
    head = FormationRepository(connection).head(root['assistant_document_id'], required=True)
    transaction = FormationTransaction(connection, root, head)
    response_id = entity_id(connection, EntityKind.MESSAGE)
    MessageRepository(connection).create_card_response(
        response_id,
        root['id'],
        None,
        original,
        formal_answer_text(cards, answers),
        answers,
        request.idempotency_key,
        at,
        document_id=original['document_id'],
        topic_refs=(),
    )
    first_event = connection.execute(
        'SELECT coalesce(max(id),0) FROM document_change_audits'
    ).fetchone()[0]
    if cards['purpose'] == 'STAGED_WRITE':
        effect = _write(
            connection,
            root,
            proposal,
            response_id,
            request.idempotency_key,
            catalog,
            transaction,
            at,
        )
        mapping = []
    else:
        from .card_route import apply_route

        effect, mapping = apply_route(
            connection,
            root,
            proposal,
            response_id,
            request.idempotency_key,
            catalog,
            transaction,
            at,
        )
    current_root = transaction.root()
    current_head = FormationRepository(connection).head(
        root['assistant_document_id'], required=True
    )
    document = transaction.document()
    event_ids = [
        row[0]
        for row in connection.execute(
            'SELECT id FROM document_change_audits WHERE document_id=? AND id>? ORDER BY id',
            (root['assistant_document_id'], first_event),
        )
    ]
    data = program_receipt(
        {
            'schema': 'formation_program_receipt_v21_1',
            'processing': 'PROGRAM',
            'requirement_id': root['id'],
            'document_id': root['assistant_document_id'],
            'discussion_version': current_root['discussion_version'],
            'formation_version': current_head['version'],
            'content_version': document['content_version'],
            'operation': cards['purpose'],
            'result': 'APPLIED',
            'user_message_id': response_id,
            'effects': {
                'content_changed': effect is not None and effect['result'] != 'NO_CHANGE',
                'revision_id': None
                if effect is None or effect['result'] == 'NO_CHANGE'
                else effect['revision_id'],
                'formation_changed': True,
                'proposal_disposition': 'APPLIED',
            },
            'event_ids': event_ids,
            'reference_map': mapping,
        }
    )
    return Success({'code': 'PROGRAM_PROCESSED', 'data': data, 'details': None}, 200)


def proposal_fact(proposal):
    key = ('PROPOSAL_APPLIED', proposal.entity_ref)
    before = proposal.snapshot()
    return RouteFact(
        'PROPOSAL',
        proposal.entity_ref,
        before,
        {**before, 'disposition': 'APPLIED', 'needs_revision': False},
        key,
    )


def consume(connection, proposal, event_id):
    updated = connection.execute(
        "UPDATE formation_proposal_index SET disposition='APPLIED',disposition_event_id=? WHERE document_id=? AND message_id=? AND card_key=? AND disposition='PENDING'",
        (
            event_id,
            proposal.document_id,
            proposal.reference['message_id'],
            proposal.reference['card_key'],
        ),
    )
    if updated.rowcount != 1:
        raise Rejected(
            'STATE_CONFLICT',
            details={
                'reason': 'PROPOSAL_BASIS_CHANGED',
                'step_ref': None,
                'proposal': proposal.reference,
            },
        )


def _write(connection, root, proposal, response_id, key, catalog, transaction, at):
    from backend.app.documents.content import commit_content

    from .artifact_links import create_links, verify_links
    from .card_write_authority import prepare_authorized_write
    from .path_facts import artifact_fact

    authority, current, candidate, source_refs, block_ids = prepare_authorized_write(
        connection, root, response_id, key, catalog, at
    )
    effect = commit_content(
        connection,
        current,
        candidate,
        resources=catalog,
        source_type='CARD_RESPONSE',
        source_id=response_id,
        source_refs=source_refs,
        summary=proposal.payload['change_summary'],
        key=key,
        at=at,
        formation_transaction=transaction,
        card_authority=authority,
    )
    after = transaction.touch(at)
    fact = proposal_fact(proposal)
    link_key = ('CONTENT_ASSOCIATED', proposal.payload['step_ref'])
    keys = (fact.owner, link_key) if block_ids else (fact.owner,)
    ids = allocate_event_ids(connection, keys)
    links = ()
    if block_ids:
        links = verify_links(
            connection,
            root,
            [
                {
                    'step_ref': proposal.payload['step_ref'],
                    'result_refs': proposal.payload['result_refs'],
                    'revision_id': effect['revision_id'],
                    'block_ids': block_ids,
                }
            ],
            catalog,
        )
    head = FormationRepository(connection).head(root['assistant_document_id'], required=True)
    views = write_headers(
        connection,
        root=root,
        command={'type': 'CARD_APPLY', 'proposal': proposal.reference},
        event_ids=ids,
        facts=(fact,),
        extra_counts={link_key: len(links)} if links else {},
        message_id=response_id,
        key=key,
        at=at,
        reason=proposal.payload['change_summary'],
        version_before=transaction.before,
        version_after=after,
        head_before=transaction.focus_before,
        head_after=head,
        content_effect=effect,
    )
    facts = [fact]
    if links:
        artifact = create_links(
            connection,
            root['assistant_document_id'],
            links,
            (ids[link_key],),
            {proposal.payload['step_ref']: proposal.payload['change_summary'][:240]},
        )[0]
        facts.append(artifact_fact(artifact, links[0].result_refs, links[0].ranges, link_key))
    consume(connection, proposal, ids[fact.owner])
    write_facts(connection, root['assistant_document_id'], ids, views, facts)
    return effect
