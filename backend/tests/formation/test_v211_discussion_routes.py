"""V2.11 accepts one audited interpretation and atomically applies current document changes."""

import asyncio
import json
from copy import deepcopy
import pytest

from backend.app.formation.chat_operations import chat_operations
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_proposal_contracts import group
from backend.tests.guide.test_v15_execution import Gateway, PROFILE, Counter, output, delta
from backend.tests.guide.test_v15_counting import offline_gate

__all__ = ['released', 'database', 'base_workspace']


@pytest.fixture
def workspace(base_workspace, monkeypatch):
    offline_gate(monkeypatch)
    db, executor, catalog = base_workspace
    with db.transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "UPDATE formation_steps SET title='邀请权限',status='IN_PROGRESS' WHERE document_id=1"
        )
        connection.execute(
            "INSERT INTO formation_steps VALUES (1,'s2',1,2,2,'有效期','PLANNED',NULL)"
        )
        connection.execute(
            "INSERT INTO formation_results VALUES (1,'s2','s2.o1','确定时长','CONTENT')"
        )
        connection.execute(
            "UPDATE formation_heads SET next_step_no=3,current_step_ref='s1' WHERE document_id=1"
        )
    return db, executor, catalog.for_formation_profile(DEFAULT_PROFILE, discussion_routes=True)


def run(workspace, instruction, make):
    db, executor, catalog = workspace
    with db.transaction() as connection:
        head_row = connection.execute(
            'SELECT current_step_ref,active_branch_ref FROM formation_heads WHERE document_id=1'
        ).fetchone()
        step = head_row[0] if head_row is not None else None
    body = request(workspace, instruction=instruction)
    body['target']['discussion_step_ref'] = step
    if head_row is not None and head_row[1]:
        body['target'].update(discussion_branch_ref=head_row[1], branch_intent='ENTER')
    accepted_run = accepted(workspace, body)
    run_id = accepted_run['data']['guide_run_id']
    gateway = Gateway(make)
    result = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': run_id},
            process_lock=executor.process_lock,
            catalog=catalog,
            profile=PROFILE,
            gateway=gateway,
            counting_counter=Counter(['OK']),
        )
    )
    assert result['code'] == 'AI_FINISHED', result
    assert len(gateway.calls) == 1
    with db.transaction() as connection:
        saved = json.loads(
            connection.execute(
                'SELECT final_result_json FROM guide_runs WHERE id=?', (run_id,)
            ).fetchone()[0]
        )
    return saved


def route(context, changes, focus=None, routes=()):
    req = context.input['current_request']
    change = {
        'intent': 'EXECUTE',
        'directive': {'user_ref': req['message_ref'], 'quote': req['content']},
        'basis': context.canonical['formation']['basis'],
        'changes': changes,
        'result_routes': list(routes),
        'focus': focus or {'mode': 'KEEP', 'step_ref': None},
    }
    return output(
        context, progress_delta={**delta(context, indexed=False), 'formation_delta': change}
    )


def snapshot(db):
    with db.transaction() as conn:
        return (
            list(
                map(
                    tuple,
                    conn.execute(
                        'SELECT step_ref,title,status,position FROM formation_steps WHERE document_id=1 ORDER BY position'
                    ),
                )
            ),
            conn.execute(
                'SELECT current_step_ref FROM formation_heads WHERE document_id=1'
            ).fetchone()[0],
        )


