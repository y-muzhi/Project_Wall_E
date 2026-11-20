"""Trusted CARD_APPLY adapter reuses the complete path planner and storage."""

from collections import Counter
from dataclasses import replace

from .artifact_links import verify_links
from .card_apply import consume, proposal_fact
from .path_commands import reference_map_view
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import artifact_fact, event_keys, route_facts
from .path_plan import prepare_route
from .repository import FormationRepository
from .route_storage import apply_disposition_events, persist_route, resolve_route


def apply_route(connection, root, proposal, response_id, key, catalog, transaction, at):
    repository = FormationRepository(connection)
    document_id = root['assistant_document_id']
    head, steps, branches, issues, edges = repository.graph(document_id)
    results = {
        row['result_ref']: dict(row)
        for row in connection.execute(
            'SELECT * FROM formation_results WHERE document_id=?',
            (document_id,),
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
    plan = prepare_route(*before, proposal.payload['changes'], proposal.payload['result_routes'])
    checked = verify_links(connection, root, plan.links, catalog) if plan.links else ()
    mapping, counters = repository.allocate_path_references(document_id, plan.scope)
    resolved = resolve_route(plan, mapping, counters)
    resolved = replace(resolved, changed=True)
    checked = tuple(
        replace(
            link,
            step_ref=mapping.get(link.step_ref, link.step_ref),
            result_refs=tuple(mapping.get(ref, ref) for ref in link.result_refs),
        )
        for link in checked
    )
    fact = proposal_fact(proposal)
    keys = (*event_keys(before, resolved), fact.owner)
    ids = allocate_event_ids(connection, keys)
    resolved = apply_disposition_events(resolved, ids)
    facts = [*route_facts(before, resolved, keys), fact]
    after = {
        **transaction.before,
        'discussion_version': transaction.before['discussion_version'] + 1,
        'formation_version': transaction.before['formation_version'] + 1,
        'goal_version': resolved.head['goal_version'],
    }
    views = write_headers(
        connection,
        root=root,
        command={'type': 'CARD_APPLY', 'proposal': proposal.reference},
        event_ids=ids,
        facts=facts,
        extra_counts=Counter(('CONTENT_ASSOCIATED', link.step_ref) for link in checked),
        message_id=response_id,
        key=key,
        at=at,
        reason=proposal.payload['change_summary'],
        version_before=transaction.before,
        version_after=after,
        head_before=head,
        head_after=resolved.head,
    )
    artifacts = persist_route(
        connection,
        before=before,
        resolved=resolved,
        verified_links=checked,
        link_event_ids=[ids[('CONTENT_ASSOCIATED', link.step_ref)] for link in checked],
        summaries={ref: '关联内容：' + step['title'] for ref, step in resolved.steps.items()},
    )
    for artifact, link in zip(artifacts, checked, strict=True):
        facts.append(
            artifact_fact(
                artifact, link.result_refs, link.ranges, ('CONTENT_ASSOCIATED', link.step_ref)
            )
        )
    consume(connection, proposal, ids[fact.owner])
    if transaction.touch(at) != after:
        raise ValueError('Actual route adoption versions differ from their event batch')
    write_facts(connection, document_id, ids, views, facts)
    return None, reference_map_view(plan, mapping)
