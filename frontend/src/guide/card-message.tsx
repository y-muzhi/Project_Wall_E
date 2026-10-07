import {useSyncExternalStore} from 'react';
import type {Message} from '../api/models.ts';
import type {RequirementCardGroups} from './card-groups.ts';
import {InteractionCardsView} from './cards-view.tsx';
/** Render in the original I35 article; source failures retain readable content
 * until verified controls recover. Damaged structures get no stale controls. */
export function CardMessage({groups,message,busy=false}:Readonly<{groups:RequirementCardGroups;message:Message;busy?:boolean}>){
 const state=useSyncExternalStore(groups.subscribe,groups.getSnapshot);if(message.message_type!=='INTERACTION_CARDS'||message.structured_content===null||message.card_state===null)return null;const slot=groups.get(message.id);
 return <div className="card-message">
  {(!slot||slot.loading)&&<p role="status">正在读取卡片的实际来源运行…</p>}
  {slot?.error&&<p role="alert" className="inline-error">{slot.error} <button type="button" disabled={!state.available||state.syncing||busy} onClick={()=>void groups.retry()}>重读卡片来源与正式回答</button></p>}
  {slot?.error&&!slot.owner&&<p className="message-content">{message.content}</p>}
  {slot?.owner&&<InteractionCardsView owner={slot.owner} busy={busy||slot.loading||slot.error!==null}/>}
 </div>;
}
