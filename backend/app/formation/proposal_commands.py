"""Program-only defer/resume/withdraw; never consumes a formal card response or calls AI."""

from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected

from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact
from .proposal_binding import check_binding
from .proposal_sources import read_reference
from .repository import FormationRepository
from .state_commands import receipt, version_basis

ACTIONS = frozenset(
    ('DEFER_WRITE_PROPOSAL', 'RESUME_WRITE_PROPOSAL', 'WITHDRAW_PROPOSAL_ADJUSTMENT')
)


def apply(connection, root, command, key, at, *, resources):
    action = command['action']
    if action not in ACTIONS:
        raise ValueError('Proposal handler requires a registered proposal action')
    if at < root['updated_at']:
        raise ValueError('Proposal action cannot precede stored activity')
    assert_idle(
        connection,
        root,
        remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
    )
    document_id = root['assistant_document_id']
    repository = FormationRepository(connection)
    head = repository.head(document_id, required=True)
    reference = command['proposal']
    row = connection.execute(
        'SELECT purpose FROM formation_proposal_index WHERE document_id=? AND message_id=? AND card_key=?',
        (document_id, reference['message_id'], reference['card_key']),
    ).fetchone()
    if row is None:
        raise Rejected('SOURCE_INVALID')
    purpose = row[0]
    proposal = read_reference(connection, root, reference, purpose=purpose)
    document = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? AND d.archived_at IS NULL',
        (document_id,),
    ).fetchone()
    if document is None:
        raise Rejected('NOT_FOUND')

    def invalid():
        raise Rejected(
            'STATE_CONFLICT',
            details={'reason': 'INVALID_TRANSITION', 'step_ref': None, 'proposal': reference},
        )

    after = proposal.snapshot()
    observed = None
    if action == 'DEFER_WRITE_PROPOSAL':
        if purpose != 'STAGED_WRITE':
            invalid()
        if proposal.disposition == 'DEFERRED':
            return receipt(root, head, document, None, (), changed=False)
        after['disposition'] = 'DEFERRED'
        event = 'PROPOSAL_DEFERRED'
        label = '暂缓写入提案'
    elif action == 'RESUME_WRITE_PROPOSAL':
        if purpose != 'STAGED_WRITE':
            invalid()
        if proposal.disposition == 'PENDING':
            return receipt(root, head, document, None, (), changed=False)
        observed = check_binding(connection, root, proposal, purpose, resources)
        after['disposition'] = 'PENDING'
        event = 'PROPOSAL_RESUMED'
        label = '恢复写入提案'
    else:
        if not proposal.needs_revision:
            return receipt(root, head, document, None, (), changed=False)
        observed = check_binding(connection, root, proposal, purpose, resources)
        after['needs_revision'] = False
        event = 'PROPOSAL_ADJUSTMENT_WITHDRAWN'
        label = '撤回提案调整'
    ids = allocate_event_ids(connection, ((event, proposal.entity_ref),))
    event_id = ids[(event, proposal.entity_ref)]
    message_id = entity_id(connection, EntityKind.MESSAGE)
    MessageRepository(connection).create_user_text(
        message_id,
        root['id'],
        None,
        label + ('。原因：' + command['reason'] if 'reason' in command else ''),
        key,
        at,
        document_id=document_id,
        topic_refs=(),
        document_ids=(document_id,),
    )
    facts = [
        RouteFact(
            'PROPOSAL',
            proposal.entity_ref,
            proposal.snapshot(),
            after,
            (event, proposal.entity_ref),
        )
    ]
    before_basis = version_basis(root, head, document)
    after_basis = {
        **before_basis,
        'discussion_version': increment(root['discussion_version']),
        'formation_version': increment(head['version']),
    }
    if action == 'WITHDRAW_PROPOSAL_ADJUSTMENT':
        proof = {
            'proposal': reference,
            'publication_binding_digest': proposal.binding_digest,
            'expected_semantic_digest': proposal.binding['protected_semantic_digest'],
            'observed_semantic_digest': observed,
            'checked_versions': before_basis,
            'check_kind': 'WITHDRAW_ADJUSTMENT',
            'result': 'MATCHED',
            'command_message_id': message_id,
        }
        facts.append(
            RouteFact(
                'PROPOSAL_CHECK', proposal.entity_ref, None, proof, (event, proposal.entity_ref)
            )
        )
    views = write_headers(
        connection,
        root=root,
        command=command,
        event_ids=ids,
        facts=facts,
        extra_counts={},
        message_id=message_id,
        key=key,
        at=at,
        reason=command.get('reason', label),
        version_before=before_basis,
        version_after=after_basis,
        head_before=head,
        head_after=head,
    )
    # No binding/payload column is ever updated.
    changed = connection.execute(
        'UPDATE formation_proposal_index SET disposition=?,disposition_event_id=? WHERE document_id=? '
        'AND message_id=? AND card_key=? AND disposition=?',
        (
            after['disposition'],
            event_id,
            document_id,
            reference['message_id'],
            reference['card_key'],
            proposal.disposition,
        ),
    )
    if changed.rowcount != 1:
        raise Rejected(
            'STATE_CONFLICT',
            details={'reason': 'PROPOSAL_BASIS_CHANGED', 'step_ref': None, 'proposal': reference},
        )
    changed = connection.execute(
        'UPDATE formation_heads SET version=? WHERE document_id=? AND version=?',
        (after_basis['formation_version'], document_id, head['version']),
    )
    if changed.rowcount != 1:
        raise Rejected(
            'STATE_CONFLICT',
            details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': reference},
        )
    updated = RequirementRepository(connection).advance_discussion(root, at)
    write_facts(connection, document_id, ids, views, facts)
    result = receipt(
        updated,
        repository.head(document_id, required=True),
        document,
        message_id,
        (event_id,),
        changed=True,
    )
    result['effects']['proposal_disposition'] = after['disposition']
    return result
