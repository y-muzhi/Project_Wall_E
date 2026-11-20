"""V2.1 adapter into the original C01 transaction, not a parallel run service."""

from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input

from .discuss_selection import apply_selection, prepare_selection
from .model_material import capture_material, freeze_message_effects, material_sources
from .proposal_sources import read_reference


def accept_discussion(connection, request, catalog, at, **continuation):
    from backend.app.guide.commands import _accept_collaboration
    from backend.app.guide.contracts import CreateGuideRunInput

    if not catalog.collaboration.formation_driven:
        raise ConfigInvalid('Formation discussion requires its own new immutable release')
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='formation_heads'"
        ).fetchone()
        is None
    ):
        raise ConfigInvalid('Formation discussion requires verified Schema210')
    root = RequirementRepository(connection).get_for_document(
        request.requirement_id, request.document_id
    )
    if root is None:
        raise Rejected('NOT_FOUND')
    document = connection.execute(
        "SELECT id,content_version FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='CURRENT'",
        (request.document_id, request.requirement_id),
    ).fetchone()
    if document is None:
        raise Rejected('SOURCE_INVALID')
    refs = list(request.source_refs)
    if request.proposal_ref is not None:
        purpose = (
            'STAGED_WRITE' if request.proposal_intent == 'ADJUST_WRITE' else 'FORMATION_PATH_CHANGE'
        )
        read_reference(connection, root, request.proposal_ref, purpose=purpose)
        source = {'kind': 'MESSAGE', 'message_id': request.proposal_ref['message_id']}
        if source not in refs:
            refs.append(source)
    internal = CreateGuideRunInput(
        request.requirement_id,
        request.document_id,
        request.expected_discussion_version,
        'DISCUSS',
        request.instruction,
        {
            'kind': 'EXISTING',
            'document_id': document['id'],
            'expected_content_version': document['content_version'],
        },
        request.scope,
        refs,
        None,
        request.acknowledge_source_changes,
        request.idempotency_key,
    )
    return _accept_collaboration(
        connection, internal, catalog, at, formation_input=request, **continuation
    )


def prepare_acceptance(connection, root_before, run_id, message, request, catalog, at, basis):
    from backend.app.guide.accepted_context import capture_source
    from backend.app.requirements.contracts import requirement_read_model
    from backend.app.requirements.source_refs import verify_source_refs

    from .proposal_adjustment import prepare_adjustment
    from .repository import FormationRepository

    original_head = FormationRepository(connection).head(root_before['assistant_document_id'])
    plan = prepare_selection(connection, root_before, request.target)
    finish_events = apply_selection(
        connection, root_before, plan, message['id'], run_id, request.idempotency_key, at
    )
    finish_adjustment = prepare_adjustment(
        connection, root_before, original_head, request, message['id'], run_id, at
    )
    current = RequirementRepository(connection).get_for_document(
        request.requirement_id, request.document_id
    )
    previous_branch = (
        None if plan.before is None else plan.before[2].get(request.target['discussion_branch_ref'])
    )
    required_steps = ()
    required_entities = ()
    if request.proposal_ref is not None:
        from .proposal_binding import scope_for

        purpose = (
            'STAGED_WRITE' if request.proposal_intent == 'ADJUST_WRITE' else 'FORMATION_PATH_CHANGE'
        )
        original = read_reference(connection, current, request.proposal_ref, purpose=purpose)
        scope = scope_for(purpose, original.payload)
        required_steps = list(scope['step_refs'])
        required_entities = scope['entities']
        for item in required_entities:
            if item['kind'] in ('ISSUE', 'BRANCH'):
                table, identity, owner = (
                    ('formation_issues', 'issue_ref', 'step_ref')
                    if item['kind'] == 'ISSUE'
                    else ('formation_branches', 'branch_ref', 'return_step_ref')
                )
                value = connection.execute(
                    'SELECT '
                    + owner
                    + ' FROM '
                    + table
                    + ' WHERE document_id=? AND '
                    + identity
                    + '=?',
                    (request.document_id, item['ref']),
                ).fetchone()
                if value is None:
                    raise Rejected('SOURCE_INVALID')
                if value[0] not in required_steps:
                    required_steps.append(value[0])
    material = capture_material(
        connection,
        current,
        plan.normalized,
        catalog,
        previous_branch=previous_branch,
        required_steps=required_steps,
        required_entities=required_entities,
    )
    refs = material_sources(material)
    verify_source_refs(connection, current['id'], refs, resources=catalog.collaboration)
    captured = {canonical_input(item['source_ref']): item for item in basis['source_snapshots']}
    for source in refs:
        captured.setdefault(
            canonical_input(source),
            capture_source(connection, current['id'], source, catalog.collaboration),
        )
    proposal_context = None
    if request.proposal_ref is not None:
        purpose = (
            'STAGED_WRITE' if request.proposal_intent == 'ADJUST_WRITE' else 'FORMATION_PATH_CHANGE'
        )
        original = read_reference(connection, current, request.proposal_ref, purpose=purpose)
        proposal_context = {
            'proposal_ref': dict(request.proposal_ref),
            'purpose': purpose,
            'action_payload': original.payload,
        }
    if proposal_context is not None:
        sources = material_sources(proposal_context)
        verify_source_refs(connection, current['id'], sources, resources=catalog.collaboration)
        for source in sources:
            name = canonical_input(source)
            if name not in captured:
                captured[name] = capture_source(
                    connection, current['id'], source, catalog.collaboration
                )
    basis.update(
        requirement=requirement_read_model(current),
        discussion=current['discussion_state_json'],
        discussion_version=current['discussion_version'],
        source_snapshots=list(captured.values()),
        formation=material,
        formation_selection=plan.normalized,
        proposal_context=proposal_context,
        formation_request=request.business_input(),
    )
    basis['request'].update(
        formation_selection=plan.normalized,
        proposal_intent=request.proposal_intent,
        proposal_ref=request.proposal_ref,
    )
    basis['message_effects'] = freeze_message_effects(connection, basis)

    def finish_all():
        return (*finish_events(), *finish_adjustment())

    return plan.normalized, finish_all
