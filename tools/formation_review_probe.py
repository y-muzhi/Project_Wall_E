"""Actual manual edit, ordinary review and unchanged completed Closure in two material variants."""

import json
import urllib.request
from copy import deepcopy


def seed(workspace, document):
    from backend.app.formation.commands import complete_step
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.tests.formation.test_v21_completion_commands import request

    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    body = request(workspace)
    body.update(document_id=document, expected_discussion_version=root['discussion_version'])
    result = complete_step(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result


def reply(context, sufficient):
    from backend.tests.formation.test_v21_model_contracts import examples
    from backend.tests.formation.test_v21_model_results import progress
    from backend.tests.guide.test_v15_execution import output

    source = [context.input['current_request']['message_ref']]
    blocks = context.input['documents'][0]['blocks']
    change = deepcopy(examples()[11])
    change.update(
        review_of='a1',
        source_refs=source,
        document_refs=[block['ref'] for block in blocks[: 2 if sufficient else 1]],
    )
    assessment = deepcopy(examples()[9])
    assessment.update(
        source_refs=source,
        document_refs=[block['ref'] for block in blocks[:2]],
        reason='关联核实与内容充分性分开，仍需补充验收边界',
    )
    changes = [change, assessment] if sufficient else [assessment]
    return output(context, progress_delta=progress(context, changes))


def facts(connection, document):
    return {
        'artifacts': [
            dict(row)
            for row in connection.execute(
                'SELECT * FROM formation_artifacts WHERE document_id=? ORDER BY artifact_ref',
                (document,),
            )
        ],
        'reviews': [
            dict(row)
            for row in connection.execute(
                'SELECT * FROM formation_artifact_reviews WHERE document_id=? ORDER BY event_id',
                (document,),
            )
        ],
        'step_status': connection.execute(
            "SELECT status FROM formation_steps WHERE document_id=? AND step_ref='s1'",
            (document,),
        ).fetchone()[0],
    }


def read_facts():
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/content-state', timeout=10
    ) as response:
        return json.load(response)


def browser(run, temporary, sufficient, *, width=1440):
    run(
        'async(page)=>{await page.setViewportSize({width:'
        + str(width)
        + ',height:900});return true;}'
    )
    run("""async(page)=>{
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const editor=page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
 await editor.waitFor();await editor.click();await page.keyboard.press('Control+Home');await page.keyboard.insertText('成果核实前的明确改稿');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open)))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 if((await page.evaluate(()=>window.formationProduct.state().reads.detail.data.status))!=='COMPLETED')throw Error('Manual edit reopened step');
 await page.getByRole('tab',{name:'成果',exact:true}).click();
 await page.getByText('需要复核',{exact:true}).waitFor();
 return true;
}""")
    edited = read_facts()
    assert edited['actual']['content_version'] == 2
    assert edited['actual']['artifact']['freshness'] == 'NEEDS_REVIEW'
    assert edited['initial']['closure'] == edited['actual']['closure']
    assert edited['actual']['run_count'] == edited['actual']['llm_count'] == 0
    diagnostic = run("""async(page)=>{
 await page.getByRole('tab',{name:'概览',exact:true}).click();
 await page.getByRole('button',{name:'讨论此步骤',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('核实修改后的正文关联，材料不足时保留提示');
 return {versions:await page.evaluate(()=>{const value=window.formationProduct.owner().regions.conversation.composer.getSnapshot();return {bound:value.target.content_version,current:value.detail.current.content_version};}),text:await page.getByRole('region',{name:'AI 消息输入',exact:true}).innerText()};
}""")
    assert diagnostic['versions'] == {'bound': 1, 'current': 2}, diagnostic
    assert '目标或来源已变化' in diagnostic['text'], diagnostic
    run("""async(page)=>{
 await page.getByRole('button',{name:'完善操作设置',exact:true}).click();
 const confirm=page.getByRole('button',{name:'使用当前整篇文档（V2）',exact:true});
 const bounds=await confirm.boundingBox();
 const viewport=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
 if(bounds===null||bounds.width<32||bounds.height<32||bounds.x<0||bounds.x+bounds.width>viewport.width+1||viewport.scroll>viewport.width+1)throw Error('Scope confirmation button inaccessible '+JSON.stringify({bounds,viewport}));
 await confirm.focus();await page.keyboard.press('Enter');
 await page.getByRole('button',{name:'取消调整',exact:true}).click();
 const bound=await page.evaluate(()=>window.formationProduct.owner().regions.conversation.composer.getSnapshot().target.content_version);
 if(bound!==1)throw Error('Cancelling scope confirmation replaced frozen target');
 await page.getByRole('button',{name:'完善操作设置',exact:true}).click();
 await page.getByRole('button',{name:'使用当前整篇文档（V2）',exact:true}).click();
 await page.getByRole('button',{name:'完成设置',exact:true}).click();
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='核实修改后的正文关联，材料不足时保留提示')throw Error('Rebinding current scope cleared input');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status==='COMPLETED');
 return true;
}""")
    after = read_facts()
    before, actual = after['initial'], after['actual']
    assert actual['content_version'] == 2 and actual['markdown'] == edited['actual']['markdown']
    assert actual['step_status'] == 'COMPLETED'
    assert before['closure'] == actual['closure']
    assert actual['artifact'] == edited['actual']['artifact']
    assert actual['run_count'] == actual['llm_count'] == 1
    assert len(actual['reviews']) == int(sufficient), actual['reviews']
    if sufficient:
        assert actual['reviews'][0]['result'] == 'REASSOCIATED', actual['reviews']
    assert len(actual['artifacts']) == (2 if sufficient else 1)
    if sufficient:
        assert actual['artifacts'][-1]['artifact_ref'] == 'a2'
        assert actual['artifacts'][-1]['freshness'] == 'CURRENT'
    result = run(
        """async(page)=>{
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 await page.getByRole('tab',{name:'概览',exact:true}).click();
 await page.getByRole('region',{name:'AI步骤评估',exact:true}).getByText('材料不足，暂无法判断',{exact:true}).waitFor();
 if((await page.evaluate(()=>window.formationProduct.state().reads.detail.data.status))!=='COMPLETED')throw Error('Review reopened completed step');
 await page.getByRole('tab',{name:'成果',exact:true}).click();
 await page.getByText(SUFFICIENT?'关联有效':'需要复核',{exact:true}).waitFor();
 if(SUFFICIENT){
   if(await page.getByText('需要复核',{exact:true}).count()!==0)throw Error('Replaced artifact remained current warning');
   await page.getByRole('checkbox',{name:'显示已替代关联',exact:true}).check();
   await page.getByText('已被替代',{exact:true}).waitFor();
 }
 return {sufficient:SUFFICIENT,step:'COMPLETED',semanticAssessment:'UNCERTAIN',currentAssociation:SUFFICIENT?'CURRENT':'NEEDS_REVIEW'};
}""".replace('SUFFICIENT', json.dumps(sufficient))
    )
    print('REVIEW_CLOSED_STEP_PASS', json.dumps(result), flush=True)
