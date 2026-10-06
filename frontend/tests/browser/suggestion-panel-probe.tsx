import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDocumentOwner} from '../../src/requirements/document-owner.ts';
import {SuggestionPanel} from '../../src/suggestions/panel.tsx';
import {SuggestionTargetLocator} from '../../src/suggestions/targets.ts';
import {suggestionMarkdown} from '../../src/suggestions/preview.ts';
import {ToastStore} from '../../src/shared/toast-store.ts';
import {ToastViewport} from '../../src/shared/toast.tsx';
import {suggestionProbe} from './suggestion-probe.ts';
import {RequirementConversation} from '../../src/guide/conversation-owner.ts';
import '../../src/shared/styles.css';

/** Actual product components in an isolated diagnostic host, not the product
 * route. Suggestions are the same explicit five-patch storage precondition. */
export async function mountSuggestionPanelProbe(api:WalleApi,unified=false){
 const main=document.createElement('main'),scroll=document.createElement('section'),host=document.createElement('div'),aside=document.createElement('aside');main.style.cssText='padding:24px;display:grid;grid-template-columns:minmax(640px,1fr) 440px;gap:24px';scroll.style.cssText='height:580px;overflow:auto;padding:24px;background:white';aside.style.height='580px';scroll.append(host);main.append(scroll,aside);document.body.append(main);
 let documents:RequirementDocumentOwner,locator:SuggestionTargetLocator|undefined,conversation:RequirementConversation|undefined;const probe=await suggestionProbe(api,actual=>documents.adopt(actual),unified?(identity,detail,api,read,adopt)=>{conversation?.dispose();conversation=new RequirementConversation(detail,api,read,adopt,()=>{shown=true;conversation!.setView(true);});conversation.setView(true);const owner=conversation.batch(identity);if(!owner)throw Error('Actual activity batch owner missing');return owner;}:undefined);documents=new RequirementDocumentOwner(host,2,api,probe.readActual,scroll);const toasts=new ToastStore(),root=createRoot(aside);let shown=true;
 const render=(markdown:string,columns?:number)=>{const binding=documents.currentBinding;if(!binding)throw Error('Actual CURRENT context unavailable');return binding.editor.action(ctx=>suggestionMarkdown(ctx,markdown,columns));};
 function View(){useSyncExternalStore(documents.subscribe,documents.getSnapshot);const state=probe.state(),activity=state.detail.activity;return <><button type="button" onClick={()=>{shown=!shown;conversation?.setView(shown);probe.visible(shown);root.render(<View/>);}}>切换建议面板显示</button>{shown&&<div style={{height:'540px'}}><SuggestionPanel key={activity.kind==='BATCH'?activity.batch.id:state.batch?.id} owner={probe.owner()} render={render} locate={id=>locator?.locate(id)??false} notify={message=>toasts.push('success',message)}/></div>}<ToastViewport store={toasts}/></>;}
 return {...probe,async begin(){locator?.dispose();const origin=await probe.begin();await conversation?.read.refresh();locator=new SuggestionTargetLocator(probe.owner(),()=>documents.currentBinding);root.render(<View/>);return origin;},
  inspect(){return {state:probe.state(),document:documents.currentBinding?.editor.loadedDocument??null,navigation:documents.getSnapshot().navigation?.getSnapshot(),toasts:toasts.getSnapshot(),counts:probe.counts,conversation:conversation?.read.getSnapshot(),batch_owner_same:conversation?conversation.getSnapshot().batch===probe.owner():null};},
  preview(markdown:string,columns?:number){const box=document.createElement('div');box.id='suggestion-rich-preview';box.append(render(markdown,columns));main.append(box);return {html:box.innerHTML,text:box.textContent};},
  async destroy(){root.unmount();locator?.dispose();conversation?.dispose();await probe.destroy();await documents.retire();toasts.dispose();main.remove();return {passed:true};}};
}
