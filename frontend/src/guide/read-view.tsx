import {useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {GuideRun,Message} from '../api/models.ts';
import {runActions,runStatuses} from '../api/models.ts';
import {MultiFilter} from '../shared/filter.tsx';
import {Pagination} from '../shared/pagination.tsx';
import {localTime} from '../shared/time.ts';
import {MessageTimeline} from '../messages/timeline.tsx';
import type {RequirementAiRead} from './read-owner.ts';
const statuses={RUNNING:'运行中',WAITING_USER:'等待回复',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消'} as const;
const actions={INITIALIZE:'初始化',ASK:'提问',REVIEW:'检查',MODIFY:'修改'} as const;
const steps={PREPARING:'正在准备',CALLING_MODEL:'正在调用模型',VALIDATING:'正在校验结果',PERSISTING:'正在提交结果',WAITING_USER:'等待补充信息',FINISHED:'运行结束'} as const;
const scopeNames={DOCUMENT:'整篇文档',SECTION:'章节',BLOCK:'区块',SELECTION:'选区'} as const;
function failure(run:GuideRun):string|null{return run.status!=='FAILED'?null:run.error_code==='EXECUTION_TIMEOUT'?'运行长时间没有进展，已停止本次运行':run.error_code==='INTERRUPTED'?'服务中断，本次运行未完成':run.error_message;}
export function RunHistory({owner}:Readonly<{owner:RequirementAiRead}>){
 const state=useSyncExternalStore(owner.history.subscribe,owner.history.getSnapshot),parent=useSyncExternalStore(owner.subscribe,owner.getSnapshot),query=state.confirmed?.query??state.requested;
 return <section className="run-history" aria-label="AI 运行记录">
  <header><strong>运行记录</strong><button type="button" disabled={state.loading||!parent.visible} onClick={()=>void owner.history.refresh()}>刷新运行记录</button></header>
  <div className="run-filters"><MultiFilter name="运行状态" options={runStatuses.map(value=>({value,label:statuses[value]}))} value={query.status.length?query.status:runStatuses} disabled={state.loading||!parent.visible} change={(selected,all)=>void owner.history.refresh({...query,status:all?[]:selected,page:1})}/>
   <MultiFilter name="运行操作" options={runActions.map(value=>({value,label:actions[value]}))} value={query.action_type.length?query.action_type:runActions} disabled={state.loading||!parent.visible} change={(selected,all)=>void owner.history.refresh({...query,action_type:all?[]:selected,page:1})}/></div>
  {state.loading&&<p role="status">正在读取运行记录…</p>}{state.error&&<p role="alert" className="inline-error">{state.error} <button type="button" disabled={state.loading||!parent.visible} onClick={()=>void owner.history.refresh()}>重试读取运行记录</button></p>}
  {state.confirmed&&<><ol>{state.confirmed.items.map(run=><li key={run.id} data-run-id={run.id}><button type="button" disabled={!parent.visible} aria-pressed={parent.selected===run.id} onClick={()=>owner.open(run)}>{actions[run.action_type]} · {statuses[run.status]} · {localTime(run.created_at)}</button></li>)}</ol>
   {state.confirmed.items.length===0&&<p>{state.confirmed.pagination.total?'当前页暂无运行':'暂无符合条件的运行'}</p>}
   <Pagination value={state.confirmed.pagination} loading={state.loading||!parent.visible} change={page=>void owner.history.refresh({...state.confirmed!.query,page})}/></>}
 </section>;
}
/** Read surfaces are independent of command/card/batch owners. A failed
 * connection keeps the last actual status and never produces FAILED. */
export function AiReadPanel({owner,structured,commands}:Readonly<{owner:RequirementAiRead;structured?:(message:Message)=>ReactNode;commands?:(run:GuideRun)=>ReactNode}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),run=state.run;
 return <section className="ai-read-panel" aria-label="AI 对话">
  <header><strong>AI 对话</strong><button type="button" disabled={!state.visible||state.refreshing} onClick={()=>{owner.readRun();void owner.refresh().catch(()=>undefined);}}>刷新 AI 状态</button></header>
  {state.refreshing&&<p role="status">正在读取实际会话与运行状态…</p>}{state.error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.selected!==null&&<section aria-label="当前查看的 AI 运行" className="run-status" aria-busy={state.querying}>
   {!run&&<p role="status">正在读取运行状态…</p>}
   {run&&<><p><strong>{actions[run.action_type]} · {statuses[run.status]}</strong> · {scopeNames[run.scope.scope_type]}</p><p>{steps[run.current_step]}</p>
    {run.source_type==='COMMENT'&&<p>来自评论的修改请求，评论处理状态保持独立。</p>}
    {run.status==='FAILED'&&<p role="alert" className="inline-error">{failure(run)}</p>}{run.status==='CANCELLED'&&<p>本次运行已取消。</p>}
    {run.final_result&&<p className="run-summary">{run.final_result.summary}</p>}{commands?.(run)}</>}
   {state.connection_error&&<p role="alert" className="inline-error">运行连接异常，保留最后确认状态。<button type="button" disabled={!state.visible||state.querying} onClick={()=>owner.readRun()}>重读运行</button></p>}
  </section>}
  <MessageTimeline messages={owner.messages} {...(structured?{structured}:{})}/><RunHistory owner={owner}/>
 </section>;
}
