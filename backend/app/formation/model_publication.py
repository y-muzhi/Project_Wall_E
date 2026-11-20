"""Prepare new immutable proposals without writing their future content or path."""

from copy import deepcopy

from backend.app.guide.card_binding import bind_cards
from backend.app.guide.progress_application import ProgressInvalid
from backend.app.shared.json_canonical import canonical_input

from .artifact_links import verify_links
from .model_evidence import ModelEvidence
from .model_plan import _resolve_sources
from .path_plan import prepare_route
from .proposal_binding import publish_binding, scope_for
from .proposal_contracts import PURPOSES, proposal_group
from .repository import FormationRepository
from .write_preview import prepare_write


def prepare_publication(
    connection, root, run, context, value, catalog, *, plan, reference_map, discussion
):
    purpose = value['purpose']
    predicted = dict(root)
    changes_d = discussion != root['discussion_state_json'] or plan is not None and plan.changed
    if purpose not in PURPOSES:
        predicted['discussion_version'] += int(changes_d)
        return bind_cards(
            connection, predicted, run, context, value, catalog, reference_map=reference_map
        ), None
    adjusting = context.canonical['proposal_context']
    if adjusting is not None and purpose != adjusting['purpose']:
        raise ProgressInvalid('Replacement must preserve the explicitly adjusted proposal purpose')
    group = deepcopy(catalog.collaboration.validate('ModelCardGroup', value))
    payload = group['action_payload']
    evidence = ModelEvidence(connection, root, context, catalog)
    _resolve_sources(payload, evidence)
    frozen = context.canonical['formation']['basis']
    if purpose == 'FORMATION_PATH_CHANGE':
        if plan is not None:
            raise ProgressInvalid('A path proposal cannot accompany an ordinary formation delta')
        repository = FormationRepository(connection)
        head, steps, branches, issues, edges = repository.graph(root['assistant_document_id'])
        if payload['basis'] != frozen:
            raise ProgressInvalid('Path proposal must name the actual frozen versions')
        results = {
            row['result_ref']: dict(row)
            for row in connection.execute(
                'SELECT * FROM formation_results WHERE document_id=?',
                (root['assistant_document_id'],),
            )
        }
        route = prepare_route(
            head,
            steps,
            results,
            branches,
            issues,
            set(edges['DEPENDENCY']),
            set(edges['REPLACES']),
            payload['changes'],
            payload['result_routes'],
        )
        declared_steps = {
            change['temp_step_ref'] for change in route.changes if change['type'] == 'ADD_STEP'
        }
        for ref in scope_for(purpose, payload)['step_refs']:
            evidence.require_visible('STEP', ref, newly_declared=declared_steps, full=False)
        _require_path_definitions(evidence, route, declared_steps)
        for change in route.changes:
            for kind, name in (('BRANCH', 'branch_ref'), ('ISSUE', 'issue_ref')):
                if name in change:
                    evidence.require_visible(kind, change[name])
        if route.links:
            verify_links(connection, root, route.links, catalog)
            visible = {
                block['block_id']
                for document in context.input['documents']
                if document['document_id'] == root['assistant_document_id']
                and document['revision_id'] == frozen['document_revision_id']
                for block in document['blocks']
            }
            if any(not set(link['block_ids']) <= visible for link in route.links):
                raise ProgressInvalid('Path link addresses content outside carried material')
    else:
        mapping = {} if plan is None else plan.mapping
        original = payload['step_ref']
        evidence.require_visible('STEP', original, newly_declared=mapping)
        payload['step_ref'] = mapping.get(original, original)
        payload['result_refs'] = [mapping.get(ref, ref) for ref in payload['result_refs']]
        if any(ref.startswith('new_') for ref in [payload['step_ref'], *payload['result_refs']]):
            raise ProgressInvalid('A write may bind only objects actually created in this round')
        if plan is None:
            head, steps, _, _, _ = FormationRepository(connection).graph(
                root['assistant_document_id']
            )
            results = {
                row['result_ref']: dict(row)
                for row in connection.execute(
                    'SELECT * FROM formation_results WHERE document_id=?',
                    (root['assistant_document_id'],),
                )
            }
        else:
            head, steps, results = plan.route.head, plan.route.steps, plan.route.results
            existing = plan.before[1].get(payload['step_ref'])
            if (
                not plan.initializing
                and existing is not None
                and (
                    existing['definition_version']
                    != steps[payload['step_ref']]['definition_version']
                )
            ):
                raise ProgressInvalid('A write cannot share a substantive target definition change')
        step = steps.get(payload['step_ref'])
        if (
            step is None
            or step['status'] == 'CANCELLED'
            or payload['definition_version'] != step['definition_version']
        ):
            raise ProgressInvalid('Write target is not an actual available step definition')
        if payload['goal_version'] != head['goal_version']:
            raise ProgressInvalid('Write refers to another Goal')
        if any(
            ref not in results or results[ref]['step_ref'] != payload['step_ref']
            for ref in payload['result_refs']
        ):
            raise ProgressInvalid('Write results must belong to its actual target step')
        if any(results[ref]['kind'] != 'CONTENT' for ref in payload['result_refs']):
            raise ProgressInvalid('A write may only cover content results')
        carried = [
            block['block_id']
            for document in context.input['documents']
            if document['document_id'] == root['assistant_document_id']
            and document['revision_id'] == frozen['document_revision_id']
            for block in document['blocks']
        ]
        prepare_write(connection, root, payload, catalog, carried_block_ids=carried)
    # Existing public message shell only; authority lives in the separate immutable index.
    group['program_binding'] = {
        'discussion_version': root['discussion_version'] + 1,
        'target_content_version': frozen['content_version'],
        'source_heads': [],
    }
    stored = proposal_group(group, catalog.collaboration, stored=True)
    catalog.collaboration.validate('StoredCardGroup', stored)
    return stored, stored


