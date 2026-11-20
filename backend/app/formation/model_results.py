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


def persist_unit(connection, row, run, root, context, profile, catalog, at):
    require_write_transaction(connection)
    raw = json.loads(row['raw_response_json']) if row['raw_response_json'] is not None else None
    original = response_text(raw)
    if original is None:
        raise Rejected('OUTPUT_INVALID')
    assistant_id = entity_id(connection, EntityKind.MESSAGE)
    parsed = None
    plan = None
    stored_cards = None
    publication = None
    discussion = root['discussion_state_json']
    progress_result = formation_result = proposal_result = 'NOT_APPLICABLE'
    error = None
    component_errors = []
    transaction = FormationTransaction(
        connection, root, FormationRepository(connection).head(root['assistant_document_id'])
    )
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
        parsed = catalog.collaboration.validate(
            'OutputDiscussion', json.loads(row['parsed_output_json'])
        )
        if parsed['basis_ref'] != context.input['current_request']['basis_ref']:
            raise ValueError('Discussion output differs from its actual accepted basis')
        progress = parsed['progress_delta']
        mapping = {}
        if progress is not None:
            discussion, mapping = apply_progress(
                discussion,
                progress,
                context,
                assistant_id,
                catalog.collaboration,
                return_mapping=True,
            )
            progress_result = (
                'APPLIED' if discussion != root['discussion_state_json'] else 'NO_CHANGE'
            )
            if progress['formation_delta'] is not None:
                plan = prepare_model(
                    connection, root, context, progress['formation_delta'], catalog
                )
                formation_result = 'APPLIED' if plan.changed else 'NO_CHANGE'
        if parsed['cards'] is not None:
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
    except (ValueError, KeyError, TypeError, Rejected):
        error = '本轮结构、依据或实际用量未通过校验，未应用进展、主线或卡片。'
        component_errors = ['OUTPUT_INVALID']
        progress_result = formation_result = proposal_result = 'REJECTED'
        plan = stored_cards = publication = None
        discussion = root['discussion_state_json']

    MessageRepository(connection).create_assistant(
        assistant_id,
        root['id'],
        run['id'],
        original if error is not None else parsed['message'],
        stored_cards,
        at,
        document_id=run['document_id'],
        phase_ref=None,
        topic_refs=()
        if discussion['focus_topic_ref'] is None
        else (discussion['focus_topic_ref'],),
        document_ids=(root['assistant_document_id'],),
    )
    formation_effect = None
    if error is None:
        if discussion != root['discussion_state_json']:
            RequirementRepository(connection).update_discussion(root, discussion, at)
        if plan is not None:
            formation_effect = store_model(
                connection, root, plan, run, assistant_id, row['id'], at, transaction=transaction
            )
        if publication is not None:
            from .model_publication import store_publication

            store_publication(
                connection, root, context, assistant_id, publication, catalog, transaction, at
            )
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
