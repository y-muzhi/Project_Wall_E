import {useEffect,useId,useRef,useState,useSyncExternalStore} from 'react';
import type {InteractionCards} from './cards.ts';
import {responses as decodeResponses} from '../api/models.ts';
import type {Responses} from '../api/models.ts';
import type {CardsState} from './cards.ts';
import {snapshotObject} from '../api/client.ts';
import {cardProgress} from './card-progress.ts';
import type {RequirementDocumentOwner} from '../requirements/document-owner.ts';
import {guideTarget} from './scope.ts';
import {SourceReference} from '../requirements/source-reference.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
/** Actual formal state and original card definitions stay separate from local
 * answers. Recommendations and associated snapshots confer no selection or
 * write scope. No submit-on-Enter or composition-end shortcut is installed. */
export function InteractionCardsView({owner,busy=false,documents}:Readonly<{owner:InteractionCards;busy?:boolean;documents?:RequirementDocumentOwner}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),name=useId(),root=useRef<HTMLElement>(null),[composing,setComposing]=useState(false);
 const disabled=!state.available||!owner.editable||!owner.allowed||busy,answered=state.message.card_state==='ANSWERED';
 let formal:Responses|null=null;if(state.formal?.structured_content!==null&&state.formal?.structured_content!==undefined)formal=decodeResponses(state.formal.structured_content);
 const progress=cardProgress(state.cards,state.answers),protectedRequest=['SUBMITTING','UNKNOWN','READING','CONFIRMED'].includes(state.phase);
 useEffect(()=>{
  if(!state.card_error||disabled)return;
  const card=[...root.current?.querySelectorAll<HTMLElement>('[data-card-key]')??[]].find(row=>row.dataset.cardKey===state.card_error),field=card?.querySelector<HTMLElement>('input:not(:disabled),textarea:not(:disabled)');
  if(!field)return;let following=0;
  // Let the added error and the message reader's ResizeObserver settle before
  // this deliberate focus move; restoring the old anchor must not hide it.
  const frame=requestAnimationFrame(()=>{following=requestAnimationFrame(()=>{
   if(field.isConnected&&root.current?.contains(field)&&!field.matches(':disabled')&&field.getClientRects().length){field.focus({preventScroll:true});field.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});}
  });});
  return()=>{cancelAnimationFrame(frame);cancelAnimationFrame(following);};
 },[state.card_error,state.error,disabled]);
 return <section ref={root} className="interaction-cards" aria-label="决策卡片组" aria-busy={state.refreshing||['SUBMITTING','READING'].includes(state.phase)}>
  <p>{state.cards.intro}</p><p role="status">{answered?'已回答 · 正式答案已保存':state.message.card_state==='EXPIRED'?'已失效 · 保留原问题供阅读':'待确认 · 未提交的选择仅保存在本地'}</p>
  <CardActionDetails state={state} owner={owner} disabled={disabled}/>
  {documents&&state.message.card_state==='AVAILABLE'&&state.cards.purpose==='DOCUMENT_ACTION'&&Array.isArray(state.cards.action_payload?.selectable_fields)&&state.cards.action_payload.selectable_fields.includes('scope')&&<CardScopeControls owner={owner} state={state} documents={documents} disabled={disabled}/>}
  {state.message.card_state==='AVAILABLE'&&<div className="card-local-progress"><strong>本地已填 {progress.ready.length} / {progress.total} 题</strong><span>{progress.remaining.length===0?'整组已填写，尚未提交':`待填必答 ${progress.required.length} 题；其余问题也需回答或明确跳过。`}</span>{progress.required.length>0&&<span>下一道必答：{state.cards.cards.find(card=>card.card_key===progress.required[0])?.question}</span>}</div>}
  <details className="card-question-disclosure" data-current={!answered} open={!answered||protectedRequest}>
  <summary>查看原问题与正式答案</summary>
  {state.cards.cards.map((card,index)=>{const local=state.answers.responses.find(answer=>answer.card_key===card.card_key)!,answer=answered?formal?.responses.find(answer=>answer.card_key===card.card_key):state.message.card_state==='AVAILABLE'?local:null;
   return <fieldset key={card.card_key} data-card-key={card.card_key} disabled={disabled||state.message.card_state!=='AVAILABLE'}>
    <legend>{index+1}. {card.question}{card.required?'（必答）':'（可跳过）'}</legend>
    {card.context&&<p>{card.context}</p>}
    {card.options.map(option=><div key={option.option_key} className="card-option-row"><label className="card-option"><input className="ui-input" type={card.card_type==='MULTI_SELECT'?'checkbox':'radio'} name={name+':'+card.card_key} checked={answer?.selected_option_keys.includes(option.option_key)??false} onChange={event=>owner.toggle(card.card_key,option.option_key,event.target.checked)}/><span><strong>{option.label}</strong>{option.description&&<span>{option.description}</span>}</span></label>{option.risks&&<p className="card-option-risk">风险：{option.risks}</p>}{option.impact&&<details className="card-option-detail"><summary>查看“{option.label}”的影响</summary><p>{option.impact}</p></details>}</div>)}
    {card.custom_answer.enabled&&<label>自定义回答<textarea className="ui-input" value={answer?.custom_answer??''} rows={3} aria-describedby={name+':help:'+index} onChange={event=>owner.custom(card.card_key,event.target.value)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={event=>{setComposing(false);owner.custom(card.card_key,event.currentTarget.value);}}/><span id={name+':help:'+index}>最多 {card.custom_answer.max_length} 个字符；自定义回答计作一次选择。</span></label>}
    {!card.required&&<label><input className="ui-input" type="checkbox" checked={answer?.skipped??false} onChange={event=>owner.skip(card.card_key,event.target.checked)}/>明确跳过此问题</label>}
    {card.card_type==='MULTI_SELECT'&&<p>请选择 {card.selection_rule.min}～{card.selection_rule.max} 项。</p>}
    {card.recommendation&&<p className="field-help">AI 推荐：{card.recommendation.option_keys.map(key=>card.options.find(option=>option.option_key===key)!.label).join('、')}。{card.recommendation.reason} 推荐仅供参考，请自行选择。</p>}
    {card.related_spec_context.length>0&&<details className="card-related-source"><summary>关联正文 · 问题生成时的原文</summary>{card.related_spec_context.map((context,i)=><blockquote key={i}><p>文档 #{context.document_id} · V{context.content_version} · 区块 #{context.block_id}</p><p className="message-content">{context.content_snapshot}</p></blockquote>)}</details>}
    {state.card_error===card.card_key&&state.error&&<p role="alert" className="inline-error">{state.error}</p>}
   </fieldset>;
  })}
  </details>
  {answered&&!state.formal&&<p>正在等待正式回答读取。<button className="ui-button" type="button" disabled={!state.available||state.refreshing||state.phase==='CONFIRMED'} onClick={()=>void owner.refresh()}>读取正式回答</button></p>}
  {answered&&state.formal?.structured_content===null&&<p className="message-content">{state.formal.content}</p>}
  {state.message.card_state==='AVAILABLE'&&<button className="ui-button primary" type="button" disabled={disabled||composing} onClick={()=>{if(!composing)void owner.submit();}}>{submitLabel(state)}</button>}
  {state.phase==='SUBMITTING'&&<p role="status">正在提交整组答案…</p>}{state.phase==='READING'&&<p role="status">正在核实正式卡片与回答，保留原请求…</p>}
  {state.phase==='CONFIRMED'&&<p role="status">{state.outcome?.processing==='PROGRAM'?'程序处理已完成，正在读取正式状态。':'正式回答已保存，正在读取新运行与对话。'}</p>}
  {state.formal?.program_receipt&&<p role="status">{state.formal.program_receipt.result==='DEFERRED'?'已记录暂缓决定。':state.formal.program_receipt.purpose==='PHASE_CHANGE'?'阶段确认已保存。':state.formal.program_receipt.document_effect?.result==='NO_CHANGE'?'确认已保存，正文无变化。':'确认的事实变更已写入文档。'}</p>}
  {state.error&&!state.card_error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.storage_error&&<p role="alert" className="inline-error">{state.storage_error} <button className="ui-button" type="button" disabled={state.refreshing||busy} onClick={()=>owner.retryStorage()}>重试本地记录</button></p>}
  {state.phase==='UNKNOWN'&&<button className="ui-button" type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.recover()}>重新确认整组提交结果</button>}
  {state.phase==='CONFIRMED'&&<button className="ui-button" type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.finish()}>重读已保存答案与运行</button>}
  {state.phase==='ERROR'&&!state.card_error&&<button className="ui-button" type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.refresh()}>重读正式卡片状态与回答</button>}
 </section>;
}

