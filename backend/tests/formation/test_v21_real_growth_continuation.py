"""Real route history beyond old cumulative thresholds continues C01/C07/C06 atomically."""

import json
from time import monotonic
from uuid import uuid4

from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.formation.commands import complete_step, update_path
from backend.app.formation.history_queries import read_history
from backend.app.formation.read_queries import read_entities
from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.messages.queries import list_messages
from backend.app.requirements.queries import get_requirement
from backend.tests.documents.test_patch_validation import patch
from backend.tests.formation.test_v21_artifact_links import link_input
from backend.tests.formation.test_v21_card_apply import submit
from backend.tests.formation.test_v21_complete_journey import frozen_closure
from backend.tests.formation.test_v21_completion_commands import request as complete_request
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
from backend.tests.formation.test_v21_path_commands import request as path_request
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_target_boundaries import all_facts
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def route(workspace, document, changes):
    result = update_path(
        workspace[1],
        path_request(workspace, changes, document_id=document),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    return result


def start_round(workspace, document, step):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    body = request(
        workspace, document_id=document, expected_discussion_version=root['discussion_version']
    )
    body['target']['discussion_step_ref'] = step
    return accepted(workspace, body)


def seed_real_growth(workspace):
    document = associated(workspace)
    # Real public program commands: no direct SQL insertion of history or artifacts.
    for offset in range(0, 200, 20):
        changes = [add_step(index + 1, ['s1']) for index in range(20)]
        for index, change in enumerate(changes):
            change['title'] = '步骤' + str(offset + index + 2)
        route(workspace, document, changes)
    with workspace[0].transaction() as connection:
        original = connection.execute(
            "SELECT * FROM formation_artifacts WHERE document_id=? AND artifact_ref='a1'",
            (document,),
        ).fetchone()
        link = link_input(connection, document, original['origin_revision_id'])
    for offset in range(0, 2000, 20):
        changes = []
        for index in range(20):
            owner = 's' + str(1 + (offset + index) // 10)
            changes.append(
                {
                    'type': 'LINK_CONTENT',
                    **link,
                    'step_ref': owner,
                    'result_refs': [owner + '.o1'],
                }
            )
        route(workspace, document, changes)
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                'SELECT count(*) FROM formation_steps WHERE document_id=?', (document,)
            ).fetchone()[0]
            == 201
        )
        assert (
            connection.execute(
                'SELECT count(*) FROM formation_artifacts WHERE document_id=?', (document,)
            ).fetchone()[0]
            == 2001
        )
        current = connection.execute(
            'SELECT * FROM requirement_documents WHERE id=?', (document,)
        ).fetchone()
        snapshot = validate_snapshot(
            current['markdown_content'],
            json.loads(current['block_state_json']),
            DocumentSources(connection, 1, workspace[2], document_id=document),
        )
        last_block = list(snapshot.by_id)[-1]
    # The last node is outside the first ten pages. It can still own an exact link.
    route(
        workspace,
        document,
        [
            {
                'type': 'LINK_CONTENT',
                'step_ref': 's201',
                'result_refs': ['s201.o1'],
                'revision_id': original['origin_revision_id'],
                'block_ids': [last_block],
            }
        ],
    )
    return document, snapshot


