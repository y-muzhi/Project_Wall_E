import {useEffect,useRef,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import {DocumentNavigation} from './navigation.ts';
import {localTime} from '../shared/time.ts';
import type {Actor,SourceType} from './contracts.ts';
import type {ReactNode} from 'react';

const actors:Record<Actor,string>={SYSTEM:'系统',AI:'AI',USER:'用户'};
const sources:Record<SourceType,string>={TEMPLATE:'模板',GUIDE_RUN:'AI 运行',SUGGESTION_BATCH:'建议批次',MANUAL_EDIT:'人工编辑'};
export function DocumentOutline({navigation}:{navigation:DocumentNavigation}){
  const state=useSyncExternalStore(navigation.subscribe,navigation.getSnapshot);
  if(state.error)return <p role="status">{state.error}</p>;
  if(!state.content)return <p role="status">正在读取文档大纲…</p>;
  if(!state.content.outline.length)return <p>本文档没有标题</p>;
  return <nav aria-label="文档章节" className="document-outline"><ol>{state.content.outline.map(item=><li key={item.block_id}>
    <button type="button" style={{paddingInlineStart:12+item.depth*16}} aria-current={state.active_heading===item.block_id?'location':undefined}
      data-heading-block={item.block_id} title={item.text} onClick={()=>navigation.locate(item.block_id)}>{item.text||'空标题'}</button>
  </li>)}</ol></nav>;
}
/** Source IDs remain internal; labels state the type and actor, never invent an
 * object title or dereference a deleted editing session as a live draft. */
export function BlockAuxiliary({navigation,extra}:{navigation:DocumentNavigation;extra?:ReactNode}){
  const state=useSyncExternalStore(navigation.subscribe,navigation.getSnapshot),trigger=useRef<HTMLButtonElement>(null),popover=useRef<HTMLDivElement>(null);
  const block=state.content?.blocks.find(item=>item.block_id===state.source_block);
  useEffect(()=>{if(!block)return;const previous=document.activeElement;popover.current?.focus();
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();navigation.source(null);}};
    const outside=(event:PointerEvent)=>{if(!popover.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))navigation.source(null);};
    document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside);
    return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside);if(previous instanceof HTMLElement&&previous.isConnected)previous.focus({preventScroll:true});};
  },[navigation,block?.block_id]);
  return createPortal(<>
    {state.toolbar&&state.selected_block!==null&&!state.error&&<div className="block-auxiliary" aria-label="区块辅助栏" style={state.toolbar}>
      <button type="button" ref={trigger} aria-expanded={block!==undefined} onClick={()=>navigation.source(block?null:state.selected_block)}>来源</button>
      {extra}
    </div>}
    {block&&<div ref={popover} className="block-source-popover" role="dialog" aria-label="区块来源" tabIndex={-1} style={{left:Math.max(8,Math.min(window.innerWidth-336,state.toolbar?.left??16)),top:Math.max(8,Math.min(window.innerHeight-300,(state.toolbar?.top??16)+40))}}>
      <header><strong>区块来源</strong><button type="button" aria-label="关闭来源" onClick={()=>navigation.source(null)}>×</button></header>
      {state.content?.kind==='REVISION'&&<p>历史版本来源</p>}
      {state.content?.kind==='MANUAL_DRAFT'&&<p>人工草稿来源；本地变更尚未在正式正文生效，保存时间以服务器确认为准。</p>}
      <dl><dt>创建</dt><dd>{actors[block.created_by_type]} · {sources[block.created_source_type]}</dd><dt>创建时间</dt><dd>{localTime(block.created_at)}</dd>
        <dt>最近修改</dt><dd>{actors[block.last_modified_by_type]} · {sources[block.last_modified_source_type]}</dd><dt>修改时间</dt><dd>{localTime(block.last_modified_at)}</dd></dl>
    </div>}
  </>,document.body);
}
