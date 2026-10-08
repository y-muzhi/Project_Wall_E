import {useEffect,useId,useRef,useState,useSyncExternalStore} from 'react';
import type {InteractionCards} from './cards.ts';
import {responses as decodeResponses} from '../api/models.ts';
import type {Responses} from '../api/models.ts';
/** Actual formal state and original card definitions stay separate from local
 * answers. Recommendations and associated snapshots confer no selection or
 * write scope. No submit-on-Enter or composition-end shortcut is installed. */
export function InteractionCardsView({owner,busy=false}:Readonly<{owner:InteractionCards;busy?:boolean}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),name=useId(),root=useRef<HTMLElement>(null),[composing,setComposing]=useState(false);
 const disabled=!state.available||!owner.editable||!owner.allowed||busy,answered=state.message.card_state==='ANSWERED';
 let formal:Responses|null=null;if(state.formal?.structured_content!==null&&state.formal?.structured_content!==undefined)formal=decodeResponses(state.formal.structured_content);
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
  {state.cards.cards.map((card,index)=>{const local=state.answers.responses.find(answer=>answer.card_key===card.card_key)!,answer=answered?formal?.responses.find(answer=>answer.card_key===card.card_key):state.message.card_state==='AVAILABLE'?local:null;
   return <fieldset key={card.card_key} data-card-key={card.card_key} disabled={disabled||state.message.card_state!=='AVAILABLE'}>
    <legend>{index+1}. {card.question}{card.required?'（必答）':'（可跳过）'}</legend>
    {card.context&&<p>{card.context}</p>}
    {card.options.map(option=><label key={option.option_key} className="card-option"><input type={card.card_type==='MULTI_SELECT'?'checkbox':'radio'} name={name+':'+card.card_key} checked={answer?.selected_option_keys.includes(option.option_key)??false} onChange={event=>owner.toggle(card.card_key,option.option_key,event.target.checked)}/><span><strong>{option.label}</strong>{option.description&&<span>{option.description}</span>}{option.impact&&<span>影响：{option.impact}</span>}{option.risks&&<span>风险：{option.risks}</span>}</span></label>)}
    {card.custom_answer.enabled&&<label>自定义回答<textarea value={answer?.custom_answer??''} rows={3} aria-describedby={name+':help:'+index} onChange={event=>owner.custom(card.card_key,event.target.value)} onCompositionStart={()=>setComposing(true)} onCompositionEnd={event=>{setComposing(false);owner.custom(card.card_key,event.currentTarget.value);}}/><span id={name+':help:'+index}>最多 {card.custom_answer.max_length} 个字符；自定义回答计作一次选择。</span></label>}
    {!card.required&&<label><input type="checkbox" checked={answer?.skipped??false} onChange={event=>owner.skip(card.card_key,event.target.checked)}/>明确跳过此问题</label>}
    {card.card_type==='MULTI_SELECT'&&<p>请选择 {card.selection_rule.min}～{card.selection_rule.max} 项。</p>}
    {card.recommendation&&<p className="field-help">AI 推荐：{card.recommendation.option_keys.map(key=>card.options.find(option=>option.option_key===key)!.label).join('、')}。{card.recommendation.reason} 推荐仅供参考，请自行选择。</p>}
    {card.related_spec_context.map((context,i)=><blockquote key={i}><p>关联正文（问题生成时的原文）</p><p className="message-content">{context.content_snapshot}</p></blockquote>)}
    {state.card_error===card.card_key&&state.error&&<p role="alert" className="inline-error">{state.error}</p>}
   </fieldset>;
  })}
  {answered&&!state.formal&&<p>正在等待正式回答读取。<button type="button" disabled={!state.available||state.refreshing||state.phase==='CONFIRMED'} onClick={()=>void owner.refresh()}>读取正式回答</button></p>}
  {answered&&state.formal?.structured_content===null&&<p className="message-content">{state.formal.content}</p>}
  {state.message.card_state==='AVAILABLE'&&<button type="button" disabled={disabled||composing} onClick={()=>{if(!composing)void owner.submit();}}>提交整组答案</button>}
  {['READY','RESOLVED'].includes(state.phase)&&<button type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.refresh()}>刷新卡片状态</button>}
  {state.phase==='SUBMITTING'&&<p role="status">正在提交整组答案…</p>}{state.phase==='READING'&&<p role="status">正在核实正式卡片与回答，保留原请求…</p>}
  {state.phase==='CONFIRMED'&&<p role="status">正式回答已保存，正在读取运行与对话；接受不表示模型成功。</p>}
  {state.error&&!state.card_error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.storage_error&&<p role="alert" className="inline-error">{state.storage_error} <button type="button" disabled={state.refreshing||busy} onClick={()=>owner.retryStorage()}>重试本地记录</button></p>}
  {state.phase==='UNKNOWN'&&<button type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.recover()}>重新确认整组提交结果</button>}
  {state.phase==='CONFIRMED'&&<button type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.finish()}>重读已保存答案与运行</button>}
  {state.phase==='ERROR'&&!state.card_error&&<button type="button" disabled={!state.available||state.refreshing||busy} onClick={()=>void owner.refresh()}>重读正式卡片状态与回答</button>}
 </section>;
}
