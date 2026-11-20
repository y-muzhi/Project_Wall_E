"""Isolated complete product probes; temporary API/Vite/CLI artifacts always cleaned.

Uses the installed Playwright CLI and real Schema210 HTTP paths with explicitly
offline Counter/Gateway substitutes. No real provider or normal data access.
Run one case at a time; --case all runs the independent environments serially.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXACT_CARD_CASES = frozenset(
    ('narrow-patch', 'two-tab-content', 'two-tab-focus', 'withdraw-refresh', 'withdraw-unknown')
)
CONTENT_CASES = EXACT_CARD_CASES | frozenset(
    (
        'viewport',
        'manual-viewport',
        'history-viewport',
        'busy-viewport',
        'full-shell',
        'narrow-errors',
        'zoom-200',
        'recommendation-coverage',
        'keyboard-route',
    )
)


def serve():
    import asyncio
    import os
    import sys
    import threading
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from backend.app.infrastructure.sqlite_runtime import activate

    activate()
    from tools.quality_python import install_guards

    temporary = Path(os.environ['WALLE_CHECK_TEMP'])
    install_guards(root, temporary)
    import pytest
    import uvicorn

    from backend.app.guide.worker import GuideWorker
    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.formation_schema_release import load_release
    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
    from backend.app.service import create_app
    from backend.tests.formation.test_v21_completion_commands import seed
    from backend.tests.formation.test_v21_discuss_acceptance import accepted, request
    from backend.tests.formation.test_v21_resume_terminal_matrix import result_output, run_round
    from backend.tests.formation.test_v21_schema import workspace as fixture
    from backend.tests.guide.test_v15_counting import Counter, offline_gate
    from backend.tests.guide.test_v15_execution import PROFILE, Gateway, output

    patch = pytest.MonkeyPatch()
    offline_gate(patch)
    if os.environ.get('W21_BROWSER_CASE', '').startswith('resume-'):
        from tools.formation_resume_probe import install_diagnostics

        install_diagnostics(patch)
    db = FormationDatabase(temporary / 'browser.sqlite', formation_release=load_release())
    db.initialize()
    fixture_gen = fixture.__wrapped__(db)
    raw = next(fixture_gen)
    workspace = (raw[0], raw[1], raw[2].for_formation_profile(DEFAULT_PROFILE))
    if os.environ.get('W21_BROWSER_CASE') in CONTENT_CASES:
        from backend.tests.documents.test_v15_editing import candidate, finish, save, start

        editing = start(workspace, identity=1, version=1)
        assert editing['code'] == 'DRAFT_STARTED', editing
        draft = editing['data']['manual_draft']
        proposed = candidate(
            workspace,
            draft,
            '# 窄窗正文\n\n正文宿主在尺寸变化中保持。\n\n## 核对范围\n\n原始正文不得被尺寸变化修改。\n',
        )
        saved = save(workspace, draft, proposed)
        assert saved['code'] == 'DRAFT_SAVED', saved
        completed = finish(workspace, saved['data'])
        assert completed['code'] == 'DRAFT_COMPLETED', completed
    seed(workspace, related=True)
    if os.environ.get('W21_BROWSER_CASE') in CONTENT_CASES:
        from backend.app.formation.commands import update_path
        from backend.tests.formation.test_v21_path_commands import request as path_request

        result = update_path(
            workspace[1],
            path_request(
                workspace,
                [
                    {'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '窄窗标题' * 30},
                    {'type': 'SET_GOAL', 'text': '目标说明' * 250, 'source_refs': []},
                ],
            ),
            catalog=workspace[2],
        )
        assert result['code'] == 'UPDATED', result
    if os.environ.get('W21_BROWSER_CASE') in ('picker-shrink', 'narrow-errors'):
        from uuid import uuid4

        from backend.app.formation.commands import update_path
        from backend.app.infrastructure.identifiers import EntityKind, entity_id
        from backend.app.infrastructure.message_repository import MessageRepository
        from backend.app.shared.command_execution import operation_time
        from backend.tests.formation.test_v21_path_commands import request as path_request

        refs = []
        with db.transaction(write=True) as connection:
            for index in range(31):
                identity = entity_id(connection, EntityKind.MESSAGE)
                MessageRepository(connection).create_user_text(
                    identity,
                    1,
                    None,
                    '分页依据' + str(index),
                    str(uuid4()),
                    operation_time(None),
                    document_id=1,
                    topic_refs=(),
                    document_ids=(1,),
                )
                refs.append({'kind': 'MESSAGE', 'message_id': identity})
        result = update_path(
            workspace[1],
            path_request(
                workspace,
                [
                    {'type': 'SET_GOAL', 'text': '分页依据初始目标', 'source_refs': refs},
                    {
                        'type': 'ADD_RESULT',
                        'step_ref': 's1',
                        'temp_result_ref': 'new_result_1',
                        'description': '分析论证',
                        'kind': 'ANALYSIS',
                    },
                ],
            ),
            catalog=workspace[2],
        )
        assert result['code'] == 'UPDATED', result
    initial_gateway = Gateway(result_output)
    if os.environ.get('W21_BROWSER_CASE') == 'recommendation-coverage':
        from tools.formation_recommendation_probe import reply

        initial_gateway = Gateway(reply)
    if os.environ.get('W21_BROWSER_CASE') in EXACT_CARD_CASES:
        import json

        from backend.app.documents.snapshot import validate_snapshot
        from backend.app.documents.sources import DocumentSources
        from backend.tests.documents.test_patch_validation import patch as exact_patch
        from backend.tests.formation.test_v21_model_publication import write_group
        from backend.tests.guide.test_v15_execution import output

        with db.transaction() as connection:
            current = connection.execute(
                'SELECT * FROM requirement_documents WHERE id=1'
            ).fetchone()
            snap = validate_snapshot(
                current['markdown_content'],
                json.loads(current['block_state_json']),
                DocumentSources(connection, 1, workspace[2], document_id=1),
            )
            target_id = list(snap.by_id)[-1]
            patch_value = exact_patch(snap, target_id, proposed='窄窗精确替换后的段落。\n')

        def proposal_reply(context):
            cards = write_group(context)
            cards['action_payload'].update(
                write_mode='PATCH_EXISTING',
                markdown_content=None,
                patches=[patch_value],
                scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': target_id}},
                goal_version=context.canonical['formation']['basis']['goal_version'],
                definition_version=context.canonical['formation']['selected_step'][
                    'definition_version'
                ],
            )
            return output(context, cards=cards)

        initial_gateway = Gateway(proposal_reply)
    first = accepted(
        workspace,
        request(
            workspace,
            target={
                'discussion_step_ref': 's1',
                'discussion_branch_ref': 'b1',
                'branch_intent': 'ENTER',
                'branch_resume_basis': None,
            },
            scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': target_id}}
            if os.environ.get('W21_BROWSER_CASE') in EXACT_CARD_CASES
            else None,
        ),
    )
    assert (
        run_round(workspace, first['data']['guide_run_id'], initial_gateway)['code']
        == 'AI_FINISHED'
    )
    if os.environ.get('W21_BROWSER_CASE') in EXACT_CARD_CASES:
        from backend.app.guide.queries import get_guide_run

        run = get_guide_run(db, first['data']['guide_run_id'], catalog=workspace[2])
        assert run['data']['effect_state'] == 'APPLIED', run['data']['component_errors']
        from backend.app.messages.queries import list_messages

        messages = list_messages(db, {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2])
        assert messages['code'] == 'READ_OK', messages
        assert messages['data']['items'][-1]['card_state'] == 'AVAILABLE', messages['data'][
            'items'
        ][-1]['card_state']
    if os.environ.get('W21_BROWSER_CASE') == 'page-scope':
        with db.transaction(write=True) as connection:
            original = dict(
                connection.execute(
                    "SELECT * FROM formation_branches WHERE branch_ref='b1'"
                ).fetchone()
            )
            columns = tuple(original)
            for index in range(2, 32):
                row = {
                    **original,
                    'branch_ref': 'b' + str(index),
                    'question': '分页支线' + str(index),
                    'status': 'OPEN',
                    'result_summary': None,
                    'result_sources_json': '[]',
                }
                connection.execute(
                    'INSERT INTO formation_branches('
                    + ','.join(columns)
                    + ') VALUES('
                    + ','.join('?' for _ in columns)
                    + ')',
                    tuple(row[key] for key in columns),
                )
            connection.execute('UPDATE formation_heads SET next_branch_no=32 WHERE document_id=1')
    if os.environ.get('W21_BROWSER_CASE') == 'ui-performance':
        from tools.formation_ui_performance_probe import seed

        seed(workspace)
    if os.environ.get('W21_BROWSER_CASE') == 'cross-return':
        from tools.formation_cross_return_probe import seed

        seed(workspace)
    try:
        next(fixture_gen)
    except StopIteration:
        pass

    class HeldGateway(Gateway):
        async def send(self, profile, context):
            while not (temporary / 'release').exists():
                await asyncio.sleep(0.05)
            return await super().send(profile, context)

    def worker(database, catalog):
        if os.environ.get('W21_BROWSER_CASE', '').startswith('storage-'):
            selected_gateway = HeldGateway(output)
        elif os.environ.get('W21_BROWSER_CASE') == 'recommendation-coverage':
            from tools.formation_recommendation_probe import reply

            selected_gateway = Gateway(reply)
        elif os.environ.get('W21_BROWSER_CASE', '').startswith('withdraw-'):
            selected_gateway = Gateway(failed=True)
        elif os.environ.get('W21_BROWSER_CASE', '').startswith('resume-'):
            from tools.formation_resume_probe import gateway

            selected_gateway = gateway(os.environ['W21_BROWSER_CASE'], temporary)
        else:
            selected_gateway = HeldGateway(
                lambda context: result_output(context, summary='本轮新支线结果')
            )
        return GuideWorker(
            database,
            catalog=catalog,
            orchestrator_options={
                'profile': PROFILE,
                'gateway': selected_gateway,
                'counting_counter': Counter(
                    ['OK']
                    * (3 if os.environ.get('W21_BROWSER_CASE', '').startswith('resume-') else 1)
                ),
            },
        )

    app = create_app(database=db, catalog=workspace[2], worker_factory=worker, schema_version=210)
    if os.environ.get('W21_BROWSER_CASE', '').startswith('storage-') or os.environ.get(
        'W21_BROWSER_CASE'
    ) in ('recommendation-coverage', 'keyboard-route'):
        from tools.formation_storage_fault_probe import register_state

        register_state(app, db)
    if os.environ.get('W21_BROWSER_CASE', '').startswith('withdraw-'):
        from tools.formation_withdraw_probe import register_state

        register_state(app, db, workspace[2])
    if os.environ.get('W21_BROWSER_CASE', '').startswith('two-tab-'):
        from tools.formation_card_conflict_probe import register_state

        register_state(app, db)
    if os.environ.get('W21_BROWSER_CASE', '').startswith('resume-'):
        from tools.formation_resume_probe import register_state

        register_state(app, db)
    server = uvicorn.Server(
        uvicorn.Config(app, host='127.0.0.1', port=8217, log_level='error', access_log=False)
    )

    def stop():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop, daemon=True).start()
    try:
        server.run()
    finally:
        patch.undo()


def late_result(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
     const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     await page.getByRole('checkbox',{name:'支线',exact:true}).check();
     await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
     await page.getByRole('button',{name:'继续讨论支线',exact:true}).click();
     await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).waitFor();
     await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.branch_intent==='ENTER');
     await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('本轮核实原支线');
     await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
     await page.waitForFunction(()=>window.formationProduct.requests().some(x=>x.path.endsWith('/guide-runs')));
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     let busyReason=null;
 if(page.viewportSize().width===480){
  await page.locator('[data-step-ref="s1"] .formation-node').click();
  await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY'&&!window.formationProduct.state().formation.loading);
  const pause=page.getByRole('button',{name:'暂停步骤',exact:true});
  if(!(await pause.isDisabled()))throw Error('Busy narrow state allowed pause');
  if(!(await page.getByRole('button',{name:'结束本步骤',exact:true}).isDisabled()))throw Error('Busy narrow state allowed complete');
  busyReason=await pause.getAttribute('title');
  if(!busyReason||busyReason.includes('读取'))throw Error('Busy reason not actual occupancy: '+busyReason);
 }
 await page.locator('[data-step-ref="s2"]').getByRole('button',{name:'下一轮讨论 下一步',exact:true}).click();
     await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('新步骤的新输入不得清除');
     return {target:await page.evaluate(()=>window.formationProduct.state().formation.next_target),instruction:await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue(),requests:await page.evaluate(()=>window.formationProduct.requests()),errors,busyReason};
     }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )
    with (t / 'release').open('xb') as stream:
        stream.write(b'go')
    started = time.monotonic()
    while True:
        try:
            with urllib.request.urlopen(
                'http://127.0.0.1:8217/api/v1/guide-runs/2', timeout=5
            ) as response:
                actual = json.load(response)['data']
        except urllib.error.HTTPError as error:
            if error.code != 404 or time.monotonic() - started > 50:
                raise
            time.sleep(0.2)
            continue
        if actual['status'] in ['COMPLETED', 'FAILED', 'CANCELLED']:
            break
        if time.monotonic() - started > 50:
            raise RuntimeError(
                'actual terminal wait '
                + str(
                    {
                        k: actual.get(k)
                        for k in ['status', 'current_step', 'failure_reason', 'error']
                    }
                )
            )
        time.sleep(0.2)
    print('ACTUAL_TERMINAL', actual['status'], actual.get('effect_state'), flush=True)
    print(
        json.dumps(
            run("""async(page)=>{
     await page.waitForTimeout(800);
     const current=await page.evaluate(()=>window.formationProduct.state());
     if(current.formation.next_target.discussion_step_ref!=='s2')throw Error('Late reply changed new target');
     if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='新步骤的新输入不得清除')throw Error('Late reply cleared new input');
     const run=(await (await page.request.get('http://127.0.0.1:5187/api/v1/guide-runs/2')).json()).data;
     if(run.status!=='COMPLETED')throw Error('Actual C07 not completed');
     if(run.accepted_target.discussion_branch_ref!=='b1')throw Error('Original reply moved branch');
     return {originalTarget:run.accepted_target,nextTarget:current.formation.next_target,instruction:current.composer.instruction,status:run.status,effect:run.effect_state,phase:current.composer.phase};
     }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def stale_enter(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     await page.getByRole('checkbox',{name:'支线',exact:true}).check();
     await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
     await page.getByRole('button',{name:'继续讨论支线',exact:true}).click();
     await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.branch_intent==='ENTER');
     await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('保留原输入，不自动恢复支线');
     return {target:await page.evaluate(()=>window.formationProduct.state().formation.next_target)};
     }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )
    import uuid

    with urllib.request.urlopen(
        'http://127.0.0.1:8217/api/v1/requirements/1?document_id=1', timeout=5
    ) as response:
        d = json.load(response)['data']['requirement']['discussion_version']
    command = {
        'expected_discussion_version': d,
        'document_id': 1,
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'DISPOSE_BRANCH',
            'branch_ref': 'b1',
            'disposition': 'DEFERRED',
            'reason': '另一个窗口暂缓',
        },
    }
    request = urllib.request.Request(
        'http://127.0.0.1:8217/api/v1/requirements/1',
        data=json.dumps(command).encode(),
        method='PATCH',
        headers={'Content-Type': 'application/json', 'Idempotency-Key': str(uuid.uuid4())},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)['data']['effects']['formation_changed']
    print(
        json.dumps(
            run("""async(page)=>{
     await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
     await page.waitForFunction(()=>window.formationProduct.state().composer.phase==='ERROR');
     const state=await page.evaluate(()=>window.formationProduct.state());
     if(state.composer.instruction!=='保留原输入，不自动恢复支线')throw Error('Conflict cleared input');
     if(!state.composer.needs_refresh)throw Error('Stale binding did not offer refresh');
 await page.getByRole('button',{name:'重新读取状态',exact:true}).click();
 await page.waitForFunction(()=>!window.formationProduct.state().composer.refreshing);
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().composer.error_code==='STATE_CONFLICT');
 const rejected=await page.evaluate(()=>window.formationProduct.state().composer.error_code);
     if(state.formation.next_target.branch_intent!=='ENTER')throw Error('Silently resumed stale target');
     const posted=await page.evaluate(()=>window.formationProduct.requests().filter(r=>r.path.endsWith('/guide-runs')));
     if(posted.length!==1||JSON.parse(posted[0].body).target.branch_intent!=='ENTER')throw Error('Wrong request target');
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     await page.getByRole('button',{name:'刷新主线',exact:true}).click();
     await page.getByRole('button',{name:'继续讨论支线',exact:true}).click();
     await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).waitFor();
     if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='保留原输入，不自动恢复支线')throw Error('Explicit resume cleared input');
     return {rejection:rejected,nextTarget:await page.evaluate(()=>window.formationProduct.state().formation.next_target),postCount:posted.length,pending:await page.evaluate(()=>window.formationProduct.state().formation.pending.length)};
     }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def cold_resume(run, t):
    original = run("""async(page)=>{
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     await page.getByRole('button',{name:'继续讨论支线',exact:true}).waitFor();
     await page.evaluate(()=>window.formationProduct.losePatch());
     await page.getByRole('button',{name:'继续讨论支线',exact:true}).click();
     await page.waitForFunction(()=>window.formationProduct.state().formation.phase==='UNKNOWN');
     return (await page.evaluate(()=>window.formationProduct.requests())).find(r=>r.method==='PATCH');
     }""")
    print('ORIGINAL_UNKNOWN_RECORDED', flush=True)
    recovered = run("""async(page)=>{
     await page.reload();await page.waitForFunction(()=>window.formationProduct?.state()?.ready);
     await page.getByRole('tab',{name:'进展',exact:true}).click();
     await page.getByRole('button',{name:'按原请求核实',exact:true}).click();
     await page.waitForFunction(()=>window.formationProduct.state().formation.phase==='IDLE'&&window.formationProduct.state().formation.pending.length===0);
     const state=await page.evaluate(()=>window.formationProduct.state());
     if(state.formation.next_target?.branch_intent!=='ENTER')throw Error('Cold resume not consumed');
     if(state.formation.next_target?.branch_resume_basis!==null)throw Error('Old resume basis retained');
     return {target:state.formation.next_target,patch:(await page.evaluate(()=>window.formationProduct.requests())).find(r=>r.method==='PATCH')};
     }""")
    assert original['key'] == recovered['patch']['key']
    assert original['body'] == recovered['patch']['body']
    print(
        'COLD_RESUME_ORIGINAL_BODY_KEY_PASS',
        json.dumps(recovered['target'], ensure_ascii=False),
        flush=True,
    )


def page_scope(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 const list=page.getByRole('region',{name:'步骤s1的支线',exact:true});
 await list.getByRole('button',{name:'下一页',exact:true}).click();
 await list.getByText('分页支线31',{exact:true}).waitFor();
 return {before:await list.getByRole('listitem').count()};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )
    import uuid

    with urllib.request.urlopen(
        'http://127.0.0.1:8217/api/v1/requirements/1?document_id=1', timeout=5
    ) as response:
        d = json.load(response)['data']['requirement']['discussion_version']
    command = {
        'expected_discussion_version': d,
        'document_id': 1,
        'discussion_command': {'type': 'FORMATION', 'action': 'PAUSE_STEP', 'step_ref': 's1'},
    }
    req = urllib.request.Request(
        'http://127.0.0.1:8217/api/v1/requirements/1',
        data=json.dumps(command).encode(),
        method='PATCH',
        headers={'Content-Type': 'application/json', 'Idempotency-Key': str(uuid.uuid4())},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        assert json.load(response)['data']['effects']['formation_changed']
    print(
        json.dumps(
            run("""async(page)=>{
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>!window.formationProduct.state().formation.loading);
 const list=page.getByRole('region',{name:'步骤s1的支线',exact:true});
 await list.getByRole('button',{name:'刷新',exact:true}).waitFor({state:'visible'});
 await page.waitForTimeout(600);
 return {alerts:await list.getByRole('alert').allTextContents(),rows:await list.getByRole('listitem').count(),requests:await page.evaluate(()=>window.formationProduct.readRequests().filter(p=>p.includes('/formation/branches')))};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def picker_shrink(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.getByRole('button',{name:'结束并继续／处理遗留',exact:true}).click();
 await page.getByRole('combobox',{name:'成果记录 s1.o2',exact:true}).selectOption('ANALYZED');
 const list=page.getByRole('region',{name:'步骤已有依据',exact:true});
 await list.getByRole('button',{name:'下一页依据',exact:true}).click();
 await list.getByRole('checkbox').first().check();
 return {rows:await list.getByRole('listitem').count()};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )
    import uuid

    with urllib.request.urlopen(
        'http://127.0.0.1:8217/api/v1/requirements/1?document_id=1', timeout=5
    ) as response:
        detail = json.load(response)['data']
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/api/v1/requirements/1?document_id=1&expand=discussion',
        timeout=5,
    ) as response:
        summary = json.load(response)['data']['discussion']['formation_summary']
    command = {
        'expected_discussion_version': detail['requirement']['discussion_version'],
        'document_id': 1,
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'ADJUST_PATH',
            'expected_formation_version': summary['formation_version'],
            'expected_content_version': 1,
            'based_on_proposal': None,
            'changes': [
                {
                    'type': 'SET_GOAL',
                    'text': '两个真实依据的新目标',
                    'source_refs': [
                        {'kind': 'MESSAGE', 'message_id': 1},
                        {'kind': 'MESSAGE', 'message_id': 2},
                    ],
                }
            ],
            'result_routes': [],
            'reason': '缩小目标引用范围',
        },
    }
    request = urllib.request.Request(
        'http://127.0.0.1:8217/api/v1/requirements/1',
        data=json.dumps(command).encode(),
        method='PATCH',
        headers={'Content-Type': 'application/json', 'Idempotency-Key': str(uuid.uuid4())},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)['data']['effects']['formation_changed']
    print(
        json.dumps(
            run("""async(page)=>{
 await page.getByRole('button',{name:'重新读取主线，保留处置选择',exact:true}).click();
 await page.getByRole('region',{name:'步骤已有依据',exact:true}).getByText('共 2 条',{exact:true}).waitFor();
 const list=page.getByRole('region',{name:'步骤已有依据',exact:true});
 if(await list.getByRole('listitem').count()!==2)throw Error('Nonempty candidates lost after shrink');
 await page.getByRole('button',{name:'已核对当前版本，保留选择',exact:true}).click();
 const selected=await page.getByRole('region',{name:'成果依据选择',exact:true}).innerText();
 if(!selected.includes('已选 1 / 100'))throw Error('Refresh cleared chosen evidence');
 const module=await page.request.get('http://127.0.0.1:5187/src/formation/evidence-picker.tsx');
 const transformed=await module.text();
 if(module.status()!==200||!transformed.includes('currentPage')||!transformed.includes('FormationEvidencePicker'))throw Error('Live module missing complete exports');
 return {rows:await list.getByRole('listitem').count(),text:await list.innerText(),selected,moduleStatus:module.status(),moduleCharacters:transformed.length};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def viewport_layout(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 const observations=[];
 const bodySelector='.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror';
 await page.locator(bodySelector).waitFor({state:'attached'});
 await page.locator(bodySelector).evaluate(node=>window.w21OriginalBody=node);
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('窄窗来回切换不得清空的输入');
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 for(const width of [480,899,900,932,964,965,966,1024,1440]){
  await page.setViewportSize({width,height:800});
  await page.waitForFunction(width=>window.formationProduct.state().layout.mode===(width>=1280?'DESKTOP':'COMPACT'),width);
  if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
  await page.getByRole('tab',{name:'进展',exact:true}).click();
  await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
  await page.locator('[data-step-ref="s1"] .formation-node').click();
  await page.getByRole('button',{name:'展开主线',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'展开文档主线',exact:true});
  await dialog.waitFor();
  observations.push(await dialog.evaluate((node)=>{const body=node.querySelector('.formation-body');const panel=node.querySelector('.formation-progress');return {viewport:innerWidth,dialogWidth:node.clientWidth,dialogScroll:node.scrollWidth,bodyWidth:body.getBoundingClientRect().width,bodyScroll:body.scrollWidth,columns:getComputedStyle(body).gridTemplateColumns,panelWidth:panel.clientWidth,documentWidth:document.documentElement.scrollWidth};}));
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'hidden'});
 }
 for(const row of observations){
  const count=row.columns.split(' ').length;
  if(count!==(row.bodyWidth>=900?2:1))throw Error('Wrong container threshold '+JSON.stringify(row));
  if(row.dialogScroll>row.dialogWidth+1||row.bodyScroll>row.bodyWidth+1||row.documentWidth>row.viewport+1)throw Error('Horizontal overflow '+JSON.stringify(row));
 }
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='窄窗来回切换不得清空的输入')throw Error('Narrow mode cleared input');
 await page.setViewportSize({width:479,height:800});
 await page.getByRole('heading',{name:'当前窗口过窄，请将窗口调整至至少 480px',exact:true}).waitFor();
 await page.setViewportSize({width:480,height:800});
 await page.getByRole('button',{name:'Ai助手',exact:true}).waitFor();
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='窄窗来回切换不得清空的输入')throw Error('Minimum crossing cleared input');
 const writes=await page.evaluate(()=>window.formationProduct.requests().length);
 if(writes!==0)throw Error('Viewport change sent business command');
 const sameBody=await page.evaluate(()=>window.w21OriginalBody.isConnected&&window.w21OriginalBody===document.querySelector('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror'));
 if(!sameBody)throw Error('Viewport remounted original editor');
 return {observations,minimumRestored:true,inputRetained:true,writes,sameBody};

 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def manual_viewport(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const selector='.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]';
 const editor=page.locator(selector);
 await editor.waitFor();
 await editor.evaluate(node=>window.w21ManualEditor=node);
 await editor.click();await page.keyboard.press('Control+End');await page.keyboard.press('Enter');await page.keyboard.insertText('窄窗草稿必须保护');
 await page.setViewportSize({width:479,height:800});
 await page.getByRole('heading',{name:'当前窗口过窄，请将窗口调整至至少 480px',exact:true}).waitFor();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().manual?.autosave.state.status==='SAVED');
 const response=await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/manual-draft?document_id=1');
 const saved=(await response.json()).data;
 if(!saved.markdown_content.includes('窄窗草稿必须保护'))throw Error('Boundary failed to protect actual draft');
 await page.setViewportSize({width:480,height:800});
 await editor.waitFor();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().manual?.getSnapshot().readonly===false);
 const retained=await editor.evaluate(node=>window.w21ManualEditor===node&&node.textContent.includes('窄窗草稿必须保护'));
 if(!retained)throw Error('Boundary remounted or overwrote dirty editor');
 await page.getByRole('button',{name:'取消编辑',exact:true}).click();
 await page.getByRole('dialog',{name:'放弃人工编辑？',exact:true}).getByRole('button',{name:'确认放弃',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().mode==='CURRENT');
 const actual=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=1')).json()).data;
 if(actual.content_version!==2||actual.markdown_content.includes('窄窗草稿必须保护'))throw Error('Cancel changed original body');
 const requests=await page.evaluate(()=>window.formationProduct.requests());
 if(requests.some(r=>r.path.endsWith('/guide-runs')))throw Error('Viewport action invoked model');
 return {savedDraftVersion:saved.content_version,retained,contentVersion:actual.content_version,commands:requests.map(r=>({method:r.method,path:r.path}))};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def history_viewport(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'文档记录',exact:true}).click();
 await page.getByRole('button',{name:'查看 V1',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().mode==='HISTORY');
 await page.getByRole('group',{name:'阅读视图',exact:true}).getByRole('button',{name:'Ai对话',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const discussion=page.getByRole('button',{name:'讨论此步骤',exact:true});
 if(!(await discussion.isDisabled()))throw Error('Historical view allowed target change');
 const reason=await discussion.getAttribute('title');
 if(!reason?.includes('历史'))throw Error('Historical action lacks concrete reason');
 if(!(await page.getByRole('button',{name:'结束本步骤',exact:true}).isDisabled()))throw Error('Historical view allowed completion');
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'文档记录',exact:true}).click();
 await page.getByRole('button',{name:'退出历史',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().mode==='CURRENT');
 const current=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=1')).json()).data;
 const writes=await page.evaluate(()=>window.formationProduct.requests().length);
 if(current.content_version!==2||writes!==0)throw Error('Historical viewing changed body');
 return {readonlyReason:reason,contentVersion:current.content_version,writes};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def busy_viewport(run, t):
    run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.waitForFunction(()=>window.formationProduct.state().layout.mode==='COMPACT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror').evaluate(node=>window.w21BusyBody=node);
 return true;
 }""")
    late_result(run, t)
    print(
        json.dumps(
            run("""async(page)=>{
 const sameBody=await page.evaluate(()=>window.w21BusyBody.isConnected&&window.w21BusyBody===document.querySelector('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror'));
 if(!sameBody)throw Error('Busy narrow workflow remounted body');
 const width=await page.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth}));
 if(width.page>width.viewport+1)throw Error('Busy narrow workflow overflowed');
 return {sameBody,width};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def full_shell_viewport(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.goto('http://127.0.0.1:5187/requirements/1?document_id=1');
 await page.getByRole('heading',{name:'形成设计',exact:true}).waitFor();
 await page.getByRole('navigation',{name:'主导航',exact:true}).waitFor();
 await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.getByRole('button',{name:'展开主线',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'展开文档主线',exact:true});
 await dialog.waitFor();
 const geometry=await page.evaluate(()=>({viewport:innerWidth,page:document.documentElement.scrollWidth,main:document.querySelector('.application-main').getBoundingClientRect().width,dialog:document.querySelector('.formation-dialog').clientWidth}));
 if(geometry.page>geometry.viewport+1)throw Error('Application shell overflowed '+JSON.stringify(geometry));
 await page.keyboard.press('Escape');
 const body=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=1')).json()).data;
 if(body.content_version!==2)throw Error('Shell viewing changed content');
 return {geometry,contentVersion:body.content_version};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def narrow_errors(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.waitForFunction(()=>window.formationProduct.state().layout.mode==='COMPACT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.getByRole('button',{name:'结束并继续／处理遗留',exact:true}).click();
 await page.getByRole('combobox',{name:'成果记录 s1.o2',exact:true}).selectOption('ANALYZED');
 await page.evaluate(()=>window.formationProduct.failRead('/messages'));
 await page.getByRole('combobox',{name:'依据来源 s1',exact:true}).selectOption('MESSAGES');
 const picker=page.getByRole('region',{name:'成果依据选择',exact:true});
 await picker.getByRole('alert').filter({hasText:'暂时无法读取'}).waitFor();
 if(await picker.getByText('此文档暂无讨论记录',{exact:true}).isVisible())throw Error('Read failure shown as empty');
 await picker.getByRole('button',{name:'刷新',exact:true}).click();
 await picker.getByRole('checkbox').first().waitFor();
 await picker.getByRole('checkbox').first().check();
 const source=picker.locator('.source-reference:visible').first();
 await page.evaluate(()=>window.formationProduct.failRead('/conversation-messages/'));
 await source.locator('summary').click();
 await source.getByRole('alert').waitFor();
 await source.getByRole('button',{name:'重新读取',exact:true}).click();
 await source.locator('pre').waitFor();
 const dialog=page.getByRole('dialog',{name:'结束并继续／处理遗留',exact:true});
 const geometry=await dialog.evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth}));
 if(geometry.scroll>geometry.width+1)throw Error('Narrow read error overflow');
 if(!(await picker.innerText()).includes('已选 1 / 100'))throw Error('Read error cleared choice');
 await dialog.getByRole('button',{name:'取消',exact:true}).click();
 const writes=await page.evaluate(()=>window.formationProduct.requests().length);
 if(writes!==0)throw Error('Read recovery wrote business data');
 return {readFailureRecovered:true,sourceFailureRecovered:true,choiceRetained:true,geometry,writes};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def zoom_200(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 const zoom=await page.evaluate(()=>({dpr:devicePixelRatio,outer:outerWidth,inner:innerWidth,scale:visualViewport.scale,cssZoom:getComputedStyle(document.documentElement).zoom}));
 if(Math.abs(zoom.outer/zoom.inner-2)>.1||Math.abs(zoom.dpr-2)>.1||zoom.scale!==1)throw Error('Native 200% not established '+JSON.stringify(zoom));
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.getByRole('button',{name:'展开主线',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'展开文档主线',exact:true});
 await dialog.waitFor();await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const geometry=await dialog.evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth,page:document.documentElement.scrollWidth,viewport:innerWidth,columns:getComputedStyle(node.querySelector('.formation-body')).gridTemplateColumns}));
 if(geometry.scroll>geometry.width+1||geometry.page>geometry.viewport+1)throw Error('Native zoom overflowed');
 await page.keyboard.press('Escape');
 return {zoom,geometry,writes:await page.evaluate(()=>window.formationProduct.requests().length)};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def narrow_patch(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 await page.setViewportSize({width:480,height:800});
 await page.waitForFunction(()=>window.formationProduct.state().layout.mode==='COMPACT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 const cards=page.getByRole('region',{name:'决策卡片组',exact:true});
 try{await cards.waitFor({timeout:30000});}catch(error){
 const messages=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/messages?document_id=1')).json()).data.items;
 throw Error('Missing actual card '+JSON.stringify({alerts:await page.getByRole('alert').allTextContents(),body:await page.getByRole('region',{name:'对话消息',exact:true}).innerText(),wire:messages.map(m=>({id:m.id,role:m.role,type:m.message_type,state:m.card_state,purpose:m.structured_content?.purpose,scope:m.structured_content?.action_payload?.scope}))}));
 }
 const scope=await cards.getByRole('region',{name:'提案原文与采用范围',exact:true}).innerText();
 if(scope.includes('undefined'))throw Error('BLOCK scope rendered undefined: '+scope);
 const before=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=1')).json()).data;
 await cards.getByRole('radio',{name:'apply',exact:true}).check();
 const count=await page.evaluate(()=>window.formationProduct.requests().length);
 if(count!==0)throw Error('Selecting proposal submitted early');
 await page.evaluate(()=>window.formationProduct.loseCard());
 const confirm=cards.getByRole('button',{name:'按提案写入',exact:true});
 await cards.getByRole('radio',{name:'apply',exact:true}).focus();
 for(let index=0;!(await confirm.evaluate(node=>node===document.activeElement));index++){
  if(index>80)throw Error('Keyboard cannot reach exact adoption');
  await page.keyboard.press('Tab');
 }
 await page.keyboard.press('Enter');
 await cards.getByRole('button',{name:'重新确认整组提交结果',exact:true}).click();
 await cards.getByText('已按提案保存文档。',{exact:true}).waitFor();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.cards.getSnapshot().slots.some(slot=>{const state=slot.owner?.getSnapshot();return state?.phase==='RESOLVED'&&!state.refreshing;}));
 const actual=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=1')).json()).data;
 if(before.content_version!==2||actual.content_version!==3||!actual.markdown_content.includes('窄窗精确替换后的段落'))throw Error('Exact adoption not saved once');
 const sent=await page.evaluate(()=>window.formationProduct.requests().filter(r=>r.path.endsWith('/responses')));
 if(sent.length!==2||sent[0].body!==sent[1].body||sent[0].key!==sent[1].key)throw Error('Lost adoption did not replay exact request: '+JSON.stringify(sent));
 const geometry=await cards.evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth,page:document.documentElement.scrollWidth,viewport:innerWidth}));
 if(geometry.scroll>geometry.width+1||geometry.page>geometry.viewport+1)throw Error('Narrow proposal overflow');
 return {scope,contentVersion:actual.content_version,replayedOriginal:true,geometry};
 }"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


def cross_document(run, t):
    print(
        json.dumps(
            run("""async(page)=>{
 let stage='branch';try{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('checkbox',{name:'支线',exact:true}).check();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.getByRole('button',{name:'继续讨论支线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.branch_intent==='ENTER');
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('文档1的在途支线讨论');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 stage='run acceptance';
 await page.waitForFunction(()=>{const run=window.formationProduct.owner().regions.conversation.read.getSnapshot().run;return run?.id===2&&['QUEUED','RUNNING'].includes(run.status);});
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.left_open)))await page.getByRole('button',{name:'展开文档导航',exact:true}).click();
 await page.locator('.document-directory-item[title="设计"]').click();
 stage='document switch';
 await page.waitForFunction(()=>window.formationProduct.state().current===2&&!window.formationProduct.owner().getSnapshot().loading);
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('文档2的新输入必须保持');
 return {document:await page.evaluate(()=>window.formationProduct.state().current)};
 }catch(error){const diagnostic=await page.evaluate(()=>{const owner=window.formationProduct.owner();const s=window.formationProduct.state();const run=owner.regions.conversation.read.getSnapshot().run;return {current:s.current,composer:s.composer.phase,error:s.error,run:run&&{id:run.id,status:run.status,document:run.document_id},formation:s.formation.phase,alerts:[...document.querySelectorAll('[role=alert]')].map(n=>n.textContent)};});throw Error(stage+': '+error.message+' '+JSON.stringify(diagnostic));}
}"""),
            ensure_ascii=False,
        ),
        flush=True,
    )
    with (t / 'release').open('xb') as stream:
        stream.write(b'go')
    started = time.monotonic()
    while True:
        with urllib.request.urlopen(
            'http://127.0.0.1:8217/api/v1/guide-runs/2', timeout=5
        ) as response:
            actual = json.load(response)['data']
        if actual['status'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
            break
        if time.monotonic() - started > 50:
            raise RuntimeError('Cross document terminal wait ' + str(actual['status']))
        time.sleep(0.2)
    assert actual['status'] == 'COMPLETED' and actual['effect_state'] == 'APPLIED', actual
    assert actual['document_id'] == 1 and actual['accepted_target']['discussion_branch_ref'] == 'b1'
    print(
        json.dumps(
            run("""async(page)=>{
 await page.waitForTimeout(1200);
 const state=await page.evaluate(()=>window.formationProduct.state());
 const activeRun=await page.evaluate(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run);
 const text=await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue();
 if(state.current!==2||text!=='文档2的新输入必须保持'||(activeRun&&activeRun.document_id!==2))throw Error('Late original document hijacked current view '+JSON.stringify({state,text,activeRun}));
 const current=(await (await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/current-document?document_id=2')).json()).data;
 if(current.content_version!==1||current.markdown_content!=='')throw Error('Old round changed document2');
 const writes=await page.evaluate(()=>window.formationProduct.requests());
 if(writes.length!==2||writes.some(row=>JSON.parse(row.body).document_id!==1))throw Error('Unexpected cross document write '+JSON.stringify(writes));
 const pending=state.formation.pending.length;
 if(pending!==0)throw Error('Current document inherited old pending');
 return {document:state.current,instruction:text,currentRun:activeRun?.id??null,contentVersion:current.content_version,writes:writes.length,pending};
}"""),
            ensure_ascii=False,
        ),
        flush=True,
    )


CASES = {
    'late-result': late_result,
    'stale-enter': stale_enter,
    'cold-resume': cold_resume,
    'page-scope': page_scope,
    'picker-shrink': picker_shrink,
    'viewport': viewport_layout,
    'manual-viewport': manual_viewport,
    'history-viewport': history_viewport,
    'busy-viewport': busy_viewport,
    'full-shell': full_shell_viewport,
    'narrow-errors': narrow_errors,
    'zoom-200': zoom_200,
    'narrow-patch': narrow_patch,
    'cross-document': cross_document,
}


def build_browser_bundle(root, temporary, env):
    import json
    import os
    import subprocess

    output = temporary / 'browser-build'
    build_script = temporary / 'browser-build.mjs'
    source = (
        'import {build} from '
        + json.dumps((root / 'frontend/node_modules/vite/dist/node/index.js').as_uri())
        + ';\nawait build('
        + json.dumps(
            {
                'root': str(root / 'frontend'),
                'configFile': str(root / 'frontend/vite.config.ts'),
                'cacheDir': str(temporary / 'vite-cache'),
                'build': {
                    'outDir': str(output),
                    'emptyOutDir': True,
                    'rolldownOptions': {
                        'input': [
                            str(root / 'frontend/index.html'),
                            str(root / 'frontend/tests/browser/formation-product.html'),
                        ]
                    },
                },
            }
        )
        + ');\n'
    )
    with build_script.open('x', encoding='utf-8') as stream:
        stream.write(source)
        stream.flush()
        os.fsync(stream.fileno())
    result = subprocess.run(
        ['node', '--require', str(root / 'tools/quality_node.cjs'), str(build_script)],
        cwd=root / 'frontend',
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=90,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(
            'Owned production browser build failed: ' + (result.stdout + result.stderr)[-3000:]
        )
    if not (output / 'tests/browser/formation-product.html').is_file():
        raise RuntimeError('Production fixture entry missing')
    print('OWNED_BROWSER_BUILD_READY', flush=True)
    return output


def verify_browser_bundle(output):
    import hashlib
    import json
    import urllib.request

    count = 0
    size = 0
    for path in sorted((output / 'assets').glob('*')):
        if path.suffix not in ('.js', '.css'):
            continue
        expected = path.read_bytes()
        with urllib.request.urlopen(
            'http://127.0.0.1:5187/assets/' + path.name, timeout=10
        ) as response:
            actual = response.read()
        if actual != expected:
            raise RuntimeError('Actual served bundle bytes mismatch: ' + path.name)
        count += 1
        size += len(actual)
    if count < 2:
        raise RuntimeError('Incomplete production asset inventory')
    html = output / 'tests/browser/formation-product.html'
    with urllib.request.urlopen(
        'http://127.0.0.1:5187/tests/browser/formation-product.html', timeout=10
    ) as response:
        actual = response.read()
    if actual != html.read_bytes():
        raise RuntimeError('Actual fixture HTML differs from owned build')
    print(
        'PRODUCTION_BUNDLES_VERIFIED',
        json.dumps(
            {
                'assets': count,
                'bytes': size,
                'fixture_sha256': hashlib.sha256(actual).hexdigest(),
            }
        ),
        flush=True,
    )


def probe(
    case, review=False, *, serve_script=None, document_id=1, startup_timeout=60, production=False
):
    import json
    import re
    import subprocess
    import sys
    import tempfile
    import time
    import urllib.request
    from pathlib import Path

    from tools.quality_gate import environment, stop_owned

    if production and case in ('picker-shrink', 'full-shell'):
        raise ValueError('This case requires its actual development module or app-route surface')
    sys.stdout.reconfigure(encoding='utf-8')
    ROOT = Path(__file__).resolve().parents[1]
    matches = sorted(
        (Path.home() / 'AppData/Local/npm-cache/_npx').glob(
            '*/node_modules/@playwright/cli/playwright-cli.js'
        )
    )
    CLI = next(
        (
            path
            for path in matches
            if json.loads(path.with_name('package.json').read_text(encoding='utf-8'))['version']
            == '0.1.24'
        ),
        None,
    )
    if CLI is None:
        raise RuntimeError('Installed Playwright CLI 0.1.24 required; no automatic installation')
    with tempfile.TemporaryDirectory(prefix='w21-concurrency-browser-') as directory:
        t = Path(directory)
        env = environment(t)
        env['W21_BROWSER_CASE'] = case
        jobs = []
        import threading
        from collections import deque

        tails = {}

        def drain(job):
            lines = deque(maxlen=80)
            tails[job.pid] = lines

            def read():
                for line in job.stdout:
                    lines.append(line)
                    if line.startswith('HISTORY_'):
                        print(line.strip(), flush=True)

            threading.Thread(target=read, daemon=True).start()

        session = t.name

        def cli(*args):
            done = subprocess.run(
                ['node', str(CLI), '-s=' + session, *args],
                cwd=t,
                env=env,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=70,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if done.returncode or '### Error' in done.stdout:
                raise RuntimeError((done.stdout + done.stderr)[-2200:])
            return done.stdout

        def run(code):
            output = cli('run-code', code)
            match = re.search(r'### Result\s*\n([\s\S]*?)\n### Ran Playwright code', output)
            if not match:
                raise RuntimeError(output[-2200:])
            return json.loads(match[1])

        try:
            server = subprocess.Popen(
                [sys.executable, '-B', str(serve_script or Path(__file__).resolve()), '--serve'],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            jobs.append(server)
            drain(server)
            vite_env = dict(env, WALLE_API_URL='http://127.0.0.1:8217')
            bundle = build_browser_bundle(ROOT, t, vite_env) if production else None
            if production:
                frontend_command = [
                    sys.executable,
                    '-B',
                    str(ROOT / 'tools/formation_static_server.py'),
                    '--directory',
                    str(bundle),
                ]
            else:
                frontend_command = [
                    'node',
                    'node_modules/vite/bin/vite.js',
                    '--host',
                    '127.0.0.1',
                    '--port',
                    '5187',
                    '--strictPort',
                ]
            vite = subprocess.Popen(
                frontend_command,
                cwd=ROOT / 'frontend',
                env=vite_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            jobs.append(vite)
            drain(vite)
            for url in [
                f'http://127.0.0.1:8217/api/v1/requirements/1?document_id={document_id}',
                f'http://127.0.0.1:5187/tests/browser/formation-product.html?document={document_id}',
            ]:
                start = time.monotonic()
                while True:
                    if any(job.poll() is not None for job in jobs):
                        raise RuntimeError(
                            'service exited '
                            + str(
                                [
                                    (job.returncode, ''.join(tails.get(job.pid, []))[-2000:])
                                    for job in jobs
                                    if job.poll() is not None
                                ]
                            )
                        )
                    try:
                        with urllib.request.urlopen(url, timeout=2) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        if time.monotonic() - start > startup_timeout:
                            raise
                        time.sleep(0.1)
            options = []
            if case == 'zoom-200':
                import math

                profile = t / 'zoom-profile'
                (profile / 'Default').mkdir(parents=True)
                with (profile / 'Default/Preferences').open('x', encoding='utf-8') as stream:
                    json.dump(
                        {'partition': {'default_zoom_level': {'x': math.log(2) / math.log(1.2)}}},
                        stream,
                    )
                config = t / 'cli-zoom-config.json'
                with config.open('x', encoding='utf-8') as stream:
                    json.dump(
                        {
                            'browser': {
                                'browserName': 'chromium',
                                'isolated': False,
                                'userDataDir': str(profile),
                                'launchOptions': {
                                    'headless': True,
                                    'channel': 'chrome',
                                    'args': ['--window-size=1440,1000'],
                                },
                                'contextOptions': {'viewport': None},
                            }
                        },
                        stream,
                    )
                options = ['--profile', str(profile), '--config', str(config)]
            cli(
                'open',
                f'http://127.0.0.1:5187/tests/browser/formation-product.html?document={document_id}',
                *options,
            )
            run(
                'async(page)=>{await page.waitForFunction(()=>window.formationProduct?.state()?.ready);return true;}'
            )
            CASES[case](run, t)
            if production:
                verify_browser_bundle(bundle)
            else:
                modules = run("""async(page)=>{
     const modules=[['/src/guide/composer-view.tsx',['GuideComposer','使用当前整篇文档','state.detail.current.content_version']],['/src/formation/proposal-details.tsx',['adoptionScopeLabel','wireScope']],['/src/formation/evidence-picker.tsx',['currentPage','FormationEvidencePicker']],['/src/requirements/detail-layout.ts',['minimumDetailWidth','480']],['/src/requirements/detail-frame.tsx',['minimumDetailWidth','DetailFrame']],['/src/formation/progress-view.css',['@container formation-expanded']]];
     const results=[];
     for(const [path,needles] of modules){
      const response=await page.request.get('http://127.0.0.1:5187'+path);const body=await response.text();
      if(response.status()!==200||body.length<500||needles.some(value=>!body.includes(value)))throw Error('Incomplete live module '+path);
      results.push({path,status:response.status(),characters:body.length});
     }
     return results;
     }""")
                print('LIVE_MODULES', json.dumps(modules), flush=True)

            if case == 'viewport' and review:
                for width in (480, 966):
                    path = t / ('viewport-' + str(width) + '.png')
                    code = "async(page)=>{await page.setViewportSize({width:WIDTH,height:800});if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();await page.getByRole('tab',{name:'进展',exact:true}).click();await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');await page.locator('[data-step-ref=\"s1\"] .formation-node').click();await page.getByRole('button',{name:'展开主线',exact:true}).click();const dialog=page.getByRole('dialog',{name:'展开文档主线',exact:true});await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY'&&!window.formationProduct.state().formation.loading);await dialog.getByRole('button',{name:'结束并继续／处理遗留',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:IMAGE});await page.keyboard.press('Escape');return true;}"
                    run(code.replace('WIDTH', str(width)).replace('IMAGE', json.dumps(str(path))))
                    print('REVIEW_IMAGE', str(path), flush=True)
                print('VISUAL_REVIEW_READY', flush=True)
                review_started = time.monotonic()
                while (
                    not (t / 'review-complete').exists() and time.monotonic() - review_started < 55
                ):
                    time.sleep(0.2)

        except Exception:
            for job in jobs:
                print(
                    'OWNED_PROCESS_DIAGNOSTIC',
                    job.pid,
                    job.poll(),
                    ''.join(tails.get(job.pid, []))[-9000:],
                    flush=True,
                )
            raise
        finally:
            try:
                cli('close')
            except (subprocess.SubprocessError, RuntimeError, OSError) as error:
                print('close', str(error)[:100])
            if 'server' in locals() and server.poll() is None:
                try:
                    server.stdin.write('stop\n')
                    server.stdin.flush()
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    stop_owned(server)
            for job in jobs:
                if job.poll() is None:
                    stop_owned(job)
            print('OWNED_ENVIRONMENT_CLEANED', flush=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--review',
        action='store_true',
        help='Pause with temporary viewport images for local visual review',
    )
    parser.add_argument(
        '--production', action='store_true', help='Use an owned temporary production build'
    )
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--case', choices=[*CASES, 'all'], default='all')
    args = parser.parse_args()
    if args.serve:
        serve()
    else:
        for name in CASES if args.case == 'all' else [args.case]:
            print('CASE', name, flush=True)
            probe(name, args.review, production=args.production)
