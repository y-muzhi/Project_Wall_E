import {ApiRejected,positiveInteger,snapshotObject} from '../api/client.ts';
import {batch as decodeBatch} from '../api/models.ts';
import type {Batch,Suggestion} from '../api/models.ts';
import type {ApiAction,WalleApi} from '../api/walle.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import type {DocumentReadModel} from '../documents/contracts.ts';

export type Decision='ACCEPTED'|'REJECTED'|'EDITED';
type Operation='DECIDE'|'COMPLETE'|'DISCARD';
type DecisionReceipt=Awaited<ReturnType<ReturnType<WalleApi['prepareDecideSuggestion']>['submit']>>['data'];
type CompleteReceipt=Awaited<ReturnType<ReturnType<WalleApi['prepareCompleteBatch']>['submit']>>['data'];
type DiscardReceipt=Awaited<ReturnType<ReturnType<WalleApi['prepareDiscardBatch']>['submit']>>['data'];
type Receipt=DecisionReceipt|CompleteReceipt|DiscardReceipt;
type Intent=Readonly<{operation:Operation;batch:Batch;current:DocumentReadModel;suggestion:Suggestion|null;decision:Decision|null;content:string|null}>;
type Api=Pick<WalleApi,'getBatch'|'prepareDecideSuggestion'|'prepareCompleteBatch'|'prepareDiscardBatch'>;
export type SuggestionBatchState=Readonly<{detail:DetailSnapshot;batch:Batch|null;available:boolean;active:boolean;phase:'READY'|'ERROR'|'SUBMITTING'|'UNKNOWN'|'READING'|'CONFIRMED';loading:boolean;error:string|null;error_code:string|null;needs_refresh:boolean;stale:boolean;intent:Intent|null;receipt:Receipt|null;observed:Batch|null;drafts:Readonly<Record<number,string>>;item_errors:Readonly<Record<number,string>>}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const fixedBatch=(value:Pick<Batch,'id'|'requirement_id'|'guide_run_id'|'source_type'|'source_id'|'title'|'summary'|'base_content_version'|'created_at'>)=>JSON.stringify([value.id,value.requirement_id,value.guide_run_id,value.source_type,value.source_id,value.title,value.summary,value.base_content_version,value.created_at]);
const mutable=new Set(['status','user_edited_content','validation_status','validation_error','decided_at','updated_at']);
const fixedSuggestion=(value:Suggestion)=>JSON.stringify(Object.fromEntries(Object.entries(value).filter(([key])=>!mutable.has(key))));

/** One retained intention for the batch. All decisions serialize before its
 * final command, so no earlier counts or pending write can race completion.
 * Read observations never stand in for the original successful receipt. */
