import type {WalleApi} from '../api/walle.ts';
import type {RevisionSummary} from '../api/models.ts';
import {RequirementDetailRead} from './detail-read.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {RequirementDocumentOwner} from './document-owner.ts';
import {RequirementHeaderCommands} from './header-commands.ts';
import {RequirementConversation} from '../guide/conversation-owner.ts';
import {RequirementCommentPanel} from '../comments/panel-owner.ts';
import {RequirementRevisionSave} from '../revisions/save.ts';
import {detailPermissions} from './permissions.ts';
import {DetailLayout,DetailViewportGuard} from './detail-layout.ts';
import type {DetailTab} from './detail-layout.ts';
import {DetailDeparture} from './departure.ts';
import {ToastStore} from '../shared/toast-store.ts';

export type DetailBindings=Readonly<{documents:RequirementDocumentOwner;header:RequirementHeaderCommands;conversation:RequirementConversation;comments:RequirementCommentPanel;layout:DetailLayout;viewport:DetailViewportGuard}>;
export type DetailOwnerState=Readonly<{detail:DetailSnapshot|null;loading:boolean;error:string|null;ready:boolean;revision:number;revisionSave:RequirementRevisionSave|null}>;
/** A complete actual detail owns all regions. Document adoption completes
 * before siblings receive new facts; inputs and original commands stay owned.
 * History and viewport gates affect views only, never business cancellation. */
