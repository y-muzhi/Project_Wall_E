import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {Message} from '../api/models.ts';
import {localTime} from '../shared/time.ts';
import type {RequirementMessages} from './read.ts';
type Anchor=Readonly<{id:string|null;offset:number;top:number;height:number;near:boolean;last:number}>;
function anchor(root:HTMLElement):Anchor{
 const box=root.getBoundingClientRect(),cards=[...root.querySelectorAll<HTMLElement>('[data-message-id]')],visible=cards.find(card=>card.getBoundingClientRect().bottom>box.top&&card.getBoundingClientRect().top<box.bottom);
 return {id:visible?.dataset.messageId??null,offset:visible?visible.getBoundingClientRect().top-box.top:0,top:root.scrollTop,height:root.scrollHeight,near:root.scrollHeight-root.clientHeight-root.scrollTop<=80,last:Number(cards.at(-1)?.dataset.messageSequence??0)};
}
/** Text is always the actual public content. Structured card/answer controls
 * can be supplied by their real owner; damaged structures remain plain text.
 * Fetching older windows preserves the native visible message, including a
 * user scroll that happens while the request is pending. */
export function MessageTimeline({messages,structured}:Readonly<{messages:RequirementMessages;structured?:(message:Message)=>ReactNode}>){
 const state=useSyncExternalStore(messages.subscribe,messages.getSnapshot),root=useRef<HTMLDivElement>(null),position=useRef<Anchor|null>(null),seen=useRef(0),[unread,setUnread]=useState(false);
 useLayoutEffect(()=>{
  const element=root.current;if(!element)return;
  if(state.loading){position.current??=anchor(element);return;}
  if(seen.current!==state.revision){
   const previous=position.current,newest=state.items?.at(-1)?.sequence_no??0;
   if(seen.current===0||state.request==='LATEST'&&previous?.near){element.scrollTop=element.scrollHeight;setUnread(false);}
   else if(previous){const item=previous.id===null?null:element.querySelector<HTMLElement>('[data-message-id="'+previous.id+'"]');if(item)element.scrollTop+=item.getBoundingClientRect().top-element.getBoundingClientRect().top-previous.offset;else element.scrollTop=previous.top+element.scrollHeight-previous.height;
    if(state.request==='LATEST'&&newest>previous.last)setUnread(true);}
   seen.current=state.revision;
  }
  position.current=null;
 },[state.items,state.loading,state.revision,state.request]);
 return <section className="message-thread" aria-label="对话消息">
  <header><button type="button" disabled={state.loading||!state.active} onClick={()=>void messages.refresh()}>刷新消息</button>{state.has_more&&<button type="button" disabled={state.loading||!state.active} onClick={()=>void messages.older()}>加载更早消息</button>}{unread&&<button type="button" onClick={()=>{if(root.current)root.current.scrollTop=root.current.scrollHeight;setUnread(false);}}>有新消息 · 回到底部</button>}</header>
  {state.loading&&<p role="status">{state.request==='OLDER'?'正在读取更早消息…':'正在读取消息…'}</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error} <button type="button" disabled={state.loading||!state.active} onClick={()=>void (state.request==='OLDER'?messages.older():messages.refresh())}>重试读取消息</button></p>}
  <div className="message-timeline" ref={root} role="region" aria-label="消息阅读区" aria-busy={state.loading} onScroll={()=>{const element=root.current;if(!element)return;if(state.loading)position.current=anchor(element);if(element.scrollHeight-element.clientHeight-element.scrollTop<=80)setUnread(false);}}>
   {state.items?.length===0&&<p>暂无消息</p>}
   {state.items?.map(message=><article key={message.id} data-message-id={message.id} data-message-sequence={message.sequence_no} className={'conversation-message '+(message.role==='USER'?'from-user':'from-assistant')}>
    <header><strong>{message.role==='USER'?'你':'AI'}</strong><time dateTime={message.created_at}>{localTime(message.created_at)}</time></header>
    <p className="message-content">{message.content}</p>
    {message.message_type==='INTERACTION_CARDS'&&message.structured_content===null&&<p role="status">历史问题结构无法读取，保留可读内容。</p>}
    {message.structured_content!==null&&structured?.(message)}
   </article>)}
  </div>
 </section>;
}
