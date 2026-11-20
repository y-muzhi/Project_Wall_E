"""Only actual audited C07 creates a valid new-purpose proposal source."""

from copy import deepcopy
import json
import asyncio
from uuid import uuid4

from backend.app.guide.commands import create_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.messages.queries import list_messages
from backend.app.formation.commands import update_proposal
from backend.app.formation.proposal_binding import check_binding
from backend.app.formation.proposal_sources import read_reference
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_model_results import initialized, progress
from backend.tests.formation.test_v21_proposal_contracts import group
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute, output

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def write_group(context, *, initial=False):
    value = group()
    payload = value['action_payload']
    payload.update(
        document_revision_id=context.canonical['formation']['basis']['document_revision_id'],
        content_version=context.canonical['formation']['basis']['content_version'],
        source_refs=[context.input['current_request']['message_ref']],
    )
    if initial:
        payload.update(step_ref='new_step_1', result_refs=['new_result_1'])
    return value


def publish(workspace, monkeypatch, *, purpose='STAGED_WRITE', initial=False):
    offline_gate(monkeypatch)
    if not initial:
        with workspace[0].transaction(write=True) as connection:
            head(connection)
    body = request(workspace)
    body['target']['discussion_step_ref'] = None if initial else 's1'
    accepted(workspace, body)

    def returned(context):
        if purpose == 'STAGED_WRITE':
            value = initialized(context) if initial else output(context)
            value['cards'] = write_group(context, initial=initial)
        else:
            cards = group(purpose)
            cards['action_payload']['basis'] = deepcopy(context.canonical['formation']['basis'])
            cards['action_payload']['source_refs'] = [
                context.input['current_request']['message_ref']
            ]
            value = output(context, cards=cards)
        return value

    gateway = Gateway(returned)
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_FINISHED', result
    read = get_guide_run(workspace[0], 1, catalog=workspace[2])
    assert read['code'] == 'READ_OK', read
    assert read['data']['effect_state'] == 'APPLIED', read
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    last = messages['data']['items'][-1]
    assert last['structured_content'] is not None and last['card_state'] == 'AVAILABLE', last
    return last, gateway


def test_initialization_binds_real_created_steps_without_changing_exact_markdown(
    workspace, monkeypatch
):
    message, gateway = publish(workspace, monkeypatch, initial=True)
    payload = message['structured_content']['action_payload']
    assert payload['step_ref'] == 's1' and payload['result_refs'] == ['s1.o1']
    assert payload['markdown_content'] == group()['action_payload']['markdown_content']
    assert gateway.calls[0].canonical['formation']['basis']['formation_version'] is None
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        proposal = read_reference(
            connection,
            root,
            {'message_id': message['id'], 'card_key': 'c1'},
            purpose='STAGED_WRITE',
        )
        check_binding(connection, root, proposal, 'STAGED_WRITE', workspace[2])
        assert proposal.binding['origin_frozen_formation_version'] is None
        assert root['discussion_version'] == 3
        assert connection.execute('SELECT version FROM formation_heads').fetchone()[0] == 1
        assert (
            connection.execute(
                'SELECT markdown_content FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
            == ''
        )


def test_path_publishes_symbols_without_allocating_future_objects(workspace, monkeypatch):
    message, _ = publish(workspace, monkeypatch, purpose='FORMATION_PATH_CHANGE')
    with workspace[0].transaction() as connection:
        head_row = connection.execute('SELECT * FROM formation_heads').fetchone()
        assert head_row['next_step_no'] == 2 and head_row['version'] == 3
        assert connection.execute('SELECT count(*) FROM formation_steps').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM formation_results').fetchone()[0] == 1
        proposal = connection.execute('SELECT * FROM formation_proposal_index').fetchone()
        assert proposal['disposition'] == 'PENDING'
    payload = message['structured_content']['action_payload']
    assert payload['changes'][0]['temp_step_ref'] == 'new_step_1'
    assert payload['changes'][0]['expected_results'][0]['temp_result_ref'] == 'new_result_1'


def test_later_unrelated_discussion_does_not_expire_original_binding(workspace, monkeypatch):
    message, _ = publish(workspace, monkeypatch)
    result = accepted(workspace, request(workspace))
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.tests.guide.test_v15_execution import PROFILE
    from backend.tests.guide.test_v15_counting import Counter

    finished = asyncio.run(
        execute_guide_run(
            workspace[0],
            {'guide_run_id': result['data']['guide_run_id']},
            process_lock=workspace[1].process_lock,
            catalog=workspace[2],
            profile=PROFILE,
            gateway=Gateway(output),
            counting_counter=Counter(['OK']),
        )
    )
    assert finished['code'] == 'AI_FINISHED', finished
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    old = next(item for item in messages['data']['items'] if item['id'] == message['id'])
    assert old['card_state'] == 'AVAILABLE'
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 2


def test_real_write_defer_resume_and_idempotent_replay_keep_original_binding(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch)
    with workspace[0].transaction() as connection:
        original = connection.execute(
            'SELECT binding_json FROM formation_proposal_index'
        ).fetchone()[0]
    for action in ('DEFER_WRITE_PROPOSAL', 'RESUME_WRITE_PROPOSAL'):
        with workspace[0].transaction() as connection:
            root = RequirementRepository(connection).get_for_document(1, 1)
        command = {
            'requirement_id': 1,
            'document_id': 1,
            'expected_discussion_version': root['discussion_version'],
            'discussion_command': {
                'type': 'FORMATION',
                'action': action,
                'proposal': {'message_id': message['id'], 'card_key': 'c1'},
                **({'reason': '暂不采用'} if action == 'DEFER_WRITE_PROPOSAL' else {}),
            },
            'idempotency_key': str(uuid4()),
        }
        result = update_proposal(workspace[1], command, catalog=workspace[2])
        assert result['code'] == 'UPDATED', result
        assert update_proposal(workspace[1], command, catalog=workspace[2]) == result
    with workspace[0].transaction() as connection:
        assert (
            connection.execute('SELECT binding_json FROM formation_proposal_index').fetchone()[0]
            == original
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1


def test_path_card_and_ordinary_delta_conflict_rejects_all_components(workspace, monkeypatch):
    offline_gate(monkeypatch)
    accepted(workspace, request(workspace))

    def returned(context):
        value = initialized(context)
        cards = group('FORMATION_PATH_CHANGE')
        value['cards'] = cards
        return value

    assert execute(workspace, Gateway(returned))['code'] == 'AI_FINISHED'
    with workspace[0].transaction() as connection:
        effect = json.loads(
            connection.execute('SELECT final_result_json FROM guide_runs').fetchone()[0]
        )
        assert effect['effect_state'] == 'STRUCTURED_REJECTED'
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert (
            connection.execute('SELECT count(*) FROM formation_proposal_index').fetchone()[0] == 0
        )
