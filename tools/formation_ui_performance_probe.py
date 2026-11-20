"""Measure actual trusted-click to local feedback, separately from delayed detail HTTP."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seed(workspace):
    from backend.tests.formation.test_v21_contracts import add_step
    from backend.tests.formation.test_v21_real_growth_continuation import route

    for offset in range(0, 199, 20):
        changes = [add_step(index + 1) for index in range(min(20, 199 - offset))]
        for index, change in enumerate(changes):
            change['title'] = '反馈步骤' + str(offset + index + 3)
        route(workspace, 1, changes)


def browser(run, temporary):
    result = run(r"""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 const baseline=await page.evaluate(()=>({current:window.formationProduct.state().reads.summary.data.current_step_ref,branches:window.formationProduct.state().reads.summary.data.counts.branches}));
 const total=await page.evaluate(()=>window.formationProduct.state().reads.page.data.data.total);
 if(total!==201)throw Error('Not actual 201 step fixture '+total);
 await page.route(/\/formation\/steps\/s[0-9]+(?:\?|$)/,async route=>{
  await new Promise(resolve=>setTimeout(resolve,350));
  await route.continue();
 });
 await page.evaluate(()=>{
  window.w21Feedback={selection:[],expansion:[],start:null,kind:null,ref:null};
  document.addEventListener('click',event=>{
   if(!event.isTrusted)return;
   const state=window.w21Feedback;
   const node=event.target.closest?.('button.formation-node');
   const expand=event.target.closest?.('button[aria-label="展开主线"]');
   if(node){state.kind='selection';state.ref=node.closest('[data-step-ref]').dataset.stepRef;}
   else if(expand){state.kind='expansion';state.ref=null;}
   else return;
   state.start=performance.now();
   const observer=new MutationObserver(()=>{
    const visible=state.kind==='selection'
      ?document.querySelector('[data-step-ref="'+state.ref+'"][data-selected="true"] .formation-node[aria-pressed="true"]')
      :document.querySelector('dialog.formation-dialog[open]');
    if(!visible)return;
    observer.disconnect();
    requestAnimationFrame(()=>{
      const elapsed=performance.now()-state.start;
      state[state.kind].push(elapsed);state.start=null;
    });
   });
   observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-selected','aria-pressed','open']});
  },true);
 });
 for(let index=0;index<21;index++){
  const ref=index%2===0?'s2':'s1';
  await page.locator('[data-step-ref="'+ref+'"] .formation-node').click();
  await page.waitForFunction(n=>window.w21Feedback.selection.length===n,index+1);
  await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 }
 await page.unroute(/\/formation\/steps\/s[0-9]+(?:\?|$)/);
 for(let index=0;index<21;index++){
  await page.getByRole('button',{name:'展开主线',exact:true}).click();
  await page.waitForFunction(n=>window.w21Feedback.expansion.length===n,index+1);
  await page.getByRole('dialog',{name:'展开文档主线',exact:true}).getByRole('button',{name:'收起主线',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('dialog.formation-dialog')===null);
 }
 const data=await page.evaluate(()=>window.w21Feedback);
 function stats(rows){const values=rows.slice(1).sort((a,b)=>a-b);return {n:values.length,firstWarmup:rows[0],p50:(values[9]+values[10])/2,p95:values[18],max:values[19]};}
 const statsSelection=stats(data.selection),statsExpansion=stats(data.expansion);
 const current=await page.evaluate(()=>window.formationProduct.state().reads.summary.data.current_step_ref);
 if(current!==baseline.current||(await page.evaluate(()=>window.formationProduct.requests())).length!==0)throw Error('Performance viewing wrote state');
 if(statsSelection.p95>100||statsExpansion.p95>100)throw Error('Local p95 missed '+JSON.stringify({statsSelection,statsExpansion}));
 return {scale:201,viewport:'1440x900',detailDelayMs:350,selection:statsSelection,expansion:statsExpansion,browser:await page.evaluate(()=>navigator.userAgent),logicalCpu:await page.evaluate(()=>navigator.hardwareConcurrency),deviceMemoryGiB:await page.evaluate(()=>navigator.deviceMemory??null),writes:0};
}""")
    print('LOCAL_FEEDBACK_PERF_PASS', json.dumps(result), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.CASES['ui-performance'] = browser
    base.probe('ui-performance')
