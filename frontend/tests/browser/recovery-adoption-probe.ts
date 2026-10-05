import {editorViewCtx} from '@milkdown/kit/core';
import {closeHistory,undo} from '@milkdown/kit/prose/history';
import {ApiRejected} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {DraftRecoveryStore} from '../../src/documents/recovery-store.ts';
import type {LocalDraftSnapshot} from '../../src/documents/recovery-store.ts';
import {ManualDraftAutosave} from '../../src/documents/autosave.ts';
import {ManualDraftRecovery} from '../../src/documents/manual-recovery.ts';
const diagnosticKey='walle-diagnostic-recovery-adoption';
// Explicit flushes isolate page-reload recovery from the existing native timer
// diagnostic. API/SQLite/editor/IndexedDB operations remain actual.
const timing={schedule:()=>()=>{}};
function append(host:RequirementEditor,text:string){host.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(closeHistory(view.state.tr).insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text(text))));});require(host.valid);}
function removeLast(host:RequirementEditor){host.action(ctx=>{const view=ctx.get(editorViewCtx),last=view.state.doc.lastChild!;view.dispatch(closeHistory(view.state.tr).delete(view.state.doc.content.size-last.nodeSize,view.state.doc.content.size));});require(host.valid);}
function binding(api:WalleApi,identity:number,host:RequirementEditor,cache:DraftRecoveryStore,draft:ConstructorParameters<typeof ManualDraftAutosave>[0]) {return new ManualDraftAutosave(draft,host.ledger!,{
  read:async()=>(await api.getManualDraft(identity)).data,
  save:async ticket=>(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data,
},cache,timing);}
async function persist(cache:DraftRecoveryStore,autosave:ManualDraftAutosave,identity:number,draftId:number){
  const record:LocalDraftSnapshot={schema_version:1,base_confirmed_version:autosave.state.confirmed_version,...autosave.localSnapshot,local_revision:autosave.state.local_revision,updated_at:new Date().toISOString()};
  require(await cache.put(identity,draftId,record));return record;
}

export async function prepareRecoveryAdoption(api:WalleApi,identity:number){
  const current=(await api.getCurrentDocument(identity)).data,draft=(await api.prepareStartManualDraft(identity,current.content_version).submit()).data.manual_draft;
  const element=document.createElement('section');document.body.append(element);let autosave:ManualDraftAutosave|undefined;
  const host=await RequirementEditor.create(element,draft,false,{change:()=>autosave?.changed()});
  const name='walle-recovery-adoption-'+crypto.randomUUID(),cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name}));autosave=binding(api,identity,host,cache,draft);
  try{
    append(host,'已保存后删除再恢复的区块');await autosave.flush();require(autosave.state.confirmed_version===2);
    const born=autosave.localSnapshot.block_state_json.blocks.at(-1)!;
    removeLast(host);await autosave.flush();require(Number(autosave.state.confirmed_version)===3);
    host.action(ctx=>{const view=ctx.get(editorViewCtx);require(undo(view.state,view.dispatch));});require(host.valid);
    require(autosave.localSnapshot.block_state_json.blocks.at(-1)!.block_id===born.block_id);
    append(host,'暂时分配然后删除的区块');const hole=autosave.localSnapshot.block_state_json.blocks.at(-1)!.block_id;removeLast(host);
    append(host,'未同步待刷新恢复的新区块😀');const local=await persist(cache,autosave,identity,draft.id),newId=local.block_state_json.blocks.at(-1)!.block_id;
    require(newId>hole&&local.block_state_json.next_block_id===newId+1&&local.base_confirmed_version===3);
    const server=(await api.getManualDraft(identity)).data;
    require(server.content_version===3&&!server.block_state_json.blocks.some(block=>block.block_id===born.block_id||block.block_id===newId));
    sessionStorage.setItem(diagnosticKey,JSON.stringify({identity,draft_id:draft.id,name,born,hole,new_id:newId,next:local.block_state_json.next_block_id,local_revision:local.local_revision,markdown:local.markdown_content,current_version:current.content_version}));
    return {passed:true,actual_draft_version:3,cache_base_version:3,local_revision:local.local_revision,born_id:born.block_id,new_id:newId,hole,next:local.block_state_json.next_block_id,
      scope:'Native I09/I11, actual editor insert/delete/undo and actual IndexedDB commit before full browser reload; explicit diagnostic flush clock'};
  }finally{autosave.dispose();await host.destroy();cache.close();element.remove();}
}

