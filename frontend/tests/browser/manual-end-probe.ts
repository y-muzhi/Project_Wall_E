import {editorViewCtx} from '@milkdown/kit/core';
import {ApiRejected,ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {ManualDraftAutosave} from '../../src/documents/autosave.ts';
import {DraftRecoveryStore} from '../../src/documents/recovery-store.ts';
import {ManualDraftEnd} from '../../src/documents/manual-end.ts';
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(accept=>{resolve=accept;});return {promise,resolve};}
export async function manualEndProbe(api:WalleApi,identity:number){
  const initial=(await api.getCurrentDocument(identity)).data,results:unknown[]=[];
  for(const operation of ['COMPLETE','CANCEL'] as const){
    const current=(await api.getCurrentDocument(identity)).data,draft=(await api.prepareStartManualDraft(identity,current.content_version).submit()).data.manual_draft;
    const element=document.createElement('section');document.body.append(element);
    let autosave:ManualDraftAutosave|undefined;
    const host=await RequirementEditor.create(element,draft,false,{change:()=>autosave?.changed()});
    const cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name:'walle-manual-end-probe-'+crypto.randomUUID()}));
    const committed=deferred(),release=deferred();let saves=0,preparations=0,submissions=0,drop=true;const sent:number[]=[],clearPhases:string[]=[];
    autosave=new ManualDraftAutosave(draft,host.ledger!,{
      read:async()=>(await api.getManualDraft(identity)).data,
      save:async ticket=>{saves++;sent.push(ticket.expected_version);const result=(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data;
        if(saves===1){committed.resolve();await release.promise;}return result;},
    },cache);
    const endingApi={
      getRequirement:(...args:Parameters<WalleApi['getRequirement']>)=>api.getRequirement(...args),
      getCurrentDocument:(...args:Parameters<WalleApi['getCurrentDocument']>)=>api.getCurrentDocument(...args),
      getManualDraft:(...args:Parameters<WalleApi['getManualDraft']>)=>api.getManualDraft(...args),
      prepareCompleteManualDraft:(...args:Parameters<WalleApi['prepareCompleteManualDraft']>)=>{
        preparations++;const original=api.prepareCompleteManualDraft(...args);return Object.freeze({submit:async()=>{submissions++;const result=await original.submit();if(drop){drop=false;throw new ApiUnknown(true);}return result;}});
      },
      prepareCancelManualDraft:(...args:Parameters<WalleApi['prepareCancelManualDraft']>)=>{
        preparations++;const original=api.prepareCancelManualDraft(...args);return Object.freeze({submit:async()=>{submissions++;const result=await original.submit();if(drop){drop=false;throw new ApiUnknown(true);}return result;}});
      },
    };
    const end=new ManualDraftEnd(current,draft,endingApi,host,autosave,{clearClosedDraft:async(...args)=>{clearPhases.push(end.getSnapshot().phase);await cache.clearClosedDraft(...args);}});
    const edit=(text:string)=>host.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text(text))));});
    try{
      edit(operation==='COMPLETE'?'结束控制器第一份真实内容':'取消前已发送真实内容');const pendingSave=autosave.flush();await committed.promise;
      edit(operation==='COMPLETE'?'结束控制器最新真实内容😀':'取消时不应再发送的最新内容');
      const ending=operation==='COMPLETE'?end.complete():end.cancelConfirmed();require((operation==='COMPLETE'?end.complete():end.cancelConfirmed())===ending);
      require(!await (operation==='COMPLETE'?end.cancelConfirmed():end.complete()));require(preparations===0);
      release.resolve();require(!await ending);await pendingSave;require(end.getSnapshot().phase==='UNKNOWN'&&clearPhases.length===0);
      require(!end.continueEditing()&&host.readonly);require(saves===(operation==='COMPLETE'?2:1));
      require(await end.retryUnknown());require(end.getSnapshot().phase==='CLOSED'&&Number(preparations)===1&&submissions===2&&Number(clearPhases.length)===1&&clearPhases[0]==='CLOSED');
      require(await cache.get(identity,draft.id)===null);
      const final=(await api.getCurrentDocument(identity)).data,root=(await api.getRequirement(identity)).data;
      require(root.document_work_state==='IDLE');
      if(operation==='COMPLETE')require(final.id===current.id&&final.content_version===current.content_version+1&&final.markdown_content.includes('结束控制器最新真实内容😀'));
      else require(final.content_version===current.content_version&&final.markdown_content===current.markdown_content&&!final.markdown_content.includes('取消前已发送真实内容'));
      results.push({operation,saves,versions_sent:sent,preparations,submissions,current_version:final.content_version,observed_draft:end.getSnapshot().observed?.manual_draft??null});
    }finally{
      release.resolve();end.dispose();autosave.dispose();await host.destroy();cache.close();element.remove();
      try{const remaining=(await api.getManualDraft(identity)).data;await api.prepareCancelManualDraft(identity,remaining.content_version).submit();}
      catch(error){if(!(error instanceof ApiRejected&&error.code==='MANUAL_DRAFT_NOT_FOUND'))throw error;}
    }
  }
  return {passed:true,requirement_id:identity,initial_current_version:initial.content_version,results,
    scope:'Real editor/ledger/autosave/IndexedDB/native API and SQLite; first save receipt held, actual complete/cancel 200 deliberately discarded then original action replayed. No full product navigation or paid AI'};
}
