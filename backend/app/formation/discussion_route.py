"""Verify a model interpretation against the frozen user request before preparing any write."""

from copy import deepcopy
from dataclasses import dataclass, replace

from backend.app.guide.progress_application import ProgressInvalid
from .artifact_links import verify_links
from .card_route import prepare_route_graph, persist_prepared_route
from .model_evidence import ModelEvidence
from .model_plan import _resolve_sources
from .model_publication import _require_path_definitions
from .native_state import apply_state_command
from .proposal_binding import check_binding, scope_for
from .proposal_sources import read_reference
from .repository import FormationRepository


def user_directive(context, directive):
    request = context.input['current_request']
    if not isinstance(directive, dict) or directive['user_ref'] != request['message_ref']:
        raise ProgressInvalid('Route instruction must cite this user message')
    quote = directive['quote']
    content = request['content']
    if not quote.strip() or not isinstance(content, str) or quote not in content:
        raise ProgressInvalid('Route instruction quote is absent from the actual user message')
    return {'kind': 'MESSAGE', 'message_id': request['message_id']}


@dataclass(frozen=True)
class DiscussionRoute:
    before: tuple
    plan: object
    links: tuple
    proposal: object
    focus_event: tuple | None
    directive: dict
    source: dict


def prepare_discussion_route(connection, root, context, delta, catalog):
    source = user_directive(context, delta['directive'])
    formation = context.canonical['formation']
    basis = formation['basis']
    document = root['assistant_document_id']
    head = FormationRepository(connection).head(document)
    revision = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
        (document, root['id']),
    ).fetchone()
    if (
        head is None
        or revision is None
        or basis != delta['basis']
        or head['version'] != basis['formation_version']
        or head['goal_version'] != basis['goal_version']
        or revision['revision_id'] != basis['document_revision_id']
        or revision['content_version'] != basis['content_version']
    ):
        raise ProgressInvalid('The route or document changed after acceptance')
    proposal = None
    evidence = ModelEvidence(connection, root, context, catalog)
    if delta['intent'] == 'ADOPT':
        candidate = formation['route_context']['previous_proposal']
        if candidate is None or (delta['proposal_ref'], delta['payload_digest']) != (
            candidate['proposal_ref'],
            candidate['payload_digest'],
        ):
            raise ProgressInvalid('Adoption needs the unique preceding route proposal')
        proposal = read_reference(
            connection, root, candidate['proposal_ref'], purpose='FORMATION_PATH_CHANGE'
        )
        if (
            proposal.disposition != 'PENDING'
            or proposal.needs_revision
            or proposal.binding['payload_digest'] != candidate['payload_digest']
        ):
            raise ProgressInvalid('The original proposal is no longer pending')
        check_binding(connection, root, proposal, 'FORMATION_PATH_CHANGE', catalog)
        payload = proposal.payload
        focus = delta.get('focus', {'mode': 'KEEP', 'step_ref': None})
    elif delta['intent'] == 'RESTORE_ORDER':
        from .order_restore import restore_changes

        candidate = formation['route_context']['previous_order']
        if not candidate or candidate['batch_id'] != delta['batch_id']:
            raise ProgressInvalid('The selected order batch is absent')
        payload = {'changes': restore_changes(connection, document, candidate), 'result_routes': []}
        focus = delta['focus']
    else:
        payload = deepcopy(delta)
        _resolve_sources(payload, evidence)
        focus = payload['focus']
    if not payload['changes'] and (payload['result_routes'] or focus['mode'] == 'KEEP'):
        raise ProgressInvalid('Empty route instruction')
    before, plan = prepare_route_graph(
        connection, root, payload['changes'], payload['result_routes']
    )
    for dependent, prerequisite in plan.dependencies:
        later, earlier = plan.steps[dependent], plan.steps[prerequisite]
        if (
            'CANCELLED' in (later['status'], earlier['status'])
            or later['position'] > earlier['position']
        ):
            continue
        old = before[1]
        if (
            (dependent, prerequisite) not in before[5]
            or dependent not in old
            or prerequisite not in old
            or old[dependent]['position'] > old[prerequisite]['position']
        ):
            raise ProgressInvalid('The new order puts a step before its prerequisite')
    declared = set(plan.scope.declared_steps)
    if proposal is None and delta['intent'] != 'RESTORE_ORDER':
        for ref in scope_for('FORMATION_PATH_CHANGE', payload)['step_refs']:
            evidence.require_visible('STEP', ref, newly_declared=declared, full=False)
        _require_path_definitions(evidence, plan, declared)
        for change in plan.changes:
            for kind, name in (('ISSUE', 'issue_ref'), ('BRANCH', 'branch_ref')):
                if name in change:
                    evidence.require_visible(kind, change[name])
        visible = {
            block['block_id']
            for doc in context.input['documents']
            if doc['document_id'] == document
            and doc['revision_id'] == basis['document_revision_id']
            for block in doc['blocks']
        }
        if any(not set(link['block_ids']) <= visible for link in plan.links):
            raise ProgressInvalid('Content association addresses unread document blocks')
    links = verify_links(connection, root, plan.links, catalog) if plan.links else ()
    mode = focus['mode']
    target = focus['step_ref']
    original_focus = head['current_step_ref']
    if mode == 'KEEP' and original_focus and plan.steps[original_focus]['status'] == 'CANCELLED':
        replacements = {
            new
            for new, old in plan.replacements
            if old == original_focus and plan.steps[new]['status'] != 'CANCELLED'
        }
        if len(replacements) != 1:
            raise ProgressInvalid(
                'Removing the current step needs one explicit discussion destination'
            )
        target = replacements.pop()
        mode = 'STEP'
    focus_event = None
    if mode != 'KEEP':
        if target is not None:
            if proposal is None or 'focus' in delta:
                evidence.require_visible('STEP', target, newly_declared=declared)
            if target not in plan.steps or plan.steps[target]['status'] not in (
                'PLANNED',
                'PAUSED',
                'IN_PROGRESS',
            ):
                raise ProgressInvalid('Discussion target must be an active route step')
        status = None if target is None else plan.steps[target]['status']
        action = {'PLANNED': 'START_STEP', 'PAUSED': 'RESUME_STEP'}.get(status, 'SWITCH_STEP')
        mutation = apply_state_command(
            plan.head,
            plan.steps,
            plan.branches,
            plan.issues,
            {'action': action, 'step_ref': target},
            lambda: 1,
            dependencies=plan.dependencies,
            replacements=plan.replacements,
        )
        if mutation.changed:
            focus_event = (mutation.action, target or 'document')
            plan = replace(
                plan,
                head=mutation.head,
                steps=mutation.steps,
                branches=mutation.branches,
                issues=mutation.issues,
                changed=True,
            )
    return DiscussionRoute(before, plan, links, proposal, focus_event, delta['directive'], source)


