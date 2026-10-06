import {createRoot} from 'react-dom/client';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetail} from '../../src/requirements/detail.tsx';
import type {RequirementDetailOwner} from '../../src/requirements/detail-owner.ts';
import type {ManualDraftSession} from '../../src/documents/manual-session.ts';
import {require} from '../../src/api/decoding.ts';
import '../../src/shared/styles.css';

/** Actual complete product component. Only faults are injected at the
 * transport boundary; no constructed document, status or model output. */
export async function mountDetailProductProbe(api:WalleApi){
 const container=document.createElement('div');container.id='native-detail-product';document.body.append(container);const root=createRoot(container);let owner:RequirementDetailOwner|undefined,readFailure=false,saveFailure=false,back=0,remembered:ManualDraftSession|null=null;
 const counts={guide_prepares:0,guide_sends:0,failed_saves:0};
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);
  if(key==='getCommentIndex')return (...args:Parameters<WalleApi['getCommentIndex']>)=>{if(readFailure)throw new ApiUnknown(false);return target.getCommentIndex(...args);};
  if(key==='prepareSaveManualDraft')return (...args:Parameters<WalleApi['prepareSaveManualDraft']>)=>{const action=target.prepareSaveManualDraft(...args);return {submit:()=>{if(saveFailure){counts.failed_saves++;throw new ApiUnknown(true);}return action.submit();}};};
  if(key==='prepareCreateGuide')return (...args:Parameters<WalleApi['prepareCreateGuide']>)=>{counts.guide_prepares++;const action=target.prepareCreateGuide(...args);let lost=false;return {submit:async()=>{counts.guide_sends++;const response=await action.submit();if(!lost){lost=true;throw new ApiUnknown(true);}return response;}};};
  return typeof value==='function'?value.bind(target):value;
 }});
 root.render(<RequirementDetail identity={2} api={wrapped} back={()=>{back++;}} ready={actual=>{owner=actual;}}/>);
 return {state(){if(!owner)return null;const regions=owner.regions,document=owner.documents.getSnapshot(),manual=document.manual;return {ready:owner.getSnapshot().ready,error:owner.getSnapshot().error,mode:document.mode,busy:document.busy,detail:document.detail,layout:regions?.layout.getSnapshot(),viewport:regions?.viewport.getSnapshot(),departure:owner.departure.getSnapshot(),composer:regions?.conversation.composer.getSnapshot(),ai:regions?.conversation.read.getSnapshot(),comment:regions?{view:regions.comments.getSnapshot().view,slots:regions.comments.getSnapshot().slots.map(slot=>({identity:slot.identity,state:slot.flow.getSnapshot()})),ready:regions.comments.comments.ready}:null,
   manual:manual?{id:manual.autosave.confirmedDocument.id,status:manual.autosave.state.status,version:manual.autosave.state.confirmed_version,local:manual.autosave.localSnapshot.markdown_content,readonly:manual.editor.readonly,blocked:manual.getSnapshot().blocked,recovery:manual.recovery.getSnapshot().phase}:null,same_session:!!manual&&manual===remembered,back,counts};},
  readFailure(value:boolean){readFailure=value;},saveFailure(value:boolean){saveFailure=value;},remember(){require(!!owner?.documents.getSnapshot().manual);remembered=owner!.documents.getSnapshot().manual;return true;},
  async inspect(){require(!!owner?.regions);const actual=(await api.getRequirement(2)).data,current=(await api.getCurrentDocument(2)).data;return {passed:true,actual,current,comments:(await api.listComments(2)).data.items,revisions:(await api.listRevisions(2)).data.items,runs:(await api.listGuideRuns(2)).data.items,counts,back};},
  async destroy(){root.unmount();await owner?.retire();container.remove();return {passed:true};}};
}
