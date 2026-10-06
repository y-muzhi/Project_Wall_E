import {ApiRejected,positiveInteger,snapshotObject} from '../api/client.ts';
import type {GuideRun,Message} from '../api/models.ts';
import type {ApiAction,WalleApi} from '../api/walle.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {detailPermissions} from '../requirements/permissions.ts';

export type RunOperation='CANCEL'|'RETRY';
type GuideAccepted=Awaited<ReturnType<ReturnType<WalleApi['prepareCancelGuide']>['submit']>>['data'];
export type RunActionState=Readonly<{detail:DetailSnapshot;run:GuideRun|null;available:boolean;phase:'READY'|'SUBMITTING'|'READING'|'UNKNOWN'|'ERROR'|'CONFIRMED';operation:RunOperation|null;origin:GuideRun|null;outcome:GuideAccepted|GuideRun|null;error:string|null;error_code:string|null;refreshing:boolean;observed:Readonly<{detail:DetailSnapshot;run:GuideRun;messages:readonly Message[]}>|null;active:boolean}>;
type Api=Pick<WalleApi,'getGuideRun'|'listMessages'|'prepareCancelGuide'|'prepareRetryGuide'>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const sameOrigin=(left:GuideRun,right:GuideRun)=>left.id===right.id&&left.requirement_id===right.requirement_id&&left.action_type===right.action_type&&left.function_type===right.function_type&&left.source_type===right.source_type&&left.source_id===right.source_id&&left.created_at===right.created_at&&JSON.stringify(left.scope)===JSON.stringify(right.scope);

/** One retained Run intention per requirement. Viewing another Run or hiding
 * its panel cannot change the original opaque request. GETs are observations;
 * only its positive original receipt confirms cancellation/retry acceptance. */
