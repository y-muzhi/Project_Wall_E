"""Shared content commit updates every affected artifact atomically, with no AI calls."""

import json
from uuid import uuid4

from backend.app.formation.commands import update_path, complete_step
from backend.app.formation import content_maintenance
from backend.app.formation.history_queries import read_history
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_artifact_links import link_input
from backend.tests.formation.test_v21_path_commands import request, snapshot
from backend.tests.formation.test_v21_completion_commands import request as completion_request
from backend.tests.documents.test_v15_editing import start, candidate, save, finish
from backend.app.documents.markdown import parse_markdown

__all__ = ['database', 'released', 'workspace']


def state(workspace, doc):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, doc)
        head = dict(
            connection.execute(
                'SELECT * FROM formation_heads WHERE document_id=?', (doc,)
            ).fetchone()
        )
        artifact = dict(
            connection.execute(
                'SELECT * FROM formation_artifacts WHERE document_id=? AND artifact_ref=?',
                (doc, 'a1'),
            ).fetchone()
        )
        ranges = [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? ORDER BY role,ordinal',
                (doc, 'a1'),
            )
        ]
        current = dict(
            connection.execute('SELECT * FROM requirement_documents WHERE id=?', (doc,)).fetchone()
        )
        return root, head, artifact, ranges, current


def edit(workspace, doc, change, *, key=None):
    version = state(workspace, doc)[4]['content_version']
    result = start(workspace, identity=doc, version=version)
    assert result['code'] == 'DRAFT_STARTED', result
    draft = result['data']['manual_draft']
    blocks = parse_markdown(draft['markdown_content']).blocks
    identities = [row['block_id'] for row in draft['block_state_json']['blocks']]
    markdown, ids = change(blocks, identities)
    prepared = candidate(workspace, draft, markdown, ids)
    saved = save(workspace, draft, prepared)
    assert saved['code'] == 'DRAFT_SAVED', saved
    return finish(workspace, saved['data'], key=key), saved['data']


def change_first(blocks, ids):
    return '\n\n'.join(
        [
            blocks[0].markdown.rstrip('\n') + '（新增范围）',
            *[block.markdown for block in blocks[1:]],
        ]
    ), ids


def test_unrelated_body_region_does_not_invalidate_or_bump_formation(workspace):
    doc = associated(workspace)
    before = state(workspace, doc)
    result, _ = edit(
        workspace,
        doc,
        lambda blocks, ids: (
            '\n\n'.join(
                [
                    *[block.markdown for block in blocks[:-1]],
                    blocks[-1].markdown.rstrip('\n') + '（补充背景）',
                ]
            ),
            ids,
        ),
    )
    assert result['code'] == 'DRAFT_COMPLETED', result
    after = state(workspace, doc)
    assert after[4]['content_version'] == 2
    assert after[0]['discussion_version'] == before[0]['discussion_version']
    assert after[1] == before[1] and after[2] == before[2] and after[3] == before[3]


def test_changed_selected_range_is_a_program_fact_original_ranges_and_lifecycle_stay(workspace):
    doc = associated(workspace)
    before = state(workspace, doc)
    key = str(uuid4())
    result, draft = edit(workspace, doc, change_first, key=key)
    assert result['code'] == 'DRAFT_COMPLETED', result
    after = state(workspace, doc)
    assert after[0]['discussion_version'] == before[0]['discussion_version'] + 1
    assert after[1]['version'] == before[1]['version'] + 1
    assert after[2]['freshness'] == 'NEEDS_REVIEW' and after[2]['review_reason'] == 'CHANGED'
    assert after[2]['origin_digest'] == before[2]['origin_digest']
    assert [row for row in after[3] if row[2] == 'ORIGIN'] == [
        row for row in before[3] if row[2] == 'ORIGIN'
    ]
    assert all(
        row[4] == after[2]['checked_against_revision_id'] for row in after[3] if row[2] == 'CURRENT'
    )
    frozen = snapshot(workspace[0])
    assert finish(workspace, draft, key=key) == result
    assert snapshot(workspace[0]) == frozen
    history = read_history(workspace[0], 1, doc, 'events', {})
    assert history['code'] == 'READ_OK', history
    event = history['data']['value']['items'][0]
    assert event['actor'] == 'PROGRAM' and event['action'] == 'ARTIFACT_CHECKED'
    assert (
        event['version_before']['content_version'] == 1
        and event['version_after']['content_version'] == 2
    )
    assert event['change_count'] == 1
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                'SELECT status FROM formation_steps WHERE document_id=?', (doc,)
            ).fetchone()[0]
            == 'PLANNED'
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_removed_range_does_not_revive_when_old_text_restored_with_new_block_identities(workspace):
    doc = associated(workspace)
    before = state(workspace, doc)
    origin_revision = before[2]['origin_revision_id']
    result, _ = edit(
        workspace,
        doc,
        lambda blocks, ids: ('\n\n'.join(block.markdown for block in blocks[2:]), ids[2:]),
    )
    assert result['code'] == 'DRAFT_COMPLETED', result
    removed = state(workspace, doc)
    assert removed[2]['freshness'] == 'REMOVED' and removed[2]['review_reason'] is None
    assert not [row for row in removed[3] if row[2] == 'CURRENT']
    restored = start(workspace, identity=doc, version=2, restore=origin_revision)
    assert restored['code'] == 'DRAFT_STARTED', restored
    result = finish(workspace, restored['data']['manual_draft'])
    assert result['code'] == 'DRAFT_COMPLETED', result
    current = state(workspace, doc)
    assert current[4]['content_version'] == 3
    assert current[2]['freshness'] == 'REMOVED'
    assert current[1]['version'] == removed[1]['version']


