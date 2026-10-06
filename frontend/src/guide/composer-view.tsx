import {useId,useMemo,useState,useSyncExternalStore} from 'react';
import type {GuideRun} from '../api/models.ts';
import type {RequirementDocumentOwner} from '../requirements/document-owner.ts';
import type {RequirementGuideComposer} from './composer.ts';
import {guideTarget,reviewTarget} from './scope.ts';
const names={INITIALIZE:'继续初始化',ASK:'提问',REVIEW:'检查',MODIFY:'修改'} as const;
const scopeNames={DOCUMENT:'整篇文档',SECTION:'当前章节',BLOCK:'当前区块',SELECTION:'当前选区'} as const;
const quietSubscribe=()=>()=>{},empty=()=>null;
export function GuideComposer({owner,documents,review}:Readonly<{owner:RequirementGuideComposer;documents:RequirementDocumentOwner;review:GuideRun|null}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),document=useSyncExternalStore(documents.subscribe,documents.getSnapshot),navigation=document.navigation,help=useId();
 const nav=useSyncExternalStore(navigation?.subscribe??quietSubscribe,navigation?.getSnapshot??empty),[composing,setComposing]=useState(false),binding=documents.currentBinding,waiting=owner.waiting;
 const options=useMemo(()=>Object.keys(scopeNames).map(key=>{const kind=key as keyof typeof scopeNames;try{if(!binding||nav?.error)throw Error('当前正式正文暂不可操作');return {kind,target:guideTarget(binding.editor,kind,nav?.selected_block??nav?.active_heading??null,document.selection),error:null};}catch(error){return {kind,target:null,error:error instanceof Error?error.message:'当前范围不可用'};}}),[binding,nav?.selected_block,nav?.active_heading,nav?.error,document.selection]);
 const disabled=!state.available||!owner.editable||state.refreshing||document.busy,actions=state.detail.requirement.status==='INITIALIZING'?['INITIALIZE'] as const:state.detail.requirement.status==='COMPLETED'?['ASK'] as const:['ASK','REVIEW','MODIFY'] as const;
 return <section aria-label="AI 消息输入" className="guide-composer" aria-busy={state.refreshing||state.phase==='SUBMITTING'||state.phase==='READING'}>
  {waiting?<p>回复当前等待运行 {waiting.id}；本次普通文字将继续同一运行。</p>:<>
   <label>AI 操作<select aria-label="AI 操作" value={state.action} disabled={disabled} onChange={event=>owner.choose(event.target.value as typeof state.action)}>{!actions.some(action=>action===state.action)&&<option value={state.action} disabled>{names[state.action]}（当前不可用）</option>}{actions.map(action=><option key={action} value={action}>{names[action]}</option>)}</select></label>
   <label>操作范围<select aria-label="操作范围" value={state.target.scope.scope_type} disabled={disabled} onChange={event=>{const target=options.find(option=>option.kind===event.target.value)?.target;if(target)owner.select(target);else owner.rejectScope();}}>{options.map(option=><option key={option.kind} value={option.kind} disabled={!option.target}>{scopeNames[option.kind]}</option>)}</select></label>
   <p>本次范围：{state.target.label}</p>{state.target.content_version!==state.detail.current.content_version&&<p role="alert">正文版本已变化，请重新选择范围；原输入仍保留。</p>}
   <button type="button" disabled={disabled||!options.find(option=>option.kind===state.target.scope.scope_type)?.target||JSON.stringify(options.find(option=>option.kind===state.target.scope.scope_type)?.target)===JSON.stringify(state.target)} onClick={()=>{const target=options.find(option=>option.kind===state.target.scope.scope_type)?.target;if(target)owner.select(target);}}>采用当前范围</button>
   {options.find(option=>option.kind==='SELECTION')?.error&&<p className="field-help">选区不可用：{options.find(option=>option.kind==='SELECTION')!.error}</p>}
   {state.review&&<p>根据已完成的检查运行 {state.review.id} 修改，提交时重新读取当前正文。</p>}
   {review?.action_type==='REVIEW'&&review.status==='COMPLETED'&&state.detail.requirement.status==='ACTIVE'&&<button type="button" disabled={disabled||!binding} onClick={()=>{try{owner.useReview(review,reviewTarget(binding!.editor,review.scope));}catch{owner.rejectScope();}}}>根据这次检查修改</button>}
  </>}
  <label>给 AI 的消息<textarea value={state.instruction} disabled={disabled} rows={4} aria-describedby={help} onChange={event=>owner.change(event.target.value)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={event=>{setComposing(false);owner.change(event.currentTarget.value);}}/></label>
  <p id={help} className="field-help">允许换行，最多 10000 个字符。发送前请核对本次范围；未发送文字仅保留在输入区。</p>
  <button type="button" disabled={disabled||composing||!owner.allowed} onClick={()=>{if(!composing)void owner.submit();}}>{waiting?'发送补充说明':'发送消息'}</button>
  {state.phase==='SUBMITTING'&&<p role="status">正在发送消息…</p>}{state.phase==='READING'&&<p role="status">正在核实实际资源，保留原请求…</p>}
  {state.phase==='CONFIRMED'&&<p role="status">消息发送已接受，正在读取正式消息与运行；接受不表示模型完成。</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.phase==='UNKNOWN'&&<button type="button" disabled={!state.available||state.refreshing} onClick={()=>void owner.recover()}>重新确认消息发送结果</button>}
  {state.phase==='CONFIRMED'&&<button type="button" disabled={!state.available||state.refreshing} onClick={()=>void owner.finish()}>重读已接受消息与运行</button>}
  {state.phase==='ERROR'&&<button type="button" disabled={disabled} onClick={()=>void owner.refresh()}>重读发送所需状态</button>}
 </section>;
}