def store_publication(connection, root, context, assistant_id, group, catalog, transaction, at):
    reference = {'message_id': assistant_id, 'card_key': group['cards'][0]['card_key']}
    binding = publish_binding(
        connection,
        root,
        group['purpose'],
        group['action_payload'],
        reference,
        context.canonical['formation']['basis']['formation_version'],
        catalog,
    )
    connection.execute(
        "INSERT INTO formation_proposal_index(document_id,message_id,card_key,purpose,disposition,disposition_event_id,binding_json,payload_digest) VALUES(?,?,?,?,'PENDING',NULL,?,?)",
        (
            root['assistant_document_id'],
            assistant_id,
            reference['card_key'],
            group['purpose'],
            canonical_input(binding),
            binding['payload_digest'],
        ),
    )
    after = transaction.touch(at)
    adjusting = context.canonical['proposal_context']
    if adjusting is not None:
        from .path_events import allocate_event_ids, write_facts, write_headers
        from .proposal_sources import read_reference, supersede, superseded_fact

        old = read_reference(connection, root, adjusting['proposal_ref'], purpose=group['purpose'])
        if not old.needs_revision:
            raise ValueError('Replacement requires its actual accepted adjustment marker')
        fact = superseded_fact(old)
        events = allocate_event_ids(connection, (fact.owner,))
        head = FormationRepository(connection).head(root['assistant_document_id'], required=True)
        run = connection.execute(
            'SELECT * FROM guide_runs WHERE id=(SELECT guide_run_id FROM conversation_messages WHERE id=?)',
            (assistant_id,),
        ).fetchone()
        views = write_headers(
            connection,
            root=root,
            command={'type': 'PROPOSAL_REPLACEMENT', 'replacement': reference},
            event_ids=events,
            facts=(fact,),
            extra_counts={},
            message_id=assistant_id,
            key=run['idempotency_key'],
            at=at,
            reason='保存调整后的新提案',
            version_before=transaction.before,
            version_after=after,
            head_before=transaction.focus_before,
            head_after=head,
            actor='AI',
            source_run_id=run['id'],
        )
        supersede(connection, old, events[fact.owner])
        write_facts(connection, root['assistant_document_id'], events, views, (fact,))


def _require_path_definitions(evidence, route, declared_steps):
    """A carried dependency identity may be referenced, never silently grant its definition."""
    changes_definitions = {
        'RENAME_STEP',
        'MOVE_STEP',
        'SET_DEPENDENCIES',
        'ADD_RESULT',
        'CANCEL_STEP',
        'LINK_CONTENT',
    }
    for change in route.changes:
        if change['type'] in changes_definitions:
            evidence.require_visible('STEP', change['step_ref'], newly_declared=declared_steps)
        elif change['type'] == 'UPDATE_RESULT':
            evidence.require_visible('STEP', change['result_ref'].split('.o')[0])
    for result_route in route.result_routes:
        evidence.require_visible('STEP', result_route['from_result_ref'].split('.o')[0])
        for target in result_route['target_result_refs']:
            if not target.startswith('new_result_'):
                evidence.require_visible('STEP', target.split('.o')[0])
