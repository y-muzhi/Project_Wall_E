import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {RequirementCommentPanel} from '../../src/comments/panel-owner.ts';
import {CommentPanel,CommentDocumentTools} from '../../src/comments/panel.tsx';
import {RequirementAiRead} from '../../src/guide/read-owner.ts';
import {AiReadPanel} from '../../src/guide/read-view.tsx';
import '../../src/shared/styles.css';

/** Every message, run and comment is created by the production API. The
 * diagnostic drops specified actual responses, without fabricating results. */
export async function mountAiReadProbe(api:WalleApi){
 const main=document.createElement('main');main.id='native-ai-read';main.style.cssText='padding:24px';const controls=document.createElement('div'),columns=document.createElement('div'),scroll=document.createElement('section'),host=document.createElement('div'),aside=document.createElement('aside');
 columns.style.cssText='display:grid;grid-template-columns:minmax(640px,1fr) 420px;gap:32px';scroll.style.cssText='height:560px;overflow:auto;padding:24px;background:white';host.className='detail-document-content';host.style.position='relative';scroll.append(host);columns.append(scroll,aside);main.append(controls,columns);document.body.append(main);
 const current=(await api.getCurrentDocument(2)).data;
 const failed=async(id:number)=>{const due=Date.now()+10000;while(Date.now()<due){const actual=(await api.getGuideRun(id)).data;if(actual.status==='FAILED'){require(actual.error_code==='CONFIG_INVALID');return;}await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Actual missing-config run did not stop');};
 let newCount=0;const append=async()=>{newCount++;const result=(await api.prepareCreateGuide(2,{expected_version:current.content_version,action_type:'ASK',instruction:'真实阅读消息 '+newCount+'😀\n'+('保留阅读位置与完整正式消息。\n'.repeat(4)),scope_type:'DOCUMENT',source_type:'USER_INSTRUCTION'}).submit()).data;await failed(result.guide_run.id);return result.guide_run.id;};
 for(let i=0;i<21;i++)await append();
 const block=current.block_state_json.blocks.find(row=>row.block_type==='paragraph')!.block_id;
 await api.prepareCreateComment(2,{expected_content_version:current.content_version,anchor_type:'BLOCK',block_id:block,content:'实际评论 AI 接收与页面切换😀'}).submit();
 const counts={messages:0,history:0,run:0,prepares:0,sends:0,opens:0,reads:0};let dropMessages=false,dropHistory=false,dropRun=false;
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);
  if(key==='listMessages')return async(...args:Parameters<WalleApi['listMessages']>)=>{counts.messages++;const actual=await target.listMessages(...args);if(dropMessages){dropMessages=false;throw new ApiUnknown(false);}return actual;};
  if(key==='listGuideRuns')return async(...args:Parameters<WalleApi['listGuideRuns']>)=>{counts.history++;const actual=await target.listGuideRuns(...args);if(dropHistory){dropHistory=false;throw new ApiUnknown(false);}return actual;};
  if(key==='getGuideRun')return async(...args:Parameters<WalleApi['getGuideRun']>)=>{counts.run++;const actual=await target.getGuideRun(...args);if(dropRun){dropRun=false;throw new ApiUnknown(false);}return actual;};
  if(key==='prepareModifyFromComment')return (...args:Parameters<WalleApi['prepareModifyFromComment']>)=>{counts.prepares++;const action=target.prepareModifyFromComment(...args);return {submit:async()=>{counts.sends++;const actual=await action.submit();if(counts.sends===1)throw new ApiUnknown(true);return actual;}};};
  return typeof value==='function'?value.bind(target):value;}});
 const reader=new RequirementDetailRead(2,wrapped),read=async()=>{counts.reads++;require(await reader.refresh());return reader.getSnapshot().confirmed!;},actual=await read(),documents=new RequirementDocumentOwner(host,2,wrapped,read,scroll);await documents.adopt(actual);
 let local:Readonly<{tab:'AI'|'COMMENTS';open:boolean}>=Object.freeze({tab:'AI',open:true}),ai:RequirementAiRead;const listeners=new Set<()=>void>();const set=(tab:'AI'|'COMMENTS',open=true)=>{local=Object.freeze({tab,open});ai.setVisible(open&&tab==='AI');for(const listener of listeners)listener();};
 ai=new RequirementAiRead(actual,wrapped,read,async snapshot=>{await documents.adopt(snapshot);},()=>{counts.opens++;set('AI');});
 const comments=new RequirementCommentPanel(actual,wrapped,read,async snapshot=>{await documents.adopt(snapshot);ai.adopt(snapshot);},ai.receive);
 const release=documents.subscribe(()=>{const state=documents.getSnapshot();comments.setView(state.mode==='HISTORY'?'HISTORY':state.mode==='MANUAL'?'MANUAL':'CURRENT');if(state.detail){comments.adopt(state.detail);}});
 await comments.refresh();ai.setVisible(true);await ai.refresh();const react=createRoot(controls),panelReact=createRoot(aside);
 function Controls(){const state=useSyncExternalStore(listener=>{listeners.add(listener);return()=>listeners.delete(listener);},()=>local);return <><button type="button" onClick={()=>set('AI')}>AI 对话</button><button type="button" onClick={()=>set('COMMENTS')}>评论</button><button type="button" onClick={()=>set(state.tab,!state.open)}>{state.open?'收起辅助面板':'展开辅助面板'}</button><CommentDocumentTools panel={comments} documents={documents}/></>;}
 function Panels(){const state=useSyncExternalStore(listener=>{listeners.add(listener);return()=>listeners.delete(listener);},()=>local);return <><div hidden={!state.open||state.tab!=='AI'}><AiReadPanel owner={ai}/></div><div hidden={!state.open||state.tab!=='COMMENTS'}><CommentPanel panel={comments} documents={documents}/></div></>;}
 react.render(<Controls/>);panelReact.render(<Panels/>);
 const visual=()=>{const area=aside.querySelector<HTMLElement>('.message-timeline');if(!area)return null;const box=area.getBoundingClientRect(),items=[...area.querySelectorAll<HTMLElement>('[data-message-id]')],first=items.find(row=>row.getBoundingClientRect().bottom>box.top&&row.getBoundingClientRect().top<box.bottom);return {top:area.scrollTop,near:area.scrollHeight-area.clientHeight-area.scrollTop<=80,id:first?.dataset.messageId,offset:first?first.getBoundingClientRect().top-box.top:null};};
 return {state:()=>({view:local,ai:ai.getSnapshot(),messages:ai.messages.getSnapshot(),history:ai.history.getSnapshot(),comments:{...comments.getSnapshot(),slots:comments.getSnapshot().slots.map(slot=>({identity:slot.identity,state:slot.flow.getSnapshot()}))},counts,visual:visual()}),
  failMessages(){dropMessages=true;},failHistory(){dropHistory=true;},failRun(){dropRun=true;},append,
  async inspect(){const now=(await api.getCurrentDocument(2)).data,index=(await api.getCommentIndex(2)).data;require(now.id===current.id&&now.content_version===current.content_version&&now.markdown_content===current.markdown_content&&JSON.stringify(now.block_state_json)===JSON.stringify(current.block_state_json));
   require(ai.messages.getSnapshot().items?.length===25&&new Set(ai.messages.getSnapshot().items!.map(row=>row.id)).size===25&&counts.prepares===1&&counts.sends===2&&counts.opens===1&&ai.getSnapshot().run?.id===25&&ai.getSnapshot().run?.status==='FAILED'&&!ai.getSnapshot().connection_error&&comments.getSnapshot().slots.length===0&&index.total_count===1&&index.open_count===1);
   return {passed:true,counts,current_id:now.id,current_version:now.content_version,message_count:25,run:ai.getSnapshot().run!.id,run_status:ai.getSnapshot().run!.status,comment_open:true,scope:'Actual I35 cursor/scroll/recovery, I19 history and I16 independent network errors, actual comment parent/AI receiver/page switch/original request recovery; no send/card/batch/full route/Provider acceptance'};},
  async destroy(){react.unmount();panelReact.unmount();release();comments.dispose();ai.dispose();reader.dispose();await documents.retire();listeners.clear();main.remove();return {passed:true};}};
}
