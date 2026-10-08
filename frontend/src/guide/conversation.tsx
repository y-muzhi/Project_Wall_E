import {useCallback,useEffect,useMemo,useState,useSyncExternalStore} from 'react';
import type {RequirementConversation} from './conversation-owner.ts';
import type {RequirementDocumentOwner} from '../requirements/document-owner.ts';
import type {ToastStore} from '../shared/toast-store.ts';
import {AiReadPanel} from './read-view.tsx';
import {RunControls} from './run-controls.tsx';
import {GuideComposer} from './composer-view.tsx';
import {CardMessage} from './card-message.tsx';
import {SuggestionPanel} from '../suggestions/panel.tsx';
import {SuggestionTargetLocator} from '../suggestions/targets.ts';

function BatchView({owner,documents,toasts}:Readonly<{owner:NonNullable<ReturnType<RequirementConversation['getSnapshot']>['batch']>;documents:RequirementDocumentOwner;toasts:ToastStore}>){
 const locator=useMemo(()=>new SuggestionTargetLocator(owner,()=>documents.currentBinding),[owner,documents]);
 useEffect(()=>()=>locator.dispose(),[locator]);
 const render=useCallback((markdown:string,columns?:number)=>{
  return documents.previewMarkdown(markdown,columns);
 },[documents]);
 return <SuggestionPanel owner={owner} render={render} locate={identity=>locator.locate(identity)} notify={message=>toasts.push('success',message)}/>;
}

/** One auxiliary panel, with a bounded suggestion list and persistent message
 * owners. Local view selection never cancels a Run or replaces an intention. */
export function GuideConversation({owner,documents,toasts}:Readonly<{owner:RequirementConversation;documents:RequirementDocumentOwner;toasts:ToastStore}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),read=useSyncExternalStore(owner.read.subscribe,owner.read.getSnapshot),document=useSyncExternalStore(documents.subscribe,documents.getSnapshot);
 const [showMessages,setShowMessages]=useState(false),batch=state.batch;
 // Retry display when the actual editor/parser becomes available or changes.
 // This only creates DOM fragments and never adopts content as CURRENT.
 const renderMarkdown=useCallback((markdown:string)=>documents.previewMarkdown(markdown),[documents,document.navigation]);
 // A different actual batch is a new display selection; original batches and
 // their drafts/unknown requests remain retained in the owner.
 useEffect(()=>setShowMessages(false),[batch]);
 return <section className="guide-conversation" aria-label="需求 AI 辅助区">
  {batch&&<div className="conversation-view-switch"><button type="button" aria-pressed={!showMessages} onClick={()=>setShowMessages(false)}>修改建议</button><button type="button" aria-pressed={showMessages} onClick={()=>setShowMessages(true)}>对话与运行</button></div>}
  <div className="conversation-suggestions" hidden={!batch||showMessages} inert={!batch||showMessages}>{batch&&<BatchView key={batch.batchId} owner={batch} documents={documents} toasts={toasts}/>}</div>
  <div className="conversation-discussion" hidden={!!batch&&!showMessages} inert={!!batch&&!showMessages}>
   <AiReadPanel owner={owner.read} structured={message=><CardMessage groups={owner.cards} message={message} busy={document.busy}/>} commands={()=><RunControls owner={owner.runs}/>} renderMarkdown={renderMarkdown}/>
   <GuideComposer owner={owner.composer} documents={documents} review={read.run}/>
  </div>
 </section>;
}
