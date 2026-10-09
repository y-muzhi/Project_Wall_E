import {editorViewCtx} from '@milkdown/kit/core';
import {ApiRejected,ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {ManualDraftSession} from '../../src/documents/manual-session.ts';
import {DraftRecoveryStore} from '../../src/documents/recovery-store.ts';
const clock={schedule:()=>()=>{}};
function append(session:ManualDraftSession,text:string){session.editor.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text(text))));});require(session.editor.valid);}

export async function manualSessionProbe(api:WalleApi,identity:number){
  const current=(await api.getCurrentDocument(identity)).data;await api.prepareStartManualDraft(identity,current.content_version).submit();
  const reader=new RequirementDetailRead(identity,api),element=document.createElement('section');document.body.append(element);
  const name='walle-session-'+crypto.randomUUID();let session:ManualDraftSession|undefined,cold:DraftRecoveryStore|undefined;
  const read=async()=>{require(await reader.refresh());return reader.getSnapshot().confirmed!;};
  try{
    session=await ManualDraftSession.create(element,await read(),api,{cacheName:name,clock});const first=session;
    require(await session.recovery.inspect());require(session.recovery.getSnapshot().phase==='SERVER_SELECTED'&&!session.getSnapshot().readonly);
    append(session,'会话窄屏保存实际内容');const saving=session.blockAndSave();require(session.editor.readonly&&session.getSnapshot().blocked);require(await saving);
    const v2=(await api.getManualDraft(identity)).data;require(v2.content_version===2&&v2.markdown_content.includes('会话窄屏保存实际内容'));
    require(session.revalidate(await read())&&session===first&&!session.editor.readonly);
    const editable=element.querySelector('.ProseMirror')!;editable.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    session.editor.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insertText('会话未完成组合',1));});
    require(!session.getSnapshot().valid);const partial=await session.prepareLeave();require(!partial.saved&&!partial.local_protected&&session.editor.readonly);
    require(session.continueAfterFailedLeave());editable.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));await Promise.resolve();require(session.getSnapshot().valid);
    require(await session.flushCurrent());const v3=(await api.getManualDraft(identity)).data;require(v3.content_version===3&&v3.markdown_content.includes('会话未完成组合'));
    const external=(await api.prepareSaveManualDraft(identity,{expected_version:3,markdown_content:v3.markdown_content,block_state_json:v3.block_state_json}).submit()).data;require(external.content_version===4);
    const before=session.autosave.localSnapshot;require(!session.revalidate(await read())&&session.getSnapshot().block_reason==='READ_CONFLICT'&&session.editor.readonly);
    require(!await session.blockAndSave('LEAVING')&&!session.continueAfterFailedLeave()&&session.getSnapshot().error!==null&&session.autosave.localSnapshot===before&&session.autosave.state.confirmed_version===3);
    await session.retire();require(!element.querySelector('.ProseMirror'));
    let loseSave=false,loseRead=false,saves=0,readLosses=0;
    const lossApi=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
      if(key==='prepareSaveManualDraft')return (...args:Parameters<WalleApi['prepareSaveManualDraft']>)=>{const original=target.prepareSaveManualDraft(...args);return {submit:async()=>{saves++;const result=await original.submit();if(loseSave){loseSave=false;throw new ApiUnknown(true);}return result;}};};
      if(key==='getManualDraft')return async(...args:Parameters<WalleApi['getManualDraft']>)=>{const result=await target.getManualDraft(...args);if(loseRead){loseRead=false;readLosses++;throw new ApiUnknown(true);}return result;};return value.bind(target);}});
    session=await ManualDraftSession.create(element,await read(),lossApi,{cacheName:name,clock});require(await session.recovery.inspect());require(session.recovery.getSnapshot().phase==='SERVER_SELECTED'&&!session.getSnapshot().readonly);
    append(session,'离开时原生保存成功但回执和复查丢失😀');loseSave=true;loseRead=true;const leave=await session.prepareLeave();require(!leave.saved&&leave.local_protected&&session.autosave.state.status==='UNKNOWN'&&session.editor.readonly);
    const local=session.autosave.localSnapshot,draftId=session.autosave.confirmedDocument.id;
    // Cold open is tracked before IDBOpenDBRequest resolves, and the actual
    // parser remains alive through the real transaction and pair validation.
    cold=session.editor.action(ctx=>new DraftRecoveryStore(ctx,{name:'walle-cold-settle-'+crypto.randomUUID()}));
    const put=cold.put(identity,draftId,{schema_version:1,base_confirmed_version:4,...local,local_revision:1,updated_at:new Date().toISOString()});
    await cold.settle();require(await put);require((await cold.get(identity,draftId))!.markdown_content===local.markdown_content);
    require(session.retire()===session.retire());await session.retire();require(!element.querySelector('.ProseMirror'));cold.close();cold=undefined;
    const fresh=await read();require(fresh.activity.kind==='MANUAL'&&fresh.activity.draft.content_version===5);
    session=await ManualDraftSession.create(element,fresh,api,{cacheName:name,clock});require(await session.recovery.inspect());
    require(session.recovery.getSnapshot().phase==='COMPARE'&&session.recovery.getSnapshot().local!.base_confirmed_version===4&&session.recovery.getSnapshot().local!.markdown_content===local.markdown_content&&session.editor.readonly);
    require(!await session.recovery.restore());require(await session.ending.cancelConfirmed());require(await session.cache.get(identity,draftId)===null);
    const root=(await api.getRequirement(identity)).data,unchanged=(await api.getCurrentDocument(identity)).data;
    require(root.document_work_state==='IDLE'&&unchanged.content_version===current.content_version&&unchanged.markdown_content===current.markdown_content);
    return {passed:true,current_version:current.content_version,native_draft_versions:[2,3,4,5],owned_save_count:saves,actual_read_losses:readLosses,partial_leave:partial,unknown_leave:leave,
      scope:'Actual session/editor/IndexedDB/native API and SQLite: synchronous block/save, same-host actual revalidation, synthetic incomplete composition refused, true external save locks original content, true I11 success and I10 loss retain cache through retirement/reopen with divergence, cold transaction settle and actual cancellation. No full product routing or Windows IME acceptance'};
  }finally{
    await session?.retire();cold?.close();reader.dispose();element.remove();
    try{const draft=(await api.getManualDraft(identity)).data;await api.prepareCancelManualDraft(identity,draft.content_version).submit();}
    catch(error){if(!(error instanceof ApiRejected&&error.code==='MANUAL_DRAFT_NOT_FOUND'))throw error;}
  }
}
