import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import {editorViewCtx} from '@milkdown/kit/core';
import {require} from '../../src/api/decoding.ts';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {RequirementHeaderCommands} from '../../src/requirements/header-commands.ts';
import {RequirementHeader} from '../../src/requirements/header.tsx';
import {ManualDraftControls} from '../../src/documents/manual-controls.tsx';
import {RevisionList} from '../../src/revisions/components.tsx';
import {RequirementCommentPanel} from '../../src/comments/panel-owner.ts';
import {CommentPanel,CommentDocumentTools} from '../../src/comments/panel.tsx';
import {GuideRunPolling} from '../../src/guide/polling.ts';
import '../../src/shared/styles.css';

/** Real APIs create every document/comment/history/draft/run. Only specified
 * actual responses are dropped; no synthetic IDs or successful projections. */
export async function mountCommentPanelProbe(api:WalleApi){
 const main=document.createElement('main');main.id='native-comment-parent';main.style.cssText='padding:24px';
 const controls=document.createElement('div'),columns=document.createElement('div'),scroll=document.createElement('section'),host=document.createElement('div'),aside=document.createElement('aside');
 columns.style.cssText='display:grid;grid-template-columns:minmax(640px,1fr) 420px;gap:32px';scroll.style.cssText='height:520px;overflow:auto;padding:24px;background:white';host.style.position='relative';host.className='detail-document-content';scroll.append(host);aside.style.cssText='height:520px;overflow:auto';columns.append(scroll,aside);main.append(controls,columns);document.body.append(main);
 const initial=(await api.getCurrentDocument(2)).data,draft=(await api.prepareStartManualDraft(2,initial.content_version).submit()).data.manual_draft;
 const temporary=document.createElement('div');main.append(temporary);const editor=await RequirementEditor.create(temporary,draft,false);
 editor.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text('父级评论正文😀'))));});require(editor.valid&&editor.ledger!==null);
 const block=editor.ledger.currentSnapshot.block_state_json.blocks.at(-1)!.block_id,ticket=editor.ledger.beginSave(),saved=(await api.prepareSaveManualDraft(2,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data;
 editor.ledger.acknowledgeSave(ticket,saved);const current=(await api.prepareCompleteManualDraft(2,saved.content_version).submit()).data;await editor.destroy();temporary.remove();
 for(let number=1;number<=21;number++)await api.prepareCreateComment(2,{expected_content_version:current.content_version,block_id:block,anchor_type:'BLOCK',content:'父级实际评论 '+number}).submit();
 const counts:Record<string,{prepares:number;sends:number}>={},dropped=new Set<string>();let dropList=false,reads=0,delivered=0,poll:GuideRunPolling|undefined;
 const methods=new Set(['prepareCreateComment','prepareEditComment','prepareModifyFromComment','prepareDeleteComment']);
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);
  if(key==='listComments')return async(...args:Parameters<WalleApi['listComments']>)=>{const actual=await target.listComments(...args);if(dropList){dropList=false;throw new ApiUnknown(false);}return actual;};
  if(typeof key==='string'&&methods.has(key))return (...args:unknown[])=>{const count=counts[key]??={prepares:0,sends:0};count.prepares++;const action=value.apply(target,args);return Object.freeze({submit:async()=>{count.sends++;const actual=await action.submit();if(key!=='prepareDeleteComment'&&!dropped.has(key)){dropped.add(key);throw new ApiUnknown(true);}return actual;}});};
  return typeof value==='function'?value.bind(target):value;}});
 const reader=new RequirementDetailRead(2,wrapped),read=async()=>{reads++;require(await reader.refresh());return reader.getSnapshot().confirmed!;},actual=await read();
 const documents=new RequirementDocumentOwner(host,2,wrapped,read,scroll);await documents.adopt(actual);require(await documents.revisions.refresh());
 const panel=new RequirementCommentPanel(actual,wrapped,read,async snapshot=>{await documents.adopt(snapshot);},async run=>{delivered++;require(poll===undefined);poll=new GuideRunPolling(run.id,async(id,signal)=>(await api.getGuideRun(id,signal)).data);poll.setVisible(true);});
 const commands=new RequirementHeaderCommands(actual,wrapped);let lastDetail=documents.getSnapshot().detail;
 const release=documents.subscribe(()=>{const state=documents.getSnapshot();panel.setView(state.mode==='HISTORY'?'HISTORY':state.mode==='MANUAL'?'MANUAL':'CURRENT');
  if(state.detail&&state.detail!==lastDetail&&state.mode!=='HISTORY'){lastDetail=state.detail;panel.adopt(state.detail);commands.adopt(state.detail);}});
 await panel.refresh();const react=createRoot(controls),commentsReact=createRoot(aside);
 const refresh=async()=>{const snapshot=await documents.refresh();await panel.refresh();return snapshot;};
 function Controls(){const state=useSyncExternalStore(documents.subscribe,documents.getSnapshot),session=state.manual;
  return <><RequirementHeader commands={commands} ready={reader.writeReady&&documents.writeReady} blocked={state.busy} history={state.mode==='HISTORY'} refresh={refresh} refreshRevisions={async()=>{require(await documents.revisions.refresh());}}/>
   {state.mode==='HISTORY'&&<button type="button" disabled={state.busy} onClick={()=>void documents.exitHistory().then(async okay=>{if(okay)await panel.refresh();})}>退出历史</button>}
   {session&&state.mode!=='HISTORY'&&<ManualDraftControls autosave={session.autosave} ending={session.ending} recovery={session.recovery} valid={session.editor.valid} blocked={state.busy||session.getSnapshot().blocked} ended={async()=>{await refresh();}} serverSelected={async()=>{await refresh();}}/>}
   <RevisionList flow={documents.revisions} blocked={state.busy} open={summary=>void documents.openHistory(summary)}/><CommentDocumentTools panel={panel} documents={documents}/></>;
 }
 react.render(<Controls/>);commentsReact.render(<CommentPanel panel={panel} documents={documents}/>);
 return {state:()=>({mode:documents.getSnapshot().mode,busy:documents.getSnapshot().busy,selection:documents.getSnapshot().selection,document_error:documents.getSnapshot().error,ready:panel.writeReady,read:panel.comments.getSnapshot(),panel:{...panel.getSnapshot(),slots:panel.getSnapshot().slots.map(slot=>({key:slot.key,identity:slot.identity,open:slot.open,intent:slot.flow.intent,state:slot.flow.getSnapshot()}))},counts,reads,delivered,run:poll?.state.confirmed,block,current_version:current.content_version,scroll:scroll.scrollTop}),
  failList(){dropList=true;},
  async inspect(){const now=(await api.getCurrentDocument(2)).data,index=(await api.getCommentIndex(2)).data;require(now.id===current.id&&now.content_version===current.content_version&&now.markdown_content===current.markdown_content&&JSON.stringify(now.block_state_json)===JSON.stringify(current.block_state_json));
   const rows=(await api.listComments(2,2)).data.items;require(index.total_count===22&&index.open_count===22&&index.blocks[0]?.open_count===22&&rows.some(row=>row.anchor_type==='SELECTION')&&panel.getSnapshot().slots.length===0&&delivered===1&&poll!==undefined&&poll.state.confirmed?.status==='FAILED'&&poll.state.confirmed.error_code==='CONFIG_INVALID');
   return {passed:true,counts,reads,delivered,run:poll.state.confirmed.id,run_status:poll.state.confirmed.status,current_id:now.id,current_version:now.content_version,total:index.total_count,open:index.open_count,scope:'Actual integrated CURRENT comment page/tools/markers and retained command owners across history/manual/page changes; lost write receipts and failed post-success reads recovered; no product root/full AI view/Provider acceptance'};},
  async destroy(){react.unmount();commentsReact.unmount();release();panel.dispose();poll?.dispose();commands.dispose();reader.dispose();await documents.retire();require(host.childNodes.length===0);main.remove();return {passed:true};}};
}
