"""C06 whole-group formal answers: one new round or one program action."""

from copy import deepcopy
import json

from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.messages.cards import (
    decode_cards,
    validate_responses,
    formal_answer_text,
    CardsInvalid,
)
from backend.app.messages.queries import card_state
from backend.app.messages.contracts import program_receipt
from backend.app.requirements.discussion import apply_user_command
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput, reject
from .contracts import submit_card_responses_input, create_guide_run_input


def _invalid(message):
    try:
        reject('responses', 'INVALID_FORMAT', message)
    except InvalidInput as error:
        raise Rejected('INVALID_INPUT', details=error.details) from None


def submit(executor, payload, *, catalog=None, clock=None):
    try:
        request = submit_card_responses_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    resources = catalog or ResourceCatalog()

    def operation(connection):
        messages, roots = MessageRepository(connection), RequirementRepository(connection)
        original = messages.get(request.message_id)
        if original is None:
            raise Rejected('NOT_FOUND')
        if (
            original['role'] != 'ASSISTANT'
            or original['message_type'] != 'INTERACTION_CARDS'
            or original['guide_run_id'] is None
        ):
            raise Rejected('SOURCE_INVALID')
        root = roots.get(original['requirement_id'])
        if root is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
        replies = messages.formal_responses(original['id'])
        if replies:
            raise Rejected(
                'CARD_ALREADY_ANSWERED', details={'response_message_id': replies[0]['id']}
            )
        if root['discussion_version'] != request.expected_discussion_version:
            raise Rejected(
                'DISCUSSION_VERSION_CONFLICT',
                details={
                    'expected_version': request.expected_discussion_version,
                    'actual_version': root['discussion_version'],
                    'resource_kind': 'Requirement',
                    'resource_id': root['id'],
                },
            )
        assert_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
        cards = decode_cards(original['structured_content_json'], resources.collaboration)
        if card_state(messages, root, original, resources.collaboration, resources) != 'AVAILABLE':
            raise Rejected('CARD_EXPIRED')
        try:
            answers = validate_responses(request.answers, cards, resources.collaboration)
        except (CardsInvalid, ProtocolInvalid):
            _invalid('回答必须准确覆盖整组卡片，并满足原问题的选项、数量和必答要求')
        purpose = cards['purpose']
        selection = answers['execution_selection']
        at = operation_time(clock)
        if at < max(root['updated_at'], original['created_at']):
            raise ValueError('Formal answer cannot precede its actual source')
        if purpose != 'DOCUMENT_ACTION' and selection is not None:
            _invalid('本组卡片不接受文档执行选择')
        if (
            purpose == 'CLARIFICATION'
            or purpose == 'DOCUMENT_ACTION'
            and answers['responses'][0]['selected_option_keys'] == ['accept']
        ):
            if purpose == 'DOCUMENT_ACTION':
                if selection is None:
                    _invalid('生成或更新前必须明确目标、范围及来源')
                payload = cards['action_payload']
                kind = payload['operation']
                target, scope, refs, ack = (
                    selection[field]
                    for field in ('target', 'scope', 'source_refs', 'acknowledge_source_changes')
                )
                proposal = {'message_id': original['id'], 'card_key': cards['cards'][0]['card_key']}
            else:
                kind = 'DISCUSS'
                binding = root['discussion_state_json']['binding']
                target = None
                if binding['target_document_id'] is not None:
                    current = DocumentRepository(connection).get_current(
                        root['id'], binding['target_document_id']
                    )
                    if current is None:
                        raise Rejected('SOURCE_INVALID')
                    target = {
                        'kind': 'EXISTING',
                        'document_id': current['id'],
                        'expected_content_version': current['content_version'],
                    }
                scope, refs, ack, proposal = binding['scope'], binding['source_refs'], False, None
            # This is a server-derived formal summary, not free-text C01 input;
            # it must not inherit the 10000-character instruction editor limit.
            from dataclasses import replace

            try:
                internal = create_guide_run_input(
                    {
                        'requirement_id': root['id'],
                        'expected_discussion_version': request.expected_discussion_version,
                        'operation': kind,
                        'instruction': '正式卡片回答',
                        'target': target,
                        'scope': scope,
                        'source_refs': refs,
                        'proposal_ref': proposal,
                        'acknowledge_source_changes': ack,
                        'idempotency_key': request.idempotency_key,
                    }
                )
            except InvalidInput as error:
                raise Rejected('INVALID_INPUT', details=error.details) from None
            internal = replace(internal, instruction=formal_answer_text(cards, answers))
            from .commands import _accept_collaboration

            data = _accept_collaboration(
                connection,
                internal,
                resources,
                at,
                parent=original['guide_run_id'],
                formal_answer={'original': original, 'answers': answers},
            )
            return Success({'code': 'CARDS_ACCEPTED', 'data': data, 'details': None}, 202)
        # Program actions have a real USER answer and no manufactured Run/LLM.
        response_id = entity_id(connection, EntityKind.MESSAGE)
        response = messages.create_card_response(
            response_id,
            root['id'],
            None,
            original,
            formal_answer_text(cards, answers),
            answers,
            request.idempotency_key,
            at,
            phase_ref=root['discussion_state_json']['phase']['phase_ref'],
            topic_refs=()
            if root['discussion_state_json']['focus_topic_ref'] is None
            else (root['discussion_state_json']['focus_topic_ref'],),
        )
        state = deepcopy(root['discussion_state_json'])
        result = 'DEFERRED'
        effect = None
        closed_phase = None
        action = answers['responses'][0]['selected_option_keys']
        if purpose == 'PHASE_CHANGE' and action == ['accept']:
            payload = cards['action_payload']
            command = {
                'type': 'CHANGE_PHASE',
                'phase_kind': payload['phase_kind'],
                'closure_message': payload['closure_summary'],
                'unresolved_refs': payload['unresolved_refs'],
            }
            state, closed_phase = apply_user_command(
                connection, root, command, response_id, resources
            )
            result = 'APPLIED' if state != root['discussion_state_json'] else 'NO_CHANGE'
        elif purpose == 'FACT_CONFIRMATION' and action == ['confirm']:
            from .fact_confirmation import apply_confirmed_action

            effect = apply_confirmed_action(
                connection, root, original, response, cards, resources, request.idempotency_key, at
            )
            result = 'NO_CHANGE' if effect['result'] == 'NO_CHANGE' else 'APPLIED'
        elif action == ['defer']:
            state['dispositions'].append(
                {
                    'kind': 'REJECT_DRAFT' if purpose == 'DOCUMENT_ACTION' else 'DEFER',
                    'scope_refs': ['m' + str(original['id']) + ':' + cards['cards'][0]['card_key']],
                    'message_id': response_id,
                    'summary': '用户暂不生成或更新文档'
                    if purpose == 'DOCUMENT_ACTION'
                    else '用户暂缓本次行动建议',
                }
            )
            state['last_step'] = None
        else:
            _invalid('行动卡片必须使用其明确的确认或暂缓选项')
        # The fact operation may temporarily use an existing internal editing
        # session; reread its released root before persisting discussion values.
        root = roots.get(root['id'])
        before = root
        if state != root['discussion_state_json']:
            root = roots.update_discussion(root, state, at)
        receipt = program_receipt(
            {
                'processing': 'PROGRAM',
                'user_message_id': response_id,
                'requirement_id': root['id'],
                'discussion_version': root['discussion_version'],
                'purpose': purpose,
                'result': result,
                'document_effect': effect,
            }
        )
        # This normal audit is tied to the actual formal answer. The immutable
        # idempotency success also supplies MessageView.program_receipt.
        payload = {
            'message_id': response_id,
            'source_message_id': original['id'],
            'program_receipt': receipt,
            'discussion_version_before': before['discussion_version'],
            'discussion_version_after': root['discussion_version'],
            'phase_before': closed_phase or before['discussion_state_json']['phase'],
            'phase_after': root['discussion_state_json']['phase'],
            'idempotency_key': request.idempotency_key,
        }
        event = 'PHASE_CHANGED' if closed_phase is not None else 'DISCUSSION_UPDATED'
        connection.execute(
            "INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,NULL,'USER_ACTION',?,'CARD_PROGRAM_ACTION',NULL,NULL,?,?,NULL,NULL,?)",
            (
                entity_id(connection, EntityKind.DOCUMENT_AUDIT),
                root['id'],
                response_id,
                at,
                event,
                canonical_input(payload),
            ),
        )
        return Success({'code': 'PROGRAM_PROCESSED', 'data': receipt, 'details': None}, 200)

    return execute_idempotent(
        executor,
        'APP-GUIDE-CMD-C06',
        request,
        operation,
        target_identity='Message:' + str(request.message_id),
        allowed_failures=frozenset(
            {
                'INVALID_INPUT',
                'NOT_FOUND',
                'STATE_CONFLICT',
                'SOURCE_INVALID',
                'SCOPE_INVALID',
                'CARD_ALREADY_ANSWERED',
                'CARD_EXPIRED',
                'WORK_STATE_CONFLICT',
                'WORK_STATE_INCONSISTENT',
                'DISCUSSION_VERSION_CONFLICT',
                'CONTENT_VERSION_CONFLICT',
                'SOURCE_VERSION_CONFLICT',
                'TARGET_STALE',
                'CONFIG_INVALID',
            }
        ),
    )
