import {positiveInteger,snapshotObject} from '../api/client.ts';
import type {GuideRun,GuideSummary} from '../api/models.ts';
import type {WalleApi} from '../api/walle.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {RequirementMessages} from '../messages/read.ts';
import {RequirementRunHistory} from './history.ts';
import {GuideRunPolling} from './polling.ts';
import type {PollClock} from './polling.ts';
type RunIdentity=Readonly<{id:number;requirement_id:number}>;
type Api=Pick<WalleApi,'getGuideRun'|'listGuideRuns'|'listMessages'>;
export type AiReadState=Readonly<{detail:DetailSnapshot;selected:number|null;selection:'ACTIVITY'|'ACCEPTED'|'HISTORY'|null;run:GuideRun|null;querying:boolean;connection_error:boolean;polling:boolean;visible:boolean;refreshing:boolean;error:string|null;active:boolean}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const changes=(run:GuideRun)=>JSON.stringify([run.status,run.latest_assistant_message_id,run.suggestion_batch_id,run.final_result]);

/** A real AI read lifetime and idempotent acceptance receiver. Acceptance
 * only selects/opens a Run and installs its real I16 polling; it never creates
 * a message or invents the final status from the accepted HTTP receipt. */
export class RequirementAiRead{
 readonly messages:RequirementMessages;readonly history:RequirementRunHistory;
 private readonly api:Api;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly openPanel:()=>void|Promise<void>;private readonly timing:PollClock|undefined;
 private value:AiReadState;private readonly listeners=new Set<()=>void>();private poll:GuideRunPolling|undefined;private releasePoll:(()=>void)|undefined;private pollSignature:string|null=null;private generation=0;private visibilityGeneration=0;private closed=false;private pending:Promise<void>|undefined;private dirty=false;
 constructor(detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,openPanel:()=>void|Promise<void>,timing?:PollClock){
  positiveInteger(detail.requirement.id);if(detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Owned actual detail required');
  this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;this.openPanel=openPanel;this.timing=timing;this.messages=new RequirementMessages(detail.requirement.id,api);this.history=new RequirementRunHistory(detail.requirement.id,api);
  this.value=Object.freeze({detail:capture(detail),selected:null,selection:null,run:null,querying:false,connection_error:false,polling:false,visible:false,refreshing:false,error:null,active:true});
  if(detail.activity.kind==='GUIDE')this.select(detail.activity.run,'ACTIVITY',detail.activity.run);
  else if(detail.activity.kind==='BATCH')this.select({id:detail.activity.batch.guide_run_id,requirement_id:detail.requirement.id},'ACTIVITY');
 }
 getSnapshot=():AiReadState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<AiReadState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E AI read observer failed',error);}}
 private owned(run:RunIdentity):void{positiveInteger(run.id);if(run.requirement_id!==this.value.detail.requirement.id)throw TypeError('Run belongs to another requirement');}
 adopt(actual:DetailSnapshot):void{
  if(this.closed)return;if(actual.requirement.id!==this.value.detail.requirement.id||actual.current.requirement_id!==actual.requirement.id||actual.current.document_type!=='CURRENT')throw TypeError('Owned actual detail required');
  this.publish({detail:capture(actual)});if(actual.activity.kind==='GUIDE'&&this.value.selection!=='HISTORY')this.select(actual.activity.run,'ACTIVITY',actual.activity.run);
  else if(actual.activity.kind==='BATCH'&&this.value.selection!=='HISTORY')this.select({id:actual.activity.batch.guide_run_id,requirement_id:actual.requirement.id},'ACTIVITY');
 }
 private select(run:RunIdentity,kind:NonNullable<AiReadState['selection']>,actual?:GuideRun):void{
  this.owned(run);if(this.closed)return;
  if(this.value.selected===run.id&&this.poll){this.publish({selection:kind});return;}
  this.releasePoll?.();this.poll?.dispose();const generation=++this.generation;this.pollSignature=null;
  this.publish({selected:run.id,selection:kind,run:actual?capture(actual):null,querying:false,connection_error:false,polling:false});
  const poll=new GuideRunPolling(run.id,async(id,signal)=>{const observed=(await this.api.getGuideRun(id,signal)).data;this.owned(observed);return observed;},this.timing);this.poll=poll;
  this.releasePoll=poll.subscribe(state=>{
   if(this.closed||generation!==this.generation)return;this.publish({...(state.confirmed?{run:capture(state.confirmed)}:{}),querying:state.querying,connection_error:state.connection_error,polling:state.polling});
   if(state.confirmed){const signature=changes(state.confirmed);if(signature!==this.pollSignature){this.pollSignature=signature;if(this.value.visible){this.dirty=true;void this.refresh().catch(()=>undefined);}}}
  });poll.setVisible(this.value.visible);
 }
 /** Safe to replay the same acknowledged receipt: layout opening and selected
  * identity are idempotent, with only one selected Run polling lifetime. */
 receive=async(run:RunIdentity):Promise<void>=>{this.owned(run);if(this.closed)throw Error('AI view is retired');await this.openPanel();if(this.closed)throw Error('AI view is retired');const resume=this.value.visible&&this.value.selected===run.id&&this.value.run?.status==='WAITING_USER';this.select(run,'ACCEPTED');this.setVisible(true);if(resume)this.poll?.refresh();};
 open(summary:GuideSummary):void{if(this.closed||!this.value.visible)return;this.select(summary,'HISTORY');}
 readRun():void{if(!this.closed&&this.value.visible)this.poll?.refresh();}
 setVisible(visible:boolean):void{
  if(this.closed||visible===this.value.visible)return;this.visibilityGeneration++;this.publish({visible});this.poll?.setVisible(visible);
  if(!visible){this.messages.pause();this.history.pause();}
  else{this.dirty=true;void this.refresh().catch(()=>undefined);}
 }
 refresh():Promise<void>{
  if(this.closed||!this.value.visible)return Promise.reject(Error('AI view is hidden or retired'));if(this.pending)return this.pending;
  const generation=this.visibilityGeneration,alive=()=>!this.closed&&this.value.visible&&generation===this.visibilityGeneration;
  const pending=Promise.resolve().then(async()=>{
   do{this.dirty=false;if(!alive())throw Error('AI view is hidden or retired');const actual=await this.readActual();if(!alive())throw Error('AI read was hidden');
    if(actual.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual detail required');await this.adoptActual(actual);if(!alive())throw Error('AI adoption was hidden');this.adopt(actual);
    const results=await Promise.all([this.messages.refresh(),this.history.refresh()]);if(!alive())throw Error('AI resources were hidden');if(results.some(ok=>!ok))throw Error('会话或运行记录暂时无法读取，已确认内容仍保留');
   }while(this.dirty);this.publish({error:null});
  }).catch(error=>{if(alive())this.publish({error:error instanceof Error?error.message:'实际AI状态暂时无法读取，已确认内容仍保留'});throw error;}).finally(()=>{if(this.pending===pending)this.pending=undefined;this.publish({refreshing:false});if(!this.closed&&this.value.visible&&generation!==this.visibilityGeneration)void this.refresh().catch(()=>undefined);});
  this.pending=pending;this.publish({refreshing:true});return pending;
 }
 dispose():void{if(this.closed)return;this.publish({active:false,visible:false});this.closed=true;this.generation++;this.releasePoll?.();this.poll?.dispose();this.messages.dispose();this.history.dispose();this.listeners.clear();}
}
