import { ApiRejected, positiveInteger, snapshotObject } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import type { Requirement, GuideRun, Batch } from '../api/models.ts';
import type { DocumentReadModel } from '../documents/contracts.ts';

type CommentIndex = Awaited<ReturnType<WalleApi['getCommentIndex']>>['data'];
type ReadApi = Pick<WalleApi,'getRequirement'|'getCurrentDocument'|'getManualDraft'|'getGuideRun'|'getBatch'|'getCommentIndex'>;
export type DetailActivity = Readonly<{kind:'IDLE'} | {kind:'MANUAL';draft:DocumentReadModel} | {kind:'GUIDE';run:GuideRun} | {kind:'BATCH';batch:Batch}>;
export type DetailSnapshot = Readonly<{requirement:Requirement;current:DocumentReadModel;activity:DetailActivity;comment_index:CommentIndex}>;
export type DetailReadError = 'MISSING' | 'INCONSISTENT' | 'CHANGED' | 'READ_FAILED';
export type DetailReadState = Readonly<{confirmed:DetailSnapshot|null;loading:boolean;active:boolean;error:string|null;error_kind:DetailReadError|null}>;
export type DetailPhase = 'DETAIL_LOADING'|'DETAIL_MISSING'|'DETAIL_ERROR'|'WORK_STATE_INCONSISTENT'|'CONTENT_VERSION_CONFLICT'|
  'IDLE_VIEW'|'MANUAL_EDITING'|'GUIDE_RUNNING'|'GUIDE_WAITING'|'BATCH_REVIEW';
class ReadMismatch extends Error {
  readonly kind:'INCONSISTENT'|'CHANGED';
  constructor(kind:'INCONSISTENT'|'CHANGED'){super(kind==='INCONSISTENT'?'数据状态异常，请重试':'读取期间当前状态或正文已变化，请重新读取');this.kind=kind;}
}
const requireRelation = (valid:boolean):void => {if(!valid)throw new ReadMismatch('INCONSISTENT');};
const captured = <T>(value:T):T => snapshotObject(value) as unknown as T;
const occupancy = (value:Requirement) => JSON.stringify([value.status,value.document_work_state,value.active_operation_type,value.active_operation_id]);

/** Complete read bundle owned by one detail lifetime. Each API has its own
 * real transaction; matching references/versions are checks, not a claimed
 * multi-endpoint database snapshot. No partial bundle or fake empty editor. */
