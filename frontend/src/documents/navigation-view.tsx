import {Icon} from '../shared/icon.tsx';
import {useEffect,useId,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import {DocumentNavigation} from './navigation.ts';
import {localTime} from '../shared/time.ts';
import type {Actor,SourceType} from './contracts.ts';
import type {ReactNode} from 'react';
import {activeModal} from '../shared/modal.ts';
import {visibleOutline} from './outline-display.ts';

const actors:Record<Actor,string>={SYSTEM:'系统',AI:'AI',USER:'用户'};
const sources:Record<SourceType,string>={TEMPLATE:'模板',GUIDE_RUN:'AI 运行',SUGGESTION_BATCH:'建议批次',MANUAL_EDIT:'人工编辑'};
export function DocumentOutline({navigation,close,heading=true}:{navigation:DocumentNavigation;close?():void;heading?:boolean}){
  const state=useSyncExternalStore(navigation.subscribe,navigation.getSnapshot);
  const [collapsed,setCollapsed]=useState<ReadonlySet<number>>(new Set()),prefix=useId();
  if(state.error)return <p role="status">{state.error}</p>;
  if(!state.content)return <p role="status">正在读取文档大纲…</p>;
  if(!state.content.outline.length)return <p>本文档没有标题</p>;
  const outline=state.content.outline,visible=visibleOutline(outline,collapsed);
  return <nav aria-label="文档章节" className="document-outline">{heading&&<header className="outline-heading"><strong>大纲</strong>{close&&<button className="ui-button icon-button" type="button" aria-label="收起大纲" title="收起大纲" onClick={close}><Icon name="collapseLeft"/></button>}</header>}<ol>{outline.map((item,index)=>{const children=(outline[index+1]?.depth??0)>item.depth,folded=collapsed.has(item.block_id);return <li key={item.block_id} id={prefix+item.block_id} hidden={!visible[index]} className="outline-entry" style={{paddingInlineStart:item.depth*12}}>
    {children?<button className="ui-button icon-button outline-fold" type="button" aria-label={(folded?'展开':'收起')+'子章节：'+item.text} aria-expanded={!folded} onClick={()=>setCollapsed(previous=>{const next=new Set(previous);if(folded)next.delete(item.block_id);else next.add(item.block_id);return next;})}><Icon name={folded?'right':'down'}/></button>:<span className="outline-fold-placeholder"/>}
    <button className="ui-button outline-locate" type="button" aria-current={state.active_heading===item.block_id?'location':undefined}
      data-heading-block={item.block_id} title={item.text} onClick={()=>navigation.locate(item.block_id)}>{item.text||'空标题'}</button>
  </li>;})}</ol></nav>;
}
/** Source IDs remain internal; labels state the type and actor, never invent an
 * object title or dereference a deleted editing session as a live draft. */
export function BlockAuxiliary({navigation,extra}:{navigation:DocumentNavigation;extra?:ReactNode}){
  const state=useSyncExternalStore(navigation.subscribe,navigation.getSnapshot),trigger=useRef<HTMLButtonElement>(null),popover=useRef<HTMLDivElement>(null);
  const block=state.content?.blocks.find(item=>item.block_id===state.source_block);
  useEffect(()=>{if(!block)return;const previous=document.activeElement,element=popover.current;let restoreFocus=true;element?.focus();
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!activeModal()){event.preventDefault();navigation.source(null);}};
    const outside=(event:PointerEvent)=>{if(!element?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node)){restoreFocus=false;navigation.source(null);}};
    document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside);
    return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside);
      const focused=document.activeElement;
      // Closing a non-modal source view must not undo a new outside focus or
      // move focus behind a confirmation dialog that has just opened.
      if(restoreFocus&&!activeModal()&&(focused===document.body||focused===null||element?.contains(focused))&&previous instanceof HTMLElement&&previous.isConnected&&!previous.closest('[inert],[hidden]')&&!previous.matches(':disabled'))previous.focus({preventScroll:true});};
  },[navigation,block?.block_id]);
  return createPortal(<>
    {state.toolbar&&state.selected_block!==null&&!state.error&&<div className="block-auxiliary" aria-label="区块辅助栏" style={state.toolbar}>
      <button className="ui-button" type="button" ref={trigger} aria-expanded={block!==undefined} onClick={()=>navigation.source(block?null:state.selected_block)}><Icon name="info"/>来源</button>
      {extra}
    </div>}
    {block&&<div ref={popover} className="block-source-popover" role="dialog" aria-label="区块来源" tabIndex={-1} style={{left:Math.max(8,Math.min(window.innerWidth-336,(state.toolbar?.left??336)-320)),top:Math.max(8,Math.min(window.innerHeight-300,(state.toolbar?.top??16)+40))}}>
      <header><strong>区块来源</strong><button className="ui-button" type="button" aria-label="关闭来源" onClick={()=>navigation.source(null)}><Icon name="close"/></button></header>
      {state.content?.kind==='REVISION'&&<p>历史版本来源</p>}
      {state.content?.kind==='MANUAL_DRAFT'&&<p>人工草稿来源；本地变更尚未在正式正文生效，保存时间以服务器确认为准。</p>}
      <dl><dt>创建</dt><dd>{actors[block.created_by_type]} · {sources[block.created_source_type]}</dd><dt>创建时间</dt><dd>{localTime(block.created_at)}</dd>
        <dt>最近修改</dt><dd>{actors[block.last_modified_by_type]} · {sources[block.last_modified_source_type]}</dd><dt>修改时间</dt><dd>{localTime(block.last_modified_at)}</dd></dl>
    </div>}
  </>,document.body);
}
