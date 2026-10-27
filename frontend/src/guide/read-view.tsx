import {useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {GuideRun,GuideSummary,Message} from '../api/models.ts';
import {runActions,runStatuses} from '../api/models.ts';
import {MultiFilter} from '../shared/filter.tsx';
import {Pagination} from '../shared/pagination.tsx';
import {localTime} from '../shared/time.ts';
import {MessageTimeline} from '../messages/timeline.tsx';
import type {MessageMarkdownRenderer} from '../messages/content.tsx';
import type {RequirementAiRead} from './read-owner.ts';
import type {RequirementRunHistory} from './history.ts';
import {RecordList} from '../shared/record-list.tsx';
import {ModelReturnContent} from '../messages/model-return.tsx';
import {RequestCallRecord} from './model-call-view.tsx';
import {AnalysisResult} from './analysis-result.tsx';
export const statuses={RUNNING:'运行中',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消'} as const;
export const actions={GENERATE:'生成',ASK:'讨论',REVIEW:'检查',MODIFY:'修改'} as const;
import {operationNames} from './operation-labels.ts';
const steps={PREPARING:'正在准备',CALLING_MODEL:'正在调用模型',VALIDATING:'正在校验结果',PERSISTING:'正在提交结果',FINISHED:'运行结束'} as const;
const scopeNames={DOCUMENT:'整篇文档',SECTION:'章节',BLOCK:'区块',SELECTION:'选区'} as const;
function ProposalResultNotice({run}:Readonly<{run:GuideRun}>){
 return run.operation==='PROPOSE_CHANGES'&&run.application_result==='NOT_APPLIED'?<p role="status" className="run-response-notice inline-error">修改建议未生成，本轮正文未变。可在本次请求的详情中查看处理结果。</p>:null;
}
function failure(run:GuideRun):string|null{return run.status!=='FAILED'?null:run.error_code==='EXECUTION_TIMEOUT'?'运行长时间没有进展，已停止本次运行':run.error_code==='INTERRUPTED'?'服务中断，本次运行未完成':run.error_message;}
export function RunHistory({history,available,selected,open}:Readonly<{history:RequirementRunHistory;available:boolean;selected:number|null;open(run:GuideSummary):void}>){
 const state=useSyncExternalStore(history.subscribe,history.getSnapshot),query=state.confirmed?.query??state.requested;
 return <RecordList title="运行记录" total={state.confirmed?.pagination.total??null} loading={state.loading} error={state.error} retry={()=>void history.refresh()} retryDisabled={state.loading||!available}
  filters={<><MultiFilter name="运行状态" options={runStatuses.map(value=>({value,label:statuses[value]}))} value={query.status} disabled={state.loading||!available} change={(values,all)=>void history.refresh({...query,status:all?[]:values,page:1})}/>
   <MultiFilter name="运行操作" options={runActions.map(value=>({value,label:actions[value]}))} value={query.action_type} disabled={state.loading||!available} change={(values,all)=>void history.refresh({...query,action_type:all?[]:values,page:1})}/></>}
  items={(state.confirmed?.items??[]).map(run=>({id:run.id,title:<><span>{operationNames[run.operation]}</span><span className="record-status" data-state={run.status}>{statuses[run.status]}</span></>,metadata:<><span>运行 #{run.id}</span><time dateTime={run.created_at}>{localTime(run.created_at)}</time></>,selected:selected===run.id,disabled:!available,label:`查看运行 #${run.id} · ${operationNames[run.operation]} · ${statuses[run.status]}`,open:()=>open(run)}))}
  empty={state.confirmed?.pagination.total?'当前页暂无运行':'暂无符合条件的运行'}
  footer={state.confirmed&&(state.confirmed.pagination.total_pages>1||state.confirmed.pagination.page>1)&&<Pagination compactSingle value={state.confirmed.pagination} loading={state.loading||!available} showLoadingStatus={false} change={page=>void history.refresh({...state.confirmed!.query,page})}/>}/>;
}
export function RunRecordSummary({run}:Readonly<{run:GuideRun}>){
 return <><p className="run-task-summary" data-state={run.status}><strong>{operationNames[run.operation]} · {statuses[run.status]}</strong> · {run.scope===null?'未指定范围':scopeNames[run.scope.scope_type]}</p>{run.current_step!=='FINISHED'&&<p>{steps[run.current_step]}</p>}
  {run.source_type==='COMMENT'&&<p>来自评论的修改请求，评论处理状态保持独立。</p>}
  {run.status==='FAILED'&&<p role="alert" className="inline-error">{failure(run)}</p>}{run.status==='CANCELLED'&&<p>本次运行已取消。</p>}
  {run.application_result==='APPLIED'&&<p>{run.suggestion_batch_id!==null?'修改建议已生成，等待审阅。':`文档已保存为 V${run.document_effect!.after_content_version}。`}</p>}
  {run.application_result==='NO_CHANGE'&&<p>未产生正文变化。</p>}{run.application_result==='NOT_APPLIED'&&<p className="inline-error">{run.operation==='PROPOSE_CHANGES'?'修改建议未生成，本轮正文未变。':'本轮未写入文档。'}</p>}
  {run.progress_result==='APPLIED'&&<p>讨论进度已更新。</p>}{run.progress_result==='REJECTED'&&<p role="alert" className="inline-error">{run.progress_error}</p>}
  {run.final_result?.analysis&&<details className="run-result"><summary>查看分析结果</summary><AnalysisResult value={run.final_result.analysis}/></details>}
  {run.final_result&&<details className="run-result"><summary>查看运行结果摘要</summary><p className="run-summary">{run.final_result.summary}</p></details>}</>;
}
export function ReturnedResponses({run}:Readonly<{run:GuideRun}>){
 return <>{run.returned_responses.map(response=><section key={response.llm_use_id} className="returned-model-response" aria-label={`模型返回 ${response.call_no}.${response.attempt_no}`}>
  <p><strong>模型返回 · 调用 {response.call_no} · 第 {response.attempt_no} 次</strong></p>
  <ModelReturnContent content={response.content}/>
 </section>)}</>;
}
/** Read surfaces are independent of command/card/batch owners. A failed
 * connection keeps the last actual status and never produces FAILED. */
export function AiReadPanel({owner,structured,commands,renderMarkdown,scrollPort,scrollContent}:Readonly<{scrollPort?:HTMLElement|null;scrollContent?:HTMLElement|null;owner:RequirementAiRead;structured?:(message:Message)=>ReactNode;commands?:(run:GuideRun)=>ReactNode;renderMarkdown?:MessageMarkdownRenderer}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),run=state.run;
 const messages=useSyncExternalStore(owner.messages.subscribe,owner.messages.getSnapshot);
 return <section className="ai-read-panel" aria-label="AI 对话">
  <header className="read-section-heading conversation-read-status"><span className="sr-only">会话状态</span><span className="read-status" role="status">{state.refreshing?'正在同步会话状态…':''}</span></header>
  {state.error&&<p role="alert" className="inline-error">{state.error} <button className="ui-button" type="button" disabled={!state.visible||state.refreshing} onClick={()=>void owner.refresh().catch(()=>undefined)}>重试读取 AI 状态</button></p>}
  {state.selected!==null&&<section aria-label="当前查看的 AI 运行" className="run-status" aria-busy={state.querying}>
   <div className="run-status-context"><strong>{state.selection==='HISTORY'?'历史运行详情':'当前任务'}</strong><span>#{state.selected}</span></div>
   {!run&&<p role="status">正在读取运行状态…</p>}
   {run&&<><RunRecordSummary run={run}/>{commands?.(run)}{run.status!=='FAILED'&&run.returned_responses.length>0&&<ReturnedResponses run={run}/>} {!messages.items?.some(message=>message.role==='USER'&&message.guide_run_id===run.id)&&<RequestCallRecord runId={run.id}/>}</>}
   {state.connection_error&&<p role="alert" className="inline-error">运行连接异常，保留最后确认状态。<button className="ui-button" type="button" disabled={!state.visible||state.querying} onClick={()=>owner.readRun()}>重读运行</button></p>}
  </section>}
  <MessageTimeline {...(scrollPort!==undefined?{scrollPort}:{})} {...(scrollContent!==undefined?{scrollContent}:{})} messages={owner.messages} resultNotice={message=>run&&message.role==='ASSISTANT'&&message.id===run.latest_assistant_message_id&&message.guide_run_id===run.id?<ProposalResultNotice run={run}/>:null} requestRecord={message=>message.role==='USER'&&message.guide_run_id!==null?<RequestCallRecord runId={message.guide_run_id} messageId={message.id}/>:null} {...(run?.latest_assistant_message_id?{reply:{message_id:run.latest_assistant_message_id,guide_run_id:run.id}}:{})} {...(structured?{structured}:{})} {...(renderMarkdown?{renderMarkdown}:{})}/>
  {run&&run.latest_assistant_message_id===null&&<ProposalResultNotice run={run}/>}
  {run?.status==='FAILED'&&<section role="status" className="run-response-notice"><p className="inline-error">本次运行失败：{failure(run)}</p><ReturnedResponses run={run}/></section>}
 </section>;
}
