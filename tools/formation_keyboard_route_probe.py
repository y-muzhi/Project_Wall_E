"""Actual keyboard route split and merge: native selects, Tab traversal and exact program saves."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HELPERS = "async function tabTo(target){\n await target.waitFor();\n await target.evaluate(node=>node.disabled?new Promise(resolve=>{const observer=new MutationObserver(()=>{if(!node.disabled){observer.disconnect();resolve(true);}});observer.observe(node,{attributes:true,attributeFilter:['disabled']});}):true);\n for(let index=0;index<250;index++){\n  if(await target.evaluate(node=>node===document.activeElement))return;\n  await page.keyboard.press('Tab');\n }\n throw Error('Tab cannot reach '+await target.evaluate(node=>node.outerHTML.slice(0,200)));\n}\nasync function activate(target){await tabTo(target);await page.keyboard.press('Enter');}\nasync function write(target,value){await tabTo(target);await page.keyboard.press('Control+A');await page.keyboard.insertText(value);}\nasync function select(target,wanted,byLabel=false){\n await tabTo(target);\n const index=await target.evaluate((node,{wanted,byLabel})=>[...node.options].findIndex(option=>byLabel?option.text.includes(wanted):option.value===wanted),{wanted,byLabel});\n if(index<0)throw Error('Missing declared option '+wanted);\n await page.keyboard.press('Alt+ArrowDown');await page.keyboard.press('Home');\n for(let count=0;count<index;count++)await page.keyboard.press('ArrowDown');\n await page.keyboard.press('Enter');\n}\nconst dialog=page.getByRole('dialog',{name:'调整文档路线',exact:true});\nconst changes=dialog.locator('.formation-edit-changes > li');\nasync function add(type){\n await select(dialog.getByRole('combobox',{name:'调整类型',exact:true}),type);\n await activate(dialog.getByRole('button',{name:'添加调整',exact:true}));\n return changes.last();\n}\nasync function addStep(title,result,replaces){\n const group=await add('ADD_STEP');\n await write(group.getByRole('textbox',{name:/新步骤名称/}),title);\n await write(group.getByRole('textbox',{name:/成果 1 说明/}),result);\n for(const old of replaces)await select(group.getByRole('combobox',{name:'替代哪些原步骤',exact:true}),old);\n}\nasync function cancel(old,replacements){\n const group=await add('CANCEL_STEP');\n await select(group.getByRole('combobox',{name:'要取消的步骤',exact:true}),old);\n for(const title of replacements)await select(group.getByRole('combobox',{name:'承接步骤',exact:true}),title,true);\n}\nasync function mapResult(label,target){\n const group=dialog.locator('.formation-result-routes > fieldset').filter({has:page.getByText(label,{exact:true})});\n await group.waitFor();\n for(const title of target)await select(group.getByRole('combobox',{name:'由哪些成果承接',exact:true}),title,true);\n await write(group.getByRole('textbox',{name:/成果去向说明/}),'保留原要求并由明确的新成果完整承接');\n}\nasync function openEditor(){\n const entry=page.getByRole('button',{name:'调整路线',exact:true});\n await entry.waitFor();await entry.focus();await page.keyboard.press('Enter');await dialog.waitFor();\n}\n"


def browser(run, temporary):
    run("""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.evaluate(()=>{
  window.w21RouteBody=document.querySelector('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror');
  window.w21RouteClicks=0;document.addEventListener('click',event=>{if(event.isTrusted&&event.detail!==0)window.w21RouteClicks++;},true);
 });
 return true;
}""")
    run(
        'async(page)=>{'
        + HELPERS
        + """
 await openEditor();
 await write(dialog.getByRole('textbox',{name:/本次调整原因/}),'使用键盘将原步骤拆分，完整保留成果范围');
 await addStep('键盘流程步骤','键盘流程成果',['s2']);
 await addStep('键盘异常步骤','键盘异常成果',['s2']);
 return true;
}"""
    )
    run(
        'async(page)=>{'
        + HELPERS
        + """
 await cancel('s2',['新步骤：键盘流程步骤','新步骤：键盘异常步骤']);
 await mapResult('下一项成果',['新成果：键盘流程成果','新成果：键盘异常成果']);
 await activate(dialog.getByRole('button',{name:'预览影响',exact:true}));
 await dialog.getByRole('heading',{name:'调整预览',exact:true}).waitFor();
 await activate(dialog.getByRole('button',{name:'上移调整 2',exact:true}));
 await dialog.getByRole('heading',{name:'上次预览（已过时）',exact:true}).waitFor();
 if(!(await dialog.getByRole('button',{name:'确认保存路线',exact:true}).isDisabled()))throw Error('Changed keyboard order retained save permission');
 await activate(dialog.getByRole('button',{name:'下移调整 1',exact:true}));
 await activate(dialog.getByRole('button',{name:'预览影响',exact:true}));
 await dialog.getByRole('heading',{name:'调整预览',exact:true}).waitFor();
 await activate(dialog.getByRole('button',{name:'确认保存路线',exact:true}));
 await dialog.waitFor({state:'detached'});
 return true;
}"""
    )
    split = run("""async(page)=>{
 const response=await page.request.get('http://127.0.0.1:8217/api/v1/requirements/1/documents/1/formation/steps?include_cancelled=true&limit=20');
 const items=(await response.json()).data.items;
 if(items.find(row=>row.step_ref==='s2')?.status!=='CANCELLED')throw Error('Original step not cancelled '+JSON.stringify(items));
 const first=items.find(row=>row.title==='键盘流程步骤'),second=items.find(row=>row.title==='键盘异常步骤');
 if(!first||!second||first.status!=='PLANNED'||second.status!=='PLANNED')throw Error('Split result missing');
 await page.evaluate(value=>{window.w21Split=value;},{first:first.step_ref,second:second.step_ref});
 return {first:first.step_ref,second:second.step_ref};
}""")
    run(
        'async(page)=>{'
        + HELPERS
        + """
 await openEditor();
 await write(dialog.getByRole('textbox',{name:/本次调整原因/}),'使用键盘合并两个步骤，逐项承接所有成果');
 const refs=await page.evaluate(()=>window.w21Split);
 await addStep('键盘合并步骤','键盘合并成果',[refs.first,refs.second]);
 await cancel(refs.first,['新步骤：键盘合并步骤']);
 await cancel(refs.second,['新步骤：键盘合并步骤']);
 return true;
}"""
    )
    run(
        'async(page)=>{'
        + HELPERS
        + """
 await mapResult('键盘流程成果',['新成果：键盘合并成果']);
 await mapResult('键盘异常成果',['新成果：键盘合并成果']);
 await activate(dialog.getByRole('button',{name:'预览影响',exact:true}));
 await dialog.getByRole('heading',{name:'调整预览',exact:true}).waitFor();
 await activate(dialog.getByRole('button',{name:'确认保存路线',exact:true}));
 await dialog.waitFor({state:'detached'});
 return true;
}"""
    )
    final = run("""async(page)=>{
 const response=await page.request.get('http://127.0.0.1:8217/api/v1/requirements/1/documents/1/formation/steps?include_cancelled=true&limit=20');
 const items=(await response.json()).data.items;
 const split=await page.evaluate(()=>window.w21Split);
 if([split.first,split.second].some(ref=>items.find(row=>row.step_ref===ref)?.status!=='CANCELLED'))throw Error('Merge did not cancel both old owners');
 const combined=items.find(row=>row.title==='键盘合并步骤');
 if(!combined||combined.status!=='PLANNED')throw Error('No real merged identity');
 const current=await (await page.request.get('http://127.0.0.1:8217/api/v1/requirements/1/current-document?document_id=1')).json();
 if(current.data.content_version!==2)throw Error('Keyboard path wrote body');
 const actual=await page.evaluate(()=>({sameBody:window.w21RouteBody.isConnected&&window.w21RouteBody===document.querySelector('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror'),pointerClicks:window.w21RouteClicks,writes:window.formationProduct.requests().filter(row=>row.method==='PATCH').length}));
 if(!actual.sameBody||actual.pointerClicks!==0||actual.writes!==2)throw Error('Keyboard route did not remain actual keyboard-only '+JSON.stringify(actual));
 const facts=await (await page.request.get('http://127.0.0.1:8217/__fixture/storage-state')).json();
 if(facts.runs!==1||facts.llm!==1)throw Error('Keyboard route added model round');
 return {combined:combined.step_ref,...actual,contentVersion:2,runs:1,llm:1};
}""")
    print('KEYBOARD_SPLIT_MERGE_PASS', json.dumps({'split': split, 'final': final}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.CASES['keyboard-route'] = browser
    base.probe('keyboard-route', production=True)
