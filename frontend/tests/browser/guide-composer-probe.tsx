import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import {editorViewCtx} from '@milkdown/kit/core';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {RequirementAiRead} from '../../src/guide/read-owner.ts';
import {AiReadPanel} from '../../src/guide/read-view.tsx';
import {RequirementGuideComposer} from '../../src/guide/composer.ts';
import {GuideComposer} from '../../src/guide/composer-view.tsx';
import '../../src/shared/styles.css';

export async function mountGuideComposerProbe(api:WalleApi,identity=2){
 const main=document.createElement('main'),scroll=document.createElement('section'),host=document.createElement('div'),aside=document.createElement('aside');main.style.cssText='padding:24px;display:grid;grid-template-columns:minmax(640px,1fr) 440px;gap:24px';scroll.style.cssText='height:580px;overflow:auto;padding:24px;background:white';scroll.append(host);main.append(scroll,aside);document.body.append(main);
 if(identity===2){const initial=(await api.getCurrentDocument(identity)).data,draft=(await api.prepareStartManualDraft(identity,initial.content_version).submit()).data.manual_draft,temporary=document.createElement('div');main.append(temporary);const edit=await RequirementEditor.create(temporary,draft,false);
  edit.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text('真实范围😀甲乙'))));});require(edit.ledger!==null&&edit.valid);const ticket=edit.ledger.beginSave(),saved=(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data;edit.ledger.acknowledgeSave(ticket,saved);await api.prepareCompleteManualDraft(identity,saved.content_version).submit();await edit.destroy();temporary.remove();}
 const current=(await api.getCurrentDocument(identity)).data,counts={prepares:0,sends:0,receives:0,reads:0,messageRefresh:0};let dropRead=false,dropMessages=false,shown=true;
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(key==='prepareCreateGuide'||key==='prepareContinueGuide')return (...args:unknown[])=>{counts.prepares++;const action=value.apply(target,args);let sent=0,receipt:string|null=null;return {submit:async()=>{counts.sends++;const result=await action.submit();sent++;if(sent===1){receipt=JSON.stringify(result.data);throw new ApiUnknown(true);}require(JSON.stringify(result.data)===receipt);return result;}};};return typeof value==='function'?value.bind(target):value;}});
 const reader=new RequirementDetailRead(identity,api),read=async()=>{counts.reads++;if(dropRead){dropRead=false;throw new ApiUnknown(false);}require(await reader.refresh());return reader.getSnapshot().confirmed!;},detail=await read(),documents=new RequirementDocumentOwner(host,identity,api,read,scroll);await documents.adopt(detail);
 let ai:RequirementAiRead,composer:RequirementGuideComposer;const adopt=async(actual:typeof detail)=>{await documents.adopt(actual);ai.adopt(actual);composer.adopt(actual);};
 ai=new RequirementAiRead(detail,api,read,adopt,()=>{shown=true;composer.setAvailable(true);});composer=new RequirementGuideComposer(detail,wrapped,read,adopt,async run=>{counts.receives++;await ai.receive(run);},async()=>{counts.messageRefresh++;if(dropMessages){dropMessages=false;throw new ApiUnknown(false);}require(await ai.messages.refresh());});
 const release=documents.subscribe(()=>{const state=documents.getSnapshot();composer.setAvailable(shown&&state.mode==='CURRENT'&&state.active);if(state.detail)composer.adopt(state.detail);});composer.setAvailable(true);ai.setVisible(true);await ai.refresh();const root=createRoot(aside);
 function View(){const state=useSyncExternalStore(ai.subscribe,ai.getSnapshot);return <><button type="button" onClick={()=>{shown=!shown;composer.setAvailable(shown);ai.setVisible(shown);aside.querySelector<HTMLElement>('[data-composer-body]')!.hidden=!shown;}}>切换发送面板显示</button><div data-composer-body><AiReadPanel owner={ai}/><GuideComposer owner={composer} documents={documents} review={state.run}/></div></>;}
 root.render(<View/>);
 return {state(){return {composer:composer.getSnapshot(),ai:ai.getSnapshot(),documents:{mode:documents.getSnapshot().mode,selection:documents.getSnapshot().selection,navigation:documents.getSnapshot().navigation?.getSnapshot()},counts,shown};},failRead(){dropRead=true;},failMessages(){dropMessages=true;},
  async inspect(){const actual=(await api.getCurrentDocument(identity)).data;require(JSON.stringify(actual)===JSON.stringify(current));const messages=(await api.listMessages(identity)).data.items,runs=(await api.listGuideRuns(identity)).data.items;return {passed:true,identity,counts,current_unchanged:true,actual_runs:runs,messages,scope:'Real I14/initialization/current scopes and I15 accepting a privately seeded WAITING precondition; no real model WAITING/question/output/REVIEW-result effectiveness or complete root acceptance'};},
  async destroy(){root.unmount();release();composer.dispose();ai.dispose();reader.dispose();await documents.retire();main.remove();return {passed:true};}};
}
