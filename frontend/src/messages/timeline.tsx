import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {Message} from '../api/models.ts';
import {localTime} from '../shared/time.ts';
import type {RequirementMessages} from './read.ts';
type Anchor=Readonly<{id:string|null;part:string|null;offset:number;top:number;height:number;near:boolean;last:number}>;
function anchor(root:HTMLElement):Anchor{
 const box=root.getBoundingClientRect(),cards=[...root.querySelectorAll<HTMLElement>('[data-message-id]')],visible=cards.find(card=>card.getBoundingClientRect().bottom>box.top&&card.getBoundingClientRect().top<box.bottom);
 const part=visible&&visible.getBoundingClientRect().top<box.top?[...visible.querySelectorAll<HTMLElement>('[data-card-key]')].find(card=>card.getBoundingClientRect().bottom>box.top&&card.getBoundingClientRect().top<box.bottom):null,target=part??visible;
 return {id:visible?.dataset.messageId??null,part:part?.dataset.cardKey??null,offset:target?target.getBoundingClientRect().top-box.top:0,top:root.scrollTop,height:root.scrollHeight,near:root.scrollHeight-root.clientHeight-root.scrollTop<=80,last:Number(cards.at(-1)?.dataset.messageSequence??0)};
}
function restore(root:HTMLElement,previous:Anchor):void{
 const message=previous.id===null?null:root.querySelector<HTMLElement>('[data-message-id="'+previous.id+'"]'),part=previous.part===null?null:[...message?.querySelectorAll<HTMLElement>('[data-card-key]')??[]].find(card=>card.dataset.cardKey===previous.part),target=part??message;
 if(target)root.scrollTop+=target.getBoundingClientRect().top-root.getBoundingClientRect().top-previous.offset;else root.scrollTop=previous.top+root.scrollHeight-previous.height;
}
/** Text is always the actual public content. Structured card/answer controls
 * can be supplied by their real owner; damaged structures remain plain text.
 * Fetching older windows preserves the native visible message, including a
 * user scroll that happens while the request is pending. */
export function MessageTimeline({messages,structured}:Readonly<{messages:RequirementMessages;structured?:(message:Message)=>ReactNode}>){
 const state=useSyncExternalStore(messages.subscribe,messages.getSnapshot),root=useRef<HTMLDivElement>(null),content=useRef<HTMLDivElement>(null),position=useRef<Anchor|null>(null),stable=useRef<Anchor|null>(null),seen=useRef(0),[unread,setUnread]=useState(false);
 useLayoutEffect(()=>{
  const element=root.current;if(!element)return;
  if(state.loading){position.current??=anchor(element);return;}
  if(seen.current!==state.revision){
   const previous=position.current,newest=state.items?.at(-1)?.sequence_no??0;
   if(seen.current===0||state.request==='LATEST'&&previous?.near){element.scrollTop=element.scrollHeight;setUnread(false);}
   else if(previous){restore(element,previous);
    if(state.request==='LATEST'&&newest>previous.last)setUnread(true);}
   seen.current=state.revision;
  }
  position.current=null;stable.current=anchor(element);
 },[state.items,state.loading,state.revision,state.request]);
 useLayoutEffect(()=>{
  const element=root.current,items=content.current;if(!element||!items)return;
  // Card source reads, error messages and native textarea resizing can change
  // a rendered message after the I35 revision was already adopted. Preserve
  // the same message/card, or keep the reader at the bottom if already near it.
  const observer=new ResizeObserver(()=>{const previous=stable.current;if(previous){if(previous.near)element.scrollTop=element.scrollHeight;else restore(element,previous);}stable.current=anchor(element);});observer.observe(items);
  return()=>observer.disconnect();
 },[]);
 return <section className="message-thread" aria-label="对话消息">
  <header><button type="button" disabled={state.loading||!state.active} onClick={()=>void messages.refresh()}>刷新消息</button>{state.has_more&&<button type="button" disabled={state.loading||!state.active} onClick={()=>void messages.older()}>加载更早消息</button>}{unread&&<button type="button" onClick={()=>{if(root.current)root.current.scrollTop=root.current.scrollHeight;setUnread(false);}}>有新消息 · 回到底部</button>}</header>
  {state.loading&&<p role="status">{state.request==='OLDER'?'正在读取更早消息…':'正在读取消息…'}</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error} <button type="button" disabled={state.loading||!state.active} onClick={()=>void (state.request==='OLDER'?messages.older():messages.refresh())}>重试读取消息</button></p>}
  <div className="message-timeline" ref={root} role="region" aria-label="消息阅读区" aria-busy={state.loading} onScroll={()=>{const element=root.current;if(!element)return;
   // A layout-driven scroll can be delivered before ResizeObserver. Let that
   // observer restore from the last geometry instead of recording a position
   // in the newly expanded content as though the reader had moved there.
   if(stable.current&&element.scrollHeight!==stable.current.height)return;
   stable.current=anchor(element);if(state.loading)position.current=stable.current;if(stable.current.near)setUnread(false);}}>
   <div ref={content}>
   {state.items?.length===0&&<p>暂无消息</p>}
   {state.items?.map(message=><article key={message.id} data-message-id={message.id} data-message-sequence={message.sequence_no} className={'conversation-message '+(message.role==='USER'?'from-user':'from-assistant')}>
    <header><strong>{message.role==='USER'?'你':'AI'}</strong><time dateTime={message.created_at}>{localTime(message.created_at)}</time></header>
    <p className="message-content">{message.content}</p>
    {message.message_type==='INTERACTION_CARDS'&&message.structured_content===null&&<p role="status">历史问题结构无法读取，保留可读内容。</p>}
    {message.structured_content!==null&&structured?.(message)}
   </article>)}
   </div>
  </div>
 </section>;
}
