"""Offline P26: a named step moves without changing the selected discussion."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.requirements.api import req_router
from backend.app.messages.api import message_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_model_results import progress
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute, output

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def test_move_preserves_focus_and_projects_committed_batch(workspace, monkeypatch):
    offline_gate(monkeypatch)
    db, executor, catalog = workspace
    with db.transaction(write=True) as conn:
        head(conn)
        conn.execute(
            "UPDATE formation_steps SET title='邀请权限' WHERE document_id=1 AND step_ref='s1'"
        )
        conn.execute("INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'有效期','PLANNED',NULL)")
        conn.execute("INSERT INTO formation_results VALUES(1,'s2','s2.o1','确定时长','CONTENT')")
        conn.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
    target = {
        'discussion_step_ref': 's1',
        'discussion_branch_ref': None,
        'branch_intent': None,
        'branch_resume_basis': None,
    }
    accepted(
        workspace,
        request(workspace, target, instruction='把有效期移到邀请权限前面，但继续聊邀请权限'),
    )

    def move(context):
        formation = context.input['project_position']['formation']
        assert formation['selected_step']['title'] == '邀请权限'
        assert any(
            item.get('definition', {}).get('title') == '有效期'
            for item in formation['coverage']['included']
        )
        return output(
            context,
            progress_delta=progress(
                context, [{'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}]
            ),
        )

    result = execute(workspace, Gateway(move))
    assert result['code'] == 'AI_FINISHED', result
    with db.transaction() as conn:
        assert [
            row[0]
            for row in conn.execute(
                'SELECT title FROM formation_steps WHERE document_id=1 ORDER BY position'
            )
        ] == ['有效期', '邀请权限']
        assistant = conn.execute(
            "SELECT id FROM conversation_messages WHERE role='ASSISTANT'"
        ).fetchone()[0]
    app = FastAPI()
    app.include_router(req_router)
    app.include_router(message_router)
    app.state.walle_runtime = HttpRuntime(db, catalog, executor)
    with TestClient(app) as client:
        response = client.get(
            '/api/v1/requirements/1?document_id=1&expand=discussion&progress_view=brief'
        )
        assert response.status_code == 200, response.text
        brief = response.json()['data']['discussion']['progress_brief']
        assert brief['focus'] == {'step_ref': 's1', 'title': '邀请权限', 'purpose': ['方案说明']}
        response = client.get(f'/api/v1/conversation-messages/{assistant}?requirement_id=1')
        assert response.status_code == 200, response.text
        operations = response.json()['data']['formation_operations']
        assert len(operations) == 1 and operations[0]['kind'] == 'UPDATED'
        assert operations[0]['steps'] == ['有效期', '邀请权限']
        assert operations[0]['focus_title'] == '邀请权限'
        assert operations[0]['moves'] == [
            {'title': '有效期', 'before': 2, 'after': 1},
            {'title': '邀请权限', 'before': 1, 'after': 2},
        ]
    accepted(workspace, request(workspace, target, instruction='继续'))
    from backend.app.guide.collaboration_context import read_canonical, compile_context

    with db.transaction() as conn:
        wire = compile_context(read_canonical(conn, 2, catalog), catalog).input
        assert wire['project_position']['formation']['selected_step']['step_ref'] == 's1'


def test_brief_uses_only_active_linked_decisions_and_open_step_questions(workspace):
    from backend.app.formation.progress_brief import progress_brief
    from backend.app.infrastructure.requirement_repository import RequirementRepository

    with workspace[0].transaction(write=True) as conn:
        head(conn)
        conn.execute("INSERT INTO formation_step_topics VALUES (1,'s1','t1')")
        conn.execute(
            "INSERT INTO formation_issues VALUES (1,'i1','s1',NULL,'是否允许撤销？','[]',1,'OPEN',NULL,'[]',NULL)"
        )
        root = RequirementRepository(conn).get_for_document(1, 1)
        source = [{'kind': 'MESSAGE', 'message_id': root['initial_message_id']}]
        original = {
            'evidence_ref': 'e1',
            'origin': 'USER_STATEMENT',
            'nature': 'FACT',
            'state': 'ACTIVE',
            'applies_to': 'GLOBAL',
            'topic_refs': [],
            'assertion': '仅管理员可以邀请',
            'source_refs': source,
        }
        root['discussion_state_json'].update(
            topics=[{'topic_ref': 't1', 'evidence_refs': ['e1', 'e3', 'e4']}],
            evidence=[
                original,
                {**original, 'evidence_ref': 'e2', 'applies_to': ['t2']},
                {**original, 'evidence_ref': 'e3', 'state': 'SUPERSEDED'},
                {**original, 'evidence_ref': 'e4', 'nature': 'PROPOSAL'},
            ],
        )
        summary = {'current_step_ref': 's1', 'formation_version': 1, 'goal': {'text': '邀请设计'}}
        brief = progress_brief(conn, root, summary)
        assert brief['decision_total'] == brief['issue_total'] == 1
        assert brief['decisions'] == [
            {
                'evidence_ref': 'e1',
                'text': '仅管理员可以邀请',
                'source_refs': source,
                'step_ref': 's1',
                'writing': None,
            }
        ]
        assert brief['issues'][0]['question'] == '是否允许撤销？'


def test_http_long_progress_pages_bind_document_group_and_versions(workspace):
    db, executor, catalog = workspace
    with db.transaction(write=True) as conn:
        head(conn)
        conn.execute(
            "UPDATE formation_heads SET current_step_ref='s1',next_issue_no=25 WHERE document_id=1"
        )
        conn.executemany(
            "INSERT INTO formation_issues VALUES(1,?,'s1',NULL,?,'[]',0,'OPEN',NULL,'[]',NULL)",
            [(f'i{i}', f'待定问题{i}') for i in range(1, 25)],
        )
    app = FastAPI()
    app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(db, catalog, executor)
    params = {'document_id': 1, 'expand': 'discussion', 'progress_view': 'brief'}
    with TestClient(app) as client:

        def read(**query):
            return client.get('/api/v1/requirements/1', params={**params, **query})

        response = read()
        assert response.status_code == 200, response.text
        brief = response.json()['data']['discussion']['progress_brief']
        assert brief['issue_total'] == 24 and len(brief['issues']) == 3
        with db.transaction(write=True) as conn:
            conn.execute(
                "INSERT INTO formation_steps(document_id,step_ref,definition_version,next_result_no,position,title,status,closure_event_id) VALUES(1,'s2',1,1,2,'通知','PLANNED',NULL)"
            )
        viewed = read(progress_step_ref='s2')
        assert viewed.status_code == 200, viewed.text
        scoped = viewed.json()['data']['discussion']
        assert scoped['formation_summary']['current_step_ref'] == 's1'
        assert (
            scoped['view_progress']['focus']['step_ref'] == 's2'
            and scoped['view_progress']['issue_total'] == 0
        )
        assert 'progress_brief' not in scoped
        assert read(progress_step_ref='s999').status_code == 404
        document = read(progress_view='document').json()['data']['discussion']
        assert (
            document['formation_summary']['current_step_ref'] == 's1'
            and document['view_progress']['focus'] is None
        )
        assert document['view_progress']['issue_total'] == 24 and 'progress_brief' not in document
        first = read(progress_group='issues', progress_limit=20).json()['data']['discussion'][
            'progress_brief'
        ]
        assert len(first['issues']) == 20 and first['issues'] != brief['issues']
        cursor = first['issue_next_cursor']
        last = read(progress_group='issues', progress_cursor=cursor, progress_limit=20).json()[
            'data'
        ]['discussion']['progress_brief']
        assert [i['issue_ref'] for i in last['issues']] == ['i21', 'i22', 'i23', 'i24'] and last[
            'issue_next_cursor'
        ] is None
        for other in (
            {'progress_group': 'decisions'},
            {'progress_group': 'issues', 'progress_step_ref': 's2'},
            {'progress_group': 'issues', 'document_id': 2},
        ):
            invalid = read(progress_cursor=cursor, **other)
            assert invalid.status_code == 422, invalid.text
        with db.transaction(write=True) as conn:
            conn.execute('UPDATE formation_heads SET version=2 WHERE document_id=1')
        changed = read(progress_group='issues', progress_cursor=cursor)
        assert changed.status_code == 409, changed.text
        assert changed.json()['error']['details']['reason'] == 'PATH_CHANGED'
        assert read(progress_group='issues').status_code == 200
        with db.transaction(write=True) as conn:
            conn.execute('UPDATE formation_heads SET current_step_ref=NULL WHERE document_id=1')
        whole = read().json()['data']['discussion']['progress_brief']
        assert whole['focus'] is None and whole['issue_total'] == 24
        assert whole['issues'][0]['step_ref'] == 's1' and whole['next']['ref'] == 'i1'


def test_unopened_mainline_and_shared_replacement_evidence_are_document_scoped(workspace):
    from backend.app.formation.progress_brief import progress_brief
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.app.requirements.queries import get_requirement

    db = workspace[0]
    with db.transaction() as conn:
        before = [
            conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]
            for table in ('formation_heads', 'guide_runs', 'document_change_audits', 'revisions')
        ]
    for _ in range(2):
        empty = get_requirement(db, 1, expand='discussion', document_id=1, progress_view='brief')
        assert empty['code'] == 'READ_OK'
        assert empty['data']['discussion']['progress_brief']['focus'] is None
    with db.transaction(write=True) as conn:
        assert before == [
            conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]
            for table in ('formation_heads', 'guide_runs', 'document_change_audits', 'revisions')
        ]
        head(conn)
        conn.execute("INSERT INTO formation_step_topics VALUES(1,'s1','t1')")
        root = RequirementRepository(conn).get_for_document(1, 1)
        source = [{'kind': 'MESSAGE', 'message_id': root['initial_message_id']}]
        common = {
            'origin': 'USER_STATEMENT',
            'nature': 'FACT',
            'applies_to': 'GLOBAL',
            'topic_refs': [],
            'source_refs': source,
        }
        root['discussion_state_json'].update(
            topics=[{'topic_ref': 't1', 'evidence_refs': ['e1']}],
            evidence=[
                {
                    **common,
                    'evidence_ref': 'e1',
                    'state': 'SUPERSEDED',
                    'assertion': '三天',
                    'supersedes': [],
                },
                {
                    **common,
                    'evidence_ref': 'e2',
                    'state': 'ACTIVE',
                    'assertion': '七天',
                    'supersedes': ['e1'],
                },
            ],
        )
        summary = {'current_step_ref': 's1', 'formation_version': 1, 'goal': None}
        for display in (False, True):
            values = progress_brief(conn, root, summary, display=display)['decisions']
            assert [(r['evidence_ref'], r['text']) for r in values] == [('e2', '七天')]
