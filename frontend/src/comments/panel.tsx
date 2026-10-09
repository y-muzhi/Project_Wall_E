import {useId,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {Icon} from '../shared/icon.tsx';
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
  if(!slot.open)return <button className="ui-button" type="button" disabled={panel.blocked} onClick={()=>panel.open(slot.flow)}>继续处理未确认评论操作</button>;
  return <>
    {intent.kind==='CREATE'&&(intent.target.document_id!==current.id||intent.target.content_version!==current.content_version)&&<p role="status">正文已变化，请在当前正文重新选择评论范围；输入仍保留。</p>}
    <CommentCommandControl key={slot.key} flow={slot.flow} blocked={panel.blocked} writeReady={panel.writable(slot.flow)} readActual={panel.observe} changed={outcome=>panel.finish(slot.flow,outcome)} cancel={()=>panel.close(slot.flow)} confirmOnMount/>
    {slot.identity!==null&&['READY','ERROR'].includes(state.phase)&&!panel.comments.getSnapshot().confirmed?.items.some(row=>row.id===slot.identity)&&<button className="ui-button" type="button" disabled={panel.blocked} onClick={()=>void panel.select(slot.identity!)}>返回评论所在页</button>}
  </>;
}
function CardActions({panel,comment}:Readonly<{panel:RequirementCommentPanel;comment:CommentItem}>){
  const [open,setOpen]=useState(false),id=useId(),trigger=useRef<HTMLButtonElement>(null),operation=useRef<HTMLDivElement>(null);
  const slot=panel.slot(comment.id);
  useLayoutEffect(()=>{
    if(slot?.open&&slot.flow.intent.kind==='EDIT')operation.current?.querySelector<HTMLTextAreaElement>('textarea:not(:disabled)')?.focus({preventScroll:true});
  },[slot?.key,slot?.open]);
  // The command/editor is outside the disclosure. Collapsing secondary actions
  // never retires a request, input, confirmation or recovery owner.
  if(slot)return <div className="comment-operation" ref={operation}><Operation panel={panel} slot={slot}/></div>;
  const allowed=panel.writeReady,orphan=comment.anchor_status==='ORPHANED'||comment.location.status==='ORPHANED';
  const execute=(kind:'RESOLVE'|'REOPEN'|'MODIFY')=>{const flow=panel.begin(comment.id,kind);if(flow)void panel.submit(flow);};
  return <div className="comment-action-group" onKeyDown={event=>{
    if(event.key==='Escape'&&open&&!event.defaultPrevented&&!(event.target instanceof Element&&event.target.closest('dialog'))){
      event.preventDefault();event.stopPropagation();setOpen(false);trigger.current?.focus();
    }
  }}>
    <button className="ui-button" type="button" disabled={!allowed} onClick={()=>execute(comment.status==='OPEN'?'RESOLVE':'REOPEN')}>{comment.status==='OPEN'?'解决评论':'重新打开评论'}</button>
    <button className="ui-button" type="button" ref={trigger} disabled={panel.blocked} aria-expanded={open} aria-controls={id} onClick={()=>setOpen(value=>!value)}><Icon name="more"/>更多</button>
    <div id={id} className="comment-more-actions" hidden={!open} inert={!open}>
      {comment.status==='OPEN'&&<><button className="ui-button" type="button" disabled={!allowed} onClick={()=>panel.begin(comment.id,'EDIT')}>编辑评论</button>
        {!orphan&&<button className="ui-button" type="button" disabled={!allowed} onClick={()=>execute('MODIFY')}>让 AI 修改</button>}</>}
      <button className="ui-button" type="button" disabled={!allowed} onClick={()=>panel.begin(comment.id,'DELETE')}>删除评论</button>
    </div>
  </div>;
}

/** All current-comment UI disappears in history. The parent owner stays alive,
 * so late write receipts, unknown requests and unsent inputs remain recoverable. */