export class RequirementRunActions{
 private value:RunActionState;private readonly api:Api;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly receive:(run:GuideAccepted|GuideRun)=>Promise<void>;
 private action:ApiAction<GuideAccepted>|ApiAction<GuideRun>|undefined;private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private work:'SEND'|'RECOVER'|'FINISH'|'REFRESH'|undefined;private controller:AbortController|undefined;private delivered=false;private closed=false;private visibility=0;
 constructor(detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,receive:(run:GuideAccepted|GuideRun)=>Promise<void>){
  this.assertDetail(detail);this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;this.receive=receive;
  this.value=Object.freeze({detail:capture(detail),run:null,available:false,phase:'READY',operation:null,origin:null,outcome:null,error:null,error_code:null,refreshing:false,observed:null,active:true});
 }
 getSnapshot=():RunActionState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private assertDetail(detail:DetailSnapshot):void{positiveInteger(detail.requirement.id);if(detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Owned actual CURRENT required');}
 private owned(run:GuideAccepted|GuideRun):void{positiveInteger(run.id);if(run.requirement_id!==this.value.detail.requirement.id)throw TypeError('Owned actual Run required');}
 private publish(changes:Partial<RunActionState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E run action observer failed',error);}}
 adopt(detail:DetailSnapshot,run:GuideRun|null):void{if(this.closed)return;this.assertDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual detail required');if(run)this.owned(run);this.publish({detail:capture(detail),run:run?capture(run):null});}
 /** The real page owner includes supported viewport/current document mode.
  * Hiding preserves a pending write and never issues a cancel command. */
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.visibility++;this.publish({available});if(!available)this.controller?.abort();}
 allowed(operation:RunOperation):boolean{
  const {detail,run,available}=this.value;if(this.closed||!available||!run)return false;
  if(operation==='CANCEL')return ['RUNNING','WAITING_USER'].includes(run.status)&&run.current_step!=='PERSISTING'&&detail.activity.kind==='GUIDE'&&detail.activity.run.id===run.id&&detail.requirement.active_operation_type==='GUIDE_RUN'&&detail.requirement.active_operation_id===run.id&&detail.requirement.document_work_state==='GUIDE_ACTIVE';
  const permissions=detailPermissions(detail,true);return run.status==='FAILED'&&detail.activity.kind==='IDLE'&&({INITIALIZE:permissions.initialize,ASK:permissions.ask,REVIEW:permissions.review,MODIFY:permissions.modify})[run.action_type];
 }
 private enqueue(work:NonNullable<RequirementRunActions['work']>,job:()=>Promise<boolean>):Promise<boolean>{
  if(this.closed)return Promise.resolve(false);if(this.pending)return work===this.work?this.pending:Promise.resolve(false);
  const pending=Promise.resolve().then(()=>this.closed?false:job()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.work=work;return pending;
 }
 start(operation:RunOperation):Promise<boolean>{
  if(this.value.phase==='UNKNOWN'||this.value.phase==='READING'||this.value.phase==='CONFIRMED')return Promise.resolve(false);
  if(this.pending)return this.work==='SEND'&&this.value.operation===operation?this.pending:Promise.resolve(false);
  if(!this.allowed(operation))return Promise.resolve(false);
  this.publish({operation,origin:capture(this.value.run!),outcome:null,observed:null,error:null,error_code:null});this.delivered=false;
  return this.enqueue('SEND',async()=>{
   if(!this.allowed(operation)||this.value.run?.id!==this.value.origin?.id){this.publish({phase:'ERROR',error:'当前运行或需求状态已变化，请重新读取后操作',error_code:'STATE_CONFLICT'});return false;}
   try{this.action=operation==='CANCEL'?this.api.prepareCancelGuide(this.value.origin!.id):this.api.prepareRetryGuide(this.value.origin!.id);}catch{this.publish({phase:'ERROR',error:'无法准备运行操作，请重新读取实际状态',error_code:'INVALID_INPUT'});return false;}
   const ok=await this.send();return ok?this.finishWork():false;
  });
 }
 private async send():Promise<boolean>{
  this.publish({phase:'SUBMITTING',error:null,error_code:null});
  try{const receipt=(await this.action!.submit()).data;if(this.closed)return false;this.owned(receipt);const origin=this.value.origin!;
   if(this.value.operation==='CANCEL'){if(receipt.id!==origin.id||receipt.status!=='CANCELLED'||receipt.current_step!=='FINISHED')throw Error('Unconfirmed cancellation receipt');}
   else{const retry=receipt as GuideRun;if(retry.id===origin.id||retry.retry_of_guide_run_id!==origin.id||retry.status!=='RUNNING'||retry.current_step!=='PREPARING'||retry.action_type!==origin.action_type||retry.function_type!==origin.function_type||retry.source_type!==origin.source_type||retry.source_id!==origin.source_id)throw Error('Unconfirmed retry receipt');}
   this.publish({phase:'CONFIRMED',outcome:capture(receipt)});this.action=undefined;return true;
  }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message,error_code:error.code});}
   else this.publish({phase:'UNKNOWN',error:'本次运行操作结果待核实，原运行和原请求已保留'});return false;}
 }
 private async observe():Promise<Readonly<{detail:DetailSnapshot;run:GuideRun;messages:readonly Message[]}>>{
  const epoch=this.visibility,alive=()=>!this.closed&&this.value.available&&epoch===this.visibility;if(!alive())throw Error('AI 操作暂时隐藏或暂停');
  const controller=new AbortController();this.controller=controller;
  try{const detail=await this.readActual();if(!alive())throw Error('Observation was hidden');this.assertDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw Error('Ownership');
   const identity=this.value.origin?.id??this.value.run?.id;if(!identity)throw Error('Actual Run required');
   const [result,messages]=await Promise.all([this.api.getGuideRun(identity,controller.signal),this.api.listMessages(detail.requirement.id,null,controller.signal)]);if(!alive())throw Error('Observation was hidden');this.owned(result.data);
   if(result.data.id!==identity||this.value.origin&&!sameOrigin(this.value.origin,result.data)||messages.data.items.some(message=>message.requirement_id!==detail.requirement.id))throw Error('Owned immutable Run origin required');
   return capture({detail,run:result.data,messages:messages.data.items});
  }finally{if(this.controller===controller)this.controller=undefined;}
 }
 recover():Promise<boolean>{
  if(this.value.phase!=='UNKNOWN'||!this.action||!this.value.available)return Promise.resolve(false);
  return this.enqueue('RECOVER',async()=>{this.publish({phase:'READING',error:null});try{const actual=await this.observe();if(this.closed)return false;this.publish({observed:actual});}
   catch{this.publish({phase:'UNKNOWN',error:'结果仍待核实，实际资源暂时无法读取；未重发，原请求已保留'});return false;}
   const ok=await this.send();return ok?this.finishWork():false;
  });
 }
 /** Known refusal re-reads current state/phase without changing the original
  * failure record. A new explicit user action will get its own fresh key. */
 refresh():Promise<boolean>{
  if(!this.value.available||!['READY','ERROR'].includes(this.value.phase))return Promise.resolve(false);
  return this.enqueue('REFRESH',async()=>{const epoch=this.visibility,alive=()=>!this.closed&&this.value.available&&epoch===this.visibility;this.publish({refreshing:true});try{const observed=await this.observe();if(!alive())return false;await this.adoptActual(observed.detail);if(!alive())return false;this.adopt(observed.detail,observed.run);this.publish({observed,error:null,error_code:null});return true;}
   catch{this.publish({error:'暂时无法重新读取运行与需求，保留最后确认状态'});return false;}finally{this.publish({refreshing:false});}});
 }
 finish():Promise<boolean>{if(this.value.phase!=='CONFIRMED'||!this.value.available)return Promise.resolve(false);return this.enqueue('FINISH',()=>this.finishWork());}
 private async finishWork():Promise<boolean>{
  const epoch=this.visibility,alive=()=>!this.closed&&this.value.available&&epoch===this.visibility;
  this.publish({refreshing:true});try{if(!alive())throw Error('操作界面已隐藏，已确认回执仍保留');
   if(!this.delivered){await this.receive(this.value.outcome!);if(this.closed)return false;this.delivered=true;}
   if(!alive())throw Error('操作界面已隐藏，已确认回执仍保留');const actual=await this.readActual();if(!alive())throw Error('操作界面已隐藏，已确认回执仍保留');this.assertDetail(actual);if(actual.requirement.id!==this.value.detail.requirement.id)throw Error('Ownership');
   await this.adoptActual(actual);if(!alive())throw Error('操作界面已隐藏，已确认回执仍保留');this.publish({detail:capture(actual),phase:'READY',operation:null,origin:null,outcome:null,error:null,error_code:null,observed:null});return true;
  }catch(error){this.publish({error:error instanceof Error?error.message:'已确认运行操作，实际详情暂时无法读取，请重试读取'});return false;}finally{this.publish({refreshing:false});}
 }
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.visibility++;this.controller?.abort();this.listeners.clear();}
}
