"""Full manual route unit: actual user/event batch, D/F, state and original success receipt."""

from copy import deepcopy
import json
from uuid import uuid4

from backend.app.formation.commands import update_path, update_state
from backend.app.formation.repository import FormationRepository
from backend.app.formation import path_commands
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_artifact_links import material, link_input

__all__ = ['database', 'released', 'workspace']


def request(workspace, changes, *, document_id=1, routes=(), **overrides):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document_id)
        state = FormationRepository(connection).head(document_id, required=True)
        content_version = connection.execute(
            'SELECT content_version FROM requirement_documents WHERE id=?',
            (document_id,),
        ).fetchone()[0]
    return {
        'requirement_id': 1,
        'document_id': document_id,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'ADJUST_PATH',
            'expected_formation_version': state['version'],
            'expected_content_version': content_version,
            'based_on_proposal': None,
            'changes': changes,
            'result_routes': list(routes),
            'reason': '按完整成果范围调整形成路线',
            **overrides,
        },
        'idempotency_key': str(uuid4()),
    }


def seed(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)


def snapshot(db):
    with db.transaction() as connection:
        return {
            table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table}')]
            for table in (
                'requirements',
                'formation_heads',
                'formation_steps',
                'formation_results',
                'formation_step_edges',
                'formation_event_changes',
                'formation_event_members',
                'formation_event_refs',
                'document_change_audits',
                'conversation_messages',
                'requirement_documents',
                'revisions',
                'sequences',
            )
        }


def test_whole_route_freezes_one_real_batch_and_reference_map_in_declaration_order(workspace):
    seed(workspace)
    first, second = add_step(1), add_step(2, ['new_step_1'])
    original = request(
        workspace,
        [
            first,
            second,
            {'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '明确范围'},
            {'type': 'MOVE_STEP', 'step_ref': 's1', 'before_step_ref': 'new_step_2'},
        ],
    )
    result = update_path(workspace[1], original, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    receipt = result['data']
    assert receipt['discussion_version'] == receipt['formation_version'] == 2
    assert receipt['content_version'] == 1
    assert receipt['reference_map'] == [
        {'temp_ref': 'new_step_1', 'resolved_ref': 's2'},
        {'temp_ref': 'new_result_1', 'resolved_ref': 's2.o1'},
        {'temp_ref': 'new_step_2', 'resolved_ref': 's3'},
        {'temp_ref': 'new_result_2', 'resolved_ref': 's3.o1'},
    ]
    assert len(receipt['event_ids']) == 4
    with workspace[0].transaction() as connection:
        events = [
            json.loads(row['payload_json'])['event']
            for row in connection.execute(
                "SELECT * FROM document_change_audits WHERE json_extract(payload_json,'$.formation_event_type') IS NOT NULL ORDER BY id"
            )
        ]
        assert len({event['batch_ref'] for event in events}) == 1
        assert [event['ordinal'] for event in events] == [1, 2, 3, 4]
        assert all(event['batch_size'] == 4 and event['actor'] == 'USER' for event in events)
        assert all(
            event['version_before']['formation_version'] == 1
            and event['version_after']['formation_version'] == 2
            for event in events
        )
        facts = [
            tuple(row)
            for row in connection.execute(
                'SELECT entity_kind,entity_ref FROM formation_event_changes'
            )
        ]
        assert len(facts) == len(set(facts))
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT step_ref,position FROM formation_steps ORDER BY position'
            )
        ] == [('s2', 1), ('s1', 2), ('s3', 3)]
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2
    frozen = snapshot(workspace[0])
    assert update_path(workspace[1], original, catalog=workspace[2]) == result
    assert snapshot(workspace[0]) == frozen


def test_manual_f_v_conflicts_and_missing_proposal_never_allocate_or_change_business(workspace):
    seed(workspace)
    before = snapshot(workspace[0])
    for overrides, code in [
        ({'expected_formation_version': 2}, 'STATE_CONFLICT'),
        ({'expected_content_version': 2}, 'CONTENT_VERSION_CONFLICT'),
        ({'based_on_proposal': {'message_id': 999, 'card_key': 'original'}}, 'SOURCE_INVALID'),
    ]:
        body = request(workspace, [add_step()], **overrides)
        result = update_path(workspace[1], body, catalog=workspace[2])
        assert result['code'] == code, result
        assert snapshot(workspace[0]) == before


