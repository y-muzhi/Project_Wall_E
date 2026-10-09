import {snapshotObject} from '../api/client.ts';
import type {GuideRun} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {detailPermissions} from '../requirements/permissions.ts';
import {RequirementComments} from './read.ts';
import {CommentCommand} from './commands.ts';
import type {CommentTarget,CommentOutcome,CommentIntent} from './commands.ts';
import type {ConfirmedNotice} from '../shared/toast-store.ts';
type Api=ConstructorParameters<typeof RequirementComments>[1]&ConstructorParameters<typeof CommentCommand>[2];
export type CommentSlot=Readonly<{key:number;identity:number|null;flow:CommentCommand;open:boolean}>;
export type CommentPanelState=Readonly<{detail:DetailSnapshot;view:'CURRENT'|'MANUAL'|'HISTORY';suspended:boolean;active:boolean;refreshing:boolean;needs_refresh:boolean;error:string|null;slots:readonly CommentSlot[];revision:number}>;
type OwnedSlot={slot:CommentSlot;release:()=>void;guideDelivered:boolean;pending?:Promise<void>};
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
const conflicts=new Set(['STATE_CONFLICT','WORK_STATE_CONFLICT','WORK_STATE_INCONSISTENT','CONTENT_VERSION_CONFLICT','ANCHOR_INVALID','COMMENT_ORPHANED','NOT_FOUND']);

/** One requirement lifetime, one retained intention per comment plus one
 * composer. Actual page changes never manufacture rows or discard commands.
 * Confirmed outcomes are retired only after actual parent/list adoption.
 * The actual Guide receiver must idempotently adopt the same Run ID if its
 * previous adoption failed before acknowledgement. */
