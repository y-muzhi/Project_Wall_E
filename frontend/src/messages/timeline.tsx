import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {Message} from '../api/models.ts';
import {conversationTime} from '../shared/time.ts';
import {Icon} from '../shared/icon.tsx';
import type {RequirementMessages} from './read.ts';
import {MessageContent} from './content.tsx';
import type {MessageMarkdownRenderer} from './content.tsx';
import {captureMessageAnchor as anchor,restoreMessageAnchor as restore} from './scroll-position.ts';
import type {MessageAnchor as Anchor} from './scroll-position.ts';
export type MessageReply=Readonly<{message_id:number;guide_run_id:number}>;
type ReplySelection=Readonly<{target:MessageReply;phase:'READING'|'LOCATE'|'LOCATED'|'MORE'|'MISSING'|'ERROR'|'INVALID'}>;
const sameReply=(left:MessageReply|undefined,right:MessageReply|undefined)=>left?.message_id===right?.message_id&&left?.guide_run_id===right?.guide_run_id;
/** Text messages render their actual public content without changing it.
 * Damaged structures retain the complete original text.
 * Valid cards use their real owner's question view and readable error fallback.
 * Fetching older windows preserves the native visible message, including a
 * user scroll that happens while the request is pending. */
export function MessageTimeline({messages,structured,renderMarkdown,reply,scrollPort,scrollContent}:Readonly<{scrollPort?:HTMLElement|null;scrollContent?:HTMLElement|null;messages:RequirementMessages;structured?:(message:Message)=>ReactNode;renderMarkdown?:MessageMarkdownRenderer;reply?:MessageReply}>){
 const state=useSyncExternalStore(messages.subscribe,messages.getSnapshot),root=useRef<HTMLDivElement>(null),content=useRef<HTMLDivElement>(null),position=useRef<Anchor|null>(null),stable=useRef<Anchor|null>(null),seen=useRef(0),[unread,setUnread]=useState(false);
 const currentReply=useRef(reply),replyGeneration=useRef(0);currentReply.current=reply;
 const [replySelection,setReplySelection]=useState<ReplySelection|null>(null),selectedReply=replySelection&&sameReply(replySelection.target,reply)?replySelection:null;
 useLayoutEffect(()=>{replyGeneration.current++;return()=>{replyGeneration.current++;};},[messages,reply?.message_id,reply?.guide_run_id,state.active]);
 const findReply=()=>{
  const target=reply,actual=messages.getSnapshot();if(!target||!actual.active||actual.loading||actual.items===null)return;
  if(actual.items.some(message=>message.id===target.message_id)){setReplySelection({target,phase:'LOCATE'});return;}
  if(!actual.has_more){setReplySelection({target,phase:'MISSING'});return;}
  setReplySelection({target,phase:'READING'});
  // One explicit click consumes at most one existing I35 cursor window.
  // No automatic sweep, guessed message or extra model request is introduced.
  const generation=replyGeneration.current;
  void messages.older().then(ok=>{
   const latest=messages.getSnapshot();
   if(generation!==replyGeneration.current||!sameReply(target,currentReply.current)||!latest.active||!ok&&(latest.loading||latest.revision!==actual.revision))return;
   setReplySelection({target,phase:ok?'LOCATE':'ERROR'});
  });
 };
 useLayoutEffect(()=>{
  const element=scrollPort===undefined?root.current:scrollPort;if(!element||!element.clientHeight||!state.active)return;
  if(state.loading){position.current??=anchor(element);return;}
  if(seen.current!==state.revision){
   const previous=position.current,newest=state.items?.at(-1)?.sequence_no??0;
   if(seen.current===0||state.request==='LATEST'&&previous?.near){element.scrollTop=element.scrollHeight;setUnread(false);}
   else if(previous){restore(element,previous);
    if(state.request==='LATEST'&&newest>previous.last)setUnread(true);}
   seen.current=state.revision;
  }
  position.current=null;stable.current=anchor(element);
 },[state.items,state.loading,state.revision,state.request,state.active,scrollPort]);
 useLayoutEffect(()=>{
  if(!selectedReply||selectedReply.phase!=='LOCATE'||!state.active||state.loading)return;
  const {target}=selectedReply,message=state.items?.find(item=>item.id===target.message_id),element=scrollPort===undefined?root.current:scrollPort;
  if(!message){setReplySelection({target,phase:state.has_more?'MORE':'MISSING'});return;}
  if(message.role!=='ASSISTANT'||message.guide_run_id!==target.guide_run_id){setReplySelection({target,phase:'INVALID'});return;}
  const card=element?.querySelector<HTMLElement>('[data-message-id="'+target.message_id+'"]');
  if(!element||!card){setReplySelection({target,phase:'ERROR'});return;}
  element.scrollTop+=card.getBoundingClientRect().top-element.getBoundingClientRect().top-8;card.focus({preventScroll:true});
  position.current=null;stable.current=anchor(element);if(stable.current.near)setUnread(false);
  setReplySelection({target,phase:'LOCATED'});
 },[selectedReply,state.items,state.active,state.loading,state.has_more,scrollPort]);
 useLayoutEffect(()=>{
  const element=scrollPort===undefined?root.current:scrollPort,items=scrollContent??content.current;if(!element||!items)return;
  // Card source reads, error messages and native textarea resizing can change
  // a rendered message after the I35 revision was already adopted. Preserve
  // the same message/card, or keep the reader at the bottom if already near it.
  const observer=new ResizeObserver(()=>{if(!element.clientHeight)return;const previous=stable.current;if(previous){if(previous.near)element.scrollTop=element.scrollHeight;else restore(element,previous);}stable.current=anchor(element);});observer.observe(items);observer.observe(element);
  return()=>observer.disconnect();
 },[scrollPort,scrollContent]);
 useLayoutEffect(()=>{
  const element=scrollPort===undefined?root.current:scrollPort;if(!element)return;
  const capture=()=>{if(!element.clientHeight||stable.current&&element.scrollHeight!==stable.current.height)return;
   stable.current=anchor(element);if(state.loading)position.current=stable.current;if(stable.current.near)setUnread(false);
  };
  element.addEventListener('scroll',capture,{passive:true});return()=>element.removeEventListener('scroll',capture);
 },[scrollPort,state.loading]);
 return <section className="message-thread" aria-label="对话消息">
  <header><div className="read-section-heading"><span className="sr-only">对话消息</span><span className="read-status" role="status">{state.loading?(state.request==='OLDER'?'正在读取更早消息…':'正在读取消息…'):''}</span></div>{state.has_more&&<button className="ui-button" type="button" disabled={state.loading||!state.active} onClick={()=>void messages.older()}>加载更早消息</button>}{reply&&<button className="ui-button" type="button" disabled={state.loading||!state.active||state.items===null} onClick={findReply}>{state.items?.some(message=>message.id===reply.message_id)?'查看本次回复':state.has_more?'加载更早消息并查找本次回复':'查找本次回复'}</button>}{unread&&<button className="ui-button" type="button" onClick={()=>{const element=scrollPort===undefined?root.current:scrollPort;if(element)element.scrollTop=element.scrollHeight;setUnread(false);}}>有新消息 · 回到底部</button>}</header>
  {selectedReply?.phase==='LOCATED'&&<p role="status">已定位到本次正式回复。</p>}
  {selectedReply?.phase==='MORE'&&<p role="status">本次回复尚未加载，可继续加载更早消息查找。</p>}
  {selectedReply?.phase==='MISSING'&&<p role="alert">已读到最早消息，未找到本次回复，请重新读取运行与消息。</p>}
  {selectedReply?.phase==='ERROR'&&<p role="status">本次回复尚未定位，可重试查找；已显示会话仍保留。</p>}
  {selectedReply?.phase==='INVALID'&&<p role="alert">回复引用与已读消息不一致，请重新读取运行与消息。</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error} <button className="ui-button" type="button" disabled={state.loading||!state.active} onClick={()=>void (state.request==='OLDER'?messages.older():messages.refresh())}>重试读取消息</button></p>}
  <div className={'message-timeline'+(scrollPort!==undefined?' message-timeline-shared':'')} ref={root} role={scrollPort===undefined?'region':undefined} aria-label={scrollPort===undefined?'消息阅读区':undefined} aria-busy={state.loading}>
   <div ref={content}>
   {state.items?.length===0&&<p>暂无消息</p>}
   {state.items?.map(message=><article key={message.id} tabIndex={-1} data-message-id={message.id} data-message-sequence={message.sequence_no} className={'conversation-message '+(message.role==='USER'?'from-user':'from-assistant')+(selectedReply?.phase==='LOCATED'&&selectedReply.target.message_id===message.id?' is-reply-target':'')}>
    {message.role==='USER'?<span className="sr-only">用户消息</span>:<header><span className="ai-message-avatar" role="img" aria-label="AI 助手"><Icon name="robot"/></span></header>}
    <div className="message-body">
    {message.message_type==='TEXT'?<MessageContent content={message.content} {...(renderMarkdown?{render:renderMarkdown}:{})}/>:
     (message.message_type!=='INTERACTION_CARDS'||message.structured_content===null||message.card_state===null||!structured)&&<p className="message-content">{message.content}</p>}
    {message.message_type==='INTERACTION_CARDS'&&message.structured_content===null&&<p role="status">历史问题结构无法读取，保留可读内容。</p>}
    {message.structured_content!==null&&structured?.(message)}
    </div>
    <footer className="message-time"><time dateTime={message.created_at}>{conversationTime(message.created_at)}</time></footer>
   </article>)}
   </div>
  </div>
 </section>;
}
