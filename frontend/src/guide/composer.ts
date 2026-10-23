import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {ApiAction,CreateGuide,WalleApi} from '../api/walle.ts';
import type {GuideRun,Message,RunReceipt} from '../api/models.ts';
import {operations,sourceRef,wireScope,runReceipt,scope as decodeScope} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {ordinaryInput} from '../shared/text.ts';
import {ComposerDrafts} from './composer-drafts.ts';
import type {GuideTarget} from './scope.ts';
type Operation=CreateGuide['operation'];
type NewTarget=Extract<NonNullable<CreateGuide['target']>,{kind:'NEW'}>;
type Submitted=Readonly<{kind:'CREATE';body:CreateGuide;raw:string}|{kind:'CONTINUE';parent:GuideRun;instruction:string;version:number;raw:string}>;
export type ComposerState=Readonly<{detail:DetailSnapshot;action:Operation;target:GuideTarget|null;new_target:NewTarget;source_refs:CreateGuide['source_refs'];
 review:GuideRun|null;parent:GuideRun|null;instruction:string;draft_warning:string|null;available:boolean;
 phase:'READY'|'ERROR'|'SUBMITTING'|'UNKNOWN'|'READING'|'CONFIRMED';submitted:Submitted|null;outcome:RunReceipt|null;user_message:Message|null;
 error:string|null;error_code:string|null;needs_refresh:boolean;refreshing:boolean;active:boolean;binding_loaded:boolean;
 observed:Readonly<{detail:DetailSnapshot;run:GuideRun|null;messages:readonly Message[]}>|null}>;
type Api=Pick<WalleApi,'prepareCreateGuide'|'prepareContinueGuide'|'getGuideRun'|'listMessages'|'getRequirementDetail'>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const conflicts=new Set(['STATE_CONFLICT','WORK_STATE_CONFLICT','WORK_STATE_INCONSISTENT','DISCUSSION_VERSION_CONFLICT','CONTENT_VERSION_CONFLICT','SOURCE_VERSION_CONFLICT','SOURCE_INVALID','SCOPE_INVALID']);
/** One explicit operation, independent of reading selection. A receipt ends
 * the send intention; all later work is actual reads, never another Chat. */