export class RequirementCommentPanel{
  readonly comments:RequirementComments;private readonly api:Api;private readonly readActual:()=>Promise<DetailSnapshot>;
  private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly acceptedGuide:(run:GuideRun)=>Promise<void>;
  private readonly notifyConfirmed:ConfirmedNotice|undefined;
  private value:CommentPanelState;private readonly listeners=new Set<()=>void>();private readonly owners=new Map<number,OwnedSlot>();private nextKey=1;private closed=false;private syncing=false;
  private readonly releaseRead:()=>void;private tail:Promise<unknown>=Promise.resolve();private jobs=0;private refreshPending:Promise<void>|undefined;
  constructor(detail:DetailSnapshot,api:Api,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,acceptedGuide:(run:GuideRun)=>Promise<void>,notifyConfirmed?:ConfirmedNotice){
    if(detail.current.document_type!=='CURRENT'||detail.current.requirement_id!==detail.requirement.id)throw TypeError('Actual owned detail required');
    this.api=api;this.readActual=readActual;this.adoptActual=adoptActual;this.acceptedGuide=acceptedGuide;this.notifyConfirmed=notifyConfirmed;
    this.value=Object.freeze({detail:capture(detail),view:detail.activity.kind==='MANUAL'?'MANUAL':'CURRENT',suspended:false,active:true,refreshing:false,needs_refresh:false,error:null,slots:Object.freeze([]),revision:0});
    this.comments=new RequirementComments(detail.current,api);this.releaseRead=this.comments.subscribe(()=>{this.syncBaselines();this.publish({});});
  }
  getSnapshot=():CommentPanelState=>this.value;
  subscribe=(callback:()=>void):(()=>void)=>{this.listeners.add(callback);return()=>this.listeners.delete(callback);};
  get blocked():boolean{return this.closed||this.value.view==='HISTORY'||this.value.suspended;}
  get writeReady():boolean{return !this.blocked&&!this.value.refreshing&&!this.value.needs_refresh&&this.value.view==='CURRENT'&&this.comments.ready&&detailPermissions(this.value.detail,true).comment_write;}
  get writeUnavailableReason():string|null{
    if(this.value.detail.requirement.status==='INITIALIZING')return '初始化中暂不支持新增评论；完成初始化后，需求进入进行中且文档空闲时可用。';
    if(this.value.detail.requirement.status==='COMPLETED')return '需求已完成；重新激活且文档空闲后可新增评论。';
    if(this.closed||this.value.suspended)return '当前评论操作已暂停。';
    if(this.value.view!=='CURRENT')return '新增评论须回到正式正文，人工草稿和历史版本不支持。';
    if(this.value.detail.requirement.document_work_state!=='IDLE')return '文档正在编辑或处理 AI 任务；恢复空闲后可新增评论。';
    if(!this.writeReady)return '评论数据尚未就绪，请等待加载完成或刷新评论。';
    return null;
  }
  writable(flow:CommentCommand):boolean{
    if(!this.writeReady||!flow.allowed)return false;const intent=flow.intent;
    return intent.kind==='CREATE'?intent.target.document_id===this.value.detail.current.id&&intent.target.content_version===this.value.detail.current.content_version:
      this.comments.getSnapshot().confirmed!.items.some(row=>row.id===intent.comment.id);
  }
  private publish(changes:Partial<CommentPanelState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes,slots:Object.freeze([...this.owners.values()].map(owner=>owner.slot)),revision:this.value.revision+1});for(const callback of this.listeners)try{callback();}catch(error){console.error('WALL-E comment panel observer failed',error);}}
  private syncBaselines():void{
    if(this.closed||this.syncing||!this.comments.ready)return;const bundle=this.comments.getSnapshot().confirmed!;if(!same(bundle.current,this.value.detail.current))return;
    this.syncing=true;try{for(const owner of this.owners.values()){const intent=owner.slot.flow.intent;if(intent.kind==='CREATE')owner.slot.flow.rebase(this.value.detail);else{const actual=bundle.items.find(row=>row.id===intent.comment.id);if(actual)owner.slot.flow.rebase(this.value.detail,actual);}}}finally{this.syncing=false;}
  }
  adopt(actual:DetailSnapshot):void{
    if(this.closed)return;if(actual.requirement.id!==this.value.detail.requirement.id||actual.current.requirement_id!==actual.requirement.id||actual.current.document_type!=='CURRENT')throw TypeError('Owned actual detail required');
    this.publish({detail:capture(actual)});this.comments.setCurrent(actual.current);this.syncBaselines();
  }
  setView(view:CommentPanelState['view'],suspended=this.value.suspended):void{
    if(this.closed||this.value.view===view&&this.value.suspended===suspended)return;this.publish({view,suspended});if(this.blocked)this.comments.pause();
  }
  private own(identity:number|null,flow:CommentCommand,content?:string):CommentCommand{
    if(content!==undefined)flow.change(content);const key=identity??0,slot:CommentSlot=Object.freeze({identity,flow,key:this.nextKey++,open:true});
    const release=flow.subscribe(()=>{if(this.closed)return;const state=flow.getSnapshot();if(state.phase==='ERROR'&&state.error_code&&conflicts.has(state.error_code))this.publish({needs_refresh:true,error:'评论状态或正文已变化，请重新读取评论与详情；输入和原引用仍保留。'});else this.publish({});});
    this.owners.set(key,{slot,release,guideDelivered:false});this.publish({error:null});return flow;
  }
  begin(identity:number,kind:Exclude<CommentIntent['kind'],'CREATE'>):CommentCommand|null{
    if(this.blocked)return null;const existing=this.owners.get(identity);if(existing){existing.slot=Object.freeze({...existing.slot,open:true});this.publish({});return existing.slot.flow;}
    if(!this.writeReady)return null;const comment=this.comments.getSnapshot().confirmed!.items.find(row=>row.id===identity);if(!comment)return null;
    try{return this.own(identity,new CommentCommand(this.value.detail,{kind,comment},this.api));}catch{this.publish({error:'当前评论不允许该操作，请重新读取评论与详情。'});return null;}
  }
  create(target:CommentTarget):CommentCommand|null{
    if(!this.writeReady)return null;const existing=this.owners.get(0);
    if(existing){const phase=existing.slot.flow.getSnapshot().phase;if(!['READY','ERROR'].includes(phase)){existing.slot=Object.freeze({...existing.slot,open:true});this.publish({error:'已有新建评论请求仍待处理，请先确认原请求结果。'});return existing.slot.flow;}
      if(same((existing.slot.flow.intent as Extract<CommentIntent,{kind:'CREATE'}>).target,target)){existing.slot=Object.freeze({...existing.slot,open:true});this.publish({});return existing.slot.flow;}
    }
    try{const flow=new CommentCommand(this.value.detail,{kind:'CREATE',target},this.api),content=existing?.slot.flow.getSnapshot().content;
      if(existing){existing.release();existing.slot.flow.dispose();this.owners.delete(0);}return this.own(null,flow,content);
    }catch{this.publish({error:'评论范围不属于当前正文，请重新选择；原输入仍保留。'});return null;}
  }
  slot(identity:number|null):CommentSlot|null{return this.owners.get(identity??0)?.slot??null;}
  rejectTarget():void{this.publish({error:'评论范围已变化，请在当前正文重新选择；原输入仍保留。'});}
  async submit(flow:CommentCommand):Promise<void>{
    if(!this.writable(flow))return;
    try{if(await flow.submit()){const outcome=flow.getSnapshot().outcome;if(outcome)await this.finish(flow,outcome);}}
    catch(error){this.publish({error:error instanceof Error?error.message:'评论操作暂时无法完成，原请求仍保留'});}
  }
  close(flow:CommentCommand):boolean{
    const entry=[...this.owners.entries()].find(([,owner])=>owner.slot.flow===flow);if(!entry||entry[1].pending)return false;
    const [identity,owner]=entry,phase=flow.getSnapshot().phase;if(['SUBMITTING','READING','CONFIRMED'].includes(phase))return false;
    if(phase==='UNKNOWN'){owner.slot=Object.freeze({...owner.slot,open:false});this.publish({});return true;}
    owner.release();flow.dispose();this.owners.delete(identity);this.publish({});return true;
  }
  open(flow:CommentCommand):void{const owner=[...this.owners.values()].find(owner=>owner.slot.flow===flow);if(this.blocked||!owner)return;owner.slot=Object.freeze({...owner.slot,open:true});this.publish({});}
  private enqueue(work:()=>Promise<void>):Promise<void>{
    if(this.closed)return Promise.reject(Error('Comment panel is retired'));this.jobs++;this.publish({refreshing:true});const pending=this.tail.then(async()=>{if(this.blocked)throw Error('当前评论已隐藏或暂停，请恢复后重新读取');await work();});this.tail=pending.catch(()=>undefined);
    return pending.catch(error=>{this.publish({error:error instanceof Error?error.message:'评论与详情暂时无法重新读取'});throw error;}).finally(()=>{this.jobs--;if(!this.jobs)this.publish({refreshing:false});});
  }
  /** Observation for UNKNOWN has no adoption/removal side effects. */
  observe=async():Promise<DetailSnapshot>=>{if(this.blocked)throw Error('Comments are blocked');const actual=await this.readActual();if(this.blocked)throw Error('Retired comment observation');if(actual.requirement.id!==this.value.detail.requirement.id)throw TypeError('Owned actual observation required');return actual;};
  private async readAndAdopt():Promise<void>{
    const actual=await this.observe();await this.adoptActual(actual);if(this.blocked)throw Error('评论暂时隐藏，已确认结果仍保留');this.adopt(actual);
    if(!await this.comments.refresh(this.comments.getSnapshot().page,true))throw Error('实际评论列表暂时无法读取，已确认结果仍保留，请重试读取');
    if(this.blocked)throw Error('Comments were hidden during adoption');this.publish({needs_refresh:false,error:null});
  }
  refresh():Promise<void>{if(this.refreshPending)return this.refreshPending;const pending=this.enqueue(()=>this.readAndAdopt()).finally(()=>{if(this.refreshPending===pending)this.refreshPending=undefined;});this.refreshPending=pending;return pending;}
  finish(flow:CommentCommand,outcome:CommentOutcome):Promise<void>{
    const entry=[...this.owners.entries()].find(([,owner])=>owner.slot.flow===flow);if(!entry||flow.getSnapshot().phase!=='CONFIRMED'||outcome!==flow.getSnapshot().outcome)return Promise.reject(Error('Original confirmed comment outcome required'));
    const [identity,owner]=entry;if(owner.pending)return owner.pending;
    if(flow.intent.kind==='DELETE'&&outcome.kind==='COMMENT')this.notifyConfirmed?.(outcome,'评论已删除');
    const pending=this.enqueue(async()=>{
      if(outcome.kind==='GUIDE'&&!owner.guideDelivered){await this.acceptedGuide(outcome.run);owner.guideDelivered=true;}
      await this.readAndAdopt();if(this.closed||this.owners.get(identity)!==owner)throw Error('Retired comment outcome');
      owner.release();flow.dispose();this.owners.delete(identity);this.publish({error:null});
    }).finally(()=>{if(owner.pending===pending)delete owner.pending;});owner.pending=pending;return pending;
  }
  async page(page:number):Promise<boolean>{if(this.blocked||this.value.refreshing)return false;return this.comments.refresh(page);}
  async select(identity:number):Promise<boolean>{if(this.blocked||this.value.refreshing)return false;return this.comments.select(identity);}
  dispose():void{if(this.closed)return;this.publish({active:false});this.closed=true;this.releaseRead();this.comments.dispose();for(const owner of this.owners.values()){owner.release();owner.slot.flow.dispose();}this.owners.clear();this.listeners.clear();}
}
