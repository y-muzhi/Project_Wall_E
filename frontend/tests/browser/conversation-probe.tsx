import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {RequirementConversation} from '../../src/guide/conversation-owner.ts';
import {AiReadPanel} from '../../src/guide/read-view.tsx';
import {GuideComposer} from '../../src/guide/composer-view.tsx';
import {RunControls} from '../../src/guide/run-controls.tsx';
import {CardMessage} from '../../src/guide/card-message.tsx';
import '../../src/shared/styles.css';

/** Existing product controls under the unified owner. Explicit card state
 * fixtures precede the real I14/I15/I36/I18 transactions; no Provider proof. */
export async function mountConversationProbe(api:WalleApi,identity:number,kind:'INITIALIZE'|'EXPIRE'|'WAITING'){
 const initial=(await api.getCurrentDocument(identity)).data,source=(await api.prepareCreateGuide(identity,{action_type:kind==='INITIALIZE'?'INITIALIZE':'ASK',expected_version:initial.content_version,scope_type:'DOCUMENT',scope_ref:null,source_type:'USER_INSTRUCTION',source_id:null,instruction:kind==='INITIALIZE'?'初始化卡片前置夹具':kind==='WAITING'?'等待卡片前置夹具':'文本替代卡片前置夹具'}).submit()).data.guide_run;
 let seeded=false;for(let attempt=0;attempt<200;attempt++){const actual=(await api.getGuideRun(source.id)).data;if(actual.status===(kind==='INITIALIZE'?'COMPLETED':'WAITING_USER')){seeded=true;break;}await new Promise(resolve=>setTimeout(resolve,25));}require(seeded);
 const messages=(await api.listMessages(identity)).data.items,message=messages.findLast(row=>row.message_type==='INTERACTION_CARDS');require(message!==undefined);
 const main=document.createElement('main'),scroll=document.createElement('section'),host=document.createElement('div'),aside=document.createElement('aside');main.style.cssText='padding:24px;display:grid;grid-template-columns:minmax(640px,1fr) 440px;gap:24px';scroll.style.cssText='height:580px;overflow:auto;padding:24px;background:white';scroll.append(host);main.append(scroll,aside);document.body.append(main);
 const counts={prepares:0,sends:0,reads:0,adopts:0},canonical=(value:unknown):unknown=>Array.isArray(value)?value.map(canonical):value!==null&&typeof value==='object'?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,value])=>[key,canonical(value)])):value;
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(['prepareCreateGuide','prepareContinueGuide','prepareCardResponses','prepareRetryGuide'].includes(String(key)))return (...args:unknown[])=>{counts.prepares++;const action=value.apply(target,args);let receipt:string|null=null;return {submit:async()=>{counts.sends++;const response=await action.submit();if(receipt===null){receipt=JSON.stringify(canonical(response.data));throw new ApiUnknown(true);}require(receipt===JSON.stringify(canonical(response.data)));return response;}};};return typeof value==='function'?value.bind(target):value;}});
 const reader=new RequirementDetailRead(identity,api);let unavailable=false,shown=true,conversation:RequirementConversation;
 const read=async()=>{counts.reads++;if(unavailable)throw new ApiUnknown(false);require(await reader.refresh());return reader.getSnapshot().confirmed!;},detail=await read(),documents=new RequirementDocumentOwner(host,identity,api,read,scroll);await documents.adopt(detail);
 conversation=new RequirementConversation(detail,wrapped,read,async actual=>{counts.adopts++;await documents.adopt(actual);},()=>{shown=true;conversation.setView(true);});conversation.setView(true);await conversation.refresh();require(await conversation.cards.ready());require(conversation.cards.get(message.id)?.owner!==null);
 const root=createRoot(aside);function View(){const state=useSyncExternalStore(conversation.subscribe,conversation.getSnapshot),actual=useSyncExternalStore(conversation.read.subscribe,conversation.read.getSnapshot);return <><button type="button" onClick={()=>{shown=!shown;conversation.setView(shown);root.render(<View/>);}}>切换统一AI面板显示</button><div hidden={!state.visible} inert={!state.visible}><AiReadPanel owner={conversation.read} structured={message=><CardMessage groups={conversation.cards} message={message}/>} commands={()=><RunControls owner={conversation.runs}/>}/><GuideComposer owner={conversation.composer} documents={documents} review={actual.run}/></div></>;}
 root.render(<View/>);
 return {state(){const card=conversation.cards.get(message.id)?.owner;return {lease:conversation.getSnapshot().lease,visible:conversation.getSnapshot().visible,composer:conversation.composer.getSnapshot(),actions:conversation.runs.getSnapshot(),ai:conversation.read.getSnapshot(),card:card?.getSnapshot(),groups:{syncing:conversation.cards.getSnapshot().syncing,error:conversation.cards.getSnapshot().error},counts,local:sessionStorage.getItem(`walle:v1:cards:${identity}:${message.id}`)};},source_id:source.id,message_id:message.id,readUnavailable(value:boolean){unavailable=value;},
  async inspect(){const current=(await api.getCurrentDocument(identity)).data;require(JSON.stringify(current)===JSON.stringify(initial));return {passed:true,identity,kind,source_id:source.id,message_id:message.id,current_unchanged:true,counts,messages:(await api.listMessages(identity)).data.items,runs:(await api.listGuideRuns(identity)).data.items,document:documents.currentBinding?.editor.loadedDocument};},
  async destroy(){root.unmount();conversation.dispose();reader.dispose();await documents.retire();main.remove();return {passed:true};}};
}
