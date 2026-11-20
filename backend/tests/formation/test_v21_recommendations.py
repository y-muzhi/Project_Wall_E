"""Recommendation basis is precise and program-owned; no fabricated AI rows or calls."""

from contextlib import contextmanager

from backend.app.formation.commands import update_path, update_state
from backend.app.formation.read_context import ReadContext
from backend.app.formation.recommendations import capture_basis, stale_reason
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_path_commands import request
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.formation.test_v21_artifact_links import material
from backend.tests.documents.test_v15_editing import start, candidate, save, finish

__all__ = ['database', 'released', 'workspace']


@contextmanager
def context(workspace, doc=1, *, write=False):
    with workspace[0].transaction(write=write) as connection:
        root = RequirementRepository(connection).get_for_document(1, doc)
        yield ReadContext(connection, root, workspace[2])


def basis(context, target=None, coverage=()):
    return capture_basis(
        context,
        's1',
        target,
        coverage,
        [{'kind': 'MESSAGE', 'message_id': 1}],
        [],
        carried_block_ids=coverage,
    )


def test_focus_counters_and_unrelated_definition_do_not_expire_basis(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    assert (
        update_path(workspace[1], request(workspace, [add_step(1)]), catalog=workspace[2])['code']
        == 'UPDATED'
    )
    with context(workspace) as current:
        original = basis(current)
    assert (
        update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s2'))['code']
        == 'UPDATED'
    )
    assert (
        update_path(
            workspace[1],
            request(workspace, [{'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '无关改名'}]),
            catalog=workspace[2],
        )['code']
        == 'UPDATED'
    )
    with context(workspace) as current:
        assert stale_reason(current, original) is None


def test_ordered_stale_reasons_cover_goal_definition_owner_target_and_new_relations(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    assert (
        update_path(workspace[1], request(workspace, [add_step(1)]), catalog=workspace[2])['code']
        == 'UPDATED'
    )
    with context(workspace) as current:
        original = basis(current, 's2')
    with context(workspace, write=True) as current:
        current.connection.execute(
            "INSERT INTO formation_issues VALUES(1,'i1','s1',NULL,'新问题','[]',0,'OPEN',NULL,'[]',NULL)"
        )
        assert stale_reason(current, original) == 'RELATED_FACT_CHANGED'
        current.connection.execute(
            "UPDATE formation_steps SET status='IN_PROGRESS' WHERE step_ref='s2'"
        )
        assert stale_reason(current, original) == 'TARGET_CHANGED'
        current.connection.execute("UPDATE formation_steps SET status='PAUSED' WHERE step_ref='s1'")
        assert stale_reason(current, original) == 'OWNER_STATE_CHANGED'
        current.connection.execute(
            "UPDATE formation_steps SET definition_version=2 WHERE step_ref='s1'"
        )
        assert stale_reason(current, original) == 'OWNER_DEFINITION_CHANGED'
        current.connection.execute('UPDATE formation_heads SET goal_version=2 WHERE document_id=1')
        # Reload the same transaction's program head, rather than using a stale ReadContext cache.
        refreshed = ReadContext(current.connection, current.root, current.resources)
        assert stale_reason(refreshed, original) == 'GOAL_CHANGED'


def test_unrelated_actual_content_commit_keeps_coverage_but_changed_selected_block_expires(
    workspace,
):
    doc, _ = material(workspace)
    with context(workspace, doc) as current:
        identity = next(iter(current.blocks))
        original = basis(current, coverage=[identity])
    for affects_selected in (False, True):
        with context(workspace, doc) as current:
            version = current.current['content_version']
        editing = start(workspace, identity=doc, version=version)
        assert editing['code'] == 'DRAFT_STARTED', editing
        draft = editing['data']['manual_draft']
        markdown = draft['markdown_content']
        updated = (
            markdown.replace('# 1. ', '# 1. 补充', 1)
            if affects_selected
            else markdown.rstrip() + '补充无关区域'
        )
        identities = [row['block_id'] for row in draft['block_state_json']['blocks']]
        proposed = candidate(workspace, draft, updated, identities)
        saved = save(workspace, draft, proposed)
        assert saved['code'] == 'DRAFT_SAVED', saved
        completed = finish(workspace, saved['data'])
        assert completed['code'] == 'DRAFT_COMPLETED', completed
        with context(workspace, doc) as current:
            assert stale_reason(current, original) == (
                'COVERAGE_CHANGED' if affects_selected else None
            )
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_sources_unavailable_take_priority_over_changed_related_facts(workspace, monkeypatch):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    with context(workspace, write=True) as current:
        original = basis(current)
        current.connection.execute(
            "INSERT INTO formation_issues VALUES(1,'i1','s1',NULL,'新问题','[]',0,'OPEN',NULL,'[]',NULL)"
        )

        def unavailable(source):
            raise Rejected('SOURCE_INVALID')

        monkeypatch.setattr(current, 'source_head', unavailable)
        assert stale_reason(current, original) == 'SOURCE_UNAVAILABLE'
