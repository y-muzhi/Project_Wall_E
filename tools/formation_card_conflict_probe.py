"""Two actual product tabs protect old exact cards across content or focus changes."""

import importlib.util
import json
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def register_state(app, db):
    @app.get('/__fixture/card-state')
    def facts():
        with db.transaction() as connection:
            return {
                'content_version': connection.execute(
                    'SELECT content_version FROM requirement_documents WHERE id=1'
                ).fetchone()[0],
                'run_count': connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],
                'llm_count': connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],
                'formal_count': connection.execute(
                    "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
                ).fetchone()[0],
            }


def browser(run, temporary, mode):
    result = run(
        """async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 const cards=page.getByRole('region',{name:'决策卡片组',exact:true});
 await cards.getByRole('radio',{name:'apply',exact:true}).check();
 const preview=await cards.getByRole('region',{name:'提案原文与采用范围',exact:true}).innerText();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('两个窗口操作后必须保留的新输入');
 const second=await page.context().newPage();
 try{
  await second.goto('http://127.0.0.1:5187/tests/browser/formation-product.html?document=1');
  await second.waitForFunction(()=>window.formationProduct.state()?.ready===true);
  if(CASE_VARIANT==='content'){
   await second.getByRole('button',{name:'更多操作',exact:true}).click();
   await second.getByRole('button',{name:'人工编辑',exact:true}).click();
   const editor=second.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
   await editor.waitFor();await editor.click();await second.keyboard.press('Control+End');await second.keyboard.insertText('另一窗口已经保存的实际修改');
   await second.getByRole('button',{name:'完成编辑',exact:true}).click();
   await second.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
  }else{
   await second.getByRole('tab',{name:'进展',exact:true}).click();
   await second.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
   await second.locator('[data-step-ref="s2"]').getByRole('button',{name:'讨论 下一步',exact:true}).click();
   await second.waitForFunction(()=>window.formationProduct.state().formation.next_target?.discussion_step_ref==='s2');
  }
  const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/responses')&&r.request().method()==='POST');
  await cards.getByRole('button',{name:'按提案写入',exact:true}).click();
  const rejected=await response;const body=await rejected.json();
  if(rejected.status()!==409)throw Error('Old D not rejected '+JSON.stringify(body));
  await cards.getByRole('button',{name:'重读正式卡片状态与回答',exact:true}).click();
  try{
   await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.cards.getSnapshot().slots.some(slot=>{const value=slot.owner?.getSnapshot();return value&&!value.refreshing&&!value.needs_refresh&&value.error===null;}),null,{timeout:10000});
  }catch(error){
   const slots=await page.evaluate(()=>window.formationProduct.owner().regions.conversation.cards.getSnapshot().slots.map(slot=>({message:slot.message,state:slot.owner?.getSnapshot()})));
   throw Error('Refresh slots '+JSON.stringify({slots,text:await cards.innerText()}));
  }
  if(await cards.getByRole('region',{name:'提案原文与采用范围',exact:true}).innerText()!==preview)throw Error('Refresh replaced original exact proposal');
  if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='两个窗口操作后必须保留的新输入')throw Error('Conflict or reread cleared newer input');
  if(CASE_VARIANT==='content'){
   const confirm=cards.getByRole('button',{name:'按提案写入',exact:true});
   if(await confirm.count()!==0&&!(await confirm.isDisabled()))throw Error('Changed content allowed stale original');
   const text=await cards.innerText();
   if(!text.includes('变化')&&!text.includes('失效'))throw Error('No concrete stale reason '+text);
  }else{
   if(!(await cards.getByRole('radio',{name:'apply',exact:true}).isChecked()))throw Error('Focus-only refresh cleared explicit choice');
   await cards.getByRole('button',{name:'按提案写入',exact:true}).click();
   await cards.getByText('已按提案保存文档。',{exact:true}).waitFor();
   await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.cards.getSnapshot().slots.some(slot=>slot.owner?.getSnapshot().phase==='RESOLVED'));
  }
  const facts=await (await page.request.get('http://127.0.0.1:8217/__fixture/card-state')).json();
  if(facts.content_version!==3||facts.run_count!==1||facts.llm_count!==1||facts.formal_count!==(CASE_VARIANT==='content'?0:1))throw Error('Unexpected effect '+JSON.stringify(facts));
  const sent=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.path.endsWith('/responses')));
  if(sent.length!==(CASE_VARIANT==='content'?1:2))throw Error('Implicit resubmission '+JSON.stringify(sent));
  if(sent.length===2&&sent[0].key===sent[1].key)throw Error('Known rejection retried altered input under old key');
  return {mode:CASE_VARIANT,firstRejection:body.error.code,originalPreviewKept:true,newInputKept:true,explicitSubmissions:sent.length,facts};
 }finally{await second.close();}
}""".replace('CASE_VARIANT', json.dumps(mode))
    )
    print('TWO_TAB_CARD_PASS', json.dumps(result), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    for mode in ('content', 'focus'):
        case = 'two-tab-' + mode
        base.CASES[case] = partial(browser, mode=mode)
        base.probe(case)