def test_question_then_compound_instruction_and_failed_focus(workspace):
    asked = run(workspace, '如果调整有效期的位置呢？', output)
    assert asked['formation_effect'] is None
    initial = snapshot(workspace[0])
    move = [{'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}]

    def invalid(context):
        result = route(context, move, {'mode': 'STEP', 'step_ref': 's99'})
        return result

    failed = run(workspace, '把有效期提前并切到不存在的步骤', invalid)
    assert failed['effect_state'] == 'STRUCTURED_REJECTED'
    assert snapshot(workspace[0]) == initial
    changed = run(
        workspace,
        '把有效期提前，并先聊有效期',
        lambda c: route(c, move, {'mode': 'STEP', 'step_ref': 's2'}),
    )
    assert changed['effect_state'] == 'APPLIED', changed
    rows, focus = snapshot(workspace[0])
    assert [r[0] for r in rows] == ['s2', 's1'] and focus == 's2' and rows[0][2] == 'IN_PROGRESS'
    with workspace[0].transaction() as conn:
        mid = changed['assistant_message_id']
        receipt = chat_operations(conn, 1, 1, [mid])[mid]
        assert (
            len(receipt) == 1
            and receipt[0]['kind'] == 'UPDATED'
            and receipt[0]['focus_title'] == '有效期'
        )

    def resume(context):
        material = context.input['project_position']['formation']
        assert material['selected_step']['title'] == '有效期'
        assert [s['title'] for s in material['route_context']['order']] == ['有效期', '邀请权限']
        return output(context)

    run(workspace, '继续', resume)


def test_adopt_only_the_immediate_immutable_route_proposal(workspace):
    def suggest(context):
        card = group('FORMATION_PATH_CHANGE')
        payload = card['action_payload']
        payload['basis'] = deepcopy(context.canonical['formation']['basis'])
        payload['source_refs'] = [context.input['current_request']['message_ref']]
        return output(context, cards=card)

    proposed = run(workspace, '你建议下一步怎么安排？', suggest)
    assert proposed['effect_state'] == 'APPLIED', proposed

    def adopt(context):
        candidate = context.input['project_position']['formation']['route_context'][
            'previous_proposal'
        ]
        req = context.input['current_request']
        value = {
            'intent': 'ADOPT',
            'focus': {'mode': 'STEP', 'step_ref': 's2'},
            'directive': {'user_ref': req['message_ref'], 'quote': req['content']},
            'basis': context.canonical['formation']['basis'],
            'proposal_ref': candidate['proposal_ref'],
            'payload_digest': candidate['payload_digest'],
        }
        return output(
            context, progress_delta={**delta(context, indexed=False), 'formation_delta': value}
        )

    saved = run(workspace, '可以，按刚才那版改，然后先聊有效期。', adopt)
    assert saved['effect_state'] == 'APPLIED', saved
    with workspace[0].transaction() as conn:
        assert (
            conn.execute('SELECT disposition FROM formation_proposal_index').fetchone()[0]
            == 'APPLIED'
        )
        assert conn.execute('SELECT count(*) FROM formation_steps').fetchone()[0] == 3
        mid = saved['assistant_message_id']
        receipts = chat_operations(conn, 1, 1, [mid])[mid]
        assert [(r['kind'], r['focus_title']) for r in receipts] == [('UPDATED', '有效期')]

    def again(context):
        assert (
            context.input['project_position']['formation']['route_context']['previous_proposal']
            is None
        )
        return output(context)

    run(workspace, '可以', again)


def test_ambiguous_discussion_cannot_adopt_unpublished_alternatives(workspace):
    before = snapshot(workspace[0])

    def suggest(context):
        response = output(context)
        response['message'] = '有两种方案：把有效期放到权限之前，或者保留顺序、先聊有效期。'
        return response

    suggestions = run(workspace, '有哪些安排？', suggest)

    def attempt(context):
        assert (
            context.input['project_position']['formation']['route_context']['previous_proposal']
            is None
        )
        return interpreted(
            context,
            'ADOPT',
            proposal_ref={'message_id': suggestions['assistant_message_id'], 'card_key': 'c1'},
            payload_digest='0' * 64,
        )

    ambiguous = run(workspace, '可以。', attempt)
    assert ambiguous['effect_state'] == 'STRUCTURED_REJECTED'
    from backend.app.messages.queries import get_message

    message = get_message(workspace[0], 1, ambiguous['assistant_message_id'])['data']
    assert '具体方案' in message['content']
    assert 'formation_operations' not in message
    assert snapshot(workspace[0]) == before


def test_split_requires_complete_result_handoff_then_resolves_new_focus(workspace):
    from backend.tests.formation.test_v21_contracts import add_step

    additions = [add_step(1), add_step(2)]
    for row, title in zip(additions, ['默认时长', '续期'], strict=True):
        row.update(title=title, before_step_ref='s1', replaces_step_refs=['s2'])
    changes = [
        *additions,
        {
            'type': 'CANCEL_STEP',
            'step_ref': 's2',
            'replacement_step_refs': ['new_step_1', 'new_step_2'],
        },
    ]
    focus = {'mode': 'STEP', 'step_ref': 'new_step_1'}
    note = '把有效期拆为默认时长和续期，放在邀请权限前面，先聊默认时长。'
    rejected = run(workspace, note, lambda c: route(c, changes, focus))
    assert rejected['effect_state'] == 'STRUCTURED_REJECTED'
    assert [row[0] for row in snapshot(workspace[0])[0]] == ['s1', 's2']
    routes = [
        {
            'from_result_ref': 's2.o1',
            'disposition': 'REPLACED',
            'target_result_refs': ['new_result_1', 'new_result_2'],
            'reason': '原时长成果分别由默认时长与续期承接',
        }
    ]
    assert rejected['route_clarification']['user_message_id']

    def clarify(c):
        assert note in json.dumps(c.input, ensure_ascii=False)
        material = c.input['project_position']['formation']
        assert any(
            row['ref'] == 's2' and row.get('definition') for row in material['coverage']['included']
        )
        return route(c, changes, focus, routes)

    result = run(workspace, '原有成果由这两个新步骤共同承接，按刚才的安排改。', clarify)
    assert result['effect_state'] == 'APPLIED', result
    rows, current = snapshot(workspace[0])
    assert [row[1] for row in rows if row[2] != 'CANCELLED'] == ['默认时长', '续期', '邀请权限']
    assert current == 's3' and len(result['formation_effect']['reference_map']) == 4
    with workspace[0].transaction() as conn:
        mid = result['assistant_message_id']
        operations = chat_operations(conn, 1, 1, [mid])[mid]
        assert (
            len(operations) == 1
            and operations[0]['kind'] == 'UPDATED'
            and operations[0]['focus_title'] == '默认时长'
            and '已拆分步骤' in operations[0]['actions']
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM document_change_audits WHERE source_id=? AND reason_code='RESULT_ROUTE'",
                (mid,),
            ).fetchone()[0]
            == 1
        )


def test_unbound_or_misquoted_structural_output_fails_closed(workspace):
    def attempt(context):
        result = route(context, [{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '不可提交'}])
        result['progress_delta']['formation_delta']['directive']['quote'] = '不存在的指令'
        return result

    result = run(workspace, '他说要修改邀请权限，我不同意。', attempt)
    assert result['effect_state'] == 'STRUCTURED_REJECTED'
    assert snapshot(workspace[0])[0][0][1] == '邀请权限'


def interpreted(context, intent, **fields):
    req = context.input['current_request']
    value = {'intent': intent, 'basis': context.canonical['formation']['basis'], **fields}
    if intent != 'SUGGEST_INITIAL':
        value['directive'] = {'user_ref': req['message_ref'], 'quote': req['content']}
    return output(
        context, progress_delta={**delta(context, indexed=False), 'formation_delta': value}
    )


def test_initial_proposal_has_no_route_then_adopts_exact_steps(base_workspace, monkeypatch):
    from backend.tests.formation.test_v21_model_contracts import examples

    offline_gate(monkeypatch)
    db, executor, catalog = base_workspace
    workspace = (db, executor, catalog.for_formation_profile(DEFAULT_PROFILE))
    steps = deepcopy(examples()[0]['steps'])
    extra = deepcopy(steps[0])
    extra.update(temp_ref='new_step_2', title='邀请通知')
    extra['expected_results'][0]['temp_ref'] = 'new_result_2'
    steps.append(extra)
    invalid = run(
        workspace,
        '创建这两步并从第三步谈起。',
        lambda c: interpreted(c, 'CREATE_INITIAL', goal='邀请流程', steps=steps, focus_position=3),
    )
    assert invalid['effect_state'] == 'STRUCTURED_REJECTED'
    with db.transaction() as conn:
        assert not conn.execute('SELECT 1 FROM formation_heads').fetchone()
    first = run(
        workspace,
        '想做邀请流程，建议怎么讨论？',
        lambda c: interpreted(c, 'SUGGEST_INITIAL', goal='邀请流程', steps=steps),
    )
    assert first['effect_state'] == 'APPLIED', first
    with db.transaction() as conn:
        assert not conn.execute('SELECT 1 FROM formation_heads').fetchone()
        assert chat_operations(conn, 1, 1, [first['assistant_message_id']]) == {}

    from backend.app.messages.queries import get_message, list_messages

    original = get_message(db, 1, first['assistant_message_id'])['data']
    assert original['initial_route_suggestion'] == {
        'goal': '邀请流程',
        'steps': [
            {
                'title': s['title'],
                'expected_results': [r['description'] for r in s['expected_results']],
            }
            for s in steps
        ],
    }
    assert 'formation_operations' not in original
    window = list_messages(db, {'requirement_id': 1, 'document_id': 1})['data']['items']
    assert next(m for m in window if m['id'] == original['id']) == original

    def adopt(context):
        candidate = context.input['project_position']['formation']['route_context'][
            'initial_proposal'
        ]
        assert candidate['titles'] == [s['title'] for s in steps]
        return interpreted(
            context,
            'ADOPT_INITIAL',
            focus_position=2,
            message_id=candidate['message_id'],
            payload_digest=candidate['payload_digest'],
        )

    saved = run(workspace, '按刚才这条建主线，先谈第二步邀请通知。', adopt)
    assert saved['effect_state'] == 'APPLIED', saved
    assert (
        'initial_route_suggestion' not in get_message(db, 1, saved['assistant_message_id'])['data']
    )
    assert get_message(db, 1, first['assistant_message_id'])['data'] == original
    with db.transaction() as conn:
        assert conn.execute('SELECT goal_text FROM formation_heads').fetchone()[0] == '邀请流程'
        assert [
            r[0] for r in conn.execute('SELECT title FROM formation_steps ORDER BY position')
        ] == [s['title'] for s in steps]
        mid = saved['assistant_message_id']
        assert conn.execute('SELECT current_step_ref FROM formation_heads').fetchone()[0] == 's2'
        receipt = chat_operations(conn, 1, 1, [mid])[mid]
        assert len(receipt) == 1
        assert (receipt[0]['kind'], receipt[0]['focus_title']) == ('CREATED', '邀请通知')


def test_explicit_creation_enters_the_requested_step_in_the_same_batch(base_workspace, monkeypatch):
    from backend.tests.formation.test_v21_model_contracts import examples

    offline_gate(monkeypatch)
    db, executor, catalog = base_workspace
    ws = (db, executor, catalog.for_formation_profile(DEFAULT_PROFILE))
    first = deepcopy(examples()[0]['steps'][0])
    second = deepcopy(first)
    second.update(temp_ref='new_step_2', title='决定通知范围')
    second['expected_results'][0]['temp_ref'] = 'new_result_2'
    result = run(
        ws,
        '建一条主线，先列明确范围，再列决定通知范围，从第二步开始谈。',
        lambda c: interpreted(
            c, 'CREATE_INITIAL', goal='设计通知', steps=[first, second], focus_position=2
        ),
    )
    assert result['effect_state'] == 'APPLIED', result
    rows, focus = snapshot(db)
    assert [(row[1], row[2]) for row in rows] == [
        (first['title'], 'PLANNED'),
        (second['title'], 'IN_PROGRESS'),
    ]
    assert focus == 's2'
    with db.transaction() as conn:
        mid = result['assistant_message_id']
        receipts = chat_operations(conn, 1, 1, [mid])[mid]
        assert [(r['kind'], r['focus_title']) for r in receipts] == [('CREATED', second['title'])]


def test_restore_order_preserves_intervening_messages_and_document(workspace):
    db = workspace[0]
    move = [{'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}]
    done = run(workspace, '把有效期提到邀请权限前面', lambda c: route(c, move))
    assert done['effect_state'] == 'APPLIED'
    intervening = run(
        workspace,
        '确认：邀请应由管理员发起。',
        lambda c: output(c, progress_delta={**delta(c), 'formation_delta': None}),
    )
    assert intervening['effect_state'] == 'APPLIED'
    with db.transaction() as conn:
        old = conn.execute(
            'SELECT discussion_state_json,content_version FROM requirement_documents WHERE id=1'
        ).fetchone()
        prior_evidence = json.loads(old[0])['evidence']
        assert prior_evidence

    def restore(c):
        candidate = c.input['project_position']['formation']['route_context']['previous_order']
        return interpreted(
            c,
            'RESTORE_ORDER',
            batch_id=candidate['batch_id'],
            focus={'mode': 'KEEP', 'step_ref': None},
        )

    restored = run(workspace, '把上次顺序改回来，其他保持。', restore)
    assert restored['effect_state'] == 'APPLIED', restored
    assert [row[0] for row in snapshot(db)[0]] == ['s1', 's2']
    with db.transaction() as conn:
        new = conn.execute(
            'SELECT discussion_state_json,content_version FROM requirement_documents WHERE id=1'
        ).fetchone()
        assert (
            new[1] == old[1]
            and json.loads(new[0])['evidence'][: len(prior_evidence)] == prior_evidence
        )
        mid = restored['assistant_message_id']
        assert chat_operations(conn, 1, 1, [mid])[mid][0]['moves']


def test_lifecycle_completion_reopen_and_pause_use_the_actual_dialogue(workspace):
    db = workspace[0]
    before = run(workspace, '这步聊清楚了。', output)
    assert before['formation_effect'] is None

    def emit(instruction, command):
        return run(workspace, instruction, lambda c: interpreted(c, 'LIFECYCLE', command=command))

    invalid = emit(
        '结束邀请权限，同时转交给不存在的步骤',
        {
            'action': 'COMPLETE_STEP',
            'step_ref': 's1',
            'next_step_ref': 's99',
            'result_dispositions': [],
            'issue_dispositions': [],
            'branch_dispositions': [],
        },
    )
    assert invalid['effect_state'] == 'STRUCTURED_REJECTED'
    finished = emit(
        '结束邀请权限，下一步聊有效期。',
        {
            'action': 'COMPLETE_STEP',
            'step_ref': 's1',
            'next_step_ref': 's2',
            'result_dispositions': [],
            'issue_dispositions': [],
            'branch_dispositions': [],
        },
    )
    assert finished['effect_state'] == 'APPLIED', finished
    with db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM document_change_audits WHERE reason_code='STEP_COMPLETED' AND source_type='AI_MESSAGE' AND source_id=?",
                (finished['assistant_message_id'],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM conversation_messages WHERE role='USER' AND guide_run_id IS NULL AND content LIKE '结束步骤%'"
            ).fetchone()[0]
            == 0
        )
    assert snapshot(db)[1] == 's2'
    reopened = emit('重新打开邀请权限', {'action': 'REOPEN_STEP', 'step_ref': 's1'})
    assert reopened['effect_state'] == 'APPLIED', reopened
    assert snapshot(db)[1] == 's1'
    paused = emit('先暂停邀请权限，回到整篇讨论。', {'action': 'PAUSE_STEP', 'step_ref': 's1'})
    assert paused['effect_state'] == 'APPLIED', paused
    assert snapshot(db)[1] is None


def test_merge_transfers_open_issue_dependency_and_preserves_version(workspace):
    from backend.tests.formation.test_v21_contracts import add_step

    db = workspace[0]
    with db.transaction(write=True) as conn:
        conn.execute("INSERT INTO formation_steps VALUES(1,'s3',1,2,3,'邮件通知','PLANNED',NULL)")
        conn.execute("INSERT INTO formation_results VALUES(1,'s3','s3.o1','通知内容','CONTENT')")
        conn.execute("INSERT INTO formation_step_edges VALUES(1,'s3','s2','DEPENDENCY')")
        conn.execute(
            "INSERT INTO formation_issues VALUES(1,'i1','s2',NULL,'哪个角色可以续期？','[]',1,'OPEN',NULL,'[]',NULL)"
        )
        conn.execute(
            'UPDATE formation_heads SET next_step_no=4,next_issue_no=2 WHERE document_id=1'
        )
        revisions = list(
            conn.execute('SELECT id,markdown_snapshot FROM revisions WHERE document_id=1')
        )
    step = add_step(1)
    step.update(title='邀请规则', replaces_step_refs=['s1', 's2'], before_step_ref='s1')
    changes = [
        step,
        {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 'new_step_1'},
        {'type': 'SET_DEPENDENCIES', 'step_ref': 's3', 'dependencies': ['new_step_1']},
        *[
            {'type': 'CANCEL_STEP', 'step_ref': s, 'replacement_step_refs': ['new_step_1']}
            for s in ('s1', 's2')
        ],
    ]
    routes = [
        {
            'from_result_ref': ref + '.o1',
            'disposition': 'REPLACED',
            'target_result_refs': ['new_result_1'],
            'reason': '统一到邀请规则',
        }
        for ref in ('s1', 's2')
    ]
    assertion = '仅管理员可以修改邀请权限。'

    def decide(context):
        progress = delta(context)
        progress['evidence_changes'][0]['assertion'] = assertion
        progress.update(
            formation_delta=None, step_evidence_links=[{'step_ref': 's1', 'evidence_ref': 'new_e1'}]
        )
        return output(context, progress_delta=progress)

    assert run(workspace, assertion, decide)['effect_state'] == 'APPLIED'

    def merge(context):
        response = route(context, changes, {'mode': 'STEP', 'step_ref': 'new_step_1'}, routes)
        decision = context.input['project_position']['formation']['route_context']['decisions'][0]
        response['progress_delta']['step_evidence_links'] = [
            {'step_ref': 'new_step_1', 'evidence_ref': decision['evidence_ref']}
        ]
        return response

    done = run(
        workspace,
        '把邀请权限和有效期合并为邀请规则，保留管理员权限结论，把续期问题转过去，邮件通知依赖新步骤，并先聊邀请规则。',
        merge,
    )
    assert done['effect_state'] == 'APPLIED', done
    from backend.app.requirements.queries import get_requirement

    brief = get_requirement(db, 1, document_id=1, expand='discussion', progress_view='brief')[
        'data'
    ]['discussion']['progress_brief']
    assert brief['focus']['step_ref'] == 's4'
    assert [(r['text'], r['step_ref']) for r in brief['decisions']] == [(assertion, 's4')]
    with db.transaction() as conn:
        mid = done['assistant_message_id']
        assert '已合并步骤' in chat_operations(conn, 1, 1, [mid])[mid][0]['actions']
        assert (
            conn.execute("SELECT step_ref FROM formation_issues WHERE issue_ref='i1'").fetchone()[0]
            == 's4'
        )
        assert {
            tuple(r)
            for r in conn.execute(
                "SELECT from_step_ref,to_step_ref FROM formation_step_edges WHERE kind='DEPENDENCY' AND from_step_ref='s3'"
            )
        } == {('s3', 's4')}
        assert (
            list(conn.execute('SELECT id,markdown_snapshot FROM revisions WHERE document_id=1'))
            == revisions
        )
        assert {
            r[0]
            for r in conn.execute(
                "SELECT to_step_ref FROM formation_step_edges WHERE kind='REPLACES' AND from_step_ref='s4'"
            )
        } == {'s1', 's2'}


def test_goal_rename_results_and_branch_recovery(workspace):
    from backend.tests.formation.test_v21_completion_commands import association_event
    from backend.app.infrastructure.requirement_repository import RequirementRepository

    db = workspace[0]
    with db.transaction(write=True) as conn:
        root = RequirementRepository(conn).get_for_document(1, 1)
        event = association_event(conn, root)
        conn.execute(
            "INSERT INTO formation_branches VALUES(1,'b1','s1','s1','谁能代理邀请？','需要确认代理范围','OPEN',?,?,NULL,'[]',NULL)",
            (event, event),
        )
        conn.execute('UPDATE formation_heads SET next_branch_no=2 WHERE document_id=1')

    def edit(c):
        return route(
            c,
            [
                {
                    'type': 'SET_GOAL',
                    'text': '明确邀请策略',
                    'source_refs': [c.input['current_request']['message_ref']],
                },
                {'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '邀请时长'},
                {
                    'type': 'UPDATE_RESULT',
                    'result_ref': 's2.o1',
                    'description': '明确邀请的有效时长',
                },
                {
                    'type': 'ADD_RESULT',
                    'step_ref': 's2',
                    'temp_result_ref': 'new_result_1',
                    'description': '定义续期规则',
                    'kind': 'CONTENT',
                },
            ],
        )

    saved = run(
        workspace, '目标改为明确邀请策略，有效期改名邀请时长，明确时长并新增续期规则成果。', edit
    )
    assert saved['effect_state'] == 'APPLIED', saved
    with db.transaction() as conn:
        assert conn.execute('SELECT goal_text FROM formation_heads').fetchone()[0] == '明确邀请策略'
        assert [
            r[0]
            for r in conn.execute(
                "SELECT description FROM formation_results WHERE step_ref='s2' ORDER BY result_ref"
            )
        ] == ['明确邀请的有效时长', '定义续期规则']

    def emit(text, command):
        result = run(workspace, text, lambda c: interpreted(c, 'LIFECYCLE', command=command))
        assert result['effect_state'] == 'APPLIED', result

    emit('先谈谁能代理邀请？', {'action': 'ENTER_BRANCH', 'branch_ref': 'b1', 'step_ref': 's1'})
    emit('回到邀请权限主线', {'action': 'RETURN_FROM_BRANCH', 'branch_ref': 'b1'})
    emit(
        '暂缓谁能代理邀请？等业务确认。',
        {
            'action': 'DISPOSE_BRANCH',
            'branch_ref': 'b1',
            'disposition': 'DEFERRED',
            'reason': '等业务确认',
        },
    )

    def restore(c):
        branch = next(
            row['definition']
            for row in c.input['project_position']['formation']['coverage']['included']
            if row['kind'] == 'BRANCH' and row['ref'] == 'b1'
        )
        return interpreted(
            c,
            'LIFECYCLE',
            command={
                'action': 'RESUME_BRANCH',
                'branch_ref': 'b1',
                'step_ref': 's1',
                'expected_branch_status': branch['status'],
                'expected_branch_event_id': branch['state_event_ref'],
                'enter_after_resume': True,
            },
        )

    resumed = run(workspace, '继续讨论谁能代理邀请？', restore)
    assert resumed['effect_state'] == 'APPLIED', resumed
    with db.transaction() as conn:
        assert (
            conn.execute("SELECT status FROM formation_branches WHERE branch_ref='b1'").fetchone()[
                0
            ]
            == 'OPEN'
        )
        assert conn.execute('SELECT active_branch_ref FROM formation_heads').fetchone()[0] == 'b1'


def test_explicit_write_failure_and_later_content_revision_keep_separate_proofs(workspace):
    from backend.app.guide.commands import create_guide_run
    from backend.app.requirements.queries import get_requirement
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from uuid import uuid4

    db, executor, catalog = workspace
    assertion = '默认邀请有效期为七天。'

    def revise(instruction, content, *, bad_target=False, with_decision=False):
        with db.transaction() as conn:
            root = RequirementRepository(conn).get_for_document(1, 1)
            doc = conn.execute(
                'SELECT name,content_version FROM requirement_documents WHERE id=1'
            ).fetchone()
        body = {
            'requirement_id': 1,
            'document_id': 1,
            'expected_discussion_version': root['discussion_version'],
            'operation': 'REVISE',
            'proposal_ref': None,
            'acknowledge_source_changes': False,
            'instruction': instruction,
            'target': {'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': doc[1]},
            'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            'source_refs': [],
            'idempotency_key': str(uuid4()),
        }
        accepted_result = create_guide_run(executor, body, catalog=catalog)
        assert accepted_result['code'] == 'GUIDE_ACCEPTED', accepted_result
        rid = accepted_result['data']['guide_run_id']

        def make(c):
            progress = None
            if with_decision:
                progress = {**delta(c), 'formation_delta': None}
                progress['evidence_changes'][0]['assertion'] = assertion
            return output(
                c,
                response_type='DOCUMENT_RESULT',
                progress_delta=progress,
                document_result={
                    'name': '错误目标' if bad_target else doc['name'],
                    'document_kind': c.input['current_request']['basis_ref']['document_kind'],
                    'markdown_content': content,
                    'change_summary': '按用户要求更新邀请时长',
                },
            )

        got = asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': rid},
                process_lock=executor.process_lock,
                catalog=catalog,
                profile=PROFILE,
                gateway=Gateway(make),
                counting_counter=Counter(['OK']),
            )
        )
        assert got['code'] == 'AI_FINISHED', got
        with db.transaction() as conn:
            return json.loads(
                conn.execute(
                    'SELECT final_result_json FROM guide_runs WHERE id=?', (rid,)
                ).fetchone()[0]
            )

    with db.transaction(write=True) as conn:
        conn.execute('UPDATE formation_heads SET current_step_ref=NULL WHERE document_id=1')

    def writing():
        detail = get_requirement(db, 1, document_id=1, expand='discussion', progress_view='brief')
        assert detail['code'] == 'READ_OK', detail
        decision = next(
            r
            for r in detail['data']['discussion']['progress_brief']['decisions']
            if r['text'] == assertion
        )
        return decision['writing']

    failed = revise('确认并写入：' + assertion, assertion, bad_target=True, with_decision=True)
    assert (
        failed['progress_result'] == 'APPLIED' and failed['application_result'] == 'NOT_APPLIED'
    ), failed
    assert writing()['state'] == 'FAILED'
    written = revise('把已确认的有效期写入正文。', assertion)
    assert written['application_result'] == 'APPLIED', written
    current = writing()
    assert (
        current['state'] == 'CURRENT'
        and current['version'] == written['document_effect']['after_content_version']
    )
    later_failure = revise('再尝试写入该结论。', assertion, bad_target=True)
    assert later_failure['application_result'] == 'NOT_APPLIED'
    assert writing() == {
        **current,
        'source_refs': [
            *current['source_refs'],
            {'kind': 'MESSAGE', 'message_id': later_failure['assistant_message_id']},
        ],
    }
    current = writing()
    revised = revise('把期限段落替换为另行约定。', '邀请期限另行约定。')
    assert revised['application_result'] == 'APPLIED', revised
    assert writing() == {**current, 'state': 'HISTORICAL'}


def test_step_decision_links_and_user_correction_survive_subsequent_discussion(workspace):
    from backend.app.requirements.queries import get_requirement

    def observe(c):
        change = {
            **delta(c),
            'formation_delta': None,
            'step_evidence_links': [{'step_ref': 's1', 'evidence_ref': 'new_e1'}],
        }
        change['evidence_changes'][0]['assertion'] = c.input['current_request']['content']
        return output(c, progress_delta=change)

    def shown(step):
        value = get_requirement(
            workspace[0],
            1,
            document_id=1,
            expand='discussion',
            progress_view='brief',
            progress_step_ref=step,
        )
        assert value['code'] == 'READ_OK', value
        return value['data']['discussion']['view_progress']['decisions']

    original = run(workspace, '默认三天。', observe)
    assert original['effect_state'] == 'APPLIED', original
    assert original['step_evidence_links'] == [{'step_ref': 's1', 'evidence_ref': 'e1'}]
    assert [r['text'] for r in shown('s1')] == ['默认三天。'] and shown('s2') == []

    def correct(c):
        progress = {**delta(c), 'formation_delta': None}
        progress['evidence_changes'][0].update(
            change='USER_REPLACE',
            assertion=c.input['current_request']['content'],
            supersedes=['e1'],
        )
        return output(c, progress_delta=progress)

    revised = run(workspace, '默认七天。', correct)
    assert revised['effect_state'] == 'APPLIED', revised
    assert [r['text'] for r in shown('s1')] == ['默认七天。'] and not shown('s2')

    def carry(c):
        assert [
            r['text']
            for r in c.input['project_position']['formation']['route_context']['decisions']
        ] == ['默认七天。']
        return output(c)

    run(workspace, '继续', carry)
    run_before = snapshot(workspace[0])

    def invalid(c):
        progress = {
            **delta(c),
            'formation_delta': None,
            'step_evidence_links': [{'step_ref': 's99', 'evidence_ref': 'new_e1'}],
        }
        return output(c, progress_delta=progress)

    rejected = run(workspace, '请将决定关联到不存在的步骤。', invalid)
    assert (
        rejected['effect_state'] == 'STRUCTURED_REJECTED' and 'step_evidence_links' not in rejected
    )
    assert snapshot(workspace[0]) == run_before and [r['text'] for r in shown('s1')] == [
        '默认七天。'
    ]


def test_focus_only_history_survives_rename_and_speculation(workspace):
    before = snapshot(workspace[0])
    for text in ('他说“把有效期删掉”，我不同意。', '顺便问一句，有效期是什么意思？'):
        response = run(workspace, text, output)
        assert not response['formation_effect'] and snapshot(workspace[0]) == before
    focused = run(
        workspace,
        '接下来先谈有效期，顺序不动。',
        lambda c: route(c, [], {'mode': 'STEP', 'step_ref': 's2'}),
    )
    assert focused['effect_state'] == 'APPLIED'
    assert [r[0] for r in snapshot(workspace[0])[0]] == ['s1', 's2'] and snapshot(workspace[0])[
        1
    ] == 's2'
    renamed = run(
        workspace,
        '把有效期改名为邀请时长。',
        lambda c: route(c, [{'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '邀请时长'}]),
    )
    assert renamed['effect_state'] == 'APPLIED', renamed
    with workspace[0].transaction() as conn:
        first = focused['assistant_message_id']
        old = chat_operations(conn, 1, 1, [first])[first]
        assert len(old) == 1 and old[0]['kind'] == 'FOCUSED'
        assert (old[0]['previous_focus_title'], old[0]['focus_title']) == ('邀请权限', '有效期')
        assert (
            '已修改步骤名称'
            in chat_operations(conn, 1, 1, [renamed['assistant_message_id']])[
                renamed['assistant_message_id']
            ][0]['actions']
        )

    def revisit(c):
        assert c.input['project_position']['formation']['selected_step']['title'] == '邀请时长'
        return output(c)

    run(workspace, '继续', revisit)


def test_over_budget_and_changed_basis_never_partially_apply(workspace):
    db = workspace[0]
    before = snapshot(db)
    move = {'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}
    over = run(workspace, '把有效期和邀请权限的顺序调整二十一次。', lambda c: route(c, [move] * 21))
    assert over['effect_state'] == 'STRUCTURED_REJECTED' and '上限' in over['progress_error'], over
    assert snapshot(db) == before

    def stale(c):
        # Simulate a concurrent committed version arriving after the actual input was frozen.
        with db.transaction(write=True) as conn:
            conn.execute('UPDATE formation_heads SET version=version+1 WHERE document_id=1')
            conn.execute(
                "UPDATE formation_steps SET title='另一标签保存的有效期' WHERE document_id=1 AND step_ref='s2'"
            )
        return route(c, [move])

    rejected = run(workspace, '将有效期移到邀请权限之前。', stale)
    assert (
        rejected['effect_state'] == 'STRUCTURED_REJECTED' and '已变化' in rejected['progress_error']
    ), rejected
    rows, focused = snapshot(db)
    assert (
        [r[0] for r in rows] == ['s1', 's2']
        and rows[1][1] == '另一标签保存的有效期'
        and focused == 's1'
    )
    with db.transaction() as conn:
        assert (
            chat_operations(
                conn, 1, 1, [over['assistant_message_id'], rejected['assistant_message_id']]
            )
            == {}
        )


def test_unread_remote_step_cannot_be_changed_from_an_invented_reference(workspace):
    db = workspace[0]
    with db.transaction(write=True) as conn:
        conn.executemany(
            "INSERT INTO formation_steps VALUES (1,?,1,2,?,?,'PLANNED',NULL)",
            [('s' + str(i), i, '工作项' + str(i)) for i in range(3, 107)],
        )
        conn.execute('UPDATE formation_heads SET next_step_no=107 WHERE document_id=1')
    before = snapshot(db)

    def attempt(context):
        actual = context.input['project_position']['formation']
        assert actual['route_context']['step_total'] == 106
        assert 's106' not in {r['step_ref'] for r in actual['route_context']['order']}
        return route(context, [{'type': 'RENAME_STEP', 'step_ref': 's106', 'title': '指定名称'}])

    result = run(workspace, '把之前没点名的那个工作项改个名字。', attempt)
    assert result['effect_state'] == 'STRUCTURED_REJECTED' and '依据' in result['progress_error']
    assert snapshot(db) == before
    with db.transaction() as conn:
        assert chat_operations(conn, 1, 1, [result['assistant_message_id']]) == {}


def test_lost_response_replays_committed_discussion_and_receipt_once(workspace):
    from backend.app.guide.commands import create_guide_run
    from backend.app.guide.queries import get_guide_run

    db, executor, catalog = workspace
    body = request(workspace, instruction='把有效期移到邀请权限前面。')
    body['target']['discussion_step_ref'] = 's1'
    accepted_result = accepted(workspace, body)
    rid = accepted_result['data']['guide_run_id']
    gateway = Gateway(
        lambda c: route(c, [{'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}])
    )

    def execute_again():
        return asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': rid},
                process_lock=executor.process_lock,
                catalog=catalog,
                profile=PROFILE,
                gateway=gateway,
                counting_counter=Counter(['OK']),
            )
        )

    assert execute_again()['code'] == 'AI_FINISHED'
    assert create_guide_run(executor, body, catalog=catalog) == accepted_result
    execute_again()
    assert len(gateway.calls) == 1
    result = get_guide_run(db, rid, catalog=catalog)
    assert result['code'] == 'READ_OK' and result['data']['status'] == 'COMPLETED'
    with db.transaction() as conn:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'",
                (rid,),
            )
        ]
        assert len(ids) == 1 and len(chat_operations(conn, 1, 1, ids)[ids[0]]) == 1