def test_path_history_failure_rolls_back_all_ids_rank_state_message_d_f_and_receipt(
    workspace, monkeypatch
):
    seed(workspace)
    before = snapshot(workspace[0])
    body = request(workspace, [add_step()])
    original = path_commands.write_facts

    def fail(*args, **kwargs):
        raise RuntimeError('injected final history failure')

    monkeypatch.setattr(path_commands, 'write_facts', fail)
    assert update_path(workspace[1], body, catalog=workspace[2])['code'] == 'INTERNAL_ERROR'
    assert snapshot(workspace[0]) == before
    monkeypatch.setattr(path_commands, 'write_facts', original)
    assert update_path(workspace[1], body, catalog=workspace[2])['code'] == 'UPDATED'


def test_cancel_keeps_positive_immutable_history_and_returns_real_result_routes(workspace):
    seed(workspace)
    body = request(
        workspace,
        [
            add_step(),
            {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
        ],
        routes=[
            {
                'from_result_ref': 's1.o1',
                'disposition': 'REPLACED',
                'target_result_refs': ['new_result_1'],
                'reason': '后续步骤承接完整成果要求',
            }
        ],
    )
    result = update_path(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                "SELECT position FROM formation_steps WHERE step_ref='s1'"
            ).fetchone()[0]
            < 0
        )
        _, steps, _, _, _ = FormationRepository(connection).graph(1)
        assert steps['s1']['position'] == 1
        assert steps['s1']['status'] == 'CANCELLED'
        route = connection.execute(
            "SELECT after_json FROM formation_event_changes WHERE entity_kind='RESULT_ROUTE'"
        ).fetchone()[0]
        assert json.loads(route)['target_result_refs'] == ['s2.o1']


def test_native_and_path_actions_advance_d_without_rewriting_old_discussion_bytes(workspace):
    seed(workspace)
    with workspace[0].transaction(write=True) as connection:
        state = connection.execute(
            'SELECT discussion_state_json FROM requirement_documents WHERE id=1'
        ).fetchone()[0]
        # Still a valid original discussion; physical whitespace is preserved by formation operations.
        original = json.dumps(json.loads(state), ensure_ascii=False, indent=2)
        connection.execute(
            'UPDATE requirement_documents SET discussion_state_json=? WHERE id=1', (original,)
        )
    body = request(workspace, [{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '真实范围'}])
    result = update_path(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    native = deepcopy(body)
    native['idempotency_key'] = str(uuid4())
    native['expected_discussion_version'] = result['data']['discussion_version']
    native['discussion_command'] = {'type': 'FORMATION', 'action': 'START_STEP', 'step_ref': 's1'}
    assert update_state(workspace[1], native)['code'] == 'UPDATED'
    with workspace[0].transaction() as connection:
        row = connection.execute(
            'SELECT discussion_state_json,discussion_version FROM requirement_documents WHERE id=1'
        ).fetchone()
        assert row[0] == original
        assert row[1] == 3


def test_actual_content_link_joins_same_route_event_and_saves_no_new_revision(workspace):
    document_id, revision = material(workspace)
    with workspace[0].transaction() as connection:
        link = link_input(connection, document_id, revision)
        revisions_before = connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
    body = request(workspace, [{'type': 'LINK_CONTENT', **link}], document_id=document_id)
    result = update_path(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    assert result['data']['effects']['content_changed'] is False
    with workspace[0].transaction() as connection:
        artifact = connection.execute('SELECT * FROM formation_artifacts').fetchone()
        assert artifact['source_event_id'] in result['data']['event_ids']
        event = connection.execute(
            'SELECT payload_json FROM document_change_audits WHERE id=?',
            (artifact['source_event_id'],),
        ).fetchone()[0]
        assert json.loads(event)['event']['action'] == 'CONTENT_ASSOCIATED'
        change = connection.execute(
            "SELECT * FROM formation_event_changes WHERE entity_kind='ARTIFACT'"
        ).fetchone()
        assert json.loads(change['after_json'])['artifact_ref'] == 'a1'
        assert change['member_count'] == 5
        assert (
            connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == revisions_before
        )


def test_route_no_change_has_only_success_receipt_without_new_action_or_versions(workspace):
    seed(workspace)
    before = snapshot(workspace[0])
    body = request(workspace, [{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '讨论方案'}])
    result = update_path(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'NO_CHANGE', result
    assert snapshot(workspace[0]) == before
