import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {ApiAction,CreateGuide,WalleApi} from '../api/walle.ts';
import type {GuideRun,Message} from '../api/models.ts';
import {scope as decodeScope} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {detailPermissions} from '../requirements/permissions.ts';
import {ordinaryInput} from '../shared/text.ts';
import {documentTarget} from './scope.ts';
import type {GuideTarget} from './scope.ts';
type Accepted=Awaited<ReturnType<ReturnType<WalleApi['prepareContinueGuide']>['submit']>>['data'];
type Created=Awaited<ReturnType<ReturnType<WalleApi['prepareCreateGuide']>['submit']>>['data'];
type Submitted=Readonly<{kind:'CREATE';body:CreateGuide;raw:string}|{kind:'CONTINUE';run:GuideRun;instruction:string;raw:string}>;
export type ComposerState=Readonly<{detail:DetailSnapshot;action:CreateGuide['action_type'];target:GuideTarget;review:GuideRun|null;instruction:string;available:boolean;phase:'READY'|'ERROR'|'SUBMITTING'|'UNKNOWN'|'READING'|'CONFIRMED';submitted:Submitted|null;outcome:Accepted|null;user_message:Message|null;error:string|null;error_code:string|null;needs_refresh:boolean;refreshing:boolean;active:boolean;observed:Readonly<{detail:DetailSnapshot;run:GuideRun|null;messages:readonly Message[]}>|null}>;
type Api=Pick<WalleApi,'prepareCreateGuide'|'prepareContinueGuide'|'getGuideRun'|'listMessages'>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const conflicts=new Set(['STATE_CONFLICT','WORK_STATE_CONFLICT','WORK_STATE_INCONSISTENT','CONTENT_VERSION_CONFLICT','SOURCE_INVALID','SCOPE_INVALID']);

/** Unsubmitted text is local state, never a ConversationMessage. One immutable
 * explicit send survives hidden controls and UNKNOWN; recovery cannot choose
 * a new Run, current version, scope, text, action or key for the old request. */
