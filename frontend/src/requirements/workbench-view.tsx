import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { MouseEvent } from 'react';
import { RequirementWorkbench } from './workbench.ts';
import type { WorkbenchQuery } from './workbench.ts';
import { CreateRequirementFlow } from './create.ts';
import { CreateRequirementDrawer } from './create_drawer.tsx';
import { requirementCatalog } from './catalog.ts';
import { MultiFilter, SearchInput } from '../shared/filter.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { Confirmation } from '../shared/confirmation.tsx';
import { localTime } from '../shared/time.ts';

const statusOptions=[{value:'INITIALIZING',label:'初始化中'},{value:'ACTIVE',label:'进行中'},{value:'COMPLETED',label:'已完成'}] as const;
const typeName=(value:'NEW'|'CHANGE')=>requirementCatalog.requirement_types.find(option=>option.value===value)!.label;
function condition(query:WorkbenchQuery):string {
  return `关键词：${query.keyword||'无'}；状态：${query.status.length===3?'全部':query.status.map(value=>statusOptions.find(option=>option.value===value)!.label).join('、')}；类型：${query.requirement_type.length===2?'全部':query.requirement_type.map(typeName).join('、')}`;
}

/** Controllers belong to the route owner; this view emits navigation intent. */
export function WorkbenchView({workbench,creation,restoreScroll=null,openRequirement,saveEntry,discardCreation,navigationGuard}:Readonly<{
  workbench:RequirementWorkbench;creation:CreateRequirementFlow;restoreScroll?:number|null;
  openRequirement(id:number):void;saveEntry(query:WorkbenchQuery,scroll:number):void;discardCreation():void;navigationGuard(blocked:boolean):void;
}>) {
  const subscribe=useCallback((notify:()=>void)=>workbench.subscribe(notify),[workbench]),createSubscribe=useCallback((notify:()=>void)=>creation.subscribe(notify),[creation]);
  const state=useSyncExternalStore(subscribe,()=>workbench.state),create=useSyncExternalStore(createSubscribe,()=>creation.state);
  const [draft,setDraft]=useState(state.requested.keyword),[searchError,setSearchError]=useState<string|null>(null),[drawer,setDrawer]=useState(false),[discard,setDiscard]=useState(false);
  const restore=useRef(restoreScroll),restoredQuery=useRef(JSON.stringify(state.requested)),opened=useRef<unknown>(null),refreshStarted=useRef(false);
  const pointer=useRef<{x:number;y:number;anchor:Node|null;focus:Node|null;start:number;end:number}|null>(null);
  useEffect(()=>{refreshStarted.current=true;void workbench.refresh();},[workbench]);
  useEffect(()=>{navigationGuard(drawer&&!create.result&&(creation.hasInput||create.busy||create.unknown));return()=>navigationGuard(false);},[drawer,creation,create.draft,create.busy,create.unknown,create.result,navigationGuard]);
  useEffect(()=>{
    const protect=(event:BeforeUnloadEvent)=>{if(drawer&&(creation.hasInput||create.busy||create.unknown)){event.preventDefault();event.returnValue='';}};
    const snapshot=()=>saveEntry(workbench.state.requested,window.scrollY);
    window.addEventListener('beforeunload',protect);window.addEventListener('pagehide',snapshot);
    return()=>{window.removeEventListener('beforeunload',protect);window.removeEventListener('pagehide',snapshot);};
  },[drawer,creation,workbench,saveEntry]);
  useLayoutEffect(()=>{
    if(!refreshStarted.current||restore.current===null||state.loading||state.error||!state.result||JSON.stringify(state.confirmed)!==restoredQuery.current)return;
    const position=restore.current;restore.current=null;const frame=requestAnimationFrame(()=>window.scrollTo({top:position,behavior:'instant'}));return()=>cancelAnimationFrame(frame);
  },[state]);
  useEffect(()=>{
    if(create.result&&opened.current!==create.result){opened.current=create.result;setDrawer(false);saveEntry(workbench.state.requested,window.scrollY);openRequirement(create.result.requirement.id);}
  },[create.result,openRequirement,saveEntry,workbench]);
  const query=(value:WorkbenchQuery,search=false)=>{
    try {const pending=workbench.query(value);restore.current=null;setSearchError(null);if(search)setDraft(workbench.state.requested.keyword);saveEntry(workbench.state.requested,window.scrollY);void pending;}
    catch(error){setSearchError(error instanceof Error?error.message:'查询条件不合法');}
  };
  const cancel=()=>{if(create.busy||create.unknown)return;if(creation.hasInput)setDiscard(true);else setDrawer(false);};
  const visit=(event:MouseEvent<HTMLElement>,id:number)=>{
    if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    const original=pointer.current,moved=event.detail!==0&&original&&Math.hypot(event.clientX-original.x,event.clientY-original.y)>4;pointer.current=null;
    const selection=window.getSelection(),newSelection=event.detail!==0&&selection&&!selection.isCollapsed&&(!original||original.anchor!==selection.anchorNode||original.focus!==selection.focusNode||original.start!==selection.anchorOffset||original.end!==selection.focusOffset);
    event.preventDefault();event.stopPropagation();if(moved||newSelection)return;
    saveEntry(workbench.state.requested,window.scrollY);openRequirement(id);
  };
  const phase=workbench.phase;
  return <main className="workbench" data-phase={phase}>
    <header className="workbench-heading"><h1>需求工作台</h1></header>
    <div className="workbench-controls"><div><SearchInput value={draft} submitted={state.requested.keyword} placeholder="请输入需求编号或需求标题" draft={setDraft}
      submit={keyword=>query({...state.requested,keyword,page:1},true)} />{(searchError||state.field_error)&&<p className="inline-error" role="alert">! {searchError||state.field_error}</p>}</div>
      <MultiFilter name="需求状态" options={statusOptions} value={state.requested.status} change={status=>query({...state.requested,status,page:1})}/>
      <MultiFilter name="需求类型" options={requirementCatalog.requirement_types} value={state.requested.requirement_type} change={requirement_type=>query({...state.requested,requirement_type,page:1})}/>
      <button type="button" className="primary" onClick={()=>setDrawer(true)}>新建需求</button>
    </div>
    {phase==='LOADING'&&<p className="list-notice" role="status">正在加载需求…</p>}
    {phase==='REFRESHING'&&<p className="list-notice" role="status">正在刷新，当前展示上次成功的查询结果。</p>}
    {state.error&&!state.field_error&&<div className="list-notice inline-error" role="alert"><p>! {state.error}</p><button type="button" onClick={()=>{void workbench.refresh();}}>重试查询</button></div>}
    {(phase==='REFRESHING'||phase==='REFRESH_ERROR')&&state.confirmed&&<p className="confirmed-condition">上次成功条件：{condition(state.confirmed)}</p>}
    {state.result&&<><div className="workbench-table-wrap"><table className="workbench-table"><colgroup><col className="number-column"/><col/><col className="type-column"/><col className="status-column"/><col className="time-column"/></colgroup>
      <thead><tr><th>需求编号</th><th>需求标题</th><th>需求类型</th><th>当前状态</th><th>更新时间</th></tr></thead>
      <tbody>{state.result.items.map(row=><tr key={row.id} onPointerDown={event=>{const selected=window.getSelection();pointer.current={x:event.clientX,y:event.clientY,anchor:selected?.anchorNode??null,focus:selected?.focusNode??null,start:selected?.anchorOffset??0,end:selected?.focusOffset??0};}}
        onClick={event=>{if((event.target as HTMLElement).closest('a'))return;visit(event,row.id);}}>
        <td>{row.requirement_no}</td><td><a href={'/requirements/'+row.id} draggable={false} title={row.title} onClick={event=>visit(event,row.id)}>{row.title}</a></td>
        <td title={typeName(row.requirement_type)}>{typeName(row.requirement_type)}</td><td><span className={'requirement-status status-'+row.status.toLowerCase()}>{statusOptions.find(option=>option.value===row.status)!.label}</span></td><td>{localTime(row.updated_at)}</td>
      </tr>)}</tbody></table></div>
      {!state.result.items.length&&<div className="workbench-empty"><p>{phase==='EMPTY'?'暂无需求':phase==='NO_MATCH'?'没有符合条件的需求':phase==='OUT_OF_RANGE'?'当前页无记录':'上次成功查询没有记录'}</p>
        {phase==='EMPTY'&&<button type="button" onClick={()=>setDrawer(true)}>新建需求</button>}</div>}
      <Pagination value={state.result.pagination} loading={state.loading} change={page=>query({...state.requested,page})}/>
    </>}
    <CreateRequirementDrawer open={drawer} state={create} edit={value=>creation.edit(value)} create={()=>{void creation.submit();}} cancel={cancel}/>
    <Confirmation open={discard} title="放弃新建需求？" description="尚未提交的输入将被清空。" busy={false} confirmLabel="放弃输入" cancel={()=>setDiscard(false)}
      confirm={()=>{setDiscard(false);setDrawer(false);discardCreation();}}/>
  </main>;
}
