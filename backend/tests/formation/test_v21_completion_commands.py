"""Actual user completion command, not an AI task or a body-writing shortcut."""

import json
from uuid import uuid4

from backend.app.formation.commands import complete_step
from backend.app.formation import completion_commands
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_artifact_links import association_event
from backend.tests.formation.test_v21_path_commands import snapshot

__all__ = ['database', 'released', 'workspace']


def request(workspace, **fields):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    return {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'COMPLETE_STEP',
            'step_ref': 's1',
            'expected_definition_version': 1,
            'expected_goal_version': 1,
            'expected_content_version': 1,
            'result_dispositions': [],
            'issue_dispositions': [],
            'branch_dispositions': [],
            'next_step_ref': None,
            **fields,
        },
        'idempotency_key': str(uuid4()),
    }


def seed(workspace, *, related=False):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'下一步','PLANNED',NULL)"
        )
        connection.execute(
            "INSERT INTO formation_results VALUES(1,'s2','s2.o1','下一项成果','CONTENT')"
        )
        connection.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
        if related:
            root = RequirementRepository(connection).get_for_document(1, 1)
            event = association_event(connection, root)
            connection.execute(
                "INSERT INTO formation_branches VALUES(1,'b1','s1','s1','待核实事项','影响当前成果','OPEN',?,?,NULL,'[]',NULL)",
                (event, event),
            )
            connection.execute(
                "INSERT INTO formation_issues VALUES(1,'i1','s1','b1','待明确范围','[{\"kind\":\"MESSAGE\",\"message_id\":1}]',1,'OPEN',NULL,'[]',NULL)"
            )
            connection.execute(
                "UPDATE formation_heads SET current_step_ref='s1',active_branch_ref='b1',next_branch_no=2,next_issue_no=2 WHERE document_id=1"
            )


def test_complete_planned_step_keeps_outstanding_and_replays_original_success(workspace):
    seed(workspace)
    body = request(workspace)
    result = complete_step(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    data = result['data']
    assert data['discussion_version'] == data['formation_version'] == 2
    assert data['content_version'] == 1
    assert data['effects']['revision_id'] is None
    frozen = snapshot(workspace[0])
    assert complete_step(workspace[1], body, catalog=workspace[2]) == result
    assert snapshot(workspace[0]) == frozen
    with workspace[0].transaction() as connection:
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s1'").fetchone()[
                0
            ]
            == 'COMPLETED'
        )
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s2'").fetchone()[
                0
            ]
            == 'PLANNED'
        )
        item = json.loads(
            connection.execute(
                "SELECT payload_json FROM formation_closure_items WHERE kind='RESULT'"
            ).fetchone()[0]
        )
        assert item['status'] == 'OUTSTANDING'
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2
        assert connection.execute('SELECT status FROM requirements').fetchone()[0] == 'PLANNING'
        event = json.loads(
            connection.execute(
                'SELECT payload_json FROM document_change_audits WHERE id=?',
                (data['event_ids'][0],),
            ).fetchone()[0]
        )['event']
        assert event['action'] == 'STEP_COMPLETED'
        assert event['closure']['result_count'] == 1
        assert event['actor'] == 'USER'


def test_closing_noncurrent_step_preserves_active_focus_without_pausing_anyone(workspace):
    seed(workspace, related=True)
    with workspace[0].transaction(write=True) as connection:
        connection.execute(
            "UPDATE formation_branches SET return_step_ref='s2' WHERE branch_ref='b1'"
        )
        connection.execute("UPDATE formation_issues SET step_ref='s2' WHERE issue_ref='i1'")
        connection.execute(
            "UPDATE formation_heads SET current_step_ref='s2',active_branch_ref='b1'"
        )
        connection.execute("UPDATE formation_steps SET status='IN_PROGRESS' WHERE step_ref='s2'")
    result = complete_step(workspace[1], request(workspace), catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        assert tuple(
            connection.execute(
                'SELECT current_step_ref,active_branch_ref FROM formation_heads'
            ).fetchone()
        ) == ('s2', 'b1')
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s2'").fetchone()[
                0
            ]
            == 'IN_PROGRESS'
        )


