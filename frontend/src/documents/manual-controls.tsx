import {useRef,useState,useSyncExternalStore} from 'react';
import type {ManualDraftAutosave} from './autosave.ts';
import type {ManualDraftEnd,ManualEndOutcome} from './manual-end.ts';
import type {ManualDraftRecovery} from './manual-recovery.ts';
import type {ManualDraftStart} from './manual-start.ts';
import type {DocumentReadModel} from './contracts.ts';
import {Confirmation} from '../shared/confirmation.tsx';
import {localTime} from '../shared/time.ts';

export function ManualStartControl(props:Readonly<{flow:ManualDraftStart;disabled:boolean;started():void|Promise<void>}>) {
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),pending=useRef(false);
  const submit=async()=>{
    if(pending.current||props.disabled&&state.phase!=='STARTED')return;pending.current=true;setBusy(true);setError(null);
    try{if(state.phase==='STARTED')await props.started();else{const started=state.phase==='UNKNOWN'?await props.flow.retryUnknown():await props.flow.start();if(started)await props.started();}}
    catch{setError('编辑请求已保留，暂时无法更新页面，请重新读取实际状态');}
    finally{pending.current=false;setBusy(false);}
  };
  return <div className="manual-start-control">
    <button type="button" disabled={props.disabled||busy||state.phase==='CHECKING'||state.phase==='SUBMITTING'||state.phase==='STARTED'}
      aria-busy={busy} onClick={()=>void submit()}>{state.phase==='UNKNOWN'?'重新确认开始编辑':busy?'正在开始编辑…':'人工编辑'}</button>
    {(state.error||error)&&<p role="alert" className="inline-error">{error??state.error}</p>}
    {state.phase==='STARTED'&&<p role="status">已创建编辑草稿，正在读取当前实际状态。</p>}
    {state.phase==='STARTED'&&error&&<button type="button" disabled={busy} onClick={()=>void submit()}>重新读取编辑状态</button>}
  </div>;
}

export interface ManualDraftControlsProps {
  autosave:ManualDraftAutosave;ending:ManualDraftEnd;recovery:ManualDraftRecovery;valid:boolean;blocked:boolean;
  ended(outcome:ManualEndOutcome,localCleanupFailed:boolean):void|Promise<void>;
  serverSelected(server:DocumentReadModel):void|Promise<void>;
}
const savingLabels={SAVED:'已保存',DIRTY:'未保存',SAVING:'保存中',RETRYING:'保存失败，正在重试',UNKNOWN:'保存结果待核实',
  VALIDATION_ERROR:'草稿校验失败',CONFLICT:'草稿版本冲突',CLOSED:'编辑已结束'} as const;

/** Real controller binding. Parent owns the editor, lifecycle, permissions and
 * actual post-command detail reload. No local IDLE or saved version is made up.
 * Local comparison is labelled authored Markdown, never a fake server model. */
