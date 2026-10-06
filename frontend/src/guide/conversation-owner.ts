import {snapshotObject} from '../api/client.ts';
import type {GuideRun} from '../api/models.ts';
import type {WalleApi} from '../api/walle.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {RequirementSuggestionBatch} from '../suggestions/batch-owner.ts';
import {RequirementAiRead} from './read-owner.ts';
import {RequirementGuideComposer} from './composer.ts';
import {RequirementRunActions} from './run-actions.ts';
import {RequirementCardGroups} from './card-groups.ts';
import {CardDrafts} from './card-drafts.ts';

export type ConversationState=Readonly<{detail:DetailSnapshot;visible:boolean;enabled:boolean;active:boolean;lease:string|null;batch:RequirementSuggestionBatch|null;revision:number}>;
const retained=(phase:string)=>['SUBMITTING','READING','UNKNOWN','CONFIRMED'].includes(phase);
/** One requirement's existing real owners. Ordinary text, cards and Run
 * commands share the same receiver and adoption boundary. Retained original
 * requests keep their owner through history selection, hidden views and new
 * actual activity; no refresh or competing button replaces that request. */
export class RequirementConversation{
 readonly read:RequirementAiRead;readonly composer:RequirementGuideComposer;readonly runs:RequirementRunActions;readonly cards:RequirementCardGroups;
 private value:ConversationState;private readonly listeners=new Set<()=>void>();private readonly releases:(()=>void)[]=[];private readonly batches=new Map<number,{owner:RequirementSuggestionBatch;release:()=>void}>();
 private readonly api:WalleApi;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private closed=false;private reconciling=false;private again=false;private runSignature='';private visibility=0;private batchRead='';
 constructor(detail:DetailSnapshot,api:WalleApi,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,openPanel:()=>void|Promise<void>,drafts=new CardDrafts()){
  if(detail.current.document_type!=='CURRENT'||detail.current.requirement_id!==detail.requirement.id)throw TypeError('Actual owned CURRENT required');this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;
  this.value=Object.freeze({detail:snapshotObject(detail) as unknown as DetailSnapshot,visible:false,enabled:true,active:true,lease:null,batch:null,revision:0});
  const adopt=async(actual:DetailSnapshot)=>{if(this.closed)throw Error('Conversation is retired');await this.adoptActual(actual);if(this.closed)throw Error('Conversation is retired');this.adopt(actual);};
  this.read=new RequirementAiRead(detail,api,readActual,adopt,openPanel);
  const refreshMessages=async()=>{if(!await this.read.messages.refresh())throw Error('实际消息暂时无法读取');};
  this.composer=new RequirementGuideComposer(detail,api,readActual,adopt,this.read.receive,refreshMessages);
  this.runs=new RequirementRunActions(detail,api,readActual,adopt,this.read.receive);
  this.cards=new RequirementCardGroups(this.read,api,drafts,readActual,adopt,this.read.receive,refreshMessages,owner=>this.permitted('CARD:'+owner.getSnapshot().message.id));
  for(const owner of [this.read,this.composer,this.runs,this.cards])this.releases.push(owner.subscribe(()=>this.reconcile()));this.reconcile();
 }
 getSnapshot=():ConversationState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<ConversationState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes,revision:this.value.revision+1});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E conversation observer failed',error);}}
 private permitted(key:string):boolean{return !this.closed&&this.value.visible&&this.value.enabled&&(this.value.lease===null||this.value.lease===key);}
 private protectedOwners():string[]{return [retained(this.composer.getSnapshot().phase)?'COMPOSER':null,retained(this.runs.getSnapshot().phase)?'RUN':null,...this.cards.retainedOwners().filter(owner=>retained(owner.getSnapshot().phase)).map(owner=>'CARD:'+owner.getSnapshot().message.id),...[...this.batches].filter(([,entry])=>retained(entry.owner.getSnapshot().phase)).map(([id])=>'BATCH:'+id)].filter((key):key is string=>key!==null);}
 private batchOwner(id:number):RequirementSuggestionBatch{
  const retained=this.batches.get(id);if(retained)return retained.owner;
  const owner=new RequirementSuggestionBatch(id,this.value.detail,this.api,this.readActual,async actual=>{if(this.closed)throw Error('Conversation is retired');await this.adoptActual(actual);if(this.closed)throw Error('Conversation is retired');this.adopt(actual);});
  this.batches.set(id,{owner,release:owner.subscribe(()=>this.reconcile())});return owner;
 }
 private reconcile():void{
  if(this.closed)return;if(this.reconciling){this.again=true;return;}this.reconciling=true;
  try{do{this.again=false;const protectedKeys=this.protectedOwners(),lease=this.value.lease&&protectedKeys.includes(this.value.lease)?this.value.lease:protectedKeys[0]??null;
   if(lease!==this.value.lease)this.publish({lease});const parent=this.read.getSnapshot(),signature=JSON.stringify([this.value.detail,parent.run]);if(signature!==this.runSignature){this.runSignature=signature;this.runs.adopt(this.value.detail,parent.run);}
   const active=this.value.detail.activity,previous=this.value.batch?.getSnapshot().batch,selected=lease?.startsWith('BATCH:')?Number(lease.slice(6)):active.kind==='BATCH'?active.batch.id:parent.run?.suggestion_batch_id??(parent.run===null&&parent.selected===previous?.guide_run_id?previous.id:null);
   const batch=selected===null?null:this.batchOwner(selected);if(batch!==this.value.batch)this.publish({batch});
   const view=this.value.visible&&this.value.enabled;this.read.setVisible(view);this.composer.setAvailable(this.permitted('COMPOSER'));this.runs.setAvailable(this.permitted('RUN'));this.cards.setAvailable(view);this.cards.reconcilePermissions();for(const [id,entry] of this.batches)entry.owner.setAvailable(entry.owner===batch&&this.permitted('BATCH:'+id));
   // A newly arrived batch may still be excluded by the original send lease.
   // Do not consume its first read until that actual owner can perform it.
   const key=selected===null?'':selected+':'+this.visibility;if(view&&batch&&batch.getSnapshot().available&&key!==this.batchRead){this.batchRead=key;if(['READY','ERROR'].includes(batch.getSnapshot().phase))void batch.refresh();}
  }while(this.again);this.publish({});}finally{this.reconciling=false;}
 }
 /** Transient document-adoption busy does not invalidate a command's own
  * confirmed reconciliation. The view may separately disable busy inputs. */
 setView(visible:boolean,enabled=this.value.enabled):void{if(this.closed||visible===this.value.visible&&enabled===this.value.enabled)return;this.visibility++;this.publish({visible,enabled});this.reconcile();}
 adopt(actual:DetailSnapshot):void{if(this.closed)return;if(actual.requirement.id!==this.value.detail.requirement.id||actual.current.document_type!=='CURRENT'||actual.current.requirement_id!==actual.requirement.id)throw TypeError('Actual owned detail required');
  const previous=this.reconciling;this.reconciling=true;try{this.publish({detail:snapshotObject(actual) as unknown as DetailSnapshot});this.composer.adopt(actual);this.read.adopt(actual);for(const entry of this.batches.values())entry.owner.adopt(actual);}finally{this.reconciling=previous;}if(!previous)this.reconcile();else this.again=true;
 }
 receive=(run:Pick<GuideRun,'id'|'requirement_id'>):Promise<void>=>this.read.receive(run);
 batch(identity:number):RequirementSuggestionBatch|null{return this.batches.get(identity)?.owner??null;}
 async refresh():Promise<void>{if(this.closed||!this.value.visible||!this.value.enabled)throw Error('Conversation is hidden');await this.read.refresh();const batch=this.value.batch;if(batch&&['READY','ERROR'].includes(batch.getSnapshot().phase)&&!await batch.refresh())throw Error('实际建议读取失败');}
 dispose():void{if(this.closed)return;this.publish({active:false,visible:false,enabled:false});this.closed=true;for(const release of this.releases)release();for(const entry of this.batches.values()){entry.release();entry.owner.dispose();}this.cards.dispose();this.runs.dispose();this.composer.dispose();this.read.dispose();this.listeners.clear();}
}
