import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {editorViewCtx} from '@milkdown/kit/core';
import type {ReactNode} from 'react';
import type {CommentItem} from '../api/models.ts';
import {Pagination} from '../shared/pagination.tsx';
import {localTime} from '../shared/time.ts';
import type {RequirementComments} from './read.ts';
import type {RequirementEditor} from '../documents/editor.ts';

export function CommentList({comments,locate,actions,blocked=false,locateReady=true,changePage,retry}:Readonly<{comments:RequirementComments;locate(identity:number):boolean;actions?:(comment:CommentItem)=>ReactNode;blocked?:boolean;locateReady?:boolean;changePage?:(page:number)=>void;retry?:()=>void}>){
  const state=useSyncExternalStore(comments.subscribe,comments.getSnapshot),list=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(state.selected!==null&&!state.loading&&!state.error){const card=list.current?.querySelector<HTMLElement>('[data-comment-id="'+state.selected+'"]');card?.scrollIntoView({block:'nearest'});card?.focus({preventScroll:true});}},[state.selection_revision]);
  return <section className="comment-panel" aria-label="评论列表" aria-busy={state.loading}>
    {!state.active&&<p role="status">当前评论交互已暂停</p>}
    {state.loading&&!state.confirmed&&<p role="status">正在读取评论</p>}
    {state.error&&<p role="alert">{state.error} <button type="button" disabled={blocked||state.loading||!state.active} onClick={()=>retry?retry():void comments.refresh()}>重试读取评论</button></p>}
    <div ref={list}>{state.confirmed?.items.map(comment=>{
      const orphan=comment.location.status==='ORPHANED',quote='selected_text' in comment.anchor_ref?comment.anchor_ref.selected_text:comment.anchor_ref.block_markdown_snapshot;
      return <article tabIndex={-1} data-comment-id={comment.id} key={comment.id} aria-label={'评论 '+comment.id} className={'comment-card'+(comment.status==='RESOLVED'?' is-resolved':'')+(state.selected===comment.id?' is-selected':'')}>
        <div className="comment-status"><span>{comment.status==='OPEN'?'未解决':'已解决'}</span><span>锚点：{comment.anchor_status==='ORPHANED'?'已失效':'有效'}</span><span>{orphan?'当前位置已失效':'当前可定位'}</span><time dateTime={comment.created_at}>{localTime(comment.created_at)}</time></div>
        {orphan&&<p className="comment-orphan-warning"><span aria-hidden="true">⚠ </span><span>以下是创建评论时的历史引用，当前正文位置已失效。</span></p>}
        <blockquote className="comment-quote">{quote}</blockquote><p className="comment-content">{comment.content}</p>
        <div className="comment-actions"><button type="button" disabled={blocked||!locateReady||orphan||!comments.ready} onClick={()=>locate(comment.id)}>定位正文</button>{actions?.(comment)}</div>
      </article>;
    })}</div>
    {state.confirmed?.pagination.total===0&&<p>暂无评论</p>}
    {state.confirmed&&<Pagination value={state.confirmed.pagination} loading={blocked||state.loading||!state.active} change={page=>changePage?changePage(page):void comments.refresh(page)}/>}
  </section>;
}

/** A block auxiliary control consumes the whole I37 count, not the visible
 * page. Parent places it beside that actual CURRENT block. */
export function BlockCommentMarker({comments,blockId,blocked=false,select}:Readonly<{comments:RequirementComments;blockId:number;blocked?:boolean;select?:(identity:number)=>void}>){
  const state=useSyncExternalStore(comments.subscribe,comments.getSnapshot),block=state.confirmed?.index.blocks.find(row=>row.block_id===blockId);
  if(!block)return null;
  return <button type="button" className="comment-marker" data-comment-block={blockId} disabled={blocked||!comments.ready} aria-label={block.open_count+'条未解决评论'} onClick={()=>select?select(block.comment_ids[0]!):void comments.select(block.comment_ids[0]!)}>评论 {block.open_count}</button>;
}

/** Owned sibling overlay, outside ProseMirror/Markdown. The parent gives it
 * the same relative container and CURRENT root; history hides it explicitly. */
export function CommentMarkerLayer({comments,editor,documentRoot,visible=true,blocked=false,select}:Readonly<{comments:RequirementComments;editor:RequirementEditor;documentRoot:HTMLElement;visible?:boolean;blocked?:boolean;select?:(identity:number)=>void}>){
  const state=useSyncExternalStore(comments.subscribe,comments.getSnapshot),[positions,setPositions]=useState<readonly Readonly<{id:number;top:number}>[]>([]);
  useEffect(()=>{
    const measure=()=>{
      const current=state.confirmed?.current,displayed=editor.loadedDocument;
      if(!visible||!current||!editor.valid||displayed.document_type!=='CURRENT'||JSON.stringify(displayed)!==JSON.stringify(current)||!documentRoot.getClientRects().length){setPositions([]);return;}
      const box=documentRoot.getBoundingClientRect();
      const result=editor.action(ctx=>{const view=ctx.get(editorViewCtx),positions:{id:number;top:number}[]=[];view.state.doc.forEach((node,offset)=>{if(!state.confirmed!.index.blocks.some(block=>block.block_id===node.attrs.walle_block_id))return;const dom=view.nodeDOM(offset);if(dom instanceof HTMLElement)positions.push({id:node.attrs.walle_block_id as number,top:dom.getBoundingClientRect().top-box.top});});return positions;});setPositions(result);
    };
    measure();const resize=new ResizeObserver(measure);resize.observe(documentRoot);window.addEventListener('resize',measure);window.addEventListener('scroll',measure,true);
    return()=>{resize.disconnect();window.removeEventListener('resize',measure);window.removeEventListener('scroll',measure,true);};
  },[state.confirmed,editor,documentRoot,visible]);
  return <div className="comment-marker-layer" aria-label="正文评论标记">{positions.map(position=><div key={position.id} style={{top:position.top}}><BlockCommentMarker comments={comments} blockId={position.id} blocked={blocked} {...(select?{select}:{})}/></div>)}</div>;
}
