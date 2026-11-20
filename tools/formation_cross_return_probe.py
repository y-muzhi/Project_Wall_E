"""Actual cross-step branch navigation keeps origin, return and current selection distinct."""

import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seed(workspace):
    from backend.app.formation.commands import update_path, update_state
    from backend.tests.formation.test_v21_contracts import add_step
    from backend.tests.formation.test_v21_path_commands import request
    from backend.tests.formation.test_v21_state_commands import payload

    with workspace[0].transaction() as connection:
        event = connection.execute(
            "SELECT state_event_id FROM formation_branches WHERE document_id=1 AND branch_ref='b1'"
        ).fetchone()[0]
    resumed = update_state(
        workspace[1],
        payload(
            workspace,
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='RESOLVED',
            expected_branch_event_id=event,
            enter_after_resume=False,
        ),
    )
    assert resumed['code'] == 'UPDATED', resumed
    result = update_path(
        workspace[1],
        request(
            workspace,
            [
                add_step(),
                {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 's2'},
                {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b1', 'return_step_ref': 's2'},
            ],
        ),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    switched = update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s3'))
    assert switched['code'] == 'UPDATED', switched


def probe(run, temporary):
    result = run("""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('跨步骤选择前保留的输入');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.getByRole('checkbox',{name:'支线',exact:true}).check();
 const current=page.locator('[data-step-ref="s3"]');
 if(await current.getAttribute('data-current')!=='true')throw Error('Fixture current step not s3');
 const owner=page.locator('[data-step-ref="s2"]');
 const branch=owner.getByRole('button',{name:'讨论支线',exact:true});
 await branch.waitFor();
 const text=await owner.innerText();
 if(!text.includes('s1')||!text.includes('s2'))throw Error('Origin and return not visible '+text);
 if((await page.evaluate(()=>window.formationProduct.requests())).length!==0)throw Error('Viewing branches changed state');
 await branch.click();
 await page.waitForFunction(()=>window.formationProduct.state().formation.next_target?.discussion_branch_ref==='b1');
 const selected=await page.evaluate(()=>window.formationProduct.state().formation.next_target);
 if(selected.discussion_step_ref!=='s2'||selected.branch_intent!=='ENTER')throw Error('Selected origin rather than return '+JSON.stringify(selected));
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='跨步骤选择前保留的输入')throw Error('Branch selection cleared input');
 const sent=await page.evaluate(()=>window.formationProduct.requests());
 if(sent.length!==1||sent[0].method!=='PATCH')throw Error('Branch selection not one complete command '+JSON.stringify(sent));
 const command=JSON.parse(sent[0].body).discussion_command;
 if(command.action!=='ENTER_BRANCH'||command.step_ref!=='s2'||command.branch_ref!=='b1')throw Error('Incomplete branch selection '+JSON.stringify(command));
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.id===2);
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('下一轮新输入保持');
 return {origin:'s1',returnStep:'s2',previousCurrent:'s3',selection:selected,selectionCommands:1};
}""")
    with (temporary / 'release').open('xb') as stream:
        stream.write(b'go')
    start = time.monotonic()
    while True:
        with urllib.request.urlopen(
            'http://127.0.0.1:8217/api/v1/guide-runs/2', timeout=10
        ) as response:
            actual = json.load(response)['data']
        if actual['status'] != 'RUNNING':
            break
        if time.monotonic() - start > 50:
            raise RuntimeError('Cross return round did not terminate')
        time.sleep(0.2)
    assert actual['status'] == 'COMPLETED' and actual['effect_state'] == 'APPLIED', actual
    assert actual['accepted_target']['discussion_step_ref'] == 's2'
    assert actual['accepted_target']['discussion_branch_ref'] == 'b1'
    states = run("""async(page)=>{
 const response=await page.request.get('http://127.0.0.1:5187/api/v1/requirements/1/documents/1/formation/steps?limit=20');
 const rows=(await response.json()).data.items;
 const statuses=Object.fromEntries(rows.map(row=>[row.step_ref,row.status]));
 if(statuses.s1!=='IN_PROGRESS'||statuses.s2!=='IN_PROGRESS'||statuses.s3!=='PLANNED')throw Error('Implicit lifecycle change '+JSON.stringify(statuses));
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='下一轮新输入保持')throw Error('Late return cleared later input');
 return statuses;
}""")
    print('CROSS_RETURN_PASS', json.dumps({**result, 'statuses': states}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.CASES['cross-return'] = probe
    base.probe('cross-return')
