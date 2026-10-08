import {useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementDocumentOwner} from './document-owner.ts';
import {DocumentOutline,BlockAuxiliary} from '../documents/navigation-view.tsx';
import {ManualDraftControls} from '../documents/manual-controls.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import type {ManualDraftSession} from '../documents/manual-session.ts';
import type {DetailSnapshot} from './detail-read.ts';
import type {ConfirmedNotice} from '../shared/toast-store.ts';

function HistoricalDraftConflict({owner,session,actual,blocked,notifyConfirmed}:{owner:RequirementDocumentOwner;session:ManualDraftSession;actual:DetailSnapshot;blocked:boolean;notifyConfirmed?:ConfirmedNotice}){
  const ending=useSyncExternalStore(session.ending.subscribe,session.ending.getSnapshot),[dialog,setDialog]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),pending=useRef(false);
  const cancelAllowed=actual.activity.kind==='MANUAL'&&actual.activity.draft.id===session.autosave.confirmedDocument.id&&actual.requirement.status!=='COMPLETED';
  const cancel=async()=>{if(pending.current||blocked)return;pending.current=true;setBusy(true);setError(null);
    try{const confirmed=ending.phase==='UNKNOWN'?await session.ending.retryUnknown():await session.ending.cancelConfirmed();if(confirmed){const outcome=session.ending.getSnapshot().outcome;if(outcome)notifyConfirmed?.(outcome,'人工编辑已取消，正式正文保持不变');setDialog(false);if(!await owner.exitHistory())setError('取消已确认，实际视图尚未恢复，请重试退出历史');}}
    catch{setError(session.ending.getSnapshot().outcome?.kind==='CANCELLED'?'取消已确认，实际视图暂时无法恢复，请重试退出历史':'取消结果尚未确认，历史及本地内容仍保留');}finally{pending.current=false;setBusy(false);}};
  return <section aria-label="历史退出草稿冲突">
    <details open><summary>对照保留的本地草稿与最新后端内容</summary><div className="draft-comparison">
      <section><h3>本页保留的人工草稿 · 确认基线 v{session.autosave.state.confirmed_version}</h3><pre>{session.autosave.localSnapshot.markdown_content}</pre></section>
      <section><h3>{actual.activity.kind==='MANUAL'?`后端草稿 · v${actual.activity.draft.content_version}`:`最新正式正文 · v${actual.current.content_version}`}</h3><pre>{actual.activity.kind==='MANUAL'?actual.activity.draft.markdown_content:actual.current.markdown_content}</pre></section>
    </div></details>
    <p>两份内容保持独立，请先保留需要的文字。重读不会自动合并或覆盖本页内容。</p>
    {cancelAllowed&&ending.phase!=='CLOSED'&&<button type="button" disabled={blocked||busy} onClick={()=>setDialog(true)}>放弃冲突人工草稿</button>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    <Confirmation open={dialog} title="放弃冲突人工草稿？" description="放弃整个人工草稿，包括本页保留的内容和后端最新更新。请先保留需要的文字。正式正文保持不变。" dangerous busy={blocked||busy}
      error={error??ending.error} confirmLabel={ending.phase==='UNKNOWN'?'重新确认结果':'确认放弃'} cancelLabel="保留草稿" cancel={()=>{if(!busy)setDialog(false);}} confirm={()=>void cancel()}/>
  </section>;
}

/** These controls share the real owner; the parent places its actual host in
 * the single main document region, and current comments only outside history. */
export function OwnedDocumentOutline({owner}:{owner:RequirementDocumentOwner}){
  const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot);return state.navigation?<DocumentOutline navigation={state.navigation}/>:<p>正在读取文档大纲…</p>;
}
export function OwnedDocumentControls({owner,blocked=false,auxiliary=true,notifyConfirmed}:{owner:RequirementDocumentOwner;blocked?:boolean;auxiliary?:boolean;notifyConfirmed?:ConfirmedNotice}){
  const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),session=state.manual;
  return <section aria-label="正文视图操作">
    {state.mode==='HISTORY'&&<><p role="status">{state.revision?`历史版本 V${state.revision.version_no} · 只读 · 来源正文 v${state.revision.source_content_version}`:'正在读取历史版本…'}</p>
      <button type="button" disabled={blocked||state.busy} onClick={()=>void owner.exitHistory()}>退出历史</button>
      {state.save_warning&&<p role="alert">草稿尚未同步，原编辑内容和本地暂存仍保留；历史正文只读。</p>}</>}
    {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
    {session&&state.mode==='HISTORY'&&state.restoration_conflict&&<HistoricalDraftConflict owner={owner} session={session} actual={state.restoration_conflict} blocked={blocked||state.busy} {...(notifyConfirmed?{notifyConfirmed}:{})}/>}
    {session&&state.mode!=='HISTORY'&&<ManualDraftControls autosave={session.autosave} ending={session.ending} recovery={session.recovery} valid={session.editor.valid}
      blocked={blocked||state.busy||session.getSnapshot().blocked} ended={async outcome=>{notifyConfirmed?.(outcome,outcome.kind==='COMPLETED'?'人工编辑已完成':'人工编辑已取消，正式正文保持不变');await owner.refresh();}} serverSelected={async()=>{await owner.refresh();}}/>}
    {auxiliary&&state.navigation&&<BlockAuxiliary navigation={state.navigation}/>}
  </section>;
}