def test_real_201_steps_2001_artifacts_continue_discussion_exact_adoption_and_history(
    workspace, monkeypatch
):
    offline_gate(monkeypatch)
    started = monotonic()
    document, snapshot = seed_real_growth(workspace)
    before_reject = all_facts(workspace)
    cycle = update_path(
        workspace[1],
        path_request(
            workspace,
            [
                {
                    'type': 'SET_DEPENDENCIES',
                    'step_ref': 's1',
                    'dependencies': ['s201'],
                }
            ],
            document_id=document,
        ),
        catalog=workspace[2],
    )
    assert cycle['code'] == 'FORMATION_INVALID', cycle
    assert all_facts(workspace) == before_reject

    frozen = read_history(workspace[0], 1, document, 'events', {'limit': 20})
    assert frozen['code'] == 'READ_OK', frozen
    assert frozen['data']['value']['total'] > 100
    frozen_total = frozen['data']['value']['total']
    frozen_upper = frozen['data']['value']['upper_event_id']

    discussion = start_round(workspace, document, 's201')
    gateway = Gateway(output)
    assert (
        run_round(workspace, discussion['data']['guide_run_id'], gateway)['code'] == 'AI_FINISHED'
    )
    actual = get_guide_run(workspace[0], discussion['data']['guide_run_id'], catalog=workspace[2])
    assert actual['data']['status'] == 'COMPLETED' and actual['data']['effect_state'] == 'APPLIED'
    assert actual['data']['accepted_target']['discussion_step_ref'] == 's201'
    assert gateway.calls[0].canonical['formation']['selected_step']['step_ref'] == 's201'

    initial = start_round(workspace, document, 's1')
    first_block = list(snapshot.by_id)[0]
    precise = patch(
        snapshot,
        first_block,
        proposed=snapshot.by_id[first_block][0].markdown.rstrip() + ' 已补充\n',
    )

    def staged(context):
        cards = write_group(context)
        cards['action_payload'].update(
            write_mode='PATCH_EXISTING',
            markdown_content=None,
            patches=[precise],
            scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': first_block}},
        )
        return output(context, cards=cards)

    proposal_gateway = Gateway(staged)
    assert (
        run_round(workspace, initial['data']['guide_run_id'], proposal_gateway)['code']
        == 'AI_FINISHED'
    )
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': document}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    card = messages['data']['items'][-1]
    assert card['card_state'] == 'AVAILABLE', card
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    command = {
        'message_id': card['id'],
        'schema_version': 1,
        'expected_discussion_version': root['discussion_version'],
        'responses': [
            {
                'card_key': 'c1',
                'selected_option_keys': ['apply'],
                'custom_answer': None,
                'skipped': False,
            }
        ],
        'execution_selection': None,
        'idempotency_key': str(uuid4()),
    }
    applied = submit(workspace, command)
    assert applied['code'] == 'PROGRAM_PROCESSED', applied
    frozen_after_write = all_facts(workspace)
    assert submit(workspace, command) == applied
    assert all_facts(workspace) == frozen_after_write
    summary = get_requirement(workspace[0], 1, document_id=document, expand='discussion')
    assert summary['code'] == 'READ_OK', summary
    counts = summary['data']['discussion']['formation_summary']['counts']
    assert sum(counts['steps'].values()) == 201
    assert counts['pending_review_artifacts'] == 2001

    cursor = None
    seen = []
    pages = 0
    while True:
        page = read_entities(
            workspace[0],
            1,
            document,
            'artifacts',
            {'limit': 20, **({} if cursor is None else {'cursor': cursor})},
            catalog=workspace[2],
        )
        assert page['code'] == 'READ_OK', page
        value = page['data']['value']
        assert value['total'] == 2003 and len(value['items']) <= 20
        seen.extend(row['artifact_ref'] for row in value['items'])
        pages += 1
        cursor = page['data']['pagination']['next_cursor']
        if cursor is None:
            break
        assert pages <= 101
    assert pages == 101 and len(seen) == len(set(seen)) == 2003
    assert seen[-1] == 'a2003'

    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
        assert (
            connection.execute(
                'SELECT content_version FROM requirement_documents WHERE id=?', (document,)
            ).fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 2
        assert (
            connection.execute(
                'SELECT freshness FROM formation_artifacts '
                "WHERE document_id=? AND artifact_ref='a2002'",
                (document,),
            ).fetchone()[0]
            == 'CURRENT'
        )
    complete = complete_request(
        workspace,
        expected_content_version=2,
        result_dispositions=[
            {
                'result_ref': 's1.o1',
                'status': 'LANDED',
                'artifact_refs': ['a2003'],
                'source_refs': [],
            }
        ],
    )
    complete.update(document_id=document, expected_discussion_version=root['discussion_version'])
    completed = complete_step(workspace[1], complete, catalog=workspace[2])
    assert completed['code'] == 'UPDATED', completed
    closure = frozen_closure(workspace, completed['data']['event_ids'][0])
    assert closure['formation_closures']

    # Continue the original immutable event cursor after all later writes.
    old_ids = [row['event_id'] for row in frozen['data']['value']['items']]
    cursor = frozen['data']['pagination']['next_cursor']
    while cursor:
        page = read_history(workspace[0], 1, document, 'events', {'limit': 20, 'cursor': cursor})
        assert page['code'] == 'READ_OK', page
        assert page['data']['value']['upper_event_id'] == frozen_upper
        assert page['data']['value']['total'] == frozen_total
        old_ids.extend(row['event_id'] for row in page['data']['value']['items'])
        cursor = page['data']['pagination']['next_cursor']
    assert len(old_ids) == len(set(old_ids)) == frozen_total
    assert max(old_ids) <= frozen_upper
    assert len(gateway.calls) == len(proposal_gateway.calls) == 1
    print('REAL_GROWTH_201_2003', pages, round(monotonic() - started, 3), flush=True)


def test_required_current_artifact_overflow_keeps_single_request_guard_and_atomic_rollback(
    workspace, monkeypatch
):
    from backend.app.guide.commands import create_guide_run

    offline_gate(monkeypatch)
    document = associated(workspace)
    with workspace[0].transaction() as connection:
        revision = connection.execute(
            'SELECT origin_revision_id FROM formation_artifacts WHERE document_id=?',
            (document,),
        ).fetchone()[0]
        link = link_input(connection, document, revision)
    for _batch in range(5):
        route(workspace, document, [{'type': 'LINK_CONTENT', **link} for _ in range(20)])
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    body = request(
        workspace, document_id=document, expected_discussion_version=root['discussion_version']
    )
    body['target']['discussion_step_ref'] = 's1'
    before = all_facts(workspace)
    result = create_guide_run(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'CAPACITY_EXHAUSTED', result
    assert all_facts(workspace) == before
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
