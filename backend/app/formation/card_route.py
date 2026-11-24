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
    before, plan = prepare_route_graph(
        connection, root, proposal.payload['changes'], proposal.payload['result_routes']
    )
    checked = verify_links(connection, root, plan.links, catalog) if plan.links else ()
    effect = persist_prepared_route(
        connection,
        root,
        before,
        plan,
        checked,
        response_id,
        key,
        transaction,
        at,
        command={'type': 'CARD_APPLY', 'proposal': proposal.reference},
        reason=proposal.payload['change_summary'],
        proposal=proposal,
    )
    return None, effect['reference_map']


def prepare_route_graph(connection, root, changes, result_routes):
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
    plan = prepare_route(*before, changes, result_routes, expanded_model_changes=not changes)
    return before, plan


def persist_prepared_route(
    connection,
    root,
    before,
    plan,
    checked,
    response_id,
    key,
    transaction,
    at,
    *,
    command,
    reason,
    proposal=None,
    source_run_id=None,
    focus_event=None,
    sources=None,
):
    document_id = root['assistant_document_id']
    repository = FormationRepository(connection)
    head = before[0]
    if not plan.changed and proposal is None:
        return {
            'result': 'NO_CHANGE',
            'event_ids': [],
            'reference_map': [],
            'formation_changed': False,
        }
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
    fact = proposal_fact(proposal) if proposal is not None else None
    keys = list(event_keys(before, resolved))
    if focus_event is not None:
        action, ref = focus_event
        keys.append((action, mapping.get(ref, ref)))
    if fact is not None:
        keys.append(fact.owner)
    ids = allocate_event_ids(connection, keys)
    resolved = apply_disposition_events(resolved, ids)
    facts = list(route_facts(before, resolved, keys))
    if fact is not None:
        facts.append(fact)
    after = {
        **transaction.before,
        'discussion_version': transaction.before['discussion_version'] + 1,
        'formation_version': transaction.before['formation_version'] + 1,
        'goal_version': resolved.head['goal_version'],
    }
    views = write_headers(
        connection,
        root=root,
        command=command,
        event_ids=ids,
        facts=facts,
        extra_counts=Counter(('CONTENT_ASSOCIATED', link.step_ref) for link in checked),
        message_id=response_id,
        key=key,
        at=at,
        reason=reason,
        source_run_id=source_run_id,
        actor='AI' if source_run_id is not None else 'USER',
        sources=None if sources is None else {event_key: sources for event_key in keys},
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
    if fact is not None:
        consume(connection, proposal, ids[fact.owner])
    if transaction.touch(at) != after:
        raise ValueError('Actual route adoption versions differ from their event batch')
    write_facts(connection, document_id, ids, views, facts)
    return {
        'result': 'APPLIED',
        'event_ids': list(ids.values()),
        'reference_map': reference_map_view(plan, mapping),
        'formation_changed': True,
    }