export function CommentPanel({panel,documents}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner}>){
  const state=useSyncExternalStore(panel.subscribe,panel.getSnapshot),read=useSyncExternalStore(panel.comments.subscribe,panel.comments.getSnapshot);
  const documentState=useSyncExternalStore(documents.subscribe,documents.getSnapshot),binding=documents.currentBinding;
  if(state.view==='HISTORY'||documentState.mode==='HISTORY')return null;
  const visible=new Set(read.confirmed?.items.map(row=>row.id)??[]),offPage=state.slots.filter(slot=>slot.identity!==null&&!visible.has(slot.identity)),creation=panel.slot(null);
  return <section aria-label="需求评论" className="requirement-comments">
    <header className="read-section-heading"><strong>评论</strong><span className="read-status" role="status">{state.refreshing||read.loading?'正在读取评论…':''}</span></header>
    {state.suspended&&<p role="status">评论操作已暂停，输入和未确认请求仍保留。</p>}
    {state.view==='MANUAL'&&<p role="status">评论关联正式正文，人工草稿尚未生效。</p>}
    {panel.writeUnavailableReason&&<p className="comment-availability" role="status">{panel.writeUnavailableReason}</p>}
    {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
    {(state.error||state.needs_refresh)&&<button className="ui-button" type="button" disabled={panel.blocked||state.refreshing} onClick={()=>void panel.refresh().catch(()=>undefined)}>重新读取评论与正文</button>}
    {creation&&<section aria-label="新建评论"><Operation panel={panel} slot={creation}/></section>}
    {offPage.length>0&&<section aria-label="保留的评论操作"><p>以下操作仍保留；列表继续按创建时间分页。</p>{offPage.map(slot=><div key={slot.key} data-retained-comment={slot.identity}><Operation panel={panel} slot={slot}/></div>)}</section>}
    <CommentList comments={panel.comments} blocked={panel.blocked||state.refreshing} locateReady={binding!==null}
      locate={identity=>binding!==null&&locateComment(panel.comments,binding.editor,binding.navigation,identity)} changePage={page=>void panel.page(page)} retry={()=>void panel.refresh().catch(()=>undefined)}
      actions={comment=><CardActions panel={panel} comment={comment}/>}/>
  </section>;
}

function CreationEntries({panel,documents,binding,openPanel}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner;binding:CurrentDocumentBinding;openPanel?:()=>void}>){
  const navigation=useSyncExternalStore(binding.navigation.subscribe,binding.navigation.getSnapshot),documentState=useSyncExternalStore(documents.subscribe,documents.getSnapshot),selection=documentState.selection,id=useId();
  const reason=panel.writeUnavailableReason,blockReason=reason??(navigation.selected_block===null?'请先选择正文区块。':null),selectionReason=reason??(selection===null?'请先选中同一正文区块内的文字，再评论选区。':null);
  const create=(range:boolean)=>{try{const block=range?selection?.block_id:navigation.selected_block;if(block!==null&&block!==undefined){if(panel.create(commentTarget(binding.editor,block,range?selection:null)))openPanel?.();}else panel.rejectTarget();}catch{panel.rejectTarget();}};
  return <BlockAuxiliary navigation={binding.navigation} extra={<>
    <span title={blockReason??'评论当前区块'}><button className="ui-button" type="button" title={blockReason??undefined} aria-describedby={reason?id:undefined} disabled={blockReason!==null} onMouseDown={event=>event.preventDefault()} onClick={()=>create(false)}>评论区块</button></span>
    <span title={selectionReason??'评论当前选中文字'}><button className="ui-button" type="button" title={selectionReason??undefined} aria-describedby={selectionReason?id:undefined} disabled={selectionReason!==null} onMouseDown={event=>event.preventDefault()} onClick={()=>create(true)}>评论选区</button></span>
    {(reason||selectionReason)&&<span id={id} className="block-comment-help">{reason??selectionReason}</span>}
  </>}/>;
}
export function CommentDocumentTools({panel,documents,openPanel}:Readonly<{panel:RequirementCommentPanel;documents:RequirementDocumentOwner;openPanel?:()=>void}>){
  const state=useSyncExternalStore(panel.subscribe,panel.getSnapshot);useSyncExternalStore(documents.subscribe,documents.getSnapshot);
  const binding=documents.currentBinding;if(panel.blocked||state.view!=='CURRENT'||binding===null)return null;
  return <><CreationEntries panel={panel} documents={documents} binding={binding} {...(openPanel?{openPanel}:{})}/>{createPortal(<CommentMarkerLayer comments={panel.comments} editor={binding.editor} documentRoot={binding.root}
    blocked={state.refreshing} select={identity=>{openPanel?.();void panel.select(identity);}}/>,binding.root.parentElement!)}</>;
}
