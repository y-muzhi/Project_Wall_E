import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementRevisionSave} from './save.ts';
import type {RequirementRevisions,Revision} from './read.ts';
import type {RevisionSummary} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {RevisionViewer} from './viewer.ts';
import {Pagination} from '../shared/pagination.tsx';
import {localTime} from '../shared/time.ts';

export function RevisionSaveControl(props:Readonly<{flow:RequirementRevisionSave;ready:boolean;blocked:boolean;refreshActual():Promise<DetailSnapshot>;saved(receipt:RevisionSummary):Promise<void>}>){
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),pending=useRef(false);
  const locked=props.blocked||busy||state.phase==='SUBMITTING'||state.phase==='READING',editable=['READY','ERROR'].includes(state.phase);
  const submit=async(readOnly=false)=>{
    if(pending.current||props.blocked||!readOnly&&state.phase!=='UNKNOWN'&&!props.ready)return;pending.current=true;setBusy(true);setError(null);
    try{const confirmed=readOnly?true:state.phase==='UNKNOWN'?await props.flow.retryUnknown():await props.flow.save();const current=props.flow.getSnapshot();
      if(confirmed&&current.receipt)await props.saved(current.receipt);
      else if(['STATE_CONFLICT','WORK_STATE_CONFLICT','CONTENT_VERSION_CONFLICT','WORK_STATE_INCONSISTENT'].includes(current.error_code??''))props.flow.rebase(await props.refreshActual());
    }catch{setError(props.flow.getSnapshot().phase==='CONFIRMED'?'版本已保存，列表暂时无法读取，请重试读取':'实际详情读取失败，版本说明已保留');}
    finally{pending.current=false;setBusy(false);}
  };
  return <section aria-label="保存手动版本">
    <label>版本说明（可选）<textarea className="ui-input" aria-label="版本说明（可选）" value={state.description} disabled={locked||!props.ready&&editable} readOnly={!editable} onChange={event=>props.flow.change(event.target.value)}/></label>
    {editable&&<button className="ui-button" type="button" disabled={locked||!props.ready||!props.flow.allowed} onClick={()=>void submit()}>保存版本</button>}
    {state.phase==='UNKNOWN'&&<button className="ui-button" type="button" disabled={locked} onClick={()=>void submit()}>重新确认保存版本</button>}
    {(state.phase==='SUBMITTING'||state.phase==='READING')&&<p role="status">{state.phase==='READING'?'正在核实保存结果…':'正在保存版本…'}</p>}
    {state.receipt&&<p role="status">版本 V{state.receipt.version_no} 已保存，来源正文 v{state.receipt.source_content_version}。</p>}
    {state.phase==='CONFIRMED'&&error&&<button className="ui-button" type="button" disabled={locked} onClick={()=>void submit(true)}>重新读取版本列表</button>}
    {(error||state.error)&&<p role="alert" className="inline-error">{error??state.error}</p>}
    {state.phase==='ERROR'&&<button className="ui-button" type="button" disabled={locked} onClick={()=>{if(pending.current)return;pending.current=true;setBusy(true);void props.refreshActual().then(actual=>{props.flow.rebase(actual);setError(null);}).catch(()=>setError('实际详情读取失败，版本说明已保留')).finally(()=>{pending.current=false;setBusy(false);});}}>重新读取版本保存条件</button>}
  </section>;
}

