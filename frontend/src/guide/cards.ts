import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {ApiAction,WalleApi} from '../api/walle.ts';
import {cards as decodeCards,responses as decodeResponses} from '../api/models.ts';
import type {Cards,Responses,Message,GuideRun} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {CardDrafts} from './card-drafts.ts';
import {blankAnswers,checkAnswers,formalAnswerText,CardAnswerError} from './card-answers.ts';
type Accepted=Awaited<ReturnType<ReturnType<WalleApi['prepareCardResponses']>['submit']>>['data'];
type Api=Pick<WalleApi,'prepareCardResponses'|'listMessages'|'getGuideRun'>;
export type CardsState=Readonly<{message:Message;source:GuideRun;detail:DetailSnapshot;cards:Cards;answers:Responses;phase:'READY'|'ERROR'|'SUBMITTING'|'UNKNOWN'|'READING'|'CONFIRMED'|'RESOLVED';submitted:Responses|null;outcome:Accepted|null;formal:Message|null;available:boolean;active:boolean;refreshing:boolean;needs_refresh:boolean;error:string|null;error_code:string|null;card_error:string|null;storage_error:string|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const identity=(message:Message)=>JSON.stringify([message.id,message.requirement_id,message.guide_run_id,message.sequence_no,message.role,message.message_type,message.content,message.structured_content,message.reply_to_message_id,message.created_at]);

/** One real assistant message, one whole group and one original opaque action.
 * Local selections never create a message. A formal response survives model
 * failure; read-derived expiration is never guessed from a timer or button. */
export class InteractionCards{
 private value:CardsState;private readonly api:Api;private readonly drafts:CardDrafts;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly receive:(run:Accepted['guide_run'])=>Promise<void>;private readonly refreshMessages:()=>Promise<void>;
 private readonly origin:string;private action:ApiAction<Accepted>|undefined;private responseReference:number|null=null;private delivered=false;private closed=false;private epoch=0;private controller:AbortController|undefined;private pending:Promise<boolean>|undefined;private work:string|undefined;private readonly listeners=new Set<()=>void>();
 constructor(message:Message,source:GuideRun,detail:DetailSnapshot,api:Api,drafts:CardDrafts,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,receive:(run:Accepted['guide_run'])=>Promise<void>,refreshMessages:()=>Promise<void>){
  if(message.role!=='ASSISTANT'||message.message_type!=='INTERACTION_CARDS'||message.structured_content===null||message.card_state===null||message.requirement_id!==detail.requirement.id||source.requirement_id!==message.requirement_id||source.id!==message.guide_run_id)throw TypeError('Owned actual card message and source Run required');
  this.assertDetail(detail,message.requirement_id);const cards=decodeCards(message.structured_content);this.origin=identity(message);this.api=api;this.drafts=drafts;this.readActual=readActual;this.adoptActual=adoptActual;this.receive=receive;this.refreshMessages=refreshMessages;
  const loaded=message.card_state==='AVAILABLE'?drafts.load(message.requirement_id,message.id,cards):{answers:null,error:drafts.clear(message.requirement_id,message.id)};
  this.value=capture({message,source,detail,cards,answers:loaded.answers??blankAnswers(cards),phase:message.card_state==='AVAILABLE'?'READY':'RESOLVED',submitted:null,outcome:null,formal:null,available:false,active:true,refreshing:false,needs_refresh:false,error:null,error_code:null,card_error:null,storage_error:loaded.error});
 }
 private assertDetail(detail:DetailSnapshot,requirement=this.value.message.requirement_id):void{if(detail.requirement.id!==requirement||detail.current.requirement_id!==requirement||detail.current.document_type!=='CURRENT')throw TypeError('Owned actual CURRENT required');}
 getSnapshot=():CardsState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<CardsState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E card observer failed',error);}}
 get editable():boolean{return !this.closed&&!this.pending&&this.value.message.card_state==='AVAILABLE'&&['READY','ERROR'].includes(this.value.phase);}
 get allowed():boolean{
  if(this.closed||!this.value.available||this.value.needs_refresh||this.value.message.card_state!=='AVAILABLE')return false;
  const {detail,source}=this.value,requirement=detail.requirement;
  if(source.action_type==='INITIALIZE')return requirement.status==='INITIALIZING'&&requirement.document_work_state==='IDLE'&&requirement.active_operation_id===null&&requirement.active_operation_type===null&&detail.activity.kind==='IDLE'&&source.status==='COMPLETED';
  return (requirement.status==='ACTIVE'||requirement.status==='COMPLETED'&&source.action_type==='ASK')&&requirement.document_work_state==='GUIDE_ACTIVE'&&requirement.active_operation_type==='GUIDE_RUN'&&requirement.active_operation_id===source.id&&detail.activity.kind==='GUIDE'&&detail.activity.run.id===source.id&&detail.activity.run.status==='WAITING_USER'&&source.status==='WAITING_USER';
 }
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.epoch++;this.publish({available});if(!available)this.controller?.abort();}
 adoptDetail(detail:DetailSnapshot):void{if(this.closed)return;this.assertDetail(detail);this.publish({detail:capture(detail)});}
 private persist():void{let storage_error:string|null;try{decodeResponses(this.value.answers);storage_error=this.drafts.save(this.value.message.requirement_id,this.value.message.id,this.value.answers);}catch{storage_error='此输入暂不符合本地记录格式，仍保留在当前页面；请修正后再刷新';}this.publish({storage_error});}
 retryStorage():void{if(this.closed)return;if(this.value.message.card_state==='AVAILABLE')this.persist();else this.publish({storage_error:this.drafts.clear(this.value.message.requirement_id,this.value.message.id)});}
 private change(key:string,update:(answer:Responses['responses'][number])=>Responses['responses'][number]):void{if(!this.editable)return;if(!this.value.cards.cards.some(card=>card.card_key===key))return;
  // Raw local input may be invalid Unicode or over its eventual limit. Keep it
  // editable in memory; only the formal request goes through JSON validation.
  const responses=this.value.answers.responses.map(answer=>{const next=answer.card_key===key?update(answer):answer;return Object.freeze({...next,selected_option_keys:Object.freeze([...next.selected_option_keys])});});
  this.publish({answers:Object.freeze({schema_version:1 as const,responses:Object.freeze(responses)}) as unknown as Responses,error:null,error_code:null,card_error:null});this.persist();}
 toggle(key:string,option:string,selected:boolean):void{
  const card=this.value.cards.cards.find(row=>row.card_key===key);if(!card?.options.some(row=>row.option_key===option))return;
  this.change(key,answer=>({...answer,skipped:false,selected_option_keys:selected?(card.card_type==='MULTI_SELECT'?[...new Set([...answer.selected_option_keys,option])]:[option]):answer.selected_option_keys.filter(row=>row!==option),custom_answer:selected&&card.card_type!=='MULTI_SELECT'?null:answer.custom_answer}));
 }
 custom(key:string,text:string):void{const card=this.value.cards.cards.find(row=>row.card_key===key);if(!card?.custom_answer.enabled)return;this.change(key,answer=>({...answer,skipped:false,custom_answer:text===''?null:text,selected_option_keys:card.card_type==='MULTI_SELECT'?answer.selected_option_keys:[]}));}
 skip(key:string,skipped:boolean):void{const card=this.value.cards.cards.find(row=>row.card_key===key);if(!card||card.required)return;this.change(key,answer=>skipped?{...answer,skipped:true,selected_option_keys:[],custom_answer:null}:{...answer,skipped:false});}
 /** Adopt only actual I35 state; an unknown original action remains recoverable
  * even after another read observes ANSWERED or EXPIRED. */
 adopt(message:Message,source:GuideRun,detail:DetailSnapshot,formal:Message|null=null):void{
  if(this.closed)return;if(identity(message)!==this.origin||source.id!==message.guide_run_id||source.requirement_id!==message.requirement_id)throw TypeError('Immutable card source changed');this.assertDetail(detail);if(formal)this.assertFormal(formal);if(formal&&message.card_state!=='ANSWERED')throw TypeError('Formal response requires actual ANSWERED');
  if(this.value.outcome){if(formal&&formal.id!==this.value.outcome.response_message.id)throw TypeError('Confirmed formal response identity changed');if(message.card_state!=='ANSWERED'){
   // I35 started before the accepted transaction may finish afterwards. Its
   // old AVAILABLE observation cannot undo our actual positive receipt.
   this.publish({source:capture(source),detail:capture(detail)});return;
  }}
  const settled=message.card_state!=='AVAILABLE',protectedRequest=['SUBMITTING','UNKNOWN','READING','CONFIRMED'].includes(this.value.phase);
  this.publish({message:capture(message),source:capture(source),detail:capture(detail),formal:formal?capture(formal):settled?this.value.formal:null,answers:!protectedRequest&&(message.card_state==='EXPIRED'||!settled&&this.value.message.card_state!=='AVAILABLE')?blankAnswers(this.value.cards):this.value.answers,phase:protectedRequest?this.value.phase:settled?'RESOLVED':this.value.phase==='RESOLVED'?'READY':this.value.phase,storage_error:settled?this.drafts.clear(message.requirement_id,message.id):this.value.storage_error});
 }
 private assertFormal(formal:Message,expected?:Responses):void{
  if(formal.requirement_id!==this.value.message.requirement_id||formal.role!=='USER'||formal.message_type!=='CARD_RESPONSE'||formal.reply_to_message_id!==this.value.message.id||formal.sequence_no<=this.value.message.sequence_no||formal.guide_run_id===null)throw TypeError('Owned formal card answer required');
  if(this.value.source.action_type!=='INITIALIZE'&&formal.guide_run_id!==this.value.source.id)throw TypeError('Original waiting Run required');
  if(formal.structured_content!==null){const decoded=decodeResponses(formal.structured_content),answers=checkAnswers(this.value.cards,decoded);if(JSON.stringify(answers)!==JSON.stringify(decoded)||formal.content!==formalAnswerText(this.value.cards,answers)||expected&&JSON.stringify(answers)!==JSON.stringify(expected))throw TypeError('Formal answer mismatch');}else if(expected)throw TypeError('Accepted formal answers required');
 }
 private enqueue(kind:string,job:()=>Promise<boolean>):Promise<boolean>{if(this.closed)return Promise.resolve(false);if(this.pending)return this.work===kind?this.pending:Promise.resolve(false);const pending=Promise.resolve().then(()=>this.closed?false:job()).finally(()=>{if(this.pending===pending){this.pending=undefined;this.publish({});}});this.pending=pending;this.work=kind;return pending;}
 submit():Promise<boolean>{if(!['READY','ERROR'].includes(this.value.phase)&&!(this.pending&&this.work==='SEND'))return Promise.resolve(false);return this.enqueue('SEND',async()=>{
  if(!this.allowed){this.publish({phase:'ERROR',error:'当前卡片或运行状态不允许提交，请重新读取',error_code:'STATE_CONFLICT'});return false;}
  try{const submitted=checkAnswers(this.value.cards,this.value.answers);this.action=this.api.prepareCardResponses(this.value.message.id,submitted);this.responseReference=null;this.delivered=false;this.publish({submitted,outcome:null,formal:null,error:null,error_code:null,card_error:null});}catch(error){this.publish({phase:'ERROR',error:error instanceof Error?error.message:'整组回答不合法',error_code:'INVALID_INPUT',card_error:error instanceof CardAnswerError?error.card_key:null});return false;}
  return await this.send()?this.finishWork():false;
 });}
 private async send():Promise<boolean>{this.publish({phase:'SUBMITTING',error:null,error_code:null});try{
  const receipt=(await this.action!.submit()).data;if(this.closed)return false;const run=receipt.guide_run,source=this.value.source;
  if(receipt.card_state!=='ANSWERED'||run.requirement_id!==this.value.message.requirement_id||run.status!=='RUNNING'||run.current_step!=='PREPARING'||(source.action_type==='INITIALIZE'?run.id===source.id:run.id!==source.id))throw TypeError('Unconfirmed card Run');this.assertFormal(receipt.response_message,this.value.submitted!);if(receipt.response_message.guide_run_id!==run.id)throw TypeError('Unconfirmed card response Run');
  this.action=undefined;this.publish({phase:'CONFIRMED',outcome:capture(receipt),formal:capture(receipt.response_message),message:capture({...this.value.message,card_state:'ANSWERED'}),storage_error:this.drafts.clear(this.value.message.requirement_id,this.value.message.id)});return true;
 }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;const reference=error.details?.response_message_id;this.responseReference=error.code==='CARD_ALREADY_ANSWERED'&&typeof reference==='number'?reference:null;this.publish({phase:'ERROR',error:error.message,error_code:error.code,needs_refresh:true});}else this.publish({phase:'UNKNOWN',error:'整组提交结果待核实，原答案与请求已保留'});return false;}}
 private async observe():Promise<Readonly<{detail:DetailSnapshot;message:Message;source:GuideRun;formal:Message|null}>>{
  const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;if(!alive())throw Error('卡片已暂停');const controller=new AbortController();this.controller=controller;
  try{
   const detail=await this.readActual();if(!alive())throw Error('Old card read');this.assertDetail(detail);const source=(await this.api.getGuideRun(this.value.source.id,controller.signal)).data;if(!alive())throw Error('Old card read');
   let cursor:number|null=null,message:Message|null=null,formal:Message|null=null;const seen=new Set<number>();
   for(;;){const result=await this.api.listMessages(this.value.message.requirement_id,cursor,controller.signal);if(!alive())throw Error('Old card read');const pagination=result.meta.pagination,rows=result.data.items;
    if(!pagination||!('has_more' in pagination)||pagination.page_size!==20||rows.length>20)throw Error('Actual message cursor required');let sequence=0;
    for(const row of rows){if(row.requirement_id!==this.value.message.requirement_id||seen.has(row.id)||row.sequence_no<=sequence||cursor!==null&&row.sequence_no>=cursor)throw Error('Actual owned message window required');seen.add(row.id);sequence=row.sequence_no;if(row.id===this.value.message.id)message=row;if(row.message_type==='CARD_RESPONSE'&&row.reply_to_message_id===this.value.message.id){if(formal)throw Error('Duplicate formal response');this.assertFormal(row);formal=row;}}
    if(pagination.has_more?(rows.length===0||pagination.next_cursor!==rows[0]!.sequence_no):pagination.next_cursor!==null)throw Error('Invalid message cursor');
    if(message&&(message.card_state!=='ANSWERED'||formal)||!pagination.has_more)break;cursor=pagination.next_cursor;
   }
   if(!message||identity(message)!==this.origin||source.id!==this.value.source.id||source.requirement_id!==message.requirement_id||message.card_state==='ANSWERED'&&!formal||message.card_state!=='ANSWERED'&&formal||this.responseReference!==null&&formal?.id!==this.responseReference)throw Error('Unconfirmed actual card state');
   return capture({detail,message,source,formal});
  }finally{if(this.controller===controller)this.controller=undefined;}
 }
 recover():Promise<boolean>{if(this.value.phase!=='UNKNOWN'||!this.action||!this.value.available)return Promise.resolve(false);return this.enqueue('RECOVER',async()=>{this.publish({phase:'READING',error:null});try{const actual=await this.observe();this.adopt(actual.message,actual.source,actual.detail,actual.formal);}catch{this.publish({phase:'UNKNOWN',error:'实际消息或运行读取失败，未重发；原答案仍保留'});return false;}return await this.send()?this.finishWork():false;});}
 refresh():Promise<boolean>{if(!this.value.available||!['READY','ERROR','RESOLVED'].includes(this.value.phase))return Promise.resolve(false);return this.enqueue('REFRESH',async()=>{const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;this.publish({refreshing:true});try{const actual=await this.observe();if(!alive())return false;await this.adoptActual(actual.detail);if(!alive())return false;this.adopt(actual.message,actual.source,actual.detail,actual.formal);await this.refreshMessages();if(!alive())return false;this.publish({needs_refresh:false,error:null,error_code:null,card_error:null});return true;}catch{this.publish({error:'正式卡片状态或回答暂时无法读取，本地答案仍保留'});return false;}finally{this.publish({refreshing:false});}});}
 finish():Promise<boolean>{if(this.value.phase!=='CONFIRMED'||!this.value.available)return Promise.resolve(false);return this.enqueue('FINISH',()=>this.finishWork());}
 private async finishWork():Promise<boolean>{const epoch=this.epoch,alive=()=>!this.closed&&this.value.available&&epoch===this.epoch;this.publish({refreshing:true});try{
  if(!alive())throw Error('回答已保存，恢复面板后读取实际状态');if(!this.delivered){await this.receive(this.value.outcome!.guide_run);if(this.closed)return false;this.delivered=true;}if(!alive())throw Error('回答已保存，恢复面板后读取实际状态');const actual=await this.observe();if(!alive())throw Error('Old confirmed read');if(actual.message.card_state!=='ANSWERED'||actual.formal?.id!==this.value.outcome!.response_message.id)throw Error('已接受回答，正式读取尚未确认');await this.adoptActual(actual.detail);if(!alive())throw Error('Old confirmed adoption');this.adopt(actual.message,actual.source,actual.detail,actual.formal);await this.refreshMessages();if(!alive())throw Error('Old confirmed messages');this.publish({phase:'RESOLVED',needs_refresh:false,error:null,error_code:null,card_error:null});return true;
 }catch(error){this.publish({error:error instanceof Error?error.message:'回答已保存，重试读取正式状态'});return false;}finally{this.publish({refreshing:false});}}
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.epoch++;this.controller?.abort();this.listeners.clear();}
}
