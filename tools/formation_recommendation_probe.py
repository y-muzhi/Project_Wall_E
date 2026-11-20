"""Actual coverage-stale recommendation and fresh replacement on a completed step."""

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def reply(context):
    from backend.tests.formation.test_v21_model_contracts import examples
    from backend.tests.formation.test_v21_model_results import progress
    from backend.tests.guide.test_v15_execution import output

    source = [context.input['current_request']['message_ref']]
    assessment, recommendation = deepcopy(examples()[9:11])
    assessment.update(
        source_refs=source,
        definition_version=context.canonical['formation']['selected_step']['definition_version'],
        document_refs=[block['ref'] for block in context.input['documents'][0]['blocks']],
    )
    recommendation.update(
        source_refs=source,
        action='REVIEW_CONTENT',
        reason='按本轮正文核实范围，保留独立结束操作',
    )
    return output(context, progress_delta=progress(context, [assessment, recommendation]))


def browser(run, temporary):
    result = run("""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const initial=await page.evaluate(()=>window.formationProduct.state().reads.detail.data.recommendation);
 if(initial?.validity!=='CURRENT')throw Error('Initial recommendation not current '+JSON.stringify(initial));
 const messages=(await (await page.request.get('http://127.0.0.1:8217/api/v1/requirements/1/messages?document_id=1')).json()).data.items;
 const old=messages.find(row=>row.id===initial.assistant_message_id);
 await page.getByRole('region',{name:'AI步骤建议',exact:true}).getByRole('heading',{name:'当前建议',exact:true}).waitFor();
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const editor=page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
 await editor.waitFor();await editor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText('建议依据变更的实际正文');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const stale=await page.evaluate(()=>window.formationProduct.state().reads.detail.data.recommendation);
 if(stale.validity!=='STALE'||stale.stale_reason!=='COVERAGE_CHANGED')throw Error('Coverage change not precise '+JSON.stringify(stale));
 const region=page.getByRole('region',{name:'AI步骤建议',exact:true});
 await region.getByRole('heading',{name:'历史建议，依据已变化',exact:true}).waitFor();
 await region.getByText('相关正文范围已变化',{exact:true}).waitFor();
 await page.getByRole('button',{name:'结束本步骤',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.data?.status==='COMPLETED');
 await page.getByRole('button',{name:'讨论此步骤',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('按当前正文重新核实建议，保持已结束步骤');
 await page.getByRole('button',{name:'完善操作设置',exact:true}).click();
 await page.getByRole('button',{name:'使用当前整篇文档（V3）',exact:true}).click();
 await page.getByRole('button',{name:'完成设置',exact:true}).click();
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.id===2&&window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status==='COMPLETED');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const step=await page.evaluate(()=>window.formationProduct.state().reads.detail.data);
 if(step.status!=='COMPLETED'||step.recommendation.validity!=='CURRENT'||step.recommendation.assistant_message_id===initial.assistant_message_id)throw Error('Fresh recommendation reopened or remained old '+JSON.stringify(step.recommendation));
 await page.getByRole('region',{name:'AI步骤建议',exact:true}).getByRole('heading',{name:'当前建议',exact:true}).waitFor();
 const now=(await (await page.request.get('http://127.0.0.1:8217/api/v1/requirements/1/messages?document_id=1')).json()).data.items.find(row=>row.id===initial.assistant_message_id);
 if(old.content!==now.content||JSON.stringify(old.structured_content)!==JSON.stringify(now.structured_content))throw Error('New recommendation rewrote historical message');
 const facts=await (await page.request.get('http://127.0.0.1:8217/__fixture/storage-state')).json();
 if(facts.runs!==2||facts.llm!==2||facts.version!==3)throw Error('Implicit recommendation calls '+JSON.stringify(facts));
 return {staleReason:stale.stale_reason,newValidity:step.recommendation.validity,stepStatus:step.status,oldMessageKept:true,runs:2,llm:2,contentVersion:3};
}""")
    print('RECOMMENDATION_COVERAGE_PASS', json.dumps(result), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.CASES['recommendation-coverage'] = browser
    base.probe('recommendation-coverage', production=True)