function submitLabel(state:CardsState):string{
 const selected=state.answers.responses[0]?.selected_option_keys[0];if(state.cards.purpose==='CLARIFICATION')return '提交整组答案';
 if(selected==='defer')return '确认暂缓';if(state.cards.purpose==='DOCUMENT_ACTION')return state.cards.action_payload?.operation==='GENERATE'?'生成工作稿':'更新工作稿';
 return state.cards.purpose==='PHASE_CHANGE'?'确认切换阶段':'确认并写入';
}
function CardActionDetails({state,owner,disabled}:Readonly<{state:CardsState;owner:InteractionCards;disabled:boolean}>){
 const purpose=state.cards.purpose,payload=state.cards.action_payload;if(purpose==='CLARIFICATION'||payload===null)return null;
 const selection=state.message.card_state==='ANSWERED'&&state.formal?.structured_content!==null&&state.formal?.structured_content!==undefined?decodeResponses(state.formal.structured_content).execution_selection:state.answers.execution_selection,selectable=Array.isArray(payload.selectable_fields)?payload.selectable_fields:[];
 const target=purpose==='DOCUMENT_ACTION'?selection?.target??null:state.source.target;
 const name=target?.kind==='NEW'?target.name:target?.kind==='EXISTING'?state.detail.documents.find(document=>document.id===target.document_id)?.name??'原目标文档':null;
 const sources=selection?.source_refs??[],changed=state.cards.program_binding.source_heads.some(head=>state.detail.documents.find(document=>document.id===head.document_id)?.content_version!==head.content_version);
 const phaseNames:Record<string,string>={DISCOVERY:'需求探索',SOLUTION:'方案设计',SPECIFICATION:'规格编写',REVIEW:'检查收束'};
 return <section className="card-action-details" aria-label="本次行动内容">
  {purpose==='DOCUMENT_ACTION'&&<><p><strong>{payload.operation==='GENERATE'?'生成新稿':'修订文档'}：{name}</strong></p>
   {target?.kind==='EXISTING'&&<p>基准版本 V{target.expected_content_version} · {selection?.scope?.scope_type==='DOCUMENT'?'整篇文档':selection?.scope?.scope_type==='SECTION'?'指定章节':selection?.scope?.scope_type==='BLOCK'?'指定区块':'指定选区'}</p>}
   {selectable.includes('target')&&target?.kind==='NEW'&&<><label>新文档名称<input className="ui-input" value={target.name} maxLength={80} disabled={disabled} onChange={event=>owner.configureExecution({target:{...target,name:event.target.value}})}/></label><label>文档类型<SingleSelect label="建议新稿类型" disabled={disabled} value={String(target.document_kind)} options={[{value:'brief',label:'需求说明'},{value:'design',label:'设计文档'},{value:'specification',label:'规格说明'}]} change={kind=>owner.configureExecution({target:{...target,document_kind:kind,template_ref:target.template_ref===null?null:{key:'structure.'+kind,version:'v1'}}})}/></label><label><input type="checkbox" disabled={disabled} checked={target.template_ref!==null} onChange={event=>owner.configureExecution({target:{...target,template_ref:event.currentTarget.checked?{key:'structure.'+String(target.document_kind),version:'v1'}:null}})}/>绑定固定结构</label></>}
   {selectable.includes('target')&&target?.kind==='EXISTING'&&selection?.scope?.scope_type==='DOCUMENT'&&<label>目标文档<select className="ui-input" disabled={disabled} value={target.document_id} onChange={event=>{const document=state.detail.documents.find(document=>document.id===Number(event.target.value));if(document)owner.configureExecution({target:{kind:'EXISTING',document_id:document.id,expected_content_version:document.content_version}});}}>{state.detail.documents.filter(document=>document.archived_at===null).map(document=><option key={document.id} value={document.id}>{document.name} · V{document.content_version}</option>)}</select></label>}
   {sources.length>0&&<ul>{sources.map(source=><li key={JSON.stringify(source)}><SourceReference read={signal=>owner.readReference(source,signal)} label={source.kind==='REVISION'?`${state.detail.documents.find(document=>document.id===source.document_id)?.name??'来源文档'} · 历史版本 #${source.revision_id}`:source.kind==='MESSAGE'||source.kind==='CARD_ANSWER'?`对话消息 #${source.message_id}`:`运行 #${source.guide_run_id} 的材料`}/></li>)}</ul>}
   {selectable.includes('source_refs')&&<fieldset disabled={disabled}><legend>参考文档</legend>{state.detail.documents.map(document=><label key={document.id}><input type="checkbox" checked={sources.some(source=>source.kind==='REVISION'&&source.document_id===document.id)} onChange={event=>{const rest=sources.filter(source=>source.kind!=='REVISION'||source.document_id!==document.id);owner.configureExecution({source_refs:event.target.checked?[...rest,{kind:'REVISION',document_id:document.id,revision_id:document.current_revision_id,block_ids:null}]:rest});}}/>{document.name} · V{document.content_version}</label>)}</fieldset>}
   {changed&&<label><input type="checkbox" disabled={disabled} checked={selection?.acknowledge_source_changes??false} onChange={event=>owner.configureExecution({acknowledge_source_changes:event.target.checked})}/>已查看来源版本变化，仍按所选来源执行</label>}
   {Array.isArray(payload.unresolved_impacts)&&payload.unresolved_impacts.length>0&&<p>待定影响：{payload.unresolved_impacts.join('；')}</p>}
  </>}
  {purpose==='PHASE_CHANGE'&&<><p><strong>建议进入：{phaseNames[String(payload.phase_kind)]??String(payload.phase_kind)}</strong></p><p>{String(payload.closure_summary)}</p></>}
  {purpose==='FACT_CONFIRMATION'&&<><p><strong>确认写入：{name}</strong>{target?.kind==='EXISTING'?` · V${target.expected_content_version}`:''}</p>
   {Array.isArray(payload.confirmed_fact_patches)&&payload.confirmed_fact_patches.map((value,index)=>{const fact=snapshotObject(value),patch=snapshotObject(fact.patch);return <article key={index}><p><strong>变更 {index+1}：{String(patch.title)}</strong></p><p>{String(patch.explanation)}</p><p>原文</p><pre className="message-content">{String(patch.original_content)}</pre><p>确认后的内容</p><pre className="message-content">{patch.patch_operation==='DELETE_BLOCK'?'删除此区块':patch.proposed_markdown===null?JSON.stringify(patch.proposed_data_json,null,2):String(patch.proposed_markdown)}</pre>{patch.selector_json!==null&&<p>目标表格行：{JSON.stringify(patch.selector_json)}</p>}</article>;})}
  </>}
 </section>;
}

