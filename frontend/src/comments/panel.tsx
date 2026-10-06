import {useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import type {CommentItem} from '../api/models.ts';
import type {RequirementDocumentOwner,CurrentDocumentBinding} from '../requirements/document-owner.ts';
import {BlockAuxiliary} from '../documents/navigation-view.tsx';
import {CommentList,CommentMarkerLayer} from './components.tsx';
import {CommentCommandControl} from './command-control.tsx';
import {commentTarget} from './target.ts';
import {locateComment} from './locate.ts';
import type {RequirementCommentPanel,CommentSlot} from './panel-owner.ts';

function Operation({panel,slot}:Readonly<{panel:RequirementCommentPanel;slot:CommentSlot}>){
  const state=slot.flow.getSnapshot(),current=panel.getSnapshot().detail.current,intent=slot.flow.intent;
  if(!slot.open)return <button type="button" disabled={panel.blocked} onClick={()=>panel.open(slot.flow)}>继续处理未确认评论操作</button>;
  return <>
    {intent.kind==='CREATE'&&(intent.target.document_id!==current.id||intent.target.content_version!==current.content_version)&&<p role="status">正文已变化，请在当前正文重新选择评论范围；输入仍保留。</p>}
    <CommentCommandControl key={slot.key} flow={slot.flow} blocked={panel.blocked} writeReady={panel.writable(slot.flow)} readActual={panel.observe} changed={outcome=>panel.finish(slot.flow,outcome)} cancel={()=>panel.close(slot.flow)} confirmOnMount/>
    {slot.identity!==null&&['READY','ERROR'].includes(state.phase)&&!panel.comments.getSnapshot().confirmed?.items.some(row=>row.id===slot.identity)&&<button type="button" disabled={panel.blocked} onClick={()=>void panel.select(slot.identity!)}>返回评论所在页</button>}
  </>;
}
function CardActions({panel,comment}:Readonly<{panel:RequirementCommentPanel;comment:CommentItem}>){
  const slot=panel.slot(comment.id);if(slot)return <Operation panel={panel} slot={slot}/>;
  const allowed=panel.writeReady,orphan=comment.anchor_status==='ORPHANED'||comment.location.status==='ORPHANED';
  const execute=(kind:'RESOLVE'|'REOPEN'|'MODIFY')=>{const flow=panel.begin(comment.id,kind);if(flow)void panel.submit(flow);};
  return <>
    {comment.status==='OPEN'?<><button type="button" disabled={!allowed} onClick={()=>panel.begin(comment.id,'EDIT')}>编辑评论</button>
      <button type="button" disabled={!allowed} onClick={()=>execute('RESOLVE')}>解决评论</button>
      {!orphan&&<button type="button" disabled={!allowed} onClick={()=>execute('MODIFY')}>让 AI 修改</button>}</>:
      <button type="button" disabled={!allowed} onClick={()=>execute('REOPEN')}>重新打开评论</button>}
    <button type="button" disabled={!allowed} onClick={()=>panel.begin(comment.id,'DELETE')}>删除评论</button>
  </>;
}

/** All current-comment UI disappears in history. The parent owner stays alive,
 * so late write receipts, unknown requests and unsent inputs remain recoverable. */
export function CommentPanel({panel,documents}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner}>){
  const state=useSyncExternalStore(panel.subscribe,panel.getSnapshot),read=useSyncExternalStore(panel.comments.subscribe,panel.comments.getSnapshot);
  const documentState=useSyncExternalStore(documents.subscribe,documents.getSnapshot),binding=documents.currentBinding;
  if(state.view==='HISTORY'||documentState.mode==='HISTORY')return null;
  const visible=new Set(read.confirmed?.items.map(row=>row.id)??[]),offPage=state.slots.filter(slot=>slot.identity!==null&&!visible.has(slot.identity)),creation=panel.slot(null);
  return <section aria-label="需求评论" className="requirement-comments">
    <header><strong>评论</strong><button type="button" disabled={panel.blocked||state.refreshing} onClick={()=>void panel.refresh().catch(()=>undefined)}>刷新评论与详情</button></header>
    {state.suspended&&<p role="status">评论操作已暂停，输入和未确认请求仍保留。</p>}
    {state.view==='MANUAL'&&<p role="status">评论关联正式正文，人工草稿尚未生效。</p>}
    {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
    {creation&&<section aria-label="新建评论"><Operation panel={panel} slot={creation}/></section>}
    {offPage.length>0&&<section aria-label="保留的评论操作"><p>以下操作仍保留；列表继续按创建时间分页。</p>{offPage.map(slot=><div key={slot.key} data-retained-comment={slot.identity}><Operation panel={panel} slot={slot}/></div>)}</section>}
    <CommentList comments={panel.comments} blocked={panel.blocked||state.refreshing} locateReady={binding!==null}
      locate={identity=>binding!==null&&locateComment(panel.comments,binding.editor,binding.navigation,identity)} changePage={page=>void panel.page(page)} retry={()=>void panel.refresh().catch(()=>undefined)}
      actions={comment=><CardActions panel={panel} comment={comment}/>}/>
  </section>;
}

function CreationEntries({panel,documents,binding}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner;binding:CurrentDocumentBinding}>){
  const navigation=useSyncExternalStore(binding.navigation.subscribe,binding.navigation.getSnapshot),documentState=useSyncExternalStore(documents.subscribe,documents.getSnapshot),selection=documentState.selection;
  const create=(range:boolean)=>{try{const block=range?selection?.block_id:navigation.selected_block;if(block!==null&&block!==undefined)panel.create(commentTarget(binding.editor,block,range?selection:null));else panel.rejectTarget();}catch{panel.rejectTarget();}};
  return <BlockAuxiliary navigation={binding.navigation} extra={<>
    <button type="button" disabled={!panel.writeReady||navigation.selected_block===null} onMouseDown={event=>event.preventDefault()} onClick={()=>create(false)}>评论区块</button>
    <button type="button" disabled={!panel.writeReady||selection===null} onMouseDown={event=>event.preventDefault()} onClick={()=>create(true)}>评论选区</button>
  </>}/>;
}
export function CommentDocumentTools({panel,documents}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner}>){
  const state=useSyncExternalStore(panel.subscribe,panel.getSnapshot);useSyncExternalStore(documents.subscribe,documents.getSnapshot);
  const binding=documents.currentBinding;if(panel.blocked||state.view!=='CURRENT'||binding===null)return null;
  return <><CreationEntries panel={panel} documents={documents} binding={binding}/>{createPortal(<CommentMarkerLayer comments={panel.comments} editor={binding.editor} documentRoot={binding.root}
    blocked={state.refreshing} select={identity=>void panel.select(identity)}/>,binding.root.parentElement!)}</>;
}
