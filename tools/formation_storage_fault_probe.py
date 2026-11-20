"""Actual product C01 remains unsent when native IndexedDB preparation fails."""

import argparse
import importlib.util
import json
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def register_state(app, db):
    @app.get('/__fixture/storage-state')
    def state():
        with db.transaction() as connection:
            return {
                'runs': connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],
                'llm': connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],
                'messages': connection.execute(
                    'SELECT count(*) FROM conversation_messages'
                ).fetchone()[0],
                'version': connection.execute(
                    'SELECT content_version FROM requirement_documents WHERE id=1'
                ).fetchone()[0],
            }


def browser(run, temporary, mode):
    prepared = run(
        """async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s2"]').getByRole('button',{name:'讨论 下一步',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('本地记录失败时必须保留，明确恢复后才发送');
 await page.waitForFunction(()=>window.formationProduct.owner().regions.formation.writeReason===null);
 const before=await (await page.request.get('http://127.0.0.1:8217/__fixture/storage-state')).json();
 await page.evaluate(async mode=>{
  window.w21Storage={mode,hit:0,aborts:0,badKey:null};
  if(mode==='abort'){
   const original=IDBDatabase.prototype.transaction;
   window.w21Storage.restore=()=>{IDBDatabase.prototype.transaction=original;};
   IDBDatabase.prototype.transaction=function(stores,access,...rest){
    const transaction=original.call(this,stores,access,...rest);
    if(window.w21Storage.hit===0&&access==='readwrite'&&[].concat(stores).includes('pending_commands')){
     window.w21Storage.hit++;
     transaction.addEventListener('abort',()=>window.w21Storage.aborts++);
     queueMicrotask(()=>transaction.abort());
    }
    return transaction;
   };
  }else if(mode==='quota'){
   const original=IDBObjectStore.prototype.add;
   window.w21Storage.restore=()=>{IDBObjectStore.prototype.add=original;};
   IDBObjectStore.prototype.add=function(...args){
    if(this.name==='pending_commands'&&window.w21Storage.hit===0){
     window.w21Storage.hit++;throw new DOMException('Injected isolated storage quota','QuotaExceededError');
    }
    return original.apply(this,args);
   };
  }else{
   const database=await new Promise((resolve,reject)=>{
    const request=indexedDB.open('walle-v2-code-command-recovery',2);
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
   });
   const key=[location.origin,crypto.randomUUID()];
   window.w21Storage.badKey=key;
   await new Promise((resolve,reject)=>{
    const transaction=database.transaction('pending_commands','readwrite');
    transaction.objectStore('pending_commands').add({schema_version:5,invalid:'isolated bad record'},key);
    transaction.oncomplete=resolve;transaction.onabort=()=>reject(transaction.error);
   });
   database.close();
  }
 },CASE_VARIANT);
 const send=page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true});
 if(!(await send.isDisabled()))await send.click();
 await page.waitForFunction(()=>window.formationProduct.state().composer.phase==='ERROR'||window.formationProduct.state().formation.recovery_error!==null);
 const error=await page.evaluate(()=>window.formationProduct.state().composer.error??window.formationProduct.state().formation.recovery_error);
 const after=await (await page.request.get('http://127.0.0.1:8217/__fixture/storage-state')).json();
 if(JSON.stringify(before)!==JSON.stringify(after))throw Error('Storage failure changed backend '+JSON.stringify({before,after}));
 const posts=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.path.endsWith('/guide-runs')));
 if(posts.length!==0)throw Error('Unpersisted preparation sent network '+JSON.stringify(posts));
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='本地记录失败时必须保留，明确恢复后才发送')throw Error('Unsent input lost');
 const injection=await page.evaluate(()=>({hit:window.w21Storage.hit,aborts:window.w21Storage.aborts}));
 if(CASE_VARIANT==='abort'&&(injection.hit!==1||injection.aborts!==1))throw Error('Not a native aborted transaction');
 if(CASE_VARIANT==='quota'&&(!error.includes('容量不足')||injection.hit!==1))throw Error('Quota not reported accurately '+error);
 if(CASE_VARIANT==='corrupt'&&!error.includes('无法完整核实'))throw Error('Bad record not distinguished '+error);
 await page.evaluate(async()=>{
  const state=window.w21Storage;
  if(state.restore){state.restore();return;}
  const database=await new Promise((resolve,reject)=>{
   const request=indexedDB.open('walle-v2-code-command-recovery',2);
   request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
  const preserved=await new Promise((resolve,reject)=>{
   const transaction=database.transaction('pending_commands','readonly');
   const request=transaction.objectStore('pending_commands').get(state.badKey);
   request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
  if(JSON.stringify(preserved)!==JSON.stringify({schema_version:5,invalid:'isolated bad record'}))throw Error('Product deleted or rewrote corrupt fixture');
  await new Promise((resolve,reject)=>{
   const transaction=database.transaction('pending_commands','readwrite');
   transaction.objectStore('pending_commands').delete(state.badKey);
   transaction.oncomplete=resolve;transaction.onabort=()=>reject(transaction.error);
  });
  database.close();
 });
 if(CASE_VARIANT==='corrupt'){
  await page.getByRole('tab',{name:'进展',exact:true}).click();
  await page.getByRole('button',{name:'刷新主线',exact:true}).click();
  await page.waitForFunction(()=>window.formationProduct.state().formation.recovery_error===null&&!window.formationProduct.state().formation.loading);
  await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 }
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.id===2);
 return {mode:CASE_VARIANT,unsentError:error,injection,backendUnchangedBeforeRetry:true,explicitRetryRun:2};
}""".replace('CASE_VARIANT', json.dumps(mode))
    )
    with (temporary / 'release').open('xb') as stream:
        stream.write(b'go')
    finished = run("""async(page)=>{
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status==='COMPLETED');
 const run=await (await page.request.get('http://127.0.0.1:8217/api/v1/guide-runs/2')).json();
 if(run.data.effect_state!=='APPLIED'||run.data.accepted_target.discussion_step_ref!=='s2')throw Error('Retry target or effect differs '+JSON.stringify(run));
 const facts=await (await page.request.get('http://127.0.0.1:8217/__fixture/storage-state')).json();
 const posts=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.path.endsWith('/guide-runs')));
 if(facts.runs!==2||facts.llm!==2||posts.length!==1)throw Error('Storage recovery duplicated model '+JSON.stringify({facts,posts}));
 return {runs:facts.runs,llm:facts.llm,explicitSends:posts.length};
}""")
    print('PRODUCT_STORAGE_UNSENT_PASS', json.dumps({**prepared, **finished}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('abort', 'quota', 'corrupt', 'all'), default='all')
    args = parser.parse_args()
    for mode in ('abort', 'quota', 'corrupt') if args.case == 'all' else (args.case,):
        case = 'storage-' + mode
        base.CASES[case] = partial(browser, mode=mode)
        base.probe(case, production=True)
