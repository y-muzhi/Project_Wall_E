"""Actual in-flight RESUME consumption survives failure, cancellation and rejected output."""

import argparse
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def gateway(case, temporary):
    import asyncio

    from backend.tests.formation.test_v21_resume_terminal_matrix import result_output
    from backend.tests.guide.test_v15_execution import Gateway, output

    class SequenceGateway(Gateway):
        def __init__(self):
            super().__init__()
            self.sequence = 0

        async def send(self, profile, context):
            self.sequence += 1
            stage = self.sequence
            with (temporary / ('gateway-entered-' + str(stage))).open('xb') as stream:
                stream.write(b'entered')
            if stage in (1, 2):
                while not (temporary / ('release-' + str(stage))).exists():
                    await asyncio.sleep(0.05)
            if stage == 1:
                return await Gateway(output).send(profile, context)
            if stage == 2:
                if case == 'resume-failed':
                    return await Gateway(failed=True).send(profile, context)
                return await Gateway(lambda value: result_output(value, invalid=True)).send(
                    profile, context
                )
            return await Gateway(
                lambda value: result_output(value, summary='后续ENTER形成的新结果')
            ).send(profile, context)

    return SequenceGateway()


def install_diagnostics(patcher):
    import traceback

    from backend.app.guide import orchestrator

    original = orchestrator._native

    async def observed(function, *args, **kwargs):
        try:
            return await original(function, *args, **kwargs)
        except Exception:
            traceback.print_exc()
            raise

    patcher.setattr(orchestrator, '_native', observed)
    from backend.app.guide import collaboration_execution

    original_execution = collaboration_execution.execute_collaboration

    async def observed_execution(*args, **kwargs):
        try:
            return await original_execution(*args, **kwargs)
        except Exception:
            traceback.print_exc()
            raise

    patcher.setattr(collaboration_execution, 'execute_collaboration', observed_execution)


def register_state(app, db):
    with db.transaction() as connection:
        event = connection.execute(
            "SELECT state_event_id FROM formation_branches WHERE document_id=1 AND branch_ref='b1'"
        ).fetchone()[0]

    def original_event(connection):
        return {
            table: [
                tuple(row)
                for row in connection.execute(
                    'SELECT * FROM ' + table + ' WHERE event_id=?', (event,)
                )
            ]
            for table in ('formation_event_changes', 'formation_event_members')
        }

    with db.transaction() as connection:
        frozen = original_event(connection)

    @app.get('/__fixture/resume-state')
    def read_state():
        with db.transaction() as connection:
            branch = dict(
                connection.execute(
                    "SELECT * FROM formation_branches WHERE document_id=1 AND branch_ref='b1'"
                ).fetchone()
            )
            return {'original': frozen, 'actual': original_event(connection), 'branch': branch}


def terminal(identity):
    start = time.monotonic()
    while True:
        with urllib.request.urlopen(
            'http://127.0.0.1:8217/api/v1/guide-runs/' + str(identity), timeout=10
        ) as response:
            actual = json.load(response)['data']
        if actual['status'] != 'RUNNING':
            return actual
        if time.monotonic() - start > 50:
            raise RuntimeError('Run did not terminate ' + str(identity))
        time.sleep(0.2)


def release(temporary, stage):
    with (temporary / ('release-' + str(stage))).open('xb') as stream:
        stream.write(b'go')


