"""Locate an immutable proposal as a source; this does not authorize applying its payload."""

import hashlib
from dataclasses import dataclass

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object

from .path_facts import RouteFact


def digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ReferencedProposal:
    document_id: int
    reference: dict
    disposition: str
    needs_revision: bool
    binding_digest: str
    binding: dict
    payload: dict

    @property
    def entity_ref(self):
        return f'{self.reference["message_id"]}:{self.reference["card_key"]}'

    def snapshot(self):
        return {
            'proposal': dict(self.reference),
            'disposition': self.disposition,
            'needs_revision': self.needs_revision,
            'binding_digest': self.binding_digest,
        }


def read_reference(connection, root, reference, *, purpose, allow_consumed=False):
    """Manual editing uses fresh D/F/V, even when this original source's basis is stale."""
    row = connection.execute(
        'SELECT p.*,m.role,m.message_type,m.structured_content_json,m.requirement_id,'
        'm.guide_run_id,g.document_id AS run_document_id,g.requirement_id AS run_requirement_id '
        'FROM formation_proposal_index p JOIN conversation_messages m '
        'ON m.id=p.message_id AND m.document_id=p.document_id '
        'LEFT JOIN guide_runs g ON g.id=m.guide_run_id '
        'WHERE p.document_id=? AND p.message_id=? AND p.card_key=?',
        (root['assistant_document_id'], reference['message_id'], reference['card_key']),
    ).fetchone()
    if (
        row is None
        or row['requirement_id'] != root['id']
        or row['role'] != 'ASSISTANT'
        or row['message_type'] != 'INTERACTION_CARDS'
        or row['purpose'] != purpose
        or row['guide_run_id'] is None
        or row['run_document_id'] != root['assistant_document_id']
        or row['run_requirement_id'] != root['id']
    ):
        raise Rejected('SOURCE_INVALID')
    if not allow_consumed and row['disposition'] not in ('PENDING', 'DEFERRED'):
        raise Rejected(
            'STATE_CONFLICT',
            details={
                'reason': 'PROPOSAL_BASIS_CHANGED',
                'step_ref': None,
                'proposal': reference,
            },
        )
    group = strict_json_object(row['structured_content_json'])
    payload = group.get('action_payload')
    cards = group.get('cards')
    if (
        group.get('purpose') != purpose
        or type(payload) is not dict
        or type(cards) is not list
        or len(cards) != 1
        or type(cards[0]) is not dict
        or cards[0].get('card_key') != reference['card_key']
        or digest(payload) != row['payload_digest']
    ):
        raise Rejected('SOURCE_INVALID')
    binding = strict_json_object(row['binding_json'])
    if (
        binding.get('schema') != 'formation_card_binding_v21_1'
        or binding.get('payload_digest') != row['payload_digest']
    ):
        raise Rejected('SOURCE_INVALID')
    binding_hash = digest(binding)
    latest = connection.execute(
        'SELECT after_json FROM formation_event_changes WHERE document_id=? AND entity_kind=? '
        'AND entity_ref=? ORDER BY event_id DESC,ordinal DESC LIMIT 1',
        (
            root['assistant_document_id'],
            'PROPOSAL',
            f'{reference["message_id"]}:{reference["card_key"]}',
        ),
    ).fetchone()
    if latest is None:
        if row['disposition'] != 'PENDING' or row['disposition_event_id'] is not None:
            raise ValueError('Proposal disposition lost its immutable history')
        needs_revision = False
    else:
        state = strict_json_object(latest[0])
        if (
            set(state) != {'proposal', 'disposition', 'needs_revision', 'binding_digest'}
            or state['proposal'] != reference
            or state['disposition'] != row['disposition']
            or state['binding_digest'] != binding_hash
            or type(state['needs_revision']) is not bool
        ):
            raise ValueError('Proposal projection differs from its immutable binding/history')
        needs_revision = state['needs_revision']
    return ReferencedProposal(
        root['assistant_document_id'],
        dict(reference),
        row['disposition'],
        needs_revision,
        binding_hash,
        binding,
        payload,
    )


def superseded_fact(proposal):
    before = proposal.snapshot()
    after = {**before, 'disposition': 'SUPERSEDED', 'needs_revision': False}
    return RouteFact(
        'PROPOSAL', proposal.entity_ref, before, after, ('PROPOSAL_SUPERSEDED', proposal.entity_ref)
    )


def supersede(connection, proposal, event_id):
    """Metadata only; the original card, publication binding and formal responses stay intact."""
    require_write_transaction(connection)
    changed = connection.execute(
        "UPDATE formation_proposal_index SET disposition='SUPERSEDED',disposition_event_id=? "
        'WHERE document_id=? AND message_id=? AND card_key=? AND disposition=?',
        (
            event_id,
            proposal.document_id,
            proposal.reference['message_id'],
            proposal.reference['card_key'],
            proposal.disposition,
        ),
    )
    if changed.rowcount != 1:
        raise Rejected(
            'STATE_CONFLICT',
            details={
                'reason': 'PROPOSAL_BASIS_CHANGED',
                'step_ref': None,
                'proposal': proposal.reference,
            },
        )
