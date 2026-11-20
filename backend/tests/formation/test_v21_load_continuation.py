"""1001 real steps and 10001 real state events keep continuation and bounded reads valid."""

from time import monotonic

from backend.app.formation.commands import update_state
from backend.app.formation.history_queries import read_history
from backend.app.formation.read_queries import read_entities
from backend.app.guide.queries import get_guide_run
from backend.app.messages.queries import list_messages
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_discuss_acceptance import (
    accepted,
    base_workspace,
    database,
    released,
    request,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import write_group
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.formation.test_v21_real_growth_continuation import route
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def test_1001_steps_10001_actual_events_continue_exact_write_with_frozen_history(
    workspace, monkeypatch
):
    offline_gate(monkeypatch)
    started = monotonic()
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    for batch in range(50):
        changes = [add_step(number + 1) for number in range(20)]
        for index, change in enumerate(changes):
            change['title'] = '负载步骤' + str(batch * 20 + index + 2)
        route(workspace, 1, changes)
    prior = read_history(workspace[0], 1, 1, 'events', {'limit': 20})
    assert prior['code'] == 'READ_OK', prior
    initial_events = prior['data']['value']['total']
    for index in range(10001):
        action = 'START_STEP' if index == 0 else 'PAUSE_STEP' if index % 2 else 'RESUME_STEP'
        response = update_state(workspace[1], payload(workspace, action, step_ref='s1'))
        assert response['code'] == 'UPDATED', response
        if index % 1000 == 0:
            print('ACTUAL_EVENT_PROGRESS', index + 1, round(monotonic() - started, 3), flush=True)
    baseline = read_history(workspace[0], 1, 1, 'events', {'limit': 20})
    assert baseline['code'] == 'READ_OK', baseline
    total = baseline['data']['value']['total']
    upper = baseline['data']['value']['upper_event_id']
    assert total == initial_events + 10001
    steps = read_entities(workspace[0], 1, 1, 'steps', {'limit': 20}, catalog=workspace[2])
    assert steps['code'] == 'READ_OK', steps
    assert steps['data']['value']['total'] == 1001
    assert len(steps['data']['value']['items']) == 20

    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1001'
    initial = accepted(workspace, body)

    def returned(context):
        cards = write_group(context)
        cards['action_payload'].update(step_ref='s1001', result_refs=['s1001.o1'])
        assert context.canonical['formation']['selected_step']['step_ref'] == 's1001'
        assert len(context.canonical['formation']['coverage']['included']) <= 100
        assert isinstance(context.input['recent_history'], list)
        assert len(context.input['recent_history']) <= 10
        return output(context, cards=cards)

    gateway = Gateway(returned)
    assert run_round(workspace, initial['data']['guide_run_id'], gateway)['code'] == 'AI_FINISHED'
    run = get_guide_run(workspace[0], initial['data']['guide_run_id'], catalog=workspace[2])
    assert run['data']['status'] == 'COMPLETED' and run['data']['effect_state'] == 'APPLIED', run
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    card = messages['data']['items'][-1]
    assert card['card_state'] == 'AVAILABLE', card
    command = answer(workspace, card)
    applied = submit(workspace, command)
    assert applied['code'] == 'PROGRAM_PROCESSED', applied
    assert submit(workspace, command) == applied
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                'SELECT content_version FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1

    ids = [row['event_id'] for row in baseline['data']['value']['items']]
    cursor = baseline['data']['pagination']['next_cursor']
    pages = 1
    while cursor:
        page = read_history(workspace[0], 1, 1, 'events', {'limit': 20, 'cursor': cursor})
        assert page['code'] == 'READ_OK', page
        data = page['data']
        assert data['value']['total'] == total and data['value']['upper_event_id'] == upper
        assert len(data['value']['items']) <= 20
        ids.extend(row['event_id'] for row in data['value']['items'])
        cursor = data['pagination']['next_cursor']
        pages += 1
    assert len(ids) == len(set(ids)) == total and max(ids) == upper
    fresh = read_history(workspace[0], 1, 1, 'events', {'limit': 20})
    assert fresh['data']['value']['total'] > total
    assert fresh['data']['value']['upper_event_id'] > upper
    print('ACTUAL_1001_10001_PASS', total, pages, round(monotonic() - started, 3), flush=True)