def store_discussion_route(connection, root, prepared, assistant_id, run, transaction, at):
    proposal = prepared.proposal
    command = {
        'type': 'DISCUSSION_ROUTE',
        'user_message_id': prepared.source['message_id'],
        'quote': prepared.directive['quote'],
        'proposal': proposal.reference if proposal else None,
    }
    return persist_prepared_route(
        connection,
        root,
        prepared.before,
        prepared.plan,
        prepared.links,
        assistant_id,
        run['idempotency_key'],
        transaction,
        at,
        command=command,
        reason=prepared.directive['quote'][:1000],
        proposal=proposal,
        source_run_id=run['id'],
        focus_event=prepared.focus_event,
        sources=[prepared.source],
    )


def rejection_message(error, output=None):
    """Report a bounded domain reason without echoing model output or internal details."""
    from backend.app.shared.command_execution import Rejected
    from backend.app.shared.validation import InvalidInput

    if isinstance(output, dict):
        progress = output.get('progress_delta')
        delta = progress.get('formation_delta') if isinstance(progress, dict) else None
        if isinstance(delta, dict) and isinstance(delta.get('changes'), list):
            from .types import MAX_CHANGES, MAX_CHANGE_BYTES
            from backend.app.shared.json_canonical import canonical_input

            batch = {'changes': delta['changes'], 'result_routes': delta.get('result_routes', [])}
            if (
                len(batch['changes']) > MAX_CHANGES
                or len(canonical_input(batch).encode('utf-8')) > MAX_CHANGE_BYTES
            ):
                return '主线未修改。本次调整超出单批上限，请缩小调整范围。'
    if isinstance(error, InvalidInput):
        fields = error.errors
        if fields and fields[0].reason == 'TOO_LONG':
            return '主线未修改。本次调整超出单批上限，请缩小调整范围。'
        if fields and ('result' in fields[0].field or 'route' in fields[0].field):
            return '主线未修改。请明确原有成果由哪一步承接，再继续调整。'
    if isinstance(error, ProgressInvalid):
        explanations = {
            'The starting step is outside the proposed route': '指定的起始步骤不在本次主线中，请指出要先讨论哪一步。',
            'An unread database identity cannot grant model mutation authority': '本轮没有读到指定步骤或关联事项的完整依据，请点名要调整的步骤。',
            'The new order puts a step before its prerequisite': '调整后的顺序会把步骤放在它的前置步骤之前，请核对依赖关系。',
            'Removing the current step needs one explicit discussion destination': '移除当前步骤后有多种讨论去向，请指定下一步或选择讨论整份文档。',
            'Adoption needs the unique preceding route proposal': '无法唯一确定要采用的提案，请指出具体方案。',
            'The route or document changed after acceptance': '本轮依据已变化，请核对当前路线后再调整。',
        }
        reason = explanations.get(str(error))
        if reason:
            return '主线未修改。' + reason
    if isinstance(error, Rejected):
        if error.code == 'CAPACITY_EXHAUSTED':
            return '主线未修改。此次操作超出当前可处理的范围，请缩小调整范围。'
        reason = (error.details or {}).get('reason') if isinstance(error.details, dict) else None
        if (
            reason
            in ('PATH_CHANGED', 'PROPOSAL_BASIS_CHANGED', 'STEP_DEFINITION_CHANGED', 'GOAL_CHANGED')
            or error.code == 'CONTENT_VERSION_CONFLICT'
        ):
            return '主线未修改。原方案所依据的文档或步骤已更新，请核对当前主线。'
        if reason in (
            'TARGET_CHANGED',
            'INVALID_TRANSITION',
            'BRANCH_STATE_CHANGED',
            'BRANCH_RETURN_MISMATCH',
        ):
            return '主线未修改。指定步骤或支线的当前状态无法执行此次操作。'
    return '本轮进展未保存。系统未能核实完整操作及其依据，当前主线保留原状。'