export class RequirementGuideComposer{
 private value:ComposerState;private readonly api:Api;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly receive:(run:Accepted)=>Promise<void>;private readonly refreshMessages:()=>Promise<void>;
 private action:ApiAction<Accepted>|ApiAction<Created>|undefined;private listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private work:'SEND'|'RECOVER'|'FINISH'|'REFRESH'|undefined;private closed=false;private epoch=0;private controller:AbortController|undefined;private delivered=false;
 constructor(detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,receive:(run:Accepted)=>Promise<void>,refreshMessages:()=>Promise<void>){
  this.assertDetail(detail);this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;this.receive=receive;this.refreshMessages=refreshMessages;
  this.value=Object.freeze({detail:capture(detail),action:detail.requirement.status==='INITIALIZING'?'INITIALIZE':'ASK',target:documentTarget(detail.current),review:null,instruction:'',available:false,phase:'READY',submitted:null,outcome:null,user_message:null,error:null,error_code:null,needs_refresh:false,refreshing:false,active:true,observed:null});
 }
 private assertDetail(detail:DetailSnapshot):void{if(detail.current.document_type!=='CURRENT'||detail.current.requirement_id!==detail.requirement.id)throw TypeError('Owned actual CURRENT required');}
 getSnapshot=():ComposerState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<ComposerState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E AI composer observer failed',error);}}
 get editable():boolean{return !this.closed&&!this.pending&&['READY','ERROR'].includes(this.value.phase);}
 get waiting():GuideRun|null{const {detail}=this.value,activity=detail.activity;return activity.kind==='GUIDE'&&activity.run.status==='WAITING_USER'&&activity.run.action_type!=='INITIALIZE'&&detail.requirement.document_work_state==='GUIDE_ACTIVE'&&detail.requirement.active_operation_type==='GUIDE_RUN'&&detail.requirement.active_operation_id===activity.run.id?activity.run:null;}
 get allowed():boolean{
  if(this.closed||!this.value.available||this.value.needs_refresh)return false;if(this.waiting)return true;
  const permissions=detailPermissions(this.value.detail,true);return ({INITIALIZE:permissions.initialize,ASK:permissions.ask,REVIEW:permissions.review,MODIFY:permissions.modify})[this.value.action]&&this.value.target.document_id===this.value.detail.current.id&&this.value.target.content_version===this.value.detail.current.content_version;
 }
 adopt(detail:DetailSnapshot):void{if(this.closed)return;this.assertDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual detail required');this.publish({detail:capture(detail)});}
 /** Visibility/supported viewport/current-view lifetime, not a transient
  * parent's adoption busy flag. The view disables inputs during that busy work
  * without invalidating this command's own confirmed resource reconciliation. */
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.epoch++;this.publish({available});if(!available)this.controller?.abort();}
 change(instruction:string):void{if(this.editable)this.publish({instruction,error:null,error_code:null});}
 choose(action:CreateGuide['action_type']):void{if(this.editable&&!this.waiting&&['INITIALIZE','ASK','REVIEW','MODIFY'].includes(action))this.publish({action,review:null,error:null,error_code:null});}
 select(target:GuideTarget):boolean{
  if(!this.editable||this.waiting)return false;try{this.assertTarget(target);this.publish({target:capture(target),error:null,error_code:null});return true;}catch{this.rejectScope();return false;}
 }
 rejectScope():void{if(this.editable)this.publish({error:'范围不属于当前正式正文或无法定位，请重新选择；输入仍保留',error_code:'SCOPE_INVALID'});}
 private assertTarget(target:GuideTarget):void{
  const current=this.value.detail.current;if(target.document_id!==current.id||target.content_version!==current.content_version)throw Error('Stale scope');const scope=decodeScope(target.scope);
  if(scope.scope_type!=='DOCUMENT'){const block=current.block_state_json.blocks.find(row=>row.block_id===scope.scope_ref.block_id);if(!block||scope.scope_type==='SECTION'&&block.block_type!=='heading')throw Error('Actual scope block required');}
  if(scope.scope_type==='SELECTION'){const selected=target.selection,ref=scope.scope_ref;if(!selected||selected.document_id!==current.id||selected.content_version!==current.content_version||selected.block_id!==ref.block_id||selected.selected_text!==ref.selected_text||selected.prefix_text!==ref.prefix_text||selected.suffix_text!==ref.suffix_text)throw Error('Actual current selection required');}
 }
 useReview(run:GuideRun,target:GuideTarget):boolean{
  if(!this.editable||this.waiting)return false;try{if(run.requirement_id!==this.value.detail.requirement.id||run.status!=='COMPLETED'||run.action_type!=='REVIEW'||!run.final_result)throw Error('Completed owned REVIEW required');this.assertTarget(target);this.publish({action:'MODIFY',review:capture(run),target:capture(target),error:null,error_code:null});return true;}
  catch{this.publish({error:'来源检查或范围已失效，请重新读取并选择；输入仍保留',error_code:'SOURCE_INVALID'});return false;}
 }
 private enqueue(kind:NonNullable<RequirementGuideComposer['work']>,job:()=>Promise<boolean>):Promise<boolean>{if(this.closed)return Promise.resolve(false);if(this.pending)return this.work===kind?this.pending:Promise.resolve(false);const pending=Promise.resolve().then(()=>this.closed?false:job()).finally(()=>{if(this.pending===pending){this.pending=undefined;this.publish({});}});this.pending=pending;this.work=kind;return pending;}
 submit():Promise<boolean>{
  if(!['READY','ERROR'].includes(this.value.phase)&&!(this.pending&&this.work==='SEND'))return Promise.resolve(false);
  return this.enqueue('SEND',async()=>{
   if(!this.allowed){this.publish({phase:'ERROR',error:'当前状态或正文范围不允许发送，请重新读取并确认',error_code:'STATE_CONFLICT'});return false;}
   try{const instruction=ordinaryInput(this.value.instruction,'AI 指令',1,10000),waiting=this.waiting;this.delivered=false;
    if(waiting){this.publish({submitted:capture({kind:'CONTINUE',run:waiting,instruction,raw:this.value.instruction}),outcome:null,user_message:null,observed:null});this.action=this.api.prepareContinueGuide(waiting.id,instruction);}
    else{this.assertTarget(this.value.target);const body:CreateGuide={expected_version:this.value.detail.current.content_version,action_type:this.value.action,instruction,scope_type:this.value.target.scope.scope_type,scope_ref:this.value.target.scope.scope_ref,source_type:this.value.review?'REVIEW_RESULT':'USER_INSTRUCTION',source_id:this.value.review?.id??null};this.publish({submitted:capture({kind:'CREATE',body,raw:this.value.instruction}),outcome:null,user_message:null,observed:null});this.action=this.api.prepareCreateGuide(this.value.detail.requirement.id,body);}
   }catch(error){this.publish({phase:'ERROR',error:error instanceof Error?error.message:'无法准备本次发送',error_code:'INVALID_INPUT'});return false;}
   return await this.send()?this.finishWork():false;
  });
 }
 private async send():Promise<boolean>{
  this.publish({phase:'SUBMITTING',error:null,error_code:null});
  try{const receipt=(await this.action!.submit()).data;if(this.closed)return false;const submitted=this.value.submitted!,created=submitted.kind==='CREATE'?receipt as Created:null,run=created?.guide_run??receipt as Accepted;
   if(run.requirement_id!==this.value.detail.requirement.id||run.status!=='RUNNING'||run.current_step!=='PREPARING'||submitted.kind==='CONTINUE'&&run.id!==submitted.run.id)throw Error('Unconfirmed actual Run receipt');
   if(created){const message=created.user_message;if(message.requirement_id!==run.requirement_id||message.guide_run_id!==run.id||message.role!=='USER'||message.message_type!=='TEXT'||message.content!==(submitted as Extract<Submitted,{kind:'CREATE'}>).body.instruction)throw Error('Unconfirmed actual USER message');}
   this.publish({phase:'CONFIRMED',outcome:capture(run),user_message:created?capture(created.user_message):null});this.action=undefined;return true;
  }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message,error_code:error.code,needs_refresh:conflicts.has(error.code)});}else this.publish({phase:'UNKNOWN',error:'发送结果待核实，输入与原请求已保留'});return false;}
 }
 private async observe():Promise<NonNullable<ComposerState['observed']>>{
  const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;if(!alive())throw Error('AI 输入已隐藏或暂停');const controller=new AbortController();this.controller=controller;
  try{const detail=await this.readActual();if(!alive())throw Error('Observation hidden');this.assertDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw Error('Ownership');const original=this.value.submitted?.kind==='CONTINUE'?this.value.submitted.run:null;
   const [run,messages]=await Promise.all([original?this.api.getGuideRun(original.id,controller.signal):Promise.resolve(null),this.api.listMessages(detail.requirement.id,null,controller.signal)]);if(!alive())throw Error('Observation hidden');
   if(run&&(run.data.id!==original!.id||run.data.requirement_id!==detail.requirement.id)||messages.data.items.some(row=>row.requirement_id!==detail.requirement.id))throw Error('Ownership');return capture({detail,run:run?.data??null,messages:messages.data.items});
  }finally{if(this.controller===controller)this.controller=undefined;}
 }
 recover():Promise<boolean>{if(this.value.phase!=='UNKNOWN'||!this.action||!this.value.available)return Promise.resolve(false);return this.enqueue('RECOVER',async()=>{this.publish({phase:'READING',error:null});try{const observed=await this.observe();this.publish({observed});}catch{this.publish({phase:'UNKNOWN',error:'实际资源暂时无法读取，未重发；输入与原请求已保留'});return false;}return await this.send()?this.finishWork():false;});}
 refresh():Promise<boolean>{if(!this.value.available||!['READY','ERROR'].includes(this.value.phase))return Promise.resolve(false);return this.enqueue('REFRESH',async()=>{const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;this.publish({refreshing:true});try{const observed=await this.observe();if(!alive())return false;await this.adoptActual(observed.detail);if(!alive())return false;this.adopt(observed.detail);this.publish({observed,needs_refresh:false,error:null,error_code:null});return true;}catch{this.publish({error:'暂时无法读取实际详情，输入与原范围仍保留'});return false;}finally{this.publish({refreshing:false});}});}
 finish():Promise<boolean>{if(this.value.phase!=='CONFIRMED'||!this.value.available)return Promise.resolve(false);return this.enqueue('FINISH',()=>this.finishWork());}
 private async finishWork():Promise<boolean>{
  const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;this.publish({refreshing:true});
  try{if(!alive())throw Error('已接受发送，恢复面板后重读实际状态');if(!this.delivered){await this.receive(this.value.outcome!);if(this.closed)return false;this.delivered=true;}if(!alive())throw Error('已接受发送，恢复面板后重读实际状态');const detail=await this.readActual();if(!alive())throw Error('AI 输入已隐藏');this.assertDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw Error('Ownership');await this.adoptActual(detail);if(!alive())throw Error('AI 输入已隐藏');await this.refreshMessages();if(!alive())throw Error('AI 输入已隐藏');
   this.publish({detail:capture(detail),phase:'READY',instruction:'',submitted:null,outcome:null,user_message:null,observed:null,error:null,error_code:null,needs_refresh:false});return true;
  }catch(error){this.publish({error:error instanceof Error?error.message:'已接受发送，实际资源暂时无法读取，请重试读取'});return false;}finally{this.publish({refreshing:false});}
 }
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.epoch++;this.controller?.abort();this.listeners.clear();}
}
