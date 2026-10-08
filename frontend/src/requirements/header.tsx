import {useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementHeaderCommands} from './header-commands.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {RequirementPropertyControl} from './property-control.tsx';
import {RequirementLifecycleControl} from './lifecycle-control.tsx';
import {ManualStartControl} from '../documents/manual-controls.tsx';
import type {ConfirmedNotice} from '../shared/toast-store.ts';
const statuses={INITIALIZING:'初始化中',ACTIVE:'维护中',COMPLETED:'已完成'} as const;
const completed={INITIALIZATION:'初始化已完成',COMPLETE:'需求已完成',REACTIVATE:'需求已重新激活'} as const;

/** Real header fields and available command owners. Other business regions
 * remain the detail parent's responsibility; no fake action handlers. */
export function RequirementHeader(props:Readonly<{commands:RequirementHeaderCommands;ready:boolean;blocked:boolean;history:boolean;refresh():Promise<DetailSnapshot>;refreshRevisions():Promise<void>;notifyConfirmed?:ConfirmedNotice}>){
  const state=useSyncExternalStore(props.commands.subscribe,props.commands.getSnapshot),[reading,setReading]=useState(false),[readError,setReadError]=useState<string|null>(null),pending=useRef<Promise<DetailSnapshot>|null>(null);
  const external=props.blocked||props.history;
  const refresh=():Promise<DetailSnapshot>=>{
    if(pending.current)return pending.current;setReading(true);setReadError(null);
    const promise=Promise.resolve().then(()=>props.refresh()).then(actual=>{props.commands.adopt(actual);return actual;}).catch(error=>{setReadError('实际详情读取失败，现有内容和输入已保留');throw error;}).finally(()=>{if(pending.current===promise)pending.current=null;setReading(false);});pending.current=promise;return promise;
  };
  const life=state.lifecycle,manual=state.manual,root=state.detail.requirement;
  const ready=props.ready&&!reading;
  return <section className="requirement-header" aria-label="需求属性和操作">
    <p>{root.requirement_no} · {root.requirement_type==='NEW'?'需求新增':'需求改造'} · <span>{statuses[root.status]}</span></p>
    <RequirementPropertyControl flow={props.commands.title} blocked={external||props.commands.blockedFor('TITLE')} writeReady={ready} refresh={refresh}/>
    <RequirementPropertyControl flow={props.commands.mode} blocked={external||props.commands.blockedFor('MODE')} writeReady={ready} refresh={refresh}/>
    {life&&<RequirementLifecycleControl key={'lifecycle-'+state.lifecycle_generation} flow={life} blocked={external||props.commands.blockedFor('LIFECYCLE')} writeReady={ready} changed={async outcome=>{props.notifyConfirmed?.(outcome,completed[outcome.kind]);if(outcome.kind==='INITIALIZATION')await props.refreshRevisions();await refresh();}}/>}
    {manual&&<ManualStartControl key={'manual-'+state.manual_generation} flow={manual} disabled={external||props.commands.blockedFor('MANUAL')} writeReady={ready} started={async()=>{await refresh();}}/>}
    {(life?.getSnapshot().phase==='ERROR'||manual?.getSnapshot().phase==='ERROR'||readError)&&<button type="button" disabled={external||reading} onClick={()=>void refresh().catch(()=>undefined)}>重新读取工具栏状态</button>}
    {reading&&<p role="status">正在读取实际详情…</p>}{readError&&<p role="alert" className="inline-error">{readError}</p>}
  </section>;
}