const quietSubscribe=()=>()=>{},empty=()=>null;
function CardScopeControls({owner,state,documents,disabled}:Readonly<{owner:InteractionCards;state:CardsState;documents:RequirementDocumentOwner;disabled:boolean}>){
 const document=useSyncExternalStore(documents.subscribe,documents.getSnapshot),nav=useSyncExternalStore(document.navigation?.subscribe??quietSubscribe,document.navigation?.getSnapshot??empty);
 const selection=state.answers.execution_selection,target=selection?.target,binding=documents.currentBinding;
 if(target?.kind!=='EXISTING'||selection?.scope===null)return null;
 const names={DOCUMENT:'整篇文档',SECTION:'当前章节',BLOCK:'当前区块',SELECTION:'当前选区'} as const;
 const candidates=Object.keys(names).map(key=>{const kind=key as keyof typeof names;try{
  if(!binding||nav?.error||binding.editor.loadedDocument.id!==target.document_id||binding.editor.loadedDocument.content_version!==target.expected_content_version)throw Error('Read the fixed target first');
  return {kind,value:guideTarget(binding.editor,kind,nav?.selected_block??nav?.active_heading??null,document.selection)};
 }catch{return {kind,value:null};}});
 return <div className="card-scope-controls"><label>操作范围<SingleSelect label="卡片操作范围" disabled={disabled} value={String(selection?.scope?.scope_type??'DOCUMENT')} options={candidates.map(item=>({value:item.kind,label:names[item.kind],disabled:item.kind!=='DOCUMENT'&&item.value===null}))} change={kind=>{
  if(kind==='DOCUMENT'){owner.configureExecution({scope:{scope_type:'DOCUMENT',scope_ref:null}});return;}
  const selected=candidates.find(item=>item.kind===kind)?.value;if(!selected)return;const scope=selected.scope;
  owner.configureExecution({scope:scope.scope_type==='SECTION'?{scope_type:'SECTION',scope_ref:{heading_block_id:scope.scope_ref.block_id}}:scope});
 }}/></label>{binding?.editor.loadedDocument.id!==target.document_id&&<p className="field-help">请先阅读目标文档，再选择其中的章节、区块或文字。</p>}</div>;
}
