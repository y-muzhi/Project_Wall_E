import type {ReactNode} from 'react';
import {useEffect,useId,useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementHeaderCommands} from './header-commands.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {RequirementLifecycleControl} from './lifecycle-control.tsx';
import {ManualStartControl} from '../documents/manual-controls.tsx';
import {RequirementPropertyControl} from './property-control.tsx';
import {Icon} from '../shared/icon.tsx';
import {activeModal} from '../shared/modal.ts';
import type {ConfirmedNotice} from '../shared/toast-store.ts';
const completed={INITIALIZATION:'初始化已完成',COMPLETE:'需求已完成',REACTIVATE:'需求已重新激活'} as const;

/** Real header fields and available command owners. Other business regions
 * remain the detail parent's responsibility; no fake action handlers. */
export function RequirementHeader(props:Readonly<{tools?:ReactNode;documentActions?:ReactNode;commands:RequirementHeaderCommands;ready:boolean;blocked:boolean;history:boolean;refresh():Promise<DetailSnapshot>;refreshRevisions():Promise<void>;notifyConfirmed?:ConfirmedNotice}>){
  const state=useSyncExternalStore(props.commands.subscribe,props.commands.getSnapshot),[reading,setReading]=useState(false),[readError,setReadError]=useState<string|null>(null),pending=useRef<Promise<DetailSnapshot>|null>(null);
  const external=props.blocked||props.history;
  const refresh=():Promise<DetailSnapshot>=>{
    if(pending.current)return pending.current;setReading(true);setReadError(null);
    const promise=Promise.resolve().then(()=>props.refresh()).then(actual=>{props.commands.adopt(actual);return actual;}).catch(error=>{setReadError('实际详情读取失败，现有内容和输入已保留');throw error;}).finally(()=>{if(pending.current===promise)pending.current=null;setReading(false);});pending.current=promise;return promise;
  };
  const life=state.lifecycle,manual=state.manual;
  const ready=props.ready&&!reading;
  const [toolsOpen,setToolsOpen]=useState(false),toolsId=useId(),toolsHost=useRef<HTMLDivElement>(null),toolsToggle=useRef<HTMLButtonElement>(null);
  const editingTitle=props.commands.title.getSnapshot().phase!=='VIEW',expanded=toolsOpen||editingTitle;
  useEffect(()=>{
    if(!toolsOpen||editingTitle)return;
    const outside=(event:Event)=>{if(!activeModal()&&event.target instanceof Node&&!toolsHost.current?.contains(event.target))setToolsOpen(false);};
    document.addEventListener('pointerdown',outside);document.addEventListener('focusin',outside);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside);};
  },[toolsOpen,editingTitle]);
  const closeTools=()=>{setToolsOpen(false);toolsToggle.current?.focus({preventScroll:true});};
  return <section className="requirement-header" aria-label="需求属性和操作">
    <div className="requirement-operations">{props.documentActions}<div className="requirement-action-group" aria-label="生命周期与人工编辑">
    {life&&(!props.history||life.getSnapshot().phase!=='READY')&&<RequirementLifecycleControl key={'lifecycle-'+state.lifecycle_generation} flow={life} blocked={external||props.commands.blockedFor('LIFECYCLE')} writeReady={ready} changed={async outcome=>{props.notifyConfirmed?.(outcome,completed[outcome.kind]);if(outcome.kind==='INITIALIZATION')await props.refreshRevisions();await refresh();}}/>}
    {manual&&(!props.history||manual.getSnapshot().phase!=='READY')&&<ManualStartControl key={'manual-'+state.manual_generation} flow={manual} disabled={external||props.commands.blockedFor('MANUAL')} writeReady={ready} started={async()=>{await refresh();}}/>}
    </div><div className="requirement-tools" ref={toolsHost} onKeyDown={event=>{if(event.key==='Escape'&&!event.defaultPrevented&&!activeModal()&&!editingTitle&&expanded){event.preventDefault();event.stopPropagation();closeTools();}}}>
      <button ref={toolsToggle} className="ui-button icon-button" type="button" aria-label="更多操作" title={editingTitle?'请先完成或取消标题编辑':'更多操作'} aria-expanded={expanded} aria-controls={toolsId} disabled={editingTitle} onClick={()=>setToolsOpen(value=>!value)}><Icon name="more"/></button>
      <div id={toolsId} className="requirement-tools-popover" role="region" aria-label="详情工具" hidden={!expanded}>
        <p className="requirement-tools-caption">需求属性与工具</p>
        <RequirementPropertyControl flow={props.commands.title} showValue={false} blocked={external||props.commands.blockedFor('TITLE')} writeReady={ready} refresh={refresh}/>
        {props.tools&&<div className="requirement-tool-actions" onClick={event=>{if(event.target instanceof Element&&event.target.closest('button'))closeTools();}}>{props.tools}</div>}
      </div>
    </div></div>
    {(life?.getSnapshot().phase==='ERROR'||manual?.getSnapshot().phase==='ERROR'||readError)&&<button className="ui-button" type="button" disabled={external||reading} onClick={()=>void refresh().catch(()=>undefined)}>重新读取操作状态</button>}
    {reading&&<p role="status">正在读取实际详情…</p>}{readError&&<p role="alert" className="inline-error">{readError}</p>}
  </section>;
}