def test_one_click_end_keeps_unresolved_branch_issue_and_their_sources(workspace):
    seed(workspace, related=True)
    result = complete_step(workspace[1], request(workspace), catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        assert tuple(
            connection.execute(
                'SELECT current_step_ref,active_branch_ref FROM formation_heads'
            ).fetchone()
        ) == (None, None)
        assert connection.execute('SELECT status FROM formation_branches').fetchone()[0] == 'OPEN'
        assert (
            connection.execute('SELECT disposition FROM formation_issues').fetchone()[0] == 'OPEN'
        )
        items = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM formation_closure_items WHERE kind IN ('ISSUE','BRANCH')"
            )
        ]
        assert all(item['disposition'] == 'KEEP_OPEN' for item in items)
        assert all(item['source_count'] == 1 for item in items)


def test_transfer_whole_open_pair_and_choose_next_do_not_start_or_rewrite_old_owner(workspace):
    seed(workspace, related=True)
    body = request(
        workspace,
        next_step_ref='s2',
        issue_dispositions=[
            {'ref': 'i1', 'disposition': 'TRANSFER', 'to_step_ref': 's2', 'reason': None}
        ],
        branch_dispositions=[
            {'ref': 'b1', 'disposition': 'TRANSFER', 'to_step_ref': 's2', 'reason': None}
        ],
    )
    result = complete_step(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    assert len(result['data']['event_ids']) == 4
    with workspace[0].transaction() as connection:
        assert tuple(
            connection.execute(
                'SELECT origin_step_ref,return_step_ref FROM formation_branches'
            ).fetchone()
        ) == ('s1', 's2')
        assert connection.execute('SELECT step_ref FROM formation_issues').fetchone()[0] == 's2'
        assert tuple(
            connection.execute(
                'SELECT current_step_ref,active_branch_ref FROM formation_heads'
            ).fetchone()
        ) == ('s2', None)
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s2'").fetchone()[
                0
            ]
            == 'PLANNED'
        )
        closure = connection.execute(
            'SELECT issue_count,branch_count FROM formation_closures'
        ).fetchone()
        assert tuple(closure) == (1, 1)
        item = json.loads(
            connection.execute(
                "SELECT payload_json FROM formation_closure_items WHERE item_ref='i1'"
            ).fetchone()[0]
        )
        assert item['to_step_ref'] == 's2' and item['disposition'] == 'TRANSFER'


def test_incomplete_transfer_and_stale_definition_reject_whole_command(workspace):
    seed(workspace, related=True)
    before = snapshot(workspace[0])
    body = request(
        workspace,
        issue_dispositions=[
            {
                'ref': 'i1',
                'disposition': 'TRANSFER',
                'to_step_ref': 's2',
                'reason': None,
            }
        ],
    )
    assert complete_step(workspace[1], body, catalog=workspace[2])['code'] == 'FORMATION_INVALID'
    assert snapshot(workspace[0]) == before
    result = complete_step(
        workspace[1], request(workspace, expected_definition_version=2), catalog=workspace[2]
    )
    assert result['code'] == 'STATE_CONFLICT'
    assert result['details']['reason'] == 'STEP_DEFINITION_CHANGED'
    assert snapshot(workspace[0]) == before


def test_failure_after_full_snapshot_and_versions_rolls_back_everything(workspace, monkeypatch):
    seed(workspace, related=True)
    before = snapshot(workspace[0])
    body = request(workspace)
    original = completion_commands.write_facts

    def fail(*args, **kwargs):
        raise RuntimeError('injected after completion snapshot')

    monkeypatch.setattr(completion_commands, 'write_facts', fail)
    assert complete_step(workspace[1], body, catalog=workspace[2])['code'] == 'INTERNAL_ERROR'
    assert snapshot(workspace[0]) == before
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_closures').fetchone()[0] == 0
        assert (
            connection.execute('SELECT count(*) FROM formation_closure_evidence').fetchone()[0] == 0
        )
    monkeypatch.setattr(completion_commands, 'write_facts', original)
    assert complete_step(workspace[1], body, catalog=workspace[2])['code'] == 'UPDATED'