export async function resumeRecoveryAdoption(api:WalleApi){
  const metadata=JSON.parse(sessionStorage.getItem(diagnosticKey)!);require(metadata&&Number.isSafeInteger(metadata.identity));const id=metadata.identity;
  const current=(await api.getCurrentDocument(id)).data,draft=(await api.getManualDraft(id)).data,root=(await api.getRequirement(id)).data;
  const element=document.createElement('section');document.body.append(element);let host:RequirementEditor|undefined,cache:DraftRecoveryStore|undefined,autosave:ManualDraftAutosave|undefined,recovery:ManualDraftRecovery|undefined;
  try{
    host=await RequirementEditor.create(element,draft,true,{change:()=>autosave?.changed()});cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name:metadata.name}));autosave=binding(api,id,host,cache,draft);
    recovery=new ManualDraftRecovery(root,current,draft,api,host,autosave,cache);
    require(await recovery.inspect());require(recovery.getSnapshot().phase==='AVAILABLE'&&host.readonly);
    const local=recovery.getSnapshot().local!;require(local.markdown_content===metadata.markdown&&local.local_revision===metadata.local_revision);
    require(host.ledger!.currentSnapshot.markdown_content===draft.markdown_content&&host.ledger!.savedVersion===3);
    // Explicit user choice is made after the fresh server/cache comparison.
    require(await recovery.restore());require(String(recovery.getSnapshot().phase)==='RESTORED'&&!host.readonly&&host.ledger!.savedVersion===3);
    require(host.ledger!.currentSnapshot.markdown_content===local.markdown_content&&host.ledger!.currentSnapshot.block_state_json.next_block_id===metadata.next);
    require(autosave.state.local_revision===metadata.local_revision+1&&autosave.state.confirmed_version===3);
    append(host,'恢复后继续真实编辑');await autosave.flush();require(autosave.state.status==='SAVED'&&Number(autosave.state.confirmed_version)===4);
    const saved=(await api.getManualDraft(id)).data,born=saved.block_state_json.blocks.find(block=>block.block_id===metadata.born.block_id)!;
    require(born.created_at===metadata.born.created_at&&born.created_by_type===metadata.born.created_by_type&&born.created_source_id===metadata.born.created_source_id);
    require(saved.block_state_json.blocks.some(block=>block.block_id===metadata.new_id)&&!saved.block_state_json.blocks.some(block=>block.block_id===metadata.hole));
    require(saved.block_state_json.next_block_id===metadata.next+1); // the post-restore paragraph is a new allocation
    const unchanged=(await api.getCurrentDocument(id)).data;require(unchanged.content_version===metadata.current_version&&unchanged.markdown_content===current.markdown_content);
    append(host,'本地冲突对照内容不能丢失');const divergent=await persist(cache,autosave,id,draft.id);
    const advanced=(await api.prepareSaveManualDraft(id,{expected_version:saved.content_version,markdown_content:saved.markdown_content,block_state_json:saved.block_state_json}).submit()).data;require(advanced.content_version===5);
    recovery.dispose();autosave.dispose();await host.destroy();cache.close();
    host=await RequirementEditor.create(element,advanced,true,{change:()=>autosave?.changed()});cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name:metadata.name}));autosave=binding(api,id,host,cache,advanced);
    recovery=new ManualDraftRecovery((await api.getRequirement(id)).data,current,advanced,api,host,autosave,cache);
    require(await recovery.inspect());require(recovery.getSnapshot().phase==='COMPARE'&&host.readonly);
    require(!await recovery.restore()&&recovery.getSnapshot().local!.markdown_content===divergent.markdown_content&&host.ledger!.currentSnapshot.markdown_content===advanced.markdown_content);
    require(await cache.get(id,draft.id)!==null);require(await recovery.discardLocalConfirmed());require(await cache.get(id,draft.id)===null);
    await api.prepareCancelManualDraft(id,advanced.content_version).submit();sessionStorage.removeItem(diagnosticKey);
    return {passed:true,actual_reload:true,restored_at_server_version:3,saved_version:4,divergent_server_version:5,divergent_cache_base:divergent.base_confirmed_version,
      continued_local_revision:divergent.local_revision,preserved_birth_id:born.block_id,preserved_birth_at:born.created_at,restored_new_id:metadata.new_id,unreused_hole:metadata.hole,
      scope:'Fresh native API/real editor and reopened IndexedDB after full page reload; explicit same-base restoration, protected deleted birth and sparse high water, native save; separate true external version conflict retains both snapshots, explicit revision-CAS discard and I13 cleanup. No full product Detail/paid AI'};
  }finally{
    recovery?.dispose();autosave?.dispose();await host?.destroy();cache?.close();element.remove();
    try{const remaining=(await api.getManualDraft(id)).data;await api.prepareCancelManualDraft(id,remaining.content_version).submit();}
    catch(error){if(!(error instanceof ApiRejected&&error.code==='MANUAL_DRAFT_NOT_FOUND'))throw error;}
  }
}
