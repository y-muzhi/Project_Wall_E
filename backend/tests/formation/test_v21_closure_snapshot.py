"""Closure scalar items and evidence are streamed, immutable and transaction-bound."""

import json
from uuid import uuid4

import pytest

from backend.app.formation.closure_snapshot import ClosureBuilder, write_closure
from backend.app.formation.closure_sources import source_reader
from backend.app.formation.commands import update_state
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import operation_time
from backend.tests.formation.test_v21_schema import database, released, workspace, head

__all__ = ['database', 'released', 'workspace']


def prepare(connection, resources, *, source_rows, result_actions=()):
    root = RequirementRepository(connection).get_for_document(1, 1)
    step = dict(
        connection.execute(
            "SELECT * FROM formation_steps WHERE document_id=1 AND step_ref='s1'"
        ).fetchone()
    )
    document = dict(
        connection.execute(
            'SELECT d.*,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
            'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=1',
        ).fetchone()
    )
    at = operation_time(None)
    key = str(uuid4())
    message_id = entity_id(connection, EntityKind.MESSAGE)
    event_id = entity_id(connection, EntityKind.DOCUMENT_AUDIT)
    MessageRepository(connection).create_user_text(
        message_id,
        1,
        None,
        '结束步骤：讨论方案',
        key,
        at,
        document_id=1,
        topic_refs=(),
        document_ids=(1,),
    )
    command = {
        'expected_goal_version': 1,
        'next_step_ref': None,
        'result_dispositions': list(result_actions),
        'issue_dispositions': [],
        'branch_dispositions': [],
    }
    plan = ClosureBuilder(
        connection,
        root=root,
        step=step,
        document=document,
        command=command,
        event_id=event_id,
        message_id=message_id,
        sources=source_rows,
        current_blocks={},
    ).prepare()
    basis = {
        'discussion_version': root['discussion_version'],
        'formation_version': 1,
        'goal_version': 1,
        'document_revision_id': document['revision_id'],
        'content_version': 1,
    }
    event = {
        'schema': 'formation_event_v1',
        'event_id': event_id,
        'document_id': 1,
        'action': 'STEP_COMPLETED',
        'actor': 'USER',
        'reason': '结束步骤',
        'created_at': at,
        'batch_ref': event_id,
        'ordinal': 1,
        'batch_size': 1,
        'change_count': 0,
        'version_before': basis,
        'version_after': {
            **basis,
            'discussion_version': basis['discussion_version'] + 1,
            'formation_version': 2,
        },
        'closure': plan.head,
    }
    connection.execute(
        'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,'
        'before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) '
        "VALUES(?,1,1,'USER_ACTION',?,'STEP_COMPLETED',NULL,NULL,?,'DISCUSSION_UPDATED',NULL,NULL,?)",
        (
            event_id,
            message_id,
            at,
            json.dumps({'formation_event_type': 'STEP_COMPLETED', 'event': event}),
        ),
    )
    return plan, root, at


def finalize(connection, plan, root, at):
    write_closure(connection, 1, plan)
    connection.execute(
        "UPDATE formation_steps SET status='COMPLETED',closure_event_id=? WHERE document_id=1 AND step_ref='s1'",
        (plan.head['event_id'],),
    )
    connection.execute('UPDATE formation_heads SET version=2 WHERE document_id=1')
    RequirementRepository(connection).advance_discussion(root, at)


def test_planned_step_ends_with_outstanding_result_and_no_fake_start_or_body_write(workspace):
    db, _, resources = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        with source_reader(connection, resources) as sources:
            plan, root, at = prepare(connection, resources, source_rows=sources)
            assert plan.head['result_count'] == 1
            assert plan.head['issue_count'] == plan.head['branch_count'] == 0
            finalize(connection, plan, root, at)
    with db.transaction() as connection:
        item = json.loads(
            connection.execute('SELECT payload_json FROM formation_closure_items').fetchone()[0]
        )
        assert item['status'] == 'OUTSTANDING'
        assert item['evidence_count'] == 0
        assert item['artifact_count'] == item['source_count'] == 0
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2
        assert connection.execute('SELECT status FROM requirements').fetchone()[0] == 'PLANNING'
        assert (
            connection.execute('SELECT count(*) FROM formation_closure_evidence').fetchone()[0] == 0
        )


def test_thousands_of_remaining_items_keep_every_source_in_separate_rows(workspace):
    db, _, resources = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        for number in range(1, 1006):
            connection.execute(
                'INSERT INTO formation_issues VALUES(1,?, ?,NULL,?,?,0,?,NULL,?,NULL)',
                (
                    f'i{number}',
                    's1',
                    f'待处理事项{number}',
                    '[{"kind":"MESSAGE","message_id":1}]',
                    'OPEN',
                    '[]',
                ),
            )
        connection.execute('UPDATE formation_heads SET next_issue_no=1006 WHERE document_id=1')
        with source_reader(connection, resources) as sources:
            plan, root, at = prepare(connection, resources, source_rows=sources)
            assert plan.head['issue_count'] == 1005
            finalize(connection, plan, root, at)
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM formation_closure_items WHERE kind='ISSUE'"
            ).fetchone()[0]
            == 1005
        )
        assert (
            connection.execute('SELECT count(*) FROM formation_closure_evidence').fetchone()[0]
            == 1005
        )
        item = json.loads(
            connection.execute(
                "SELECT payload_json FROM formation_closure_items WHERE item_ref='i1005'"
            ).fetchone()[0]
        )
        assert item['disposition'] == 'KEEP_OPEN'
        assert item['state_at_close'] == 'OPEN'
        assert item['source_count'] == 1
        assert 'source_refs' not in item
        assert (
            connection.execute(
                "SELECT count(*) FROM formation_issues WHERE disposition='OPEN'"
            ).fetchone()[0]
            == 1005
        )


def test_original_closure_is_immutable_after_user_reopens_step(workspace):
    db, executor, resources = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        with source_reader(connection, resources) as sources:
            plan, root, at = prepare(connection, resources, source_rows=sources)
            finalize(connection, plan, root, at)
    with db.transaction() as connection:
        before = [tuple(row) for row in connection.execute('SELECT * FROM formation_closure_items')]
        version = connection.execute(
            'SELECT discussion_version FROM requirement_documents WHERE id=1'
        ).fetchone()[0]
    result = update_state(
        executor,
        {
            'requirement_id': 1,
            'document_id': 1,
            'expected_discussion_version': version,
            'discussion_command': {'type': 'FORMATION', 'action': 'REOPEN_STEP', 'step_ref': 's1'},
            'idempotency_key': str(uuid4()),
        },
    )
    assert result['code'] == 'UPDATED', result
    with db.transaction() as connection:
        assert [
            tuple(row) for row in connection.execute('SELECT * FROM formation_closure_items')
        ] == before
        assert (
            connection.execute('SELECT closure_event_id FROM formation_steps').fetchone()[0] is None
        )


def test_failure_after_snapshot_insertion_rolls_back_closure_and_sources(workspace):
    db, _, resources = workspace
    with db.transaction(write=True) as connection:
        head(connection)
    with pytest.raises(RuntimeError, match='after closure'):
        with db.transaction(write=True) as connection:
            with source_reader(connection, resources) as sources:
                plan, root, at = prepare(connection, resources, source_rows=sources)
                finalize(connection, plan, root, at)
                raise RuntimeError('injected after closure')
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_closures').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM formation_closure_items').fetchone()[0] == 0
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s1'").fetchone()[
                0
            ]
            == 'PLANNED'
        )
