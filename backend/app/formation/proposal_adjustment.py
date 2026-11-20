"""Proposal adjustment is a real accepted USER action, separate from its immutable binding."""

from backend.app.shared.command_execution import Rejected

from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact
from .proposal_sources import read_reference
from .repository import FormationRepository
from .transaction import FormationTransaction


def prepare_adjustment(connection, root_before, original_head, request, message_id, run_id, at):
    if request.proposal_ref is None:
        return lambda: ()
    purpose = (
        'STAGED_WRITE' if request.proposal_intent == 'ADJUST_WRITE' else 'FORMATION_PATH_CHANGE'
    )
    proposal = read_reference(connection, root_before, request.proposal_ref, purpose=purpose)
    if proposal.needs_revision:
        return lambda: ()
    if original_head is None:
        raise Rejected('SOURCE_INVALID')
    transaction = FormationTransaction(connection, root_before, original_head)
    after_versions = transaction.touch(at)
    action = ('PROPOSAL_ADJUSTMENT_REQUESTED', proposal.entity_ref)
    ids = allocate_event_ids(connection, (action,))
    before = proposal.snapshot()
    facts = [
        RouteFact(
            'PROPOSAL', proposal.entity_ref, before, {**before, 'needs_revision': True}, action
        )
    ]
    after_head = FormationRepository(connection).head(
        root_before['assistant_document_id'], required=True
    )

    def finish():
        views = write_headers(
            connection,
            root=root_before,
            command={
                'type': 'PROPOSAL_ADJUSTMENT',
                'proposal': request.proposal_ref,
                'intent': request.proposal_intent,
            },
            event_ids=ids,
            facts=facts,
            extra_counts={},
            message_id=message_id,
            key=request.idempotency_key,
            at=at,
            reason='请求调整原提案',
            version_before=transaction.before,
            version_after=after_versions,
            head_before=original_head,
            head_after=after_head,
            actor='USER',
            source_run_id=run_id,
        )
        write_facts(connection, root_before['assistant_document_id'], ids, views, facts)
        return tuple(ids.values())

    return finish
