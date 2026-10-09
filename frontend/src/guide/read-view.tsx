import {useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {GuideRun,Message} from '../api/models.ts';
import {runActions,runStatuses} from '../api/models.ts';
import {MultiFilter} from '../shared/filter.tsx';
import {Pagination} from '../shared/pagination.tsx';
import {localTime} from '../shared/time.ts';
import {MessageTimeline} from '../messages/timeline.tsx';
import type {MessageMarkdownRenderer} from '../messages/content.tsx';
import type {RequirementAiRead} from './read-owner.ts';
const statuses={RUNNING:'运行中',WAITING_USER:'等待回复',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消'} as const;
const actions={INITIALIZE:'初始化',ASK:'提问',REVIEW:'检查',MODIFY:'修改'} as const;
const steps={PREPARING:'正在准备',CALLING_MODEL:'正在调用模型',VALIDATING:'正在校验结果',PERSISTING:'正在提交结果',WAITING_USER:'等待补充信息',FINISHED:'运行结束'} as const;
const scopeNames={DOCUMENT:'整篇文档',SECTION:'章节',BLOCK:'区块',SELECTION:'选区'} as const;
function failure(run:GuideRun):string|null{return run.status!=='FAILED'?null:run.error_code==='EXECUTION_TIMEOUT'?'运行长时间没有进展，已停止本次运行':run.error_code==='INTERRUPTED'?'服务中断，本次运行未完成':run.error_message;}
export function RunHistory({owner}:Readonly<{owner:RequirementAiRead}>){
 const state=useSyncExternalStore(owner.history.subscribe,owner.history.getSnapshot),parent=useSyncExternalStore(owner.subscribe,owner.getSnapshot),query=state.confirmed?.query??state.requested;
 return <section className="run-history" aria-label="AI 运行记录" aria-busy={state.loading}>
  <details className="run-history-disclosure"><summary><strong>运行记录</strong><span>{state.confirmed?`共 ${state.confirmed.pagination.total} 条`:''}</span><span className="read-status" role="status">{state.loading?'正在读取运行记录…':state.error?'读取失败':''}</span></summary>
  <div className="run-filters"><MultiFilter name="运行状态" options={runStatuses.map(value=>({value,label:statuses[value]}))} value={query.status} disabled={state.loading||!parent.visible} change={(selected,all)=>void owner.history.refresh({...query,status:all?[]:selected,page:1})}/>
   <MultiFilter name="运行操作" options={runActions.map(value=>({value,label:actions[value]}))} value={query.action_type} disabled={state.loading||!parent.visible} change={(selected,all)=>void owner.history.refresh({...query,action_type:all?[]:selected,page:1})}/></div>
  {state.confirmed&&<><ol>{state.confirmed.items.map(run=><li key={run.id} data-run-id={run.id}><button className="ui-button" type="button" disabled={!parent.visible} aria-pressed={parent.selected===run.id} onClick={()=>owner.open(run)}>{actions[run.action_type]} · {statuses[run.status]} · {localTime(run.created_at)}</button></li>)}</ol>
   {state.confirmed.items.length===0&&<p>{state.confirmed.pagination.total?'当前页暂无运行':'暂无符合条件的运行'}</p>}
   <Pagination compactSingle value={state.confirmed.pagination} loading={state.loading||!parent.visible} showLoadingStatus={false} change={page=>void owner.history.refresh({...state.confirmed!.query,page})}/></>}
  </details>
  {state.error&&<p role="alert" className="inline-error">{state.error} <button className="ui-button" type="button" disabled={state.loading||!parent.visible} onClick={()=>void owner.history.refresh()}>重试读取运行记录</button></p>}
 </section>;
}
/** Read surfaces are independent of command/card/batch owners. A failed
 * connection keeps the last actual status and never produces FAILED. */
export function AiReadPanel({owner,structured,commands,renderMarkdown,scrollPort,scrollContent}:Readonly<{scrollPort?:HTMLElement|null;scrollContent?:HTMLElement|null;owner:RequirementAiRead;structured?:(message:Message)=>ReactNode;commands?:(run:GuideRun)=>ReactNode;renderMarkdown?:MessageMarkdownRenderer}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),run=state.run;
 return <section className="ai-read-panel" aria-label="AI 对话">
  <header className="read-section-heading conversation-read-status"><span className="sr-only">会话状态</span><span className="read-status" role="status">{state.refreshing?'正在同步会话状态…':''}</span></header>
  {state.error&&<p role="alert" className="inline-error">{state.error} <button className="ui-button" type="button" disabled={!state.visible||state.refreshing} onClick={()=>void owner.refresh().catch(()=>undefined)}>重试读取 AI 状态</button></p>}
  {state.selected!==null&&<section aria-label="当前查看的 AI 运行" className="run-status" aria-busy={state.querying}>
   <div className="run-status-context"><strong>{state.selection==='HISTORY'?'历史运行详情':'当前任务'}</strong><span>#{state.selected}</span></div>
   {!run&&<p role="status">正在读取运行状态…</p>}
   {run&&<><p className="run-task-summary" data-state={run.status}><strong>{actions[run.action_type]} · {statuses[run.status]}</strong> · {scopeNames[run.scope.scope_type]}</p>{run.current_step!=='FINISHED'&&<p>{steps[run.current_step]}</p>}
    {run.source_type==='COMMENT'&&<p>来自评论的修改请求，评论处理状态保持独立。</p>}
    {run.status==='FAILED'&&<p role="alert" className="inline-error">{failure(run)}</p>}{run.status==='CANCELLED'&&<p>本次运行已取消。</p>}
    {run.final_result&&<details className="run-result"><summary>查看运行结果摘要</summary><p className="run-summary">{run.final_result.summary}</p></details>}{commands?.(run)}</>}
   {state.connection_error&&<p role="alert" className="inline-error">运行连接异常，保留最后确认状态。<button className="ui-button" type="button" disabled={!state.visible||state.querying} onClick={()=>owner.readRun()}>重读运行</button></p>}
  </section>}
  <MessageTimeline {...(scrollPort!==undefined?{scrollPort}:{})} {...(scrollContent!==undefined?{scrollContent}:{})} messages={owner.messages} {...(run?.latest_assistant_message_id?{reply:{message_id:run.latest_assistant_message_id,guide_run_id:run.id}}:{})} {...(structured?{structured}:{})} {...(renderMarkdown?{renderMarkdown}:{})}/><RunHistory owner={owner}/>
 </section>;
}
