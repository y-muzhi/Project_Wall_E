import {useEffect,useId,useMemo,useState,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {GuideRun} from '../api/models.ts';
import type {RequirementRunHistory} from '../guide/history.ts';
import type {RequirementRevisions} from '../revisions/read.ts';
import {RunHistory,RunRecordSummary} from '../guide/read-view.tsx';
import {GuideRunPolling} from '../guide/polling.ts';
import {Icon} from '../shared/icon.tsx';
import {localTime} from '../shared/time.ts';

type RunReader=(identity:number,signal:AbortSignal)=>Promise<GuideRun>;
const tabs=[{value:'VERSIONS',label:'版本记录'},{value:'RUNS',label:'运行记录'}] as const;
function RunRecordDetail({identity,read,active,back}:Readonly<{identity:number;read:RunReader;active:boolean;back():void}>){
 const polling=useMemo(()=>new GuideRunPolling(identity,read),[identity,read]);
 const state=useSyncExternalStore(listener=>polling.subscribe(()=>listener()),()=>polling.state),run=state.confirmed;
 useEffect(()=>()=>polling.dispose(),[polling]);
 useEffect(()=>{polling.setVisible(active);return()=>polling.setVisible(false);},[polling,active]);
 return <section className="record-detail" aria-label={`运行 #${identity} 详情`} aria-busy={state.querying}>
  <header className="record-detail-heading"><button className="ui-button" type="button" onClick={back}><Icon name="left"/>运行列表</button><span>运行 #{identity}</span><span className="read-status" role="status">{state.querying?'正在读取…':''}</span></header>
  {!run&&!state.connection_error&&<p role="status">正在读取运行详情…</p>}
  {state.connection_error&&<p className="inline-error" role="alert">读取异常，已确认的状态仍保留。<button className="ui-button" type="button" disabled={!active||state.querying} onClick={()=>polling.refresh()}>重试读取</button></p>}
  {run&&<><div className="record-detail-summary"><RunRecordSummary run={run}/></div><dl className="record-detail-properties"><dt>创建时间</dt><dd>{localTime(run.created_at)}</dd><dt>开始时间</dt><dd>{run.started_at?localTime(run.started_at):'尚未开始'}</dd><dt>结束时间</dt><dd>{run.ended_at?localTime(run.ended_at):'尚未结束'}</dd><dt>来源</dt><dd>{run.source_type==='COMMENT'?'评论':run.source_type==='REVIEW_RESULT'?'检查结果':'用户指令'}</dd></dl><p className="field-help">这里查看运行过程；任务操作与回复在 AI 对话中处理。</p></>}
 </section>;
}
/** Local record navigation retains lists, filters, selected identity and version
 * save input. The run viewer reads status only and never selects the AI task. */
export function DocumentRecords({active,blocked,revisions,history,readRun,versions}:Readonly<{
 active:boolean;blocked:boolean;revisions:RequirementRevisions;history:RequirementRunHistory;readRun:RunReader;versions:ReactNode;
}>){
 const [tab,setTab]=useState<typeof tabs[number]['value']>('VERSIONS'),[selected,setSelected]=useState<number|null>(null),[detailOpen,setDetailOpen]=useState(false),id=useId();
 const version=useSyncExternalStore(revisions.subscribe,revisions.getSnapshot);
 const available=active&&!blocked,runActive=available&&tab==='RUNS';
 useEffect(()=>{if(version.history.phase!=='CLOSED')setTab('VERSIONS');},[version.history.requested?.id]);
 useEffect(()=>{if(!available)return;if(tab==='RUNS')void history.refresh();else void revisions.refresh();return()=>{if(tab==='RUNS')history.pause();};},[available,tab,history,revisions]);
 return <section className="document-records" aria-label="文档记录">
  <div className="document-record-tabs" role="tablist" aria-label="文档记录类型">{tabs.map((item,index)=><button key={item.value} type="button" role="tab" id={`${id}-${item.value}`} aria-controls={`${id}-panel-${item.value}`} aria-selected={tab===item.value} tabIndex={tab===item.value?0:-1} disabled={!active} onClick={()=>setTab(item.value)} onKeyDown={event=>{
   const next=event.key==='ArrowRight'||event.key==='ArrowLeft'?1-index:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
   if(next===null)return;event.preventDefault();setTab(tabs[next]!.value);event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`button:nth-child(${next+1})`)?.focus({preventScroll:true});
  }}>{item.label}</button>)}</div>
  <div className="document-record-content" role="tabpanel" id={`${id}-panel-VERSIONS`} aria-labelledby={`${id}-VERSIONS`} hidden={tab!=='VERSIONS'} inert={tab!=='VERSIONS'}>{versions}</div>
  <div className="document-record-content" role="tabpanel" id={`${id}-panel-RUNS`} aria-labelledby={`${id}-RUNS`} hidden={tab!=='RUNS'} inert={tab!=='RUNS'}>
   <div hidden={detailOpen} inert={detailOpen}><RunHistory history={history} available={runActive} selected={selected} open={run=>{setSelected(run.id);setDetailOpen(true);}}/></div>
   <div hidden={!detailOpen} inert={!detailOpen}>{selected!==null&&<RunRecordDetail key={selected} identity={selected} read={readRun} active={runActive&&detailOpen} back={()=>{setDetailOpen(false);if(runActive)void history.refresh();}}/>}</div>
  </div>
 </section>;
}
