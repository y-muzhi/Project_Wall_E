"""Same-snapshot proposal projection uses original protection and independent disposition flags."""

from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_object

from .availability import action
from .proposal_binding import PROTECTED_FIELDS, digest, protected_projection, validate_use
from .proposal_contracts import proposal_group
from .proposal_sources import read_reference
from .read_contracts import validate


def binding_reason(connection, root, proposal, purpose, catalog):
    binding = proposal.binding
    projection = {name: binding[name] for name in PROTECTED_FIELDS}
    if (
        binding.get('protected_semantic_digest') != digest(projection)
        or binding.get('proposal') != proposal.reference
        or binding.get('purpose') != purpose
    ):
        raise ValueError('Original proposal protection is damaged')
    try:
        current = protected_projection(connection, root, purpose, proposal.payload, catalog)
    except Rejected:
        return 'SOURCE_UNAVAILABLE'
    for names, reason in (
        (('document_revision_id', 'content_version'), 'CONTENT_CHANGED'),
        (('goal_version',), 'GOAL_CHANGED'),
        (('step_definitions',), 'DEFINITION_CHANGED'),
        (('source_heads',), 'SOURCE_UNAVAILABLE'),
        (('payload_digest', 'related_entries'), 'BASIS_CHANGED'),
    ):
        if any(current[name] != projection[name] for name in names):
            return reason
    try:
        validate_use(connection, root, purpose, proposal.payload, proposal.reference)
    except Rejected:
        return 'PURPOSE_CHANGED'
    return None


def proposal_view(context, row):
    original = context.connection.execute(
        'SELECT * FROM conversation_messages WHERE id=?', (row['message_id'],)
    ).fetchone()
    if original is None:
        raise ValueError('Indexed proposal lost its immutable original message')
    group = proposal_group(
        strict_json_object(original['structured_content_json']),
        context.resources.collaboration,
        stored=True,
    )
    reference = {'message_id': row['message_id'], 'card_key': row['card_key']}
    proposal = read_reference(
        context.connection, context.root, reference, purpose=row['purpose'], allow_consumed=True
    )
    answered = (
        context.connection.execute(
            "SELECT 1 FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'",
            (row['message_id'],),
        ).fetchone()
        is not None
    )
    closed = (
        'ALREADY_ANSWERED'
        if answered or proposal.disposition == 'APPLIED'
        else 'SUPERSEDED'
        if proposal.disposition == 'SUPERSEDED'
        else None
    )
    semantic = (
        None
        if closed
        else binding_reason(
            context.connection, context.root, proposal, row['purpose'], context.resources
        )
    )
    adjusting = 'PROPOSAL_ADJUSTING' if proposal.needs_revision else None
    deferred = 'DEFERRED' if proposal.disposition == 'DEFERRED' else None
    apply_reason = closed or semantic or adjusting or deferred or context.busy
    expiry = (
        'ALREADY_ANSWERED'
        if answered or proposal.disposition == 'APPLIED'
        else 'BASIS_CHANGED'
        if proposal.disposition == 'SUPERSEDED'
        else semantic or ('ADJUSTING' if adjusting else None)
    )
    availability = [
        action('apply', apply_reason),
        action('adjust', closed or context.busy),
        action('preview'),
        action(
            'WITHDRAW_PROPOSAL_ADJUSTMENT',
            closed
            or semantic
            or context.busy
            or (None if proposal.needs_revision else 'INVALID_TRANSITION'),
        ),
    ]
    if row['purpose'] == 'STAGED_WRITE':
        availability.extend(
            (
                action(
                    'DEFER_WRITE_PROPOSAL',
                    closed
                    or context.busy
                    or (None if proposal.disposition == 'PENDING' else 'INVALID_TRANSITION'),
                ),
                action(
                    'RESUME_WRITE_PROPOSAL',
                    closed
                    or semantic
                    or context.busy
                    or (None if proposal.disposition == 'DEFERRED' else 'INVALID_TRANSITION'),
                ),
            )
        )
    return validate(
        'ProposalView',
        {
            **reference,
            'purpose': row['purpose'],
            'payload': group['action_payload'],
            'disposition': proposal.disposition,
            'needs_revision': proposal.needs_revision,
            'can_apply': apply_reason is None,
            'reasons': [] if apply_reason is None else [apply_reason],
            'availability': availability,
            'expiry_reason': expiry,
            'source_run_id': original['guide_run_id'],
        },
    )