export class RequirementGuideComposer{
 private value:ComposerState;private readonly api:Api;private readonly drafts:ComposerDrafts;
 private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;
 private readonly receive:(run:Pick<GuideRun,'id'|'requirement_id'>)=>Promise<void>;private readonly refreshMessages:()=>Promise<void>;
 private command:ApiAction<RunReceipt>|undefined;private pending:Promise<boolean>|undefined;private work:string|undefined;
 private readonly listeners=new Set<()=>void>();private closed=false;private epoch=0;private controller:AbortController|undefined;private delivered=false;private configured=false;
 constructor(detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,receive:(run:Pick<GuideRun,'id'|'requirement_id'>)=>Promise<void>,refreshMessages:()=>Promise<void>,drafts=new ComposerDrafts()){
  this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;this.receive=receive;this.refreshMessages=refreshMessages;this.drafts=drafts;
  const draft=drafts.load(detail.requirement.id);
  this.value=Object.freeze({detail:capture(detail),action:'DISCUSS',target:null,new_target:{kind:'NEW' as const,name:'',document_kind:'brief' as const,template_ref:null},source_refs:[],review:null,parent:null,
   instruction:draft.instruction,draft_warning:draft.warning,available:false,phase:'READY',submitted:null,outcome:null,user_message:null,error:null,error_code:null,needs_refresh:false,
   refreshing:false,active:true,binding_loaded:false,observed:null});
 }
 getSnapshot=():ComposerState=>this.value;
 subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<ComposerState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E composer observer failed',error);}}
 get editable():boolean{return !this.closed&&!this.pending&&['READY','ERROR'].includes(this.value.phase);}
 get allowed():boolean{
  const state=this.value;if(this.closed||!state.available||state.needs_refresh||state.refreshing||state.detail.requirement.document_work_state!=='IDLE')return false;
  if(state.parent!==null)return true;
  if(state.action==='GENERATE')return [...state.new_target.name.trim()].length>0&&[...state.new_target.name].length<=80;
  const target=state.target;
  if(target!==null){const actual=state.detail.documents.find(document=>document.id===target.document_id);if(!actual||actual.content_version!==target.content_version)return false;
   if(['REVISE','PROPOSE_CHANGES'].includes(state.action)&&actual.archived_at!==null)return false;}
  return ['REVISE','PROPOSE_CHANGES'].includes(state.action)?target!==null:['COMPARE','REVIEW'].includes(state.action)?target!==null||state.source_refs.length>0:true;
 }
 adopt(detail:DetailSnapshot):void{if(detail.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual detail required');this.publish({detail:capture(detail)});}
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.epoch++;this.publish({available});if(!available)this.controller?.abort();}
 change(instruction:string):void{if(this.editable)this.publish({instruction,draft_warning:this.drafts.save(this.value.detail.requirement.id,instruction),error:null,error_code:null});}
 choose(action:Operation):void{if(this.editable&&operations.includes(action)){this.configured=true;this.publish({action,parent:null,review:null,error:null,error_code:null});}}
 configureNew(name:string,kind:NewTarget['document_kind'],framework:boolean):void{if(this.editable){this.configured=true;this.publish({new_target:{kind:'NEW',name,document_kind:kind,template_ref:framework?{key:'structure.'+kind,version:'v1'}:null}});}}
 chooseReferences(identities:readonly number[]):void{if(!this.editable)return;this.configured=true;const refs=identities.map(identity=>{const document=this.value.detail.documents.find(item=>item.id===identity);if(!document)throw TypeError('Actual source document required');return sourceRef({kind:'REVISION',document_id:identity,revision_id:document.current_revision_id,block_ids:null});});
  this.publish({source_refs:[...this.value.source_refs.filter(ref=>ref.kind!=='REVISION'),...refs],error:null,error_code:null});}
 selectDocument(identity:number|null):void{if(!this.editable)return;this.configured=true;if(identity===null){this.publish({target:null});return;}
  const document=this.value.detail.documents.find(item=>item.id===identity);if(!document)throw TypeError('Actual target document required');
  this.publish({target:{document_id:identity,content_version:document.content_version,label:document.name,scope:{scope_type:'DOCUMENT',scope_ref:null},selection:null},error:null,error_code:null});}
 select(target:GuideTarget):boolean{if(!this.editable)return false;try{const current=this.value.detail.current;
   if(current===null||target.document_id!==current.id||target.content_version!==current.content_version)throw Error('Stale scope');decodeScope(target.scope);
   this.configured=true;this.publish({target:capture(target),error:null,error_code:null});return true;
  }catch{this.rejectScope();return false;}}
 rejectScope():void{if(this.editable)this.publish({error:'范围无法定位，请重新选择；原输入仍保留。',error_code:'SCOPE_INVALID'});}
 useReview(run:GuideRun,target:GuideTarget):boolean{if(!this.editable||run.requirement_id!==this.value.detail.requirement.id||run.action_type!=='REVIEW'||run.status!=='COMPLETED'||!this.select(target))return false;
  this.publish({action:'REVISE',parent:null,review:capture(run),source_refs:[...this.value.source_refs.filter(ref=>ref.kind!=='RUN_RESULT'),sourceRef({kind:'RUN_RESULT',guide_run_id:run.id})]});return true;}
 continueFrom(run:GuideRun|null):void{if(!this.editable)return;if(run&&(run.requirement_id!==this.value.detail.requirement.id||run.status==='RUNNING'))throw TypeError('Owned ended parent required');this.configured=true;this.publish({parent:run?capture(run):null,action:'DISCUSS'});}
 async loadBinding():Promise<boolean>{if(!this.editable||this.configured||this.value.binding_loaded)return false;
  const controller=new AbortController();this.controller=controller;const epoch=this.epoch;
  try{const actual=(await this.api.getRequirementDetail(this.value.detail.requirement.id,controller.signal,true)).data;
   if(this.closed||epoch!==this.epoch||this.configured)return false;
   if(actual.requirement.discussion_version!==this.value.detail.requirement.discussion_version||actual.discussion===null)throw Error('Discussion changed');
   const binding=snapshotObject(actual.discussion.binding),targetId=binding.target_document_id;
   if(targetId!==null){if(typeof targetId!=='number')throw Error('Invalid target');this.selectDocument(targetId);
    if(binding.scope!==null&&this.value.target){this.publish({target:{...this.value.target,scope:wireScope(binding.scope)}});}}
   const refs=binding.source_refs;if(!Array.isArray(refs))throw Error('Invalid sources');this.publish({source_refs:refs.map(sourceRef),binding_loaded:true});return true;
  }catch{if(!this.closed&&epoch===this.epoch)this.publish({error:'讨论绑定暂时无法读取，请重新读取状态；当前输入保留。',needs_refresh:true});return false;
  }finally{if(this.controller===controller)this.controller=undefined;}
 }
 private enqueue(kind:string,job:()=>Promise<boolean>):Promise<boolean>{if(this.closed)return Promise.resolve(false);if(this.pending)return this.work===kind?this.pending:Promise.resolve(false);
  const pending=Promise.resolve().then(job).finally(()=>{if(this.pending===pending){this.pending=undefined;this.publish({});}});this.pending=pending;this.work=kind;return pending;}
 submit():Promise<boolean>{if(!['READY','ERROR'].includes(this.value.phase))return Promise.resolve(false);return this.enqueue('SEND',async()=>{
  if(!this.allowed){this.publish({phase:'ERROR',error:'请核对讨论版本、工作占用及明确目标。'});return false;}
  try{const state=this.value;ordinaryInput(state.instruction,'AI 指令',1,10000);if([...state.instruction].length>10000)throw Error('消息不能超过10000字符');this.delivered=false;
   if(state.parent){this.publish({submitted:capture({kind:'CONTINUE',parent:state.parent,instruction:state.instruction,version:state.detail.requirement.discussion_version,raw:state.instruction}),outcome:null});
    this.command=this.api.prepareContinueGuide(state.parent.id,state.instruction,state.detail.requirement.discussion_version);}
   else{const scope=state.target?.scope;const wire=scope===undefined?null:scope.scope_type==='SECTION'?{scope_type:'SECTION',scope_ref:{heading_block_id:scope.scope_ref.block_id}}:scope;
    const body:CreateGuide={expected_discussion_version:state.detail.requirement.discussion_version,operation:state.action,instruction:state.instruction,
     target:state.action==='GENERATE'?state.new_target:state.target===null?null:{kind:'EXISTING',document_id:state.target.document_id,expected_content_version:state.target.content_version},
     scope:state.action==='GENERATE'?null:wire,source_refs:state.source_refs,proposal_ref:null,acknowledge_source_changes:false};
    this.publish({submitted:capture({kind:'CREATE',body,raw:state.instruction}),outcome:null});this.command=this.api.prepareCreateGuide(state.detail.requirement.id,body);}
  }catch(error){this.publish({phase:'ERROR',error:error instanceof Error?error.message:'无法准备发送。',error_code:'INVALID_INPUT'});return false;}
  return await this.send()?this.finishWork():false;
 });}
 private async send():Promise<boolean>{this.publish({phase:'SUBMITTING',error:null,error_code:null});try{
  const receipt=runReceipt((await this.command!.submit()).data);if(this.closed)return false;this.command=undefined;
  this.publish({phase:'CONFIRMED',outcome:capture(receipt),draft_warning:this.drafts.clear(this.value.detail.requirement.id)});return true;
 }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.command=undefined;this.publish({phase:'ERROR',error:error.message,error_code:error.code,needs_refresh:conflicts.has(error.code)});}else this.publish({phase:'UNKNOWN',error:'发送结果待核实，原请求与输入已保留。'});return false;}}
 private async observe(){const epoch=this.epoch,controller=new AbortController(),alive=()=>!this.closed&&epoch===this.epoch&&this.value.available;this.controller=controller;try{
   if(!alive())throw Error('View hidden');const detail=await this.readActual();
   if(!alive())throw Error('View hidden');if(detail.requirement.id!==this.value.detail.requirement.id)throw Error('Foreign actual requirement');
   const messages=(await this.api.listMessages(detail.requirement.id,null,controller.signal)).data.items;
   if(!alive())throw Error('View hidden');if(messages.some(message=>message.requirement_id!==detail.requirement.id))throw Error('Foreign actual message');
   return capture({detail,run:null,messages});}finally{if(this.controller===controller)this.controller=undefined;}}
 recover():Promise<boolean>{if(this.value.phase!=='UNKNOWN'||!this.command||!this.value.available)return Promise.resolve(false);return this.enqueue('RECOVER',async()=>{
  this.publish({phase:'READING',error:null});try{this.publish({observed:await this.observe()});}catch{this.publish({phase:'UNKNOWN',error:'实际资源暂时无法读取，原请求和输入仍保留。'});return false;}
  return await this.send()?this.finishWork():false;
 });}
 refresh():Promise<boolean>{if(!this.value.available||!['READY','ERROR'].includes(this.value.phase))return Promise.resolve(false);return this.enqueue('REFRESH',async()=>{
  this.publish({refreshing:true});try{const observed=await this.observe();await this.adoptActual(observed.detail);this.publish({detail:observed.detail,observed,needs_refresh:false,error:null,error_code:null});return true;}catch{this.publish({error:'实际状态暂时无法读取，输入与配置仍保留。'});return false;}finally{this.publish({refreshing:false});}
 });}
 finish():Promise<boolean>{if(this.value.phase!=='CONFIRMED'||!this.value.available)return Promise.resolve(false);return this.enqueue('FINISH',()=>this.finishWork());}
 private async finishWork():Promise<boolean>{const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;this.publish({refreshing:true});try{
  if(!alive())throw Error('消息已接受，恢复面板后读取实际结果。');const receipt=this.value.outcome!,submitted=this.value.submitted!;
  const run=(await this.api.getGuideRun(receipt.guide_run_id)).data;if(!alive())throw Error('View hidden');
  if(run.requirement_id!==this.value.detail.requirement.id||submitted.kind==='CONTINUE'&&run.parent_guide_run_id!==submitted.parent.id||submitted.kind==='CREATE'&&run.operation!==submitted.body.operation)throw Error('运行与原操作不一致。');
  if(!this.delivered){await this.receive(run);this.delivered=true;}if(!alive())throw Error('View hidden');const actual=await this.readActual();if(!alive())throw Error('View hidden');await this.adoptActual(actual);await this.refreshMessages();if(!alive())throw Error('View hidden');
  this.publish({detail:capture(actual),phase:'READY',instruction:'',submitted:null,outcome:null,user_message:null,parent:null,observed:null,error:null,error_code:null,needs_refresh:false});return true;
 }catch(error){this.publish({error:error instanceof Error?error.message:'已接受发送，实际资源暂时无法读取。'});return false;}finally{this.publish({refreshing:false});}}
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.epoch++;this.controller?.abort();this.listeners.clear();}
}