export function ManualDraftControls(props:ManualDraftControlsProps) {
  const save=useSyncExternalStore(listener=>props.autosave.subscribe(()=>listener()),()=>props.autosave.state);
  const ending=useSyncExternalStore(props.ending.subscribe,props.ending.getSnapshot),recovery=useSyncExternalStore(props.recovery.subscribe,props.recovery.getSnapshot);
  const [busy,setBusy]=useState(false),[dialog,setDialog]=useState<'CANCEL'|'LOCAL'|null>(null),[error,setError]=useState<string|null>(null),[comparison,setComparison]=useState(false);
  const pending=useRef(false),callbacks=useRef(props);callbacks.current=props;
  const endingBusy=['PREPARING','SUBMITTING','CHECKING'].includes(ending.phase),endingUnknown=ending.phase==='UNKNOWN';
  const editable=['RESTORED','SERVER_SELECTED'].includes(recovery.phase)&&ending.phase==='EDITING';
  const locked=props.blocked||busy||endingBusy||recovery.checking;
  const execute=async(work:()=>Promise<boolean>|boolean,after?:(confirmed:boolean)=>void|Promise<void>)=>{
    if(pending.current||props.blocked)return;pending.current=true;setBusy(true);setError(null);
    try{const confirmed=await work();await after?.(confirmed);}
    catch{setError('暂时无法更新页面，当前草稿和请求状态仍保留，请重新读取实际资源');}
    finally{pending.current=false;setBusy(false);}
  };
  const afterEnd=async(confirmed:boolean)=>{
    if(!confirmed)return;const outcome=callbacks.current.ending.getSnapshot().outcome;
    if(outcome){setDialog(null);await callbacks.current.ended(outcome,callbacks.current.ending.getSnapshot().local_cleanup_error);}
  };
  const afterServer=async(confirmed:boolean)=>{
    if(!confirmed)return;const server=callbacks.current.recovery.getSnapshot().server;
    if(server){setDialog(null);await callbacks.current.serverSelected(server);}
  };
  const closeDialog=()=>{
    if(locked)return;setDialog(null);
    // Dismissing an unknown-result dialog only closes the UI; it never
    // cancels an already submitted request or unfreezes the editor.
    if(dialog==='CANCEL'&&ending.phase==='ERROR')props.ending.continueEditing();
  };
  const sourcePair=<div className="draft-comparison" aria-label="草稿内容对照">
    <section><h3>本地未同步草稿 · 基于版本 {recovery.local?.base_confirmed_version}</h3><pre>{recovery.local?.markdown_content}</pre></section>
    <section><h3>后端已保存草稿 · 版本 {recovery.server?.content_version}</h3><pre>{recovery.server?.markdown_content}</pre></section>
  </div>;
  return <section className="manual-draft-controls" aria-label="人工编辑操作">
    <div className="manual-draft-toolbar">
      <p role="status">{props.valid?savingLabels[save.status]:'未保存 · 当前输入尚未形成完整快照'}
        {props.valid&&save.status==='SAVED'&&<> · {localTime(save.saved_at)}</>}</p>
      <button type="button" disabled={locked||error!==null||!editable||!props.valid||save.status!=='SAVED'} onClick={()=>void execute(()=>props.ending.complete(),afterEnd)}>完成编辑</button>
      <button type="button" disabled={locked||error!==null||endingUnknown||ending.phase==='CLOSED'} onClick={()=>setDialog('CANCEL')}>取消编辑</button>
    </div>
    {save.local_storage_error&&<p role="alert" className="inline-error">本地暂存未成功保护最新内容，请保持页面；后端保存状态以实际回执为准。</p>}
    {save.error&&<p role="alert" className="inline-error">{save.error}</p>}
    {save.server_conflict&&<details><summary>查看后端最新草稿 · 版本 {save.server_conflict.content_version}</summary><pre className="draft-source">{save.server_conflict.markdown_content}</pre></details>}
    {endingBusy&&<p role="status">{ending.operation==='CANCEL'?'正在确认并放弃编辑草稿…':'正在保存最新草稿并完成编辑…'}</p>}
    {ending.error&&dialog!=='CANCEL'&&<p role="alert" className="inline-error">{ending.error}</p>}
    {endingUnknown&&dialog!=='CANCEL'&&<button type="button" disabled={locked} onClick={()=>void execute(()=>props.ending.retryUnknown(),afterEnd)}>重新确认结束操作</button>}
    {ending.phase==='ERROR'&&dialog!=='CANCEL'&&<button type="button" disabled={locked} onClick={()=>props.ending.continueEditing()}>继续编辑</button>}
    {ending.phase==='CLOSED'&&<p role="status">{ending.outcome?.kind==='COMPLETED'?'已完成人工编辑':'已取消人工编辑'}，{error?'详情尚未重新读取。':'正在读取实际详情。'}</p>}
    {ending.phase==='CLOSED'&&error&&<button type="button" disabled={locked} onClick={()=>void execute(()=>props.ending.getSnapshot().outcome!==null,afterEnd)}>重新读取实际详情</button>}
    {recovery.phase==='SERVER_SELECTED'&&ending.phase==='EDITING'&&error&&<button type="button" disabled={locked} onClick={()=>void execute(()=>props.recovery.getSnapshot().server!==null,afterServer)}>重新读取后端草稿</button>}
    {ending.local_cleanup_error&&<div role="alert" className="inline-error">服务器已确认结束，本地暂存尚未清除。<button type="button" disabled={locked} onClick={()=>void execute(()=>props.ending.clearLocal())}>重试清理本地暂存</button></div>}
    {!['RESTORED','SERVER_SELECTED'].includes(recovery.phase)&&ending.phase!=='CLOSED'&&<section className="draft-recovery-notice" aria-label="本地草稿恢复">
      {recovery.checking&&<p role="status">正在读取实际编辑会话与本地暂存…</p>}
      {recovery.error&&<p role="alert" className="inline-error">{recovery.error}</p>}
      {recovery.local&&<>
        <p>{recovery.phase==='COMPARE'?'后端版本已变化，请保留本地内容并对照处理。':'发现本地未同步内容，可选择恢复或继续后端草稿。'}</p>
        {recovery.phase==='AVAILABLE'&&<button type="button" disabled={locked||error!==null||ending.phase!=='EDITING'} onClick={()=>void execute(()=>props.recovery.restore())}>恢复本地内容</button>}
        <button type="button" disabled={locked} aria-expanded={comparison} onClick={()=>setComparison(value=>!value)}>对照内容</button>
        <button type="button" disabled={locked||error!==null||ending.phase!=='EDITING'} onClick={()=>setDialog('LOCAL')}>使用后端草稿</button>
        {comparison&&sourcePair}
      </>}
      {!recovery.local&&props.recovery.canContinueServer&&<button type="button" disabled={locked||ending.phase!=='EDITING'} onClick={()=>void execute(()=>props.recovery.continueServerWithoutLocal(),afterServer)}>继续后端草稿</button>}
      {recovery.phase==='ERROR'&&<button type="button" disabled={locked||ending.phase!=='EDITING'} onClick={()=>void execute(()=>props.recovery.inspect())}>重新读取草稿与暂存</button>}
    </section>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    <Confirmation open={dialog!==null} title={dialog==='LOCAL'?'放弃本地未同步内容？':'放弃人工编辑？'}
      description={dialog==='LOCAL'?'清除此草稿的本地未同步内容，继续后端已保存草稿。请先确认需要保留的内容。':'放弃整个编辑草稿，包括本地未同步内容。正式正文保持不变。'}
      dangerous busy={locked} error={error??(dialog==='LOCAL'?recovery.error:ending.error)}
      confirmLabel={dialog==='CANCEL'&&endingUnknown?'重新确认结果':'确认放弃'} cancelLabel={dialog==='CANCEL'&&endingUnknown?'保留请求并关闭弹窗':'继续编辑'}
      cancel={closeDialog} confirm={()=>void execute(dialog==='LOCAL'?()=>props.recovery.discardLocalConfirmed():endingUnknown?()=>props.ending.retryUnknown():()=>props.ending.cancelConfirmed(),dialog==='LOCAL'?afterServer:afterEnd)} />
  </section>;
}