export class RequirementDetailOwner{
 readonly read:RequirementDetailRead;readonly documents:RequirementDocumentOwner;readonly departure:DetailDeparture;readonly toasts=new ToastStore();
 private readonly api:WalleApi;private readonly width:()=>number;private readonly storage:Pick<Storage,'getItem'|'setItem'>|null;private bindings:DetailBindings|null=null;private readonly listeners=new Set<()=>void>();private readonly releases:(()=>void)[]=[];
 private value:DetailOwnerState=Object.freeze({detail:null,loading:false,error:null,ready:false,revision:0,revisionSave:null});private closed=false;private syncing=false;private previous:DetailSnapshot|null=null;private priorHistory=false;private refreshing:Promise<DetailSnapshot>|null=null;private retiring:Promise<void>|null=null;
 constructor(identity:number,api:WalleApi,host:HTMLElement,width:()=>number,storage:Pick<Storage,'getItem'|'setItem'>|null,scrollport:HTMLElement|null=null){
  this.api=api;this.width=width;this.storage=storage;this.read=new RequirementDetailRead(identity,api);this.documents=new RequirementDocumentOwner(host,identity,api,this.readActual,scrollport);this.departure=new DetailDeparture(this.documents);
  this.releases.push(this.read.subscribe(()=>this.sync()),this.documents.subscribe(()=>this.sync()),this.documents.revisions.subscribe(()=>this.sync()),this.departure.subscribe(()=>this.sync()));
 }
 getSnapshot=():DetailOwnerState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 get regions():DetailBindings|null{return this.bindings;}
 get supported():boolean{return !!this.bindings&&this.bindings.layout.getSnapshot().mode!=='BLOCKED'&&this.bindings.viewport.getSnapshot().phase==='SUPPORTED'&&this.departure.getSnapshot().phase==='IDLE';}
 private publish(changes:Partial<DetailOwnerState>){if(this.closed)return;this.value=Object.freeze({...this.value,...changes,revision:this.value.revision+1});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E detail observer failed',error);}}
 readActual=async():Promise<DetailSnapshot>=>{if(this.closed||!await this.read.refresh())throw Error(this.read.getSnapshot().error??'实际详情暂时无法读取');if(this.closed)throw Error('Detail is retired');return this.read.getSnapshot().confirmed!;};
 private createRegions(actual:DetailSnapshot):void{
  const layout=new DetailLayout(actual.requirement.status,this.width(),this.storage),viewport=new DetailViewportGuard(this.width(),{blockAndSave:()=>this.documents.blockAndSave(),readAfterSupport:async signal=>{if(signal.aborted)throw Error('Restore aborted');await this.documents.restoreSupported();if(signal.aborted)throw Error('Restore aborted');if(!this.documents.historical&&!await this.bindings!.comments.comments.refresh(this.bindings!.comments.comments.getSnapshot().page,true))throw Error('正文评论标记暂时无法读取');if(signal.aborted)throw Error('Restore aborted');}}),header=new RequirementHeaderCommands(actual,this.api);
  const conversation=new RequirementConversation(actual,this.api,this.readActual,this.adoptActual,()=>{layout.openTab('AI');this.sync();});
  const comments=new RequirementCommentPanel(actual,this.api,this.readActual,this.adoptActual,conversation.receive);
  this.bindings=Object.freeze({documents:this.documents,header,conversation,comments,layout,viewport});
  this.releases.push(layout.subscribe(()=>this.sync()),viewport.subscribe(()=>this.sync()),header.subscribe(()=>this.sync()));
 }
 private sync():void{
  if(this.closed||this.syncing)return;this.syncing=true;
  try{const document=this.documents.getSnapshot(),actual=document.detail,regions=this.bindings;
   if(actual&&regions&&actual!==this.previous){const changedCurrent=this.previous!==null&&JSON.stringify(this.previous.current)!==JSON.stringify(actual.current);this.previous=actual;regions.header.adopt(actual);regions.conversation.adopt(actual);regions.comments.adopt(actual);const saved=this.value.revisionSave;
    if(saved)saved.rebase(actual);else if(detailPermissions(actual,true).revision_save)this.publish({revisionSave:new RequirementRevisionSave(actual,this.api)});
    if(changedCurrent&&this.supported&&!this.documents.historical)void regions.comments.comments.refresh(regions.comments.comments.getSnapshot().page,true);
   }
   if(regions){const historical=this.documents.historical||document.mode==='HISTORY',geometry=regions.layout.getSnapshot();
    // Transient reads/adoption must not invalidate their own positive command
    // reconciliation. Visual availability follows stable view gates only.
    regions.conversation.setView(this.supported&&geometry.right_open&&geometry.right_tab==='AI',!historical);
    regions.comments.setView(historical?'HISTORY':document.mode==='MANUAL'?'MANUAL':'CURRENT',!this.supported);
    if(this.priorHistory&&!historical&&this.supported)void regions.comments.comments.refresh(regions.comments.comments.getSnapshot().page,true);this.priorHistory=historical;
    document.navigation?.setVisible(this.supported);
   }
   // A header mutation must not reuse the pre-mutation composite refresh.
   // Keep writes gated through document adoption and the final comments read.
   this.publish({detail:actual??this.value.detail,loading:this.read.getSnapshot().loading||this.refreshing!==null,error:this.read.getSnapshot().error??document.error,ready:!!regions&&this.refreshing===null&&this.supported&&this.read.writeReady&&this.documents.writeReady});
  }finally{this.syncing=false;}
 }
 adoptActual=async(actual:DetailSnapshot):Promise<void>=>{if(this.closed)throw Error('Detail is retired');await this.documents.adopt(actual);if(this.closed)throw Error('Detail is retired');this.sync();};
 refresh=():Promise<DetailSnapshot>=>{
  if(this.closed)return Promise.reject(Error('Detail is retired'));if(this.refreshing)return this.refreshing;
  const pending=(async()=>{const actual=await this.readActual();if(this.documents.historical){await this.documents.restoreSupported();return this.documents.getSnapshot().detail!;}
   await this.documents.adopt(actual);if(this.closed)throw Error('Detail is retired');if(!this.bindings)this.createRegions(actual);this.sync();
   // Full index/list assurance is independent of which auxiliary tab is open.
   if(this.supported&&!await this.bindings!.comments.comments.refresh(this.bindings!.comments.comments.getSnapshot().page,true))throw Error('正文评论标记暂时无法读取，已确认正文仍保留');return actual;
  })().catch(error=>{this.publish({error:error instanceof Error?error.message:'实际详情无法展示'});throw error;}).finally(()=>{if(this.refreshing===pending){this.refreshing=null;this.publish({loading:this.read.getSnapshot().loading,ready:!!this.bindings&&this.supported&&this.read.writeReady&&this.documents.writeReady&&!this.value.error});}});this.refreshing=pending;this.sync();return pending;
 };
 async readPanel(tab:DetailTab,signal:AbortSignal):Promise<void>{const regions=this.bindings;if(!regions||!this.supported||signal.aborted)throw Error('Panel is unavailable');
  if(tab==='AI'){if(this.documents.historical)return;await regions.conversation.refresh();}
  else if(tab==='COMMENTS'){if(this.documents.historical)return;if(!await regions.comments.comments.refresh())throw Error('实际评论暂时无法读取');}
  else if(!await this.documents.revisions.refresh())throw Error('实际版本记录暂时无法读取');
 }
 openComments=():void=>{if(this.supported){this.bindings?.layout.openTab('COMMENTS');this.sync();}};
 async openHistory(summary:RevisionSummary):Promise<void>{if(!this.supported)return;this.bindings!.layout.openTab('REVISIONS');await this.documents.openHistory(summary);this.sync();}
 async savedRevision(receipt:RevisionSummary):Promise<void>{if(receipt.requirement_id!==this.value.detail?.requirement.id)throw TypeError('Owned revision required');if(!await this.documents.revisions.refresh())throw Error('实际版本记录暂时无法读取');
  if(this.closed)return;const actual=await this.refresh();this.toasts.push('success',`版本 V${receipt.version_no} 已保存`);
  const previous=this.value.revisionSave;if(previous?.getSnapshot().receipt?.id===receipt.id){previous.dispose();this.publish({revisionSave:detailPermissions(actual,true).revision_save?new RequirementRevisionSave(actual,this.api):null});}
 }
 retire():Promise<void>{if(this.retiring)return this.retiring;this.closed=true;for(const release of this.releases)release();this.departure.dispose();this.bindings?.viewport.dispose();this.bindings?.header.dispose();this.bindings?.conversation.dispose();this.bindings?.comments.dispose();this.value.revisionSave?.dispose();this.read.dispose();this.toasts.dispose();this.listeners.clear();this.retiring=this.documents.retire();return this.retiring;}
}
