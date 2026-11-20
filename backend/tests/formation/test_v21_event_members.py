"""History members stream to rows and native recovery freezes old real sources."""

from uuid import uuid4
import json

import pytest

from backend.app.formation.commands import update_state
from backend.app.formation.digests import digest_rows
from backend.app.formation.events import record_change
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_artifact_links import association_event

__all__ = ['database', 'released', 'workspace']


def members(count):
    for number, ref in enumerate(sorted(f's{value + 1}' for value in range(1, count + 1)), 1):
        yield {
            'ordinal': number,
            'collection': 'DEPENDENCY',
            'member_key': ref,
            'before': None,
            'after': {'kind': 'REF', 'ref': ref},
        }


def test_large_member_delta_keeps_exact_count_digest_and_every_row_without_nested_array(workspace):
    db = workspace[0]
    calls = 0

    def repeatable():
        nonlocal calls
        calls += 1
        yield from members(1100)

    with db.transaction(write=True) as connection:
        head(connection)
        root = RequirementRepository(connection).get_for_document(1, 1)
        event_id = association_event(connection, root)
        # Real same-document endpoints support the stored dependency facts.
        connection.executemany(
            "INSERT INTO formation_steps VALUES(1,?,1,2,?,?,'PLANNED',NULL)",
            [(f's{number}', number, f'关联步骤{number}') for number in range(2, 1102)],
        )
        connection.executemany(
            'INSERT INTO formation_results VALUES(1,?,?,?,?)',
            [
                (f's{number}', f's{number}.o1', '完整预期成果', 'CONTENT')
                for number in range(2, 1102)
            ],
        )
        connection.execute('UPDATE formation_heads SET next_step_no=1102 WHERE document_id=1')
        connection.executemany(
            'INSERT INTO formation_step_edges VALUES(1,?,?,?)',
            [('s1', f's{number}', 'DEPENDENCY') for number in range(2, 1102)],
        )
        snapshot = {
            'step_ref': 's1',
            'definition_version': 1,
            'title': '讨论方案',
            'status': 'PLANNED',
            'position': 1,
            'next_result_no': 2,
            'closure_event_ref': None,
        }
        record_change(connection, 1, event_id, 1, 'STEP', 's1', snapshot, snapshot, repeatable)
        stored = connection.execute(
            'SELECT * FROM formation_event_changes WHERE event_id=?', (event_id,)
        ).fetchone()
        assert stored['member_count'] == 1100
        assert stored['member_digest'] == digest_rows(members(1100))
        assert (
            connection.execute(
                'SELECT count(*) FROM formation_event_members WHERE event_id=?', (event_id,)
            ).fetchone()[0]
            == 1100
        )
        assert len(stored['after_json']) < 300
    assert calls == 2


def test_changing_stream_between_passes_rolls_back_header_and_members(workspace):
    db = workspace[0]
    calls = 0

    def unstable():
        nonlocal calls
        calls += 1
        yield from members(calls)

    with pytest.raises(ValueError, match='changed during'):
        with db.transaction(write=True) as connection:
            head(connection)
            root = RequirementRepository(connection).get_for_document(1, 1)
            event_id = association_event(connection, root)
            record_change(
                connection,
                1,
                event_id,
                1,
                'STEP',
                's1',
                {
                    'step_ref': 's1',
                    'definition_version': 1,
                    'title': '讨论方案',
                    'status': 'PLANNED',
                    'position': 1,
                    'next_result_no': 2,
                    'closure_event_ref': None,
                },
                {
                    'step_ref': 's1',
                    'definition_version': 1,
                    'title': '讨论方案',
                    'status': 'PLANNED',
                    'position': 1,
                    'next_result_no': 2,
                    'closure_event_ref': None,
                },
                unstable,
            )
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_event_changes').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM formation_event_members').fetchone()[0] == 0


def test_native_branch_recovery_records_old_result_sources_and_actual_review_event(workspace):
    db, executor, _ = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        root = RequirementRepository(connection).get_for_document(1, 1)
        event_id = association_event(connection, root)
        connection.execute(
            'INSERT INTO formation_branches(document_id,branch_ref,origin_step_ref,return_step_ref,'
            'question,relevance,status,origin_event_id,state_event_id,result_summary,result_sources_json,disposition_event_id) '
            "VALUES(1,'b1','s1','s1','继续核实方案','与方案形成有关','RESOLVED',?,?,?, ?,NULL)",
            (
                event_id,
                event_id,
                '原有结果及依据',
                json.dumps([{'kind': 'MESSAGE', 'message_id': 1}]),
            ),
        )
        connection.execute('UPDATE formation_heads SET next_branch_no=2 WHERE document_id=1')
        discussion_version = root['discussion_version']
    result = update_state(
        executor,
        {
            'requirement_id': 1,
            'document_id': 1,
            'expected_discussion_version': discussion_version,
            'discussion_command': {
                'type': 'FORMATION',
                'action': 'RESUME_BRANCH',
                'step_ref': 's1',
                'branch_ref': 'b1',
                'expected_branch_status': 'RESOLVED',
                'expected_branch_event_id': event_id,
                'enter_after_resume': True,
            },
            'idempotency_key': str(uuid4()),
        },
    )
    assert result['code'] == 'UPDATED', result
    resumed = result['data']['event_ids'][0]
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM formation_event_changes WHERE event_id=? AND entity_kind='BRANCH'",
            (resumed,),
        ).fetchone()
        assert row['member_count'] == 1
        member = connection.execute(
            'SELECT * FROM formation_event_members WHERE event_id=?', (resumed,)
        ).fetchone()
        assert member['collection'] == 'BRANCH_RESULT_SOURCE'
        assert json.loads(member['before_json']) == {
            'kind': 'SOURCE',
            'source_ref': {'kind': 'MESSAGE', 'message_id': 1},
        }
        assert member['after_json'] is None
        assert json.loads(row['before_json'])['result_summary'] == '原有结果及依据'
        assert json.loads(row['after_json'])['state_event_ref'] == resumed