def probe(run, temporary, case):
    run("""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s2"]').getByRole('button',{name:'讨论 下一步',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('先讨论步骤2，保持旧支线结果');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.id===2);
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('checkbox',{name:'支线',exact:true}).check();
 await page.getByRole('button',{name:'下一轮讨论支线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.branch_intent==='RESUME');
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('下一轮继续支线');
 return true;
}""")
    release(temporary, 1)
    first = terminal(2)
    print('FIRST_TERMINAL', first['status'], first['effect_state'], flush=True)
    assert first['status'] == 'COMPLETED' and first['effect_state'] == 'APPLIED', first
    run("""async(page)=>{
 const finish=page.getByRole('button',{name:'读取已接受结果',exact:true});
 if(await finish.isVisible())await finish.click();
 await page.waitForFunction(()=>window.formationProduct.state().composer.phase==='READY');
 const target=await page.evaluate(()=>window.formationProduct.state().formation.next_target);
 if(target.branch_intent!=='RESUME')throw Error('Unsent RESUME consumed by old round');
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='下一轮继续支线')throw Error('Old round cleared next input');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.id===3);
 await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.branch_intent==='ENTER');
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('失败后仍要保留的新输入');
 return true;
}""")
    started = time.monotonic()
    while not (temporary / 'gateway-entered-2').exists():
        if time.monotonic() - started > 20:
            raise RuntimeError('Second original provider stage was not entered')
        time.sleep(0.05)
    if case == 'resume-cancelled':
        run("""async(page)=>{
 await page.getByRole('region',{name:'AI 运行操作',exact:true}).getByRole('button',{name:'取消运行',exact:true}).click();
 return true;
}""")
    else:
        release(temporary, 2)
    failed = terminal(3)
    expected = {
        'resume-failed': ('FAILED', 'FAILED'),
        'resume-cancelled': ('CANCELLED', 'CANCELLED'),
        'resume-invalid': ('COMPLETED', 'STRUCTURED_REJECTED'),
    }[case]
    assert (failed['status'], failed['effect_state']) == expected, failed
    if case == 'resume-failed':
        assert failed['error_code'] == 'MODEL_ERROR', failed
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/resume-state', timeout=10
    ) as response:
        state = json.load(response)
    assert state['original'] == state['actual'] and state['branch']['status'] == 'OPEN', state
    assert state['branch']['result_summary'] is None, state
    run("""async(page)=>{
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status!=='RUNNING');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 const finish=page.getByRole('button',{name:'读取已接受结果',exact:true});
 if(await finish.isVisible())await finish.click();
 const state=await page.evaluate(()=>window.formationProduct.state());
 if(state.formation.next_target.branch_intent!=='ENTER'||state.formation.next_target.branch_resume_basis!==null)throw Error('Terminal result restored old RESUME');
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='失败后仍要保留的新输入')throw Error('Terminal result cleared later input');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.requests().filter(r=>r.path.endsWith('/guide-runs')).length===3);
 return true;
}""")
    last = terminal(4)
    assert last['status'] == 'COMPLETED' and last['effect_state'] == 'APPLIED', last
    result = run("""async(page)=>{
 const sent=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.path.endsWith('/guide-runs')).map(row=>JSON.parse(row.body).target));
 if(sent.length!==3||sent[0].discussion_step_ref!=='s2'||sent[0].discussion_branch_ref!==null||sent[1].branch_intent!=='RESUME'||sent[2].branch_intent!=='ENTER'||sent[2].branch_resume_basis!==null)throw Error('Unexpected target consumption '+JSON.stringify(sent));
 const extra=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.method==='PATCH').map(row=>JSON.parse(row.body).discussion_command));
 if(extra.some(command=>command.action==='RESUME_BRANCH'))throw Error('Busy selection sent implicit native RESUME');
 return {intents:sent.map(target=>target.branch_intent),patches:extra.map(command=>command.action)};
}""")
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/resume-state', timeout=10
    ) as response:
        state = json.load(response)
    assert state['original'] == state['actual'], state
    assert state['branch']['status'] == 'RESOLVED'
    assert state['branch']['result_summary'] == '后续ENTER形成的新结果'
    print('RESUME_TERMINAL_PASS', case, json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    cases = ['resume-failed', 'resume-cancelled', 'resume-invalid']
    parser.add_argument('--case', choices=[*cases, 'all'], default='all')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    from functools import partial

    for selected in cases if args.case == 'all' else [args.case]:
        base.CASES[selected] = partial(probe, case=selected)
        print('CASE', selected, flush=True)
        base.probe(selected)
