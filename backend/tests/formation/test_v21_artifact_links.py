"""Artifact links use real block snapshots, source events and transaction-bound evidence."""

from dataclasses import replace
import json
from uuid import uuid4

import pytest

from backend.app.documents.commands import create_document
from backend.app.formation.artifact_links import verify_links, create_links, block_digest
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import operation_time, Rejected
from backend.tests.formation.test_v21_schema import database, released, workspace, head

__all__ = ['database', 'released', 'workspace']


def material(workspace):
    db, commands, resources = workspace
    result = create_document(
        commands,
        {
            'requirement_id': 1,
            'name': '已有材料',
            'document_kind': 'REQUIREMENT_BRIEF',
            'template_ref': resources.collaboration.reference('structure.brief'),
            'idempotency_key': str(uuid4()),
        },
        catalog=resources,
    )
    assert result['code'] == 'CREATED', result
    identity = result['data']['document']['id']
    with db.transaction(write=True) as connection:
        head(connection, identity)
    return identity, result['data']['revision_id']


def association_event(connection, root):
    message_id = entity_id(connection, EntityKind.MESSAGE)
    at = operation_time(None)
    MessageRepository(connection).create_user_text(
        message_id,
        root['id'],
        None,
        '关联已核实的文档内容',
        str(uuid4()),
        at,
        document_id=root['assistant_document_id'],
        topic_refs=(),
        document_ids=(root['assistant_document_id'],),
    )
    event_id = entity_id(connection, EntityKind.DOCUMENT_AUDIT)
    connection.execute(
        'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,'
        'before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) '
        "VALUES(?,?,?,'USER_ACTION',?,'CONTENT_ASSOCIATED',NULL,NULL,?,'DISCUSSION_UPDATED',NULL,NULL,?)",
        (
            event_id,
            root['id'],
            root['assistant_document_id'],
            message_id,
            at,
            json.dumps({'formation_event_type': 'CONTENT_ASSOCIATED'}),
        ),
    )
    return event_id


def link_input(connection, document_id, revision_id):
    state = json.loads(
        connection.execute(
            'SELECT block_state_json FROM requirement_documents WHERE id=?',
            (document_id,),
        ).fetchone()[0]
    )
    ids = [row['block_id'] for row in state['blocks']]
    return {
        'step_ref': 's1',
        'result_refs': ['s1.o1'],
        'revision_id': revision_id,
        'block_ids': ids[:2],
    }


def test_verified_association_freezes_original_ranges_and_changes_no_document_content(workspace):
    db, _, resources = workspace
    document_id, revision = material(workspace)
    with db.transaction(write=True) as connection:
        root = RequirementRepository(connection).get_for_document(1, document_id)
        before = connection.execute(
            'SELECT markdown_content,content_version FROM requirement_documents WHERE id=?',
            (document_id,),
        ).fetchone()[:]
        link = link_input(connection, document_id, revision)
        checked = verify_links(connection, root, [link], resources)
        event = association_event(connection, root)
        created = create_links(
            connection, document_id, checked, [event], {'s1': '已核实的原始材料'}
        )
        assert created[0]['artifact_ref'] == 'a1'
        assert created[0]['origin_revision_id'] == revision
        assert created[0]['freshness'] == 'CURRENT'
        after = connection.execute(
            'SELECT markdown_content,content_version FROM requirement_documents WHERE id=?',
            (document_id,),
        ).fetchone()[:]
        assert after == before
    with db.transaction() as connection:
        ranges = [
            tuple(row)
            for row in connection.execute(
                'SELECT role,ordinal,block_id,block_digest FROM formation_artifact_ranges ORDER BY role,ordinal'
            )
        ]
        assert len(ranges) == 4
        assert ranges[:2] == [('CURRENT', row[1], row[2], row[3]) for row in ranges[2:]]
        assert (
            connection.execute(
                'SELECT next_artifact_no FROM formation_heads WHERE document_id=?', (document_id,)
            ).fetchone()[0]
            == 2
        )


def test_preview_verification_cannot_be_reused_on_another_transaction(workspace):
    db, _, resources = workspace
    document_id, revision = material(workspace)
    with db.transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document_id)
        checked = verify_links(
            connection, root, [link_input(connection, document_id, revision)], resources
        )
    with pytest.raises(ValueError, match='transferred'):
        with db.transaction(write=True) as connection:
            event = association_event(connection, root)
            create_links(connection, document_id, checked, [event], {'s1': '已有内容'})
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 0
        assert (
            connection.execute(
                'SELECT next_artifact_no FROM formation_heads WHERE document_id=?', (document_id,)
            ).fetchone()[0]
            == 1
        )


def test_wrong_revision_missing_blocks_and_missing_event_cannot_create_artifact(workspace):
    db, _, resources = workspace
    document_id, revision = material(workspace)
    with db.transaction(write=True) as connection:
        root = RequirementRepository(connection).get_for_document(1, document_id)
        link = link_input(connection, document_id, revision)
        for invalid in ({**link, 'revision_id': revision + 1}, {**link, 'block_ids': [99999]}):
            with pytest.raises(Rejected):
                verify_links(connection, root, [invalid], resources)
        checked = verify_links(connection, root, [link], resources)
        with pytest.raises(ValueError, match='actual current revision'):
            create_links(connection, document_id, checked, [99999], {'s1': '已有内容'})
        with pytest.raises(ValueError):
            create_links(
                connection,
                document_id,
                (replace(checked[0], result_refs=()),),
                [99999],
                {'s1': '已有内容'},
            )
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 0


def test_block_digest_preserves_exact_whitespace():
    assert block_digest('内容') != block_digest('内容 ')
    assert block_digest('内容\n') != block_digest('内容\r\n')
