"""Actual manual ADJUST_PATH transaction; the old card never supplies write authority."""

from collections import Counter
from dataclasses import replace

from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.command_execution import Rejected

from .artifact_links import verify_links
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import artifact_fact, event_keys, route_facts
from .path_plan import prepare_route
from .proposal_sources import read_reference, supersede, superseded_fact
from .repository import FormationRepository
from .route_storage import apply_disposition_events, persist_route, resolve_route
from .state_commands import receipt, version_basis


def load_input(connection, root, command):
    """The same complete read is usable by PREVIEW; it allocates and writes nothing."""
    document_id = root['assistant_document_id']
    document = connection.execute(
        'SELECT d.*,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? '
        "AND d.requirement_id=? AND d.document_type='CURRENT' AND d.archived_at IS NULL",
        (document_id, root['id']),
    ).fetchone()
    if document is None:
        raise Rejected('NOT_FOUND')
    repository = FormationRepository(connection)
    head, steps, branches, issues, edges = repository.graph(document_id)
    if head['version'] != command['expected_formation_version']:
        raise Rejected(
            'STATE_CONFLICT', details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None}
        )
    if document['content_version'] != command['expected_content_version']:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    results = {
        row['result_ref']: dict(row)
        for row in connection.execute(
            'SELECT * FROM formation_results WHERE document_id=?', (document_id,)
        )
    }
    before = (
        head,
        steps,
        results,
        branches,
        issues,
        set(edges['DEPENDENCY']),
        set(edges['REPLACES']),
    )
    proposal = None
    if command['based_on_proposal'] is not None:
        proposal = read_reference(
            connection, root, command['based_on_proposal'], purpose='FORMATION_PATH_CHANGE'
        )
    plan = prepare_route(*before, command['changes'], command['result_routes'])
    return document, before, proposal, plan


def reference_map_view(plan, mapping):
    ordered = []
    for change in plan.changes:
        if change['type'] == 'ADD_STEP':
            ordered.append(change['temp_step_ref'])
            ordered.extend(result['temp_result_ref'] for result in change['expected_results'])
        elif change['type'] == 'ADD_RESULT':
            ordered.append(change['temp_result_ref'])
    return [{'temp_ref': ref, 'resolved_ref': mapping[ref]} for ref in ordered]


def apply(connection, root, command, key, at, *, resources):
    require_write_transaction(connection)
    if command['action'] != 'ADJUST_PATH':
        raise ValueError('Manual route application requires its own strict native action')
    if at < root['updated_at']:
        raise ValueError('Manual route cannot precede the stored document activity')
    assert_idle(
        connection,
        root,
        remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
    )
    document, before, proposal, plan = load_input(connection, root, command)
    if not plan.changed and proposal is None:
        return receipt(root, before[0], document, None, (), changed=False)
    for change in plan.changes:
        if change['type'] == 'SET_GOAL':
            verify_source_refs(
                connection, root['id'], change['source_refs'], resources=resources.collaboration
            )
    checked = verify_links(connection, root, plan.links, resources) if plan.links else ()
    repository = FormationRepository(connection)
    mapping, counters = repository.allocate_path_references(
        root['assistant_document_id'], plan.scope
    )
    resolved = resolve_route(plan, mapping, counters)
    if proposal is not None and not resolved.changed:
        resolved = replace(resolved, changed=True)
    checked = tuple(
        replace(
            link,
            step_ref=mapping.get(link.step_ref, link.step_ref),
            result_refs=tuple(mapping.get(ref, ref) for ref in link.result_refs),
        )
        for link in checked
    )
    keys = event_keys(before, resolved)
    if proposal is not None:
        keys = (*keys, ('PROPOSAL_SUPERSEDED', proposal.entity_ref))
    event_ids = allocate_event_ids(connection, keys)
    resolved = apply_disposition_events(resolved, event_ids)
    facts = route_facts(before, resolved, keys)
    if proposal is not None:
        facts = (*facts, superseded_fact(proposal))
    message_id = entity_id(connection, EntityKind.MESSAGE)
    MessageRepository(connection).create_user_text(
        message_id,
        root['id'],
        None,
        '调整文档形成路线。原因：' + command['reason'],
        key,
        at,
        document_id=root['assistant_document_id'],
        topic_refs=(),
        document_ids=(root['assistant_document_id'],),
    )
    basis_before = version_basis(root, before[0], document)
    basis_after = {
        **basis_before,
        'discussion_version': increment(root['discussion_version']),
        'formation_version': increment(before[0]['version']),
        'goal_version': resolved.head['goal_version'],
    }
    extra_counts = Counter(('CONTENT_ASSOCIATED', link.step_ref) for link in checked)
    views = write_headers(
        connection,
        root=root,
        command=command,
        event_ids=event_ids,
        facts=facts,
        extra_counts=extra_counts,
        message_id=message_id,
        key=key,
        at=at,
        reason=command['reason'],
        version_before=basis_before,
        version_after=basis_after,
        head_before=before[0],
        head_after=resolved.head,
    )
    link_events = [event_ids[('CONTENT_ASSOCIATED', link.step_ref)] for link in checked]
    summaries = {
        ref: '关联步骤“' + step['title'] + '”的既有内容' for ref, step in resolved.steps.items()
    }
    artifacts = persist_route(
        connection,
        before=before,
        resolved=resolved,
        verified_links=checked,
        link_event_ids=link_events,
        summaries=summaries,
    )
    all_facts = list(facts)
    for artifact, link in zip(artifacts, checked, strict=True):
        all_facts.append(
            artifact_fact(
                artifact, link.result_refs, link.ranges, ('CONTENT_ASSOCIATED', link.step_ref)
            )
        )
    if proposal is not None:
        supersede(connection, proposal, event_ids[('PROPOSAL_SUPERSEDED', proposal.entity_ref)])
    updated = RequirementRepository(connection).advance_discussion(root, at)
    write_facts(connection, root['assistant_document_id'], event_ids, views, all_facts)
    current_head = repository.head(root['assistant_document_id'], required=True)
    if version_basis(updated, current_head, document) != basis_after:
        raise ValueError('Persisted route versions differ from their immutable event batch')
    result = receipt(
        updated, current_head, document, message_id, tuple(event_ids.values()), changed=True
    )
    result['reference_map'] = reference_map_view(plan, mapping)
    if proposal is not None:
        result['effects']['proposal_disposition'] = 'SUPERSEDED'
    return result
