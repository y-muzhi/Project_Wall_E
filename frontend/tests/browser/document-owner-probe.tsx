import {createRoot} from 'react-dom/client';
import {useEffect,useSyncExternalStore} from 'react';
import {editorViewCtx} from '@milkdown/kit/core';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {require} from '../../src/api/decoding.ts';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {OwnedDocumentControls,OwnedDocumentOutline} from '../../src/requirements/document-controls.tsx';
import {RequirementHeaderCommands} from '../../src/requirements/header-commands.ts';
import {RequirementHeader} from '../../src/requirements/header.tsx';
import {RevisionList} from '../../src/revisions/components.tsx';
import type {ManualDraftSession} from '../../src/documents/manual-session.ts';

export async function mountDocumentOwnerProbe(api:WalleApi){
  const main=document.createElement('main');main.id='native-document-owner';main.style.padding='24px';const controls=document.createElement('div'),columns=document.createElement('div'),outline=document.createElement('aside'),region=document.createElement('section'),host=document.createElement('div');
  columns.style.cssText='display:grid;grid-template-columns:200px minmax(640px,1fr);gap:32px';region.style.cssText='height:480px;overflow:auto;background:white;padding:24px';host.className='detail-document-content';region.append(host);columns.append(outline,region);main.append(controls,columns);document.body.append(main);
  let failNext=false,reads=0;const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const actual=await target.getCommentIndex(...args);if(failNext){failNext=false;throw new ApiUnknown(false);}return actual;};return typeof value==='function'?value.bind(target):value;}});
  const reader=new RequirementDetailRead(2,wrapped);const read=async()=>{reads++;require(await reader.refresh());return reader.getSnapshot().confirmed!;};const initial=await read();
  const owner=new RequirementDocumentOwner(host,2,wrapped,read,region);await owner.adopt(initial);require(await owner.revisions.refresh());const commands=new RequirementHeaderCommands(initial,wrapped),react=createRoot(controls),outlineReact=createRoot(outline);
  const returned=()=>owner.refresh();let remembered:ManualDraftSession|undefined;let parkedEvidence:unknown;let conflictEvidence:unknown;
  function Controls(){const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot);useSyncExternalStore(reader.subscribe,reader.getSnapshot);
    useEffect(()=>{if(state.detail)commands.adopt(state.detail);},[state.detail]);
    return <><RequirementHeader commands={commands} ready={reader.writeReady&&owner.writeReady} blocked={state.busy} history={state.mode==='HISTORY'} refresh={returned} refreshRevisions={async()=>{require(await owner.revisions.refresh());}}/>
      <OwnedDocumentControls owner={owner}/><RevisionList flow={owner.revisions} blocked={state.busy} open={summary=>void owner.openHistory(summary)}/></>;
  }
  react.render(<Controls/>);outlineReact.render(<OwnedDocumentOutline owner={owner}/>);
  return {state:()=>{const state=owner.getSnapshot(),session=state.manual;return {mode:state.mode,busy:state.busy,error:state.error,save_warning:state.save_warning,history:owner.revisions.getSnapshot().history,
    root:state.detail?.requirement,manual:session?{id:session.autosave.confirmedDocument.id,version:session.autosave.state.confirmed_version,status:session.autosave.state.status,local:session.autosave.localSnapshot.markdown_content,
      readonly:session.editor.readonly,blocked:session.getSnapshot().blocked,recovery:session.recovery.getSnapshot().phase,ending:session.ending.getSnapshot().phase}:null,reads,same_session:session===remembered,conflict:state.restoration_conflict};},
    remember(){const session=owner.getSnapshot().manual;require(session!==null&&session.recovery.getSnapshot().phase==='SERVER_SELECTED'&&!session.editor.readonly);remembered=session;return session.autosave.confirmedDocument.id;},
    async parked(){require(remembered!==undefined&&owner.getSnapshot().mode==='HISTORY'&&owner.getSnapshot().manual===remembered&&remembered.editor.readonly&&remembered.getSnapshot().blocked);
      const actual=(await api.getManualDraft(2)).data;require(actual.content_version===2&&actual.markdown_content.includes('历史停放保留😀')&&owner.revisions.getSnapshot().history.snapshot?.markdown_content===initial.current.markdown_content);
      parkedEvidence={draft_id:actual.id,version:actual.content_version,same_session:true,local_preserved:remembered.autosave.localSnapshot.markdown_content===actual.markdown_content};failNext=true;return parkedEvidence;},
    async restored(){require(remembered!==undefined&&owner.getSnapshot().mode==='MANUAL'&&owner.getSnapshot().manual===remembered&&!remembered.editor.readonly&&!remembered.getSnapshot().blocked&&remembered.autosave.state.status==='SAVED');
      require(remembered.autosave.localSnapshot.markdown_content.includes('历史停放保留😀')&&owner.revisions.getSnapshot().history.phase==='CLOSED');const current=(await api.getCurrentDocument(2)).data;require(current.content_version===initial.current.content_version&&current.markdown_content===initial.current.markdown_content);return {passed:true,same_editor:remembered.editor===owner.getSnapshot().manual?.editor,same_session:true,current_version:current.content_version};},
    async externalUpdate(){const draft=(await api.getManualDraft(2)).data,temporary=document.createElement('div');document.body.append(temporary);const external=await RequirementEditor.create(temporary,draft,false);
      try{external.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insertText('另一页后端更新😀',view.state.doc.content.size-1));});require(external.ledger!==null);const ticket=external.ledger.beginSave(),saved=(await api.prepareSaveManualDraft(2,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data;external.ledger.acknowledgeSave(ticket,saved);require(saved.content_version===3);return saved.content_version;}
      finally{await external.destroy();temporary.remove();}},
    captureConflict(){const state=owner.getSnapshot();require(state.mode==='HISTORY'&&state.restoration_conflict?.activity.kind==='MANUAL'&&state.manual!==null&&state.manual.getSnapshot().block_reason==='READ_CONFLICT'&&state.manual.editor.readonly);
      require(state.manual.autosave.state.confirmed_version===2&&state.restoration_conflict.activity.draft.content_version===3&&state.manual.autosave.localSnapshot.markdown_content.includes('冲突保留本地😀')&&!state.manual.autosave.localSnapshot.markdown_content.includes('另一页后端更新😀')&&state.restoration_conflict.activity.draft.markdown_content.includes('另一页后端更新😀'));
      conflictEvidence={local_version:2,server_version:3,local_retained:true,server_retained:true,historical_guard:true};return conflictEvidence;},
    async inspect(){require(parkedEvidence!==undefined&&remembered!==undefined&&owner.getSnapshot().mode==='CURRENT'&&owner.getSnapshot().manual===null);const actual=(await api.getCurrentDocument(2)).data,root=(await api.getRequirement(2)).data;
      require(root.document_work_state==='IDLE'&&actual.content_version===initial.current.content_version+1&&actual.markdown_content.includes('历史停放保留😀')&&!actual.markdown_content.includes('冲突保留本地😀')&&!actual.markdown_content.includes('另一页后端更新😀'));return {passed:true,parked:parkedEvidence,conflict:conflictEvidence,reads,current_id:actual.id,current_version:actual.content_version,actual_work_state:root.document_work_state,scope:'Actual header start/recovery/native input/history owner parks identical session/editor, failed/fresh restoration, actual completion; second actual draft v2 vs another page v3 rejects restoration and retains both until explicitly confirmed actual cancellation; no whole route/AI/comments/true IME or Provider'};},
    async destroy(){const actual=owner.getSnapshot().detail!;react.unmount();outlineReact.unmount();commands.dispose();reader.dispose();const foreign=document.createElement('p');foreign.textContent='Parent-owned sibling';host.append(foreign);
      await owner.retire();require(!owner.getSnapshot().active&&host.childNodes.length===1&&foreign.parentElement===host);
      const queuedRoot=document.createElement('div'),queuedForeign=document.createElement('p');queuedRoot.append(queuedForeign);main.append(queuedRoot);let lateReads=0;
      const queued=new RequirementDocumentOwner(queuedRoot,2,wrapped,async()=>{lateReads++;return actual;}),adoption=queued.adopt(actual).then(()=>false,()=>true);await queued.retire();require(await adoption);require(!queued.getSnapshot().active&&queuedRoot.childNodes.length===1&&queuedForeign.parentElement===queuedRoot&&lateReads===0);
      main.remove();return {passed:true,retired:true,parent_sibling_preserved:true,queued_adoption_skipped:true};}};
}