export class RequirementDetailRead {
  private readonly identity:number; private readonly api:ReadApi;
  private value:DetailReadState=Object.freeze({confirmed:null,loading:false,active:true,error:null,error_kind:null});
  private readonly listeners=new Set<()=>void>();private generation=0;private closed=false;
  private controller:AbortController|undefined;private pending:Promise<boolean>|undefined;
  constructor(identity:number,api:ReadApi){this.identity=positiveInteger(identity);this.api=api;}
  getSnapshot=():DetailReadState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  get writeReady():boolean{return !this.closed&&this.value.active&&!this.value.loading&&!this.value.error&&this.value.confirmed!==null;}
  get phase():DetailPhase {
    if(this.value.loading||!this.value.active)return 'DETAIL_LOADING';
    if(this.value.error_kind==='MISSING')return 'DETAIL_MISSING';
    if(this.value.error_kind==='INCONSISTENT')return 'WORK_STATE_INCONSISTENT';
    if(this.value.error_kind==='CHANGED')return 'CONTENT_VERSION_CONFLICT';
    if(this.value.error||!this.value.confirmed)return this.value.error?'DETAIL_ERROR':'DETAIL_LOADING';
    const activity=this.value.confirmed.activity;
    return activity.kind==='IDLE'?'IDLE_VIEW':activity.kind==='MANUAL'?'MANUAL_EDITING':activity.kind==='BATCH'?'BATCH_REVIEW':activity.run.status==='WAITING_USER'?'GUIDE_WAITING':'GUIDE_RUNNING';
  }
  private publish(changes:Partial<DetailReadState>):void{
    if(this.closed)return;this.value=Object.freeze({...this.value,...changes});
    for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E detail read observer failed',error);}}
  }
  refresh(force=false):Promise<boolean>{
    if(this.closed)return Promise.resolve(false);if(this.pending&&!force)return this.pending;
    const generation=++this.generation,controller=new AbortController();this.controller?.abort();this.controller=controller;
    let rootConfirmed=false;
    const pending=Promise.resolve().then(async()=>{
      if(this.closed||generation!==this.generation)return false;
      try{
        const root=captured((await this.api.getRequirement(this.identity,controller.signal)).data);
        if(this.closed||generation!==this.generation)return false;rootConfirmed=true;requireRelation(root.id===this.identity);
        const [documentResponse,indexResponse]=await Promise.all([this.api.getCurrentDocument(this.identity,controller.signal),this.api.getCommentIndex(this.identity,controller.signal)]);
        if(this.closed||generation!==this.generation)return false;
        const current=captured(documentResponse.data),index=captured(indexResponse.data);
        requireRelation(current.requirement_id===this.identity&&current.document_type==='CURRENT'&&index.requirement_id===this.identity&&index.document_id===current.id);
        if(index.content_version!==current.content_version)throw new ReadMismatch('CHANGED');
        const ids=new Set(current.block_state_json.blocks.map(block=>block.block_id));
        requireRelation(index.blocks.every(block=>ids.has(block.block_id))&&index.comments.every(comment=>comment.location.status!=='ATTACHED'||ids.has(comment.location.block_id!)));
        let activity:DetailActivity;
        switch(root.document_work_state){
          case 'IDLE':requireRelation(root.active_operation_type===null&&root.active_operation_id===null);activity=Object.freeze({kind:'IDLE'});break;
          case 'MANUAL_EDITING':{
            requireRelation(root.status!=='COMPLETED'&&root.active_operation_type==='MANUAL_DRAFT'&&root.active_operation_id!==null);
            const draft=captured((await this.api.getManualDraft(this.identity,controller.signal)).data);
            requireRelation(draft.document_type==='MANUAL_DRAFT'&&draft.id===root.active_operation_id&&draft.id!==current.id&&draft.requirement_id===this.identity);
            activity=Object.freeze({kind:'MANUAL',draft});break;
          }
          case 'GUIDE_ACTIVE':{
            requireRelation(root.active_operation_type==='GUIDE_RUN'&&root.active_operation_id!==null);
            const run=captured((await this.api.getGuideRun(root.active_operation_id!,controller.signal)).data);
            requireRelation(run.id===root.active_operation_id&&run.requirement_id===this.identity);
            requireRelation(root.status==='INITIALIZING'?run.action_type==='INITIALIZE':root.status==='COMPLETED'?run.action_type==='ASK':run.action_type!=='INITIALIZE');
            activity=Object.freeze({kind:'GUIDE',run});break;
          }
          case 'SUGGESTION_REVIEWING':{
            requireRelation(root.status==='ACTIVE'&&root.active_operation_type==='SUGGESTION_BATCH'&&root.active_operation_id!==null);
            const batch=captured((await this.api.getBatch(root.active_operation_id!,controller.signal)).data);
            requireRelation(batch.id===root.active_operation_id&&batch.requirement_id===this.identity&&batch.status==='PENDING');
            if(batch.base_content_version!==current.content_version)throw new ReadMismatch('CHANGED');
            activity=Object.freeze({kind:'BATCH',batch});break;
          }
          default:throw new ReadMismatch('INCONSISTENT');
        }
        if(this.closed||generation!==this.generation)return false;
        const latest=captured((await this.api.getRequirement(this.identity,controller.signal)).data);requireRelation(latest.id===this.identity);
        if(occupancy(root)!==occupancy(latest))throw new ReadMismatch('CHANGED');
        if(activity.kind==='GUIDE')requireRelation(activity.run.status==='RUNNING'||activity.run.status==='WAITING_USER');
        if(this.closed||generation!==this.generation)return false;
        const confirmed:DetailSnapshot=Object.freeze({requirement:latest,current,activity,comment_index:index});
        this.publish({confirmed,loading:false,error:null,error_kind:null});return true;
      }catch(error){
        if(this.closed||generation!==this.generation)return false;
        const kind:DetailReadError=error instanceof ReadMismatch?error.kind:error instanceof ApiRejected&&error.code==='NOT_FOUND'&&!rootConfirmed?'MISSING':
          error instanceof ApiRejected&&['WORK_STATE_INCONSISTENT','MANUAL_DRAFT_NOT_FOUND','NOT_FOUND'].includes(error.code)?'INCONSISTENT':'READ_FAILED';
        this.publish({loading:false,error_kind:kind,error:kind==='MISSING'?'需求不存在':error instanceof ReadMismatch?error.message:kind==='INCONSISTENT'?'数据状态异常，请重试':error instanceof ApiRejected?error.message:'暂时无法读取详情，请重试'});return false;
      }
    }).finally(()=>{if(this.pending===pending)this.pending=undefined;if(this.controller===controller)this.controller=undefined;});
    this.pending=pending;this.publish({loading:true,active:true,error:null,error_kind:null});return pending;
  }
  pause():void{if(this.closed)return;this.generation++;this.controller?.abort();this.controller=undefined;this.pending=undefined;this.publish({loading:false,active:false});}
  dispose():void{this.closed=true;this.generation++;this.controller?.abort();this.listeners.clear();}
}