export class RequirementSuggestionBatch{
 get batchId():number{return this.identity;}
 private readonly identity:number;private readonly api:Api;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;
 private value:SuggestionBatchState;private readonly listeners=new Set<()=>void>();private action:ApiAction<Receipt>|undefined;private pending:Promise<boolean>|undefined;private work:string|undefined;private closed=false;private visibility=0;private controller:AbortController|undefined;
 constructor(identity:number,detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>){
  this.identity=positiveInteger(identity);this.checkDetail(detail);this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;
  this.value=Object.freeze({detail:capture(detail),batch:null,available:false,active:true,phase:'READY',loading:false,error:null,error_code:null,needs_refresh:false,stale:false,intent:null,receipt:null,observed:null,drafts:Object.freeze({}),item_errors:Object.freeze({})});
 }
 getSnapshot=():SuggestionBatchState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private checkDetail(detail:DetailSnapshot):void{positiveInteger(detail.requirement.id);if(detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Owned actual CURRENT required');}
 private checked(input:Batch,detail:DetailSnapshot):Batch{
  const result=decodeBatch(input);if(result.id!==this.identity||result.requirement_id!==detail.requirement.id)throw Error('Owned batch required');
  const previous=this.value.batch;if(previous&&(fixedBatch(previous)!==fixedBatch(result)||previous.suggestions.length!==result.suggestions.length||previous.suggestions.some((item,index)=>fixedSuggestion(item)!==fixedSuggestion(result.suggestions[index]!))))throw Error('Immutable batch targets changed');
  return capture(result);
 }
 private publish(changes:Partial<SuggestionBatchState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E suggestion observer failed',error);}}
 adopt(detail:DetailSnapshot):void{if(this.closed)return;this.checkDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual detail required');this.publish({detail:capture(detail)});}
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.visibility++;this.publish({available});if(!available)this.controller?.abort();}
 private ownedPending():boolean{const {detail,batch,available}=this.value,root=detail.requirement;return !this.closed&&available&&batch?.status==='PENDING'&&root.status==='ACTIVE'&&root.document_work_state==='SUGGESTION_REVIEWING'&&root.active_operation_type==='SUGGESTION_BATCH'&&root.active_operation_id===this.identity&&detail.activity.kind==='BATCH'&&detail.activity.batch.id===this.identity;}
 get editable():boolean{return this.ownedPending()&&!this.value.loading&&!this.value.needs_refresh&&!this.value.stale&&['READY','ERROR'].includes(this.value.phase)&&this.value.detail.current.content_version===this.value.batch!.base_content_version;}
 get canComplete():boolean{return this.editable&&this.value.batch!.counts.pending===0;}
 get canDiscard():boolean{return this.ownedPending()&&!this.value.loading&&['READY','ERROR'].includes(this.value.phase);}
 draft(identity:number,content:string):void{positiveInteger(identity);if(!this.editable||!this.value.batch?.suggestions.some(item=>item.id===identity&&item.patch_operation!=='DELETE_BLOCK'))return;this.publish({drafts:Object.freeze({...this.value.drafts,[identity]:content})});}
 private enqueue(work:string,job:()=>Promise<boolean>):Promise<boolean>{
  if(this.closed)return Promise.resolve(false);if(this.pending)return work===this.work?this.pending:Promise.resolve(false);
  const pending=Promise.resolve().then(()=>this.closed?false:job()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.work=work;return pending;
 }
 private async observe():Promise<Readonly<{detail:DetailSnapshot;batch:Batch}>>{
  const epoch=this.visibility,alive=()=>!this.closed&&this.value.available&&epoch===this.visibility;if(!alive())throw Error('Suggestion panel unavailable');const controller=new AbortController();this.controller=controller;
  try{const detail=await this.readActual();if(!alive())throw Error('Read hidden');this.checkDetail(detail);if(detail.requirement.id!==this.value.detail.requirement.id)throw Error('Ownership');
   const input=(await this.api.getBatch(this.identity,controller.signal)).data;if(!alive())throw Error('Read hidden');return {detail:capture(detail),batch:this.checked(input,detail)};
  }finally{if(this.controller===controller)this.controller=undefined;}
 }
 refresh():Promise<boolean>{
  if(!this.value.available||!['READY','ERROR'].includes(this.value.phase))return Promise.resolve(false);
  return this.enqueue('REFRESH',async()=>{const epoch=this.visibility;this.publish({loading:true});try{const actual=await this.observe();await this.adoptActual(actual.detail);if(this.closed||!this.value.available||epoch!==this.visibility)throw Error('Adoption hidden');
   this.publish({detail:actual.detail,batch:actual.batch,loading:false,error:null,error_code:null,needs_refresh:false,stale:actual.batch.status==='PENDING'&&(this.value.stale||actual.batch.base_content_version!==actual.detail.current.content_version)});return true;
  }catch{this.publish({loading:false,needs_refresh:true,error:'建议与需求读取失败，保留上次确认的批次和编辑内容，请重试'});return false;}});
 }
 decide(identity:number,decision:Decision):Promise<boolean>{
  positiveInteger(identity);if(!['ACCEPTED','REJECTED','EDITED'].includes(decision))throw TypeError('Actual decision required');if(!this.editable)return Promise.resolve(false);
  const item=this.value.batch!.suggestions.find(item=>item.id===identity);if(!item)return Promise.resolve(false);let content:string|null=null;
  if(decision==='EDITED'){
   content=this.value.drafts[identity]??item.user_edited_content??item.proposed_markdown??JSON.stringify(item.proposed_data);
   try{if(item.patch_operation==='DELETE_BLOCK'||!content||[...content].length>100000)throw Error('Invalid edit');snapshotObject({content});
    if(item.patch_operation==='REPLACE_TABLE_ROW'){const row=JSON.parse(content);if(!row||typeof row!=='object'||Array.isArray(row)||Object.keys(row).length!==1||!Array.isArray(row.cells)||row.cells.length!==item.proposed_data!.cells.length||row.cells.some((cell:unknown)=>typeof cell!=='string'))throw Error('Invalid cells');}
   }catch{this.publish({phase:'ERROR',error:'编辑内容不合法；表格行只允许原列数的 cells JSON，删除不能编辑',error_code:'INVALID_INPUT',item_errors:Object.freeze({...this.value.item_errors,[identity]:'请修正编辑内容后重试'})});return Promise.resolve(false);}
  }
  return this.start({operation:'DECIDE',batch:this.value.batch!,current:this.value.detail.current,suggestion:item,decision,content});
 }
 complete():Promise<boolean>{return this.canComplete?this.start({operation:'COMPLETE',batch:this.value.batch!,current:this.value.detail.current,suggestion:null,decision:null,content:null}):Promise.resolve(false);}
 discard():Promise<boolean>{return this.canDiscard?this.start({operation:'DISCARD',batch:this.value.batch!,current:this.value.detail.current,suggestion:null,decision:null,content:null}):Promise.resolve(false);}
 private start(intent:Intent):Promise<boolean>{
  if(this.pending)return Promise.resolve(false);this.publish({phase:'SUBMITTING',intent:capture(intent),receipt:null,observed:null,error:null,error_code:null,item_errors:Object.freeze({})});
  return this.enqueue('SEND',async()=>{if(!this.ownedPending()||this.value.loading||intent.operation!=='DISCARD'&&(this.value.needs_refresh||this.value.stale||this.value.detail.current.content_version!==intent.batch.base_content_version||intent.operation==='COMPLETE'&&this.value.batch!.counts.pending!==0)){this.publish({phase:'ERROR',error:'当前批次或显示状态已变化，未发送，请重新读取',needs_refresh:true});return false;}
   try{this.action=intent.operation==='DECIDE'?this.api.prepareDecideSuggestion(intent.suggestion!.id,{decision:intent.decision!,edited_content:intent.content}):intent.operation==='COMPLETE'?this.api.prepareCompleteBatch(this.identity,intent.batch.base_content_version):this.api.prepareDiscardBatch(this.identity);}
   catch{this.publish({phase:'ERROR',error:'无法准备建议操作，原编辑内容保留',error_code:'INVALID_INPUT'});return false;}return await this.send()?this.finishWork():false;
  });
 }
 private async send():Promise<boolean>{
  this.publish({phase:'SUBMITTING',error:null,error_code:null});try{const receipt=(await this.action!.submit()).data;if(this.closed)return false;const intent=this.value.intent!;
   if(intent.operation==='DECIDE'){const result=receipt as DecisionReceipt;if(result.suggestion.batch_id!==this.identity||result.suggestion.id!==intent.suggestion!.id||fixedSuggestion(result.suggestion)!==fixedSuggestion(intent.suggestion!)||result.suggestion.status!==intent.decision||result.suggestion.user_edited_content!==intent.content)throw Error('Invalid decision receipt');}
   else{const result=receipt as DiscardReceipt;if(fixedBatch(result.batch)!==fixedBatch(intent.batch)||result.batch.id!==this.identity||result.batch.status!==(intent.operation==='DISCARD'?'DISCARDED':'COMPLETED'))throw Error('Invalid batch receipt');if(intent.operation==='COMPLETE'){const document=(receipt as CompleteReceipt).current_document;if(document.id!==intent.current.id||document.requirement_id!==intent.batch.requirement_id||document.content_version!==(result.batch.applied_content_version??intent.batch.base_content_version)||result.batch.completion_result==='NO_CHANGE'&&(document.markdown_content!==intent.current.markdown_content||JSON.stringify(document.block_state_json)!==JSON.stringify(intent.current.block_state_json)))throw Error('Invalid document receipt');}}
   if(receipt.counts.total!==intent.batch.counts.total)throw Error('Invalid receipt membership');
   this.publish({phase:'CONFIRMED',receipt:capture(receipt),needs_refresh:false});this.action=undefined;return true;
  }catch(error){if(this.closed)return false;
   if(error instanceof ApiRejected&&!['REQUEST_IN_PROGRESS','STORAGE_UNAVAILABLE','INTERNAL_ERROR'].includes(error.code)){
    this.action=undefined;const errors:Record<number,string>={};const rows=error.details?.suggestion_errors;if(Array.isArray(rows))for(const row of rows){if(row&&typeof row==='object'&&!Array.isArray(row)&&this.value.batch!.suggestions.some(item=>item.id===row.suggestion_id))errors[Number(row.suggestion_id)]=String(row.message);}
    this.publish({phase:'ERROR',error:error.message,error_code:error.code,needs_refresh:!['PATCH_INVALID','INVALID_INPUT','VALIDATION_FAILED'].includes(error.code),stale:this.value.stale||['TARGET_STALE','CONTENT_VERSION_CONFLICT'].includes(error.code),item_errors:Object.freeze(errors)});
   }else this.publish({phase:'UNKNOWN',error:'本批修改结果待核实，原请求与编辑内容已保留；请复查后按原请求恢复',error_code:error instanceof ApiRejected?error.code:null});return false;
  }
 }
 recover():Promise<boolean>{if(this.value.phase!=='UNKNOWN'||!this.action||!this.value.available)return Promise.resolve(false);return this.enqueue('RECOVER',async()=>{const epoch=this.visibility;this.publish({phase:'READING',error:null});try{const actual=await this.observe();if(this.closed)return false;this.publish({observed:actual.batch});if(!this.value.available||epoch!==this.visibility)throw Error('Observation hidden before replay');}catch{this.publish({phase:'UNKNOWN',error:'实际批次或正文暂时无法读取，未重发；原请求保留'});return false;}return await this.send()?this.finishWork():false;});}
 finish():Promise<boolean>{return this.value.phase==='CONFIRMED'&&this.value.available?this.enqueue('FINISH',()=>this.finishWork()):Promise.resolve(false);}
 private async finishWork():Promise<boolean>{
  const epoch=this.visibility;this.publish({loading:true});try{const actual=await this.observe();await this.adoptActual(actual.detail);if(this.closed||!this.value.available||epoch!==this.visibility)throw Error('Adoption hidden');
   const drafts={...this.value.drafts};if(this.value.intent!.operation==='DECIDE')delete drafts[this.value.intent!.suggestion!.id];
   this.publish({detail:actual.detail,batch:actual.batch,phase:'READY',intent:null,receipt:null,observed:null,error:null,error_code:null,needs_refresh:false,stale:actual.batch.status==='PENDING'&&(this.value.stale||actual.batch.base_content_version!==actual.detail.current.content_version),drafts:Object.freeze(drafts),item_errors:Object.freeze({})});return true;
  }catch{this.publish({error:'建议操作已确认；实际批次、正文或评论读取失败，请仅读恢复，已保留确认回执'});return false;}finally{this.publish({loading:false});}
 }
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.visibility++;this.controller?.abort();this.listeners.clear();}
}
