import {useId,useMemo,useState,useSyncExternalStore} from 'react';
import type {GuideRun} from '../api/models.ts';
import type {RequirementDocumentOwner} from '../requirements/document-owner.ts';
import type {RequirementGuideComposer} from './composer.ts';
import {guideTarget,reviewTarget} from './scope.ts';
import {instructionFeedback} from './input-feedback.ts';
import {isSendShortcut} from './send-shortcut.ts';
import {Icon} from '../shared/icon.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
const names={INITIALIZE:'继续初始化',ASK:'提问',REVIEW:'检查',MODIFY:'修改'} as const;
const scopeNames={DOCUMENT:'整篇文档',SECTION:'当前章节',BLOCK:'当前区块',SELECTION:'当前选区'} as const;
const quietSubscribe=()=>()=>{},empty=()=>null;
export function GuideComposer({owner,documents,review,viewingHistory=null}:Readonly<{owner:RequirementGuideComposer;documents:RequirementDocumentOwner;review:GuideRun|null;viewingHistory?:number|null}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),document=useSyncExternalStore(documents.subscribe,documents.getSnapshot),navigation=document.navigation,help=useId();
 const nav=useSyncExternalStore(navigation?.subscribe??quietSubscribe,navigation?.getSnapshot??empty),[composing,setComposing]=useState(false),binding=documents.currentBinding,waiting=owner.waiting;
 const options=useMemo(()=>Object.keys(scopeNames).map(key=>{const kind=key as keyof typeof scopeNames;try{if(!binding||nav?.error)throw Error('当前正式正文暂不可操作');return {kind,target:guideTarget(binding.editor,kind,nav?.selected_block??nav?.active_heading??null,document.selection),error:null};}catch(error){return {kind,target:null,error:error instanceof Error?error.message:'当前范围不可用'};}}),[binding,nav?.selected_block,nav?.active_heading,nav?.error,document.selection]);
 const disabled=!state.available||!owner.editable||state.refreshing||document.busy,actions=state.detail.requirement.status==='INITIALIZING'?['INITIALIZE'] as const:state.detail.requirement.status==='COMPLETED'?['ASK'] as const:['ASK','REVIEW','MODIFY'] as const;
 const chosen=options.find(option=>option.kind===state.target.scope.scope_type),candidate=chosen?.target;
 const changed=candidate!==null&&candidate!==undefined&&JSON.stringify(candidate)!==JSON.stringify(state.target);
 const stale=state.target.content_version!==state.detail.current.content_version,feedback=instructionFeedback(state.instruction);
 const canSend=!disabled&&!composing&&owner.allowed&&feedback.valid;
 const send=()=>{if(canSend)void owner.submit();};
 return <section aria-label="AI 消息输入" className="guide-composer" aria-busy={state.refreshing||state.phase==='SUBMITTING'||state.phase==='READING'}>
  <div className="guide-composer-body">
  {viewingHistory!==null&&<p className="field-help">正在查看历史运行 #{viewingHistory}；{waiting?`此输入回复当前等待中的运行 #${waiting.id}。`:'此输入将对当前需求发起新操作，不回复历史运行。'}</p>}
  {waiting?<p>回复当前等待中的运行 #{waiting.id}；继续同一运行。</p>:<>
   <details className="guide-composer-settings"><summary aria-label="操作设置"><span>{names[state.action]}</span><span className="scope-summary" title={'已采用：'+state.target.label}>{state.target.label}</span><span className="guide-settings-trigger"><Icon name="settings"/><span>操作设置</span><span className="guide-settings-chevron"><Icon name="down"/></span></span></summary>
   <label>AI 操作<SingleSelect label="AI 操作" value={state.action} disabled={disabled} change={value=>owner.choose(value as typeof state.action)} options={[
    ...(!actions.some(action=>action===state.action)?[{value:state.action,label:names[state.action]+'（当前不可用）',disabled:true}]:[]),
    ...actions.map(action=>({value:action,label:names[action]}))]}/></label>
   <label>操作范围<SingleSelect label="操作范围" value={state.target.scope.scope_type} disabled={disabled} change={value=>{const target=options.find(option=>option.kind===value)?.target;if(target)owner.select(target);else owner.rejectScope();}} options={options.map(option=>({value:option.kind,label:scopeNames[option.kind],disabled:!option.target}))}/></label>
   <p className="field-help">已采用：{state.target.label} · 正文 v{state.target.content_version}</p>
   {state.target.scope.scope_type!=='DOCUMENT'&&!changed&&!chosen?.error&&!stale&&<p className="field-help">已采用当前范围，无需重复确认。</p>}
   {chosen?.error&&<p className="field-help" role="status">当前范围不可更新：{chosen.error}</p>}
   {state.review&&<p>根据已完成的检查结果修改，提交时重新读取当前正文。</p>}
   {review?.action_type==='REVIEW'&&review.status==='COMPLETED'&&state.detail.requirement.status==='ACTIVE'&&<>
    <button className="ui-button" type="button" disabled={disabled||!binding} onClick={()=>{try{owner.useReview(review,reviewTarget(binding!.editor,review.scope));}catch{owner.rejectScope();}}}>根据这次检查修改</button>
    <button className="ui-button" type="button" disabled={disabled||!binding||!owner.allowed} onClick={()=>{try{
     const current=binding!.editor.loadedDocument;
     if(state.target.document_id!==current.id||state.target.content_version!==current.content_version)throw Error('Stale chosen scope');
     owner.useReview(review,reviewTarget(binding!.editor,state.target.scope));
    }catch{owner.rejectScope();}}}>按本次范围根据检查修改</button>
   </>}
   </details>
   {stale&&<p role="alert" className="inline-error">正文版本已变化，请更新范围或展开操作设置重新选择；原输入仍保留。</p>}
   {changed&&<button className="ui-button" type="button" disabled={disabled} onClick={()=>{if(candidate)owner.select(candidate);}}>更新为{scopeNames[state.target.scope.scope_type]}</button>}
  </>}
  <label className="guide-message-field"><span className="sr-only">给 AI 的消息</span><textarea className="ui-input" aria-label="给 AI 的消息" value={state.instruction} disabled={disabled} placeholder={waiting?'补充当前问题需要的信息…':state.action==='INITIALIZE'?'补充背景、目标或需要明确的需求…':state.action==='MODIFY'?'说明希望修改的内容和期望结果…':state.action==='REVIEW'?'说明重点检查哪些问题…':'针对当前范围提出问题…'} rows={3} aria-invalid={!composing&&state.instruction.length>0&&!feedback.valid} aria-describedby={help} onChange={event=>owner.change(event.target.value)} onKeyDown={event=>{if(isSendShortcut(event.nativeEvent,canSend)){event.preventDefault();send();}}} onCompositionStart={()=>setComposing(true)} onCompositionEnd={event=>{setComposing(false);owner.change(event.currentTarget.value);}}/></label>
  <p id={help} className={!composing&&state.instruction.length>0&&!feedback.valid?'field-help inline-error':'field-help'}>{composing?'正在输入…':state.instruction.length===0?'输入消息，发送前核对动作与范围。':`${feedback.length} / 10000 字符 · ${feedback.error??'允许换行，发送前请核对范围。'}`}</p>
  {state.phase==='SUBMITTING'&&<p role="status">正在发送消息…</p>}{state.phase==='READING'&&<p role="status">正在核实实际资源，保留原请求…</p>}
  {state.phase==='CONFIRMED'&&<p role="status">消息发送已接受，正在读取正式消息与运行；接受不表示模型完成。</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.phase==='UNKNOWN'&&<button className="ui-button" type="button" disabled={!state.available||state.refreshing} onClick={()=>void owner.recover()}>重新确认消息发送结果</button>}
  {state.phase==='CONFIRMED'&&<button className="ui-button" type="button" disabled={!state.available||state.refreshing} onClick={()=>void owner.finish()}>重读已接受消息与运行</button>}
  {state.phase==='ERROR'&&<button className="ui-button" type="button" disabled={disabled} onClick={()=>void owner.refresh()}>重读发送所需状态</button>}
  </div>
  <footer className="guide-composer-footer"><span className="guide-send-hint">Ctrl / ⌘ + Enter 发送</span><button className="ui-button primary" type="button" disabled={!canSend} onClick={send}><Icon name="send"/>{waiting?'发送补充说明':'发送消息'}</button></footer>
 </section>;
}