def test_content_change_on_completed_step_keeps_immutable_closure_and_completion(workspace):
    doc = associated(workspace)
    before = state(workspace, doc)
    body = completion_request(
        workspace,
        result_dispositions=[
            {'result_ref': 's1.o1', 'status': 'LANDED', 'artifact_refs': ['a1'], 'source_refs': []}
        ],
    )
    body.update(document_id=doc, expected_discussion_version=before[0]['discussion_version'])
    result = complete_step(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        closure = [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM formation_closures WHERE document_id=?', (doc,)
            )
        ]
        items = [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM formation_closure_items WHERE event_id=?', (closure[0][0],)
            )
        ]
    edited, _ = edit(workspace, doc, change_first)
    assert edited['code'] == 'DRAFT_COMPLETED', edited
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                'SELECT status FROM formation_steps WHERE document_id=?', (doc,)
            ).fetchone()[0]
            == 'COMPLETED'
        )
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM formation_closures WHERE document_id=?', (doc,)
            )
        ] == closure
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM formation_closure_items WHERE event_id=?', (closure[0][0],)
            )
        ] == items
    assert state(workspace, doc)[2]['freshness'] == 'NEEDS_REVIEW'


def test_failure_after_maintenance_rolls_back_content_revision_ranges_versions_and_keeps_draft(
    workspace, monkeypatch
):
    doc = associated(workspace)
    original = content_maintenance.maintain_content
    frozen = None
    key = str(uuid4())

    def fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise StorageUnavailable('offline injected rollback')

    with monkeypatch.context() as patch:
        patch.setattr(content_maintenance, 'maintain_content', fail_after)
        version = state(workspace, doc)[4]['content_version']
        draft = start(workspace, identity=doc, version=version)['data']['manual_draft']
        blocks = parse_markdown(draft['markdown_content']).blocks
        ids = [row['block_id'] for row in draft['block_state_json']['blocks']]
        markdown, identities = change_first(blocks, ids)
        saved = save(workspace, draft, candidate(workspace, draft, markdown, identities))
        assert saved['code'] == 'DRAFT_SAVED', saved
        frozen = snapshot(workspace[0])
        before_state = state(workspace, doc)
        result = finish(workspace, saved['data'], key=key)
        assert result['code'] == 'STORAGE_UNAVAILABLE', result
        assert snapshot(workspace[0]) == frozen
        assert state(workspace, doc) == before_state
        with workspace[0].transaction() as connection:
            assert (
                connection.execute(
                    'SELECT count(*) FROM idempotency_records WHERE idempotency_key=?', (key,)
                ).fetchone()[0]
                == 0
            )
    result = finish(workspace, saved['data'], key=key)
    assert result['code'] == 'DRAFT_COMPLETED', result


def test_more_than_one_page_of_artifacts_are_maintained_in_one_program_event(workspace):
    doc = associated(workspace)
    with workspace[0].transaction() as connection:
        revision = state(workspace, doc)[2]['origin_revision_id']
        link = link_input(connection, doc, revision)
    for count in (20, 20, 20, 20, 20, 4):
        result = update_path(
            workspace[1],
            request(
                workspace,
                [{'type': 'LINK_CONTENT', **link} for _ in range(count)],
                document_id=doc,
            ),
            catalog=workspace[2],
        )
        assert result['code'] == 'UPDATED', result
    before = state(workspace, doc)
    result, _ = edit(workspace, doc, change_first)
    assert result['code'] == 'DRAFT_COMPLETED', result
    after = state(workspace, doc)
    assert after[1]['version'] == before[1]['version'] + 1
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM formation_artifacts WHERE document_id=? AND freshness='NEEDS_REVIEW'",
                (doc,),
            ).fetchone()[0]
            == 105
        )
        event = connection.execute(
            "SELECT payload_json FROM document_change_audits WHERE document_id=? AND source_type='PROGRAM' "
            'ORDER BY id DESC LIMIT 1',
            (doc,),
        ).fetchone()
        assert json.loads(event[0])['event']['change_count'] == 105