export function RevisionList(props:Readonly<{flow:RequirementRevisions;blocked:boolean;open(summary:RevisionSummary):void}>){
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot),list=state.list;
  return <section aria-label="版本记录" aria-busy={state.loading}>
    <header className="read-section-heading"><strong>版本记录</strong><span className="read-status" role="status">{state.loading?`正在读取第 ${state.page} 页…`:''}</span></header>
    {!list&&!state.loading&&state.error&&<p role="alert" className="inline-error">{state.error} <button className="ui-button" type="button" onClick={()=>void props.flow.refresh()}>重试</button></p>}
    {list&&<>{list.items.length===0&&<p>{list.pagination.total===0?'暂无版本记录。完成初始化后生成基线；进行中且正文空闲时，可填写版本说明保存手动版本。':'当前页暂无版本记录'}</p>}
      <ol>{list.items.map(row=><li key={row.id}><strong>V{row.version_no}</strong> · {row.revision_type==='BASELINE'?'初始化基线':'手动版本'} · 来源正文 v{row.source_content_version}
        <p className="revision-description">{row.description??'--'}</p><time dateTime={row.created_at}>{localTime(row.created_at)}</time>{' '}
        <button className="ui-button" type="button" disabled={props.blocked||['EXITING','RESTORING'].includes(state.history.phase)} onClick={()=>props.open(row)}>查看 V{row.version_no}</button></li>)}</ol>
      <Pagination value={list.pagination} compactSingle loading={state.loading} showLoadingStatus={false} error={state.error} change={page=>void props.flow.refresh(page)} retry={()=>void props.flow.refresh()}/>
    </>}
  </section>;
}

export function RevisionDocument(props:Readonly<{snapshot:Revision;ready?(viewer:RevisionViewer):void}>){
  const root=useRef<HTMLDivElement>(null),callbacks=useRef(props);callbacks.current=props;
  const [loading,setLoading]=useState(true),[error,setError]=useState(false),[retry,setRetry]=useState(0);
  useEffect(()=>{let retired=false,viewer:RevisionViewer|undefined;setLoading(true);setError(false);
    void RevisionViewer.create(root.current!,props.snapshot).then(actual=>{if(retired){void actual.destroy();return;}viewer=actual;setLoading(false);try{callbacks.current.ready?.(actual);}catch(error){console.error('WALL-E revision viewer observer failed',error);}}).catch(()=>{if(!retired){setLoading(false);setError(true);}});
    return()=>{retired=true;if(viewer)void viewer.destroy();};
  },[props.snapshot,retry]);
  return <div className="detail-document-content revision-readonly-document">{loading&&<p role="status">正在展示只读历史正文…</p>}{error&&<p role="alert" className="inline-error">历史正文暂时无法展示 <button className="ui-button" type="button" onClick={()=>setRetry(value=>value+1)}>重试展示</button></p>}<div ref={root}/></div>;
}

/** Parent hides current comments and parks the actual current/manual editor
 * while phase is not CLOSED. Exit requires a fresh complete actual read. */
export function RevisionHistory(props:Readonly<{flow:RequirementRevisions;refreshActual():Promise<DetailSnapshot>;restored(actual:DetailSnapshot):void|Promise<void>;ready?(viewer:RevisionViewer):void}>){
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot).history,[error,setError]=useState<string|null>(null),pending=useRef(false),[busy,setBusy]=useState(false);
  const exit=async()=>{if(pending.current)return;pending.current=true;setBusy(true);setError(null);
    try{const actual=await props.flow.exit(props.refreshActual);if(actual){await props.restored(actual);if(!props.flow.finishExit(actual))throw Error('Retired restoration');}}
    catch{setError('实际视图暂时无法恢复，历史仍保留，请重新读取并恢复');}finally{pending.current=false;setBusy(false);}};
  if(state.phase==='CLOSED')return null;
  return <section aria-label="只读历史版本">
    <p role="status">{state.snapshot?`历史版本 V${state.snapshot.version_no} · 只读 · 来源正文 v${state.snapshot.source_content_version}`:'历史版本 · 只读'}</p>
    <button className="ui-button" type="button" disabled={busy||state.phase==='EXITING'} onClick={()=>void exit()}>退出历史</button>
    {state.phase==='LOADING'&&<p role="status">正在读取历史版本 V{state.requested?.version_no}…</p>}
    {state.phase==='EXITING'&&<p role="status">正在重新读取当前需求和活动对象…</p>}
    {state.phase==='RESTORING'&&<p role="status">正在恢复实际视图…</p>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    {state.error&&<p role="alert" className="inline-error">{state.error} {state.requested&&<button className="ui-button" type="button" disabled={busy} onClick={()=>void props.flow.open(state.requested!)}>重试读取历史</button>}</p>}
    {state.snapshot&&<RevisionDocument snapshot={state.snapshot} {...(props.ready?{ready:props.ready}:{})}/>}
  </section>;
}
