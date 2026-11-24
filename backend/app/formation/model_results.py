"""One audited DISCUSS return applies all structured components together or none."""

import json

from backend.app.guide.progress_application import apply_progress
from backend.app.guide.response_display import response_text
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.practical_usage import validate_collaboration_usage
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input

from .model_plan import prepare_model
from .model_storage import store_model
from .repository import FormationRepository
from .transaction import FormationTransaction


def persist_unit(connection, row, run, root, context, profile, catalog, at, attempt):
    require_write_transaction(connection)
    raw = json.loads(row['raw_response_json']) if row['raw_response_json'] is not None else None
    original = response_text(raw)
    if original is None:
        raise Rejected('OUTPUT_INVALID')
    assistant_id = entity_id(connection, EntityKind.MESSAGE)
    parsed = None
    candidate = None
    plan = None
    route = lifecycle = None
    intent = None
    stored_cards = None
    publication = None
    discussion = root['discussion_state_json']
    progress_result = formation_result = proposal_result = 'NOT_APPLICABLE'
    error = None
    component_errors = []
    decision_links = []
    clarification = None
    transaction = FormationTransaction(
        connection, root, FormationRepository(connection).head(root['assistant_document_id'])
    )

    def save_message(text, cards):
        focus = discussion['focus_topic_ref']
        MessageRepository(connection).create_assistant(
            assistant_id,
            root['id'],
            run['id'],
            text,
            cards,
            at,
            document_id=run['document_id'],
            phase_ref=None,
            topic_refs=() if focus is None else (focus,),
            document_ids=(root['assistant_document_id'],),
        )

    formation_effect = None
    try:
        validate_collaboration_usage(
            raw,
            profile=profile,
            context=context,
            catalog=catalog,
            input_tokens=row['input_tokens'],
            output_tokens=row['output_tokens'],
        )
        if (row['call_status'], row['parse_status'], row['finish_reason']) != (
            'SUCCEEDED',
            'SUCCEEDED',
            'stop',
        ):
            raise ValueError('A normal complete audited return is required')
        candidate = json.loads(row['parsed_output_json'])
        parsed = catalog.collaboration.validate('OutputDiscussion', candidate)
        if parsed['basis_ref'] != context.input['current_request']['basis_ref']:
            raise ValueError('Discussion output differs from its actual accepted basis')
        progress = parsed['progress_delta']
        mapping = {}
        if progress is not None:
            discussion, mapping = apply_progress(
                discussion,
                {k: v for k, v in progress.items() if k != 'step_evidence_links'},
                context,
                assistant_id,
                catalog.collaboration,
                return_mapping=True,
            )
            progress_result = (
                'APPLIED' if discussion != root['discussion_state_json'] else 'NO_CHANGE'
            )
            if progress['formation_delta'] is not None:
                delta = progress['formation_delta']
                intent = delta.get('intent')
                if intent in ('SUGGEST_INITIAL', 'ADOPT_INITIAL', 'CREATE_INITIAL'):
                    from .initial_suggestion import initial_plan

                    initial = initial_plan(connection, root, context, delta, catalog)
                    if intent in ('ADOPT_INITIAL', 'CREATE_INITIAL'):
                        plan = initial
                        formation_result = 'APPLIED'
                    else:
                        formation_result = 'NO_CHANGE'
                elif intent == 'LIFECYCLE':
                    from .discussion_lifecycle import prepare

                    lifecycle = prepare(connection, root, context, delta, catalog, transaction)
                elif intent is not None:
                    from .discussion_route import prepare_discussion_route

                    route = prepare_discussion_route(connection, root, context, delta, catalog)
                    formation_result = (
                        'APPLIED' if route.plan.changed or route.proposal else 'NO_CHANGE'
                    )
                else:
                    if catalog.collaboration.discussion_routes:
                        from .discussion_route import user_directive

                        structural = {
                            'INITIALIZE_PATH',
                            'ADD_STEP',
                            'UPDATE_STEP',
                            'MOVE_STEP',
                            'SET_BRANCH_FOCUS',
                        }
                        if catalog.collaboration.route_lifecycle and not any(
                            item['type'] == 'INITIALIZE_PATH' for item in delta['changes']
                        ):
                            if any(
                                item['type'] in ('ADD_STEP', 'MOVE_STEP')
                                or item['type'] == 'UPDATE_STEP'
                                and (
                                    item['title'] is not None
                                    or item['add_results']
                                    or item['dependencies'] is not None
                                )
                                for item in delta['changes']
                            ):
                                raise ValueError(
                                    'Use the complete route planner for existing structural changes'
                                )
                        if 'directive' in delta or any(
                            item['type'] in structural for item in delta['changes']
                        ):
                            user_directive(context, delta.get('directive'))
                    plan = prepare_model(
                        connection,
                        root,
                        context,
                        {k: v for k, v in delta.items() if k != 'directive'},
                        catalog,
                    )
                    formation_result = 'APPLIED' if plan.changed else 'NO_CHANGE'
        if parsed['cards'] is not None:
            if intent is not None:
                raise ValueError('A route instruction and proposal cannot share a round')
            from .model_publication import prepare_publication

            stored_cards, publication = prepare_publication(
                connection,
                root,
                run,
                context,
                parsed['cards'],
                catalog,
                plan=plan,
                reference_map=mapping,
                discussion=discussion,
            )
            proposal_result = 'APPLIED'
        save_message(parsed['message'], stored_cards)
        if discussion != root['discussion_state_json']:
            RequirementRepository(connection).update_discussion(root, discussion, at)
        if plan is not None:
            formation_effect = store_model(
                connection, root, plan, run, assistant_id, row['id'], at, transaction=transaction
            )
        if route is not None:
            from .discussion_route import store_discussion_route

            formation_effect = store_discussion_route(
                connection, root, route, assistant_id, run, transaction, at
            )
        if lifecycle is not None:
            from .discussion_lifecycle import store

            formation_effect = store(
                connection, root, lifecycle, run, assistant_id, catalog, transaction, at
            )
            formation_result = formation_effect['result']
        if progress is not None and progress.get('step_evidence_links'):
            from .decision_links import bind_links

            decision_links = bind_links(
                connection,
                root,
                context,
                catalog,
                progress['step_evidence_links'],
                discussion,
                mapping,
                formation_effect,
            )
            if decision_links:
                if transaction.root()['discussion_version'] == root['discussion_version']:
                    RequirementRepository(connection).advance_discussion(root, at)
                progress_result = 'APPLIED'
        if publication is not None:
            from .model_publication import store_publication

            store_publication(
                connection, root, context, assistant_id, publication, catalog, transaction, at
            )
    except (ValueError, KeyError, TypeError, Rejected) as failure:
        attempt.rollback()
        assistant_id = entity_id(connection, EntityKind.MESSAGE)
        discussion = root['discussion_state_json']
        formation_effect = None
        error = '本轮结构、依据或实际用量未通过校验，未应用进展、主线或卡片。'
        if catalog.collaboration.discussion_routes:
            from .discussion_route import rejection_message

            error = rejection_message(failure, candidate)
            from backend.app.shared.validation import InvalidInput

            if isinstance(failure, InvalidInput) and any(
                field.field == 'result_routes' for field in failure.errors
            ):
                clarification = {
                    'user_message_id': run['trigger_message_id'],
                    'discussion_version': root['discussion_version'],
                    'basis': context.canonical['formation']['basis'],
                }
        component_errors = ['OUTPUT_INVALID']
        progress_result = formation_result = proposal_result = 'REJECTED'
        save_message(error if catalog.collaboration.discussion_routes else original, None)
    effects = {
        'summary': '模型返回已保存；本轮结构未应用。' if error else parsed['message'][:10000],
        'assistant_message_id': assistant_id,
        'application_result': 'NOT_REQUESTED',
        'progress_result': progress_result,
        'progress_error': error,
        'document_effect': None,
        'suggestion_batch_id': None,
        'analysis': None,
        'validation_error': error,
        'effect_state': 'STRUCTURED_REJECTED' if error else 'APPLIED',
        'formation_result': formation_result,
        'proposal_result': proposal_result,
        'component_errors': component_errors,
        'accepted_target': context.canonical['formation_selection'],
        'formation_effect': formation_effect,
    }
    if clarification:
        effects['route_clarification'] = clarification
    if decision_links and error is None:
        effects['step_evidence_links'] = decision_links
    if row['parse_status'] == 'SUCCEEDED':
        connection.execute(
            'UPDATE llm_uses SET validation_status=?,validation_error=?,trusted_output_json=?,error_code=?,error_message=? WHERE id=?',
            (
                'FAILED' if error else 'SUCCEEDED',
                error,
                None if error else audit_json(parsed, credentials=(profile.api_key,)),
                'OUTPUT_INVALID' if error else None,
                error,
                row['id'],
            ),
        )
    gate = connection.execute(
        "UPDATE guide_runs SET current_step='PERSISTING' WHERE id=? AND status='RUNNING' AND current_step IN ('VALIDATING','CALLING_MODEL')",
        (run['id'],),
    )
    if gate.rowcount != 1:
        raise Rejected('STATE_CONFLICT')
    connection.execute(
        "UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=? AND status='RUNNING' AND current_step='PERSISTING'",
        (canonical_input(effects), at, at, run['id']),
    )
    current_root = RequirementRepository(connection).get_for_document(
        root['id'], root['assistant_document_id']
    )
    RequirementRepository(connection).recover_occupancy(current_root, None, None, at)
    return {
        'code': 'AI_RESULT_PERSISTED',
        'data': {
            'guide_run_id': run['id'],
            'status': 'COMPLETED',
            'assistant_message_id': assistant_id,
        },
        'details': None,
    }
