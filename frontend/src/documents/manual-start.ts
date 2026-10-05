import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {Requirement} from '../api/models.ts';
import type {DocumentReadModel} from './contracts.ts';

type Api=Pick<WalleApi,'prepareStartManualDraft'|'getRequirement'|'getCurrentDocument'|'getManualDraft'>;
type Receipt=Awaited<ReturnType<ReturnType<WalleApi['prepareStartManualDraft']>['submit']>>['data'];
export type ManualStartObservation=Readonly<{requirement:Requirement;current:DocumentReadModel;manual_draft:DocumentReadModel|null}>;
export type ManualStartState=Readonly<{phase:'READY'|'SUBMITTING'|'UNKNOWN'|'CHECKING'|'ERROR'|'STARTED';error:string|null;
  receipt:Receipt|null;observed:ManualStartObservation|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
// Object field order is irrelevant, but every source field and array order
// must be inherited exactly. This is receipt checking, never content matching
// used to infer that an unknown command committed.
const canonical=(value:unknown):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)
  ?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);

/** One explicit start intention at the loaded CURRENT version. A native 201
 * confirms this action; the page must read latest detail before mounting an
 * editable session. A historical idempotent receipt is not a live occupancy. */
export class ManualDraftStart {
  private readonly api:Api;private readonly requirement:Requirement;private readonly current:DocumentReadModel;
  private action:ReturnType<WalleApi['prepareStartManualDraft']>|undefined;private pending:Promise<boolean>|undefined;
  private disposed=false;private readonly listeners=new Set<()=>void>();
  private value:ManualStartState=Object.freeze({phase:'READY',error:null,receipt:null,observed:null});
  constructor(requirement:Requirement,current:DocumentReadModel,api:Api){
    if(!['INITIALIZING','ACTIVE'].includes(requirement.status)||requirement.document_work_state!=='IDLE'||requirement.active_operation_type!==null||requirement.active_operation_id!==null||
      current.document_type!=='CURRENT'||current.requirement_id!==requirement.id)throw new TypeError('Confirmed writable idle CURRENT required');
    this.requirement=capture(requirement);this.current=capture(current);this.api=api;
  }
  getSnapshot=():ManualStartState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<ManualStartState>):void{
    if(this.disposed)return;this.value=Object.freeze({...this.value,...changes});
    for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E manual start observer failed',error);}}
  }
  start():Promise<boolean>{
    if(this.disposed||this.value.phase==='STARTED'||this.value.phase==='UNKNOWN'||this.value.phase==='CHECKING')return Promise.resolve(false);
    if(this.pending)return this.pending;
    if(!this.action){try{this.action=this.api.prepareStartManualDraft(this.requirement.id,this.current.content_version);}
      catch{this.publish({phase:'ERROR',error:'无法准备编辑请求，请重新读取详情'});return Promise.resolve(false);}}
    return this.run(()=>this.submit());
  }
  private run(work:()=>Promise<boolean>):Promise<boolean>{
    if(this.pending)return this.pending;
    const pending=Promise.resolve().then(()=>this.disposed?false:work()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;return pending;
  }
  private async submit():Promise<boolean>{
    this.publish({phase:'SUBMITTING',error:null});
    try{
      const receipt=(await this.action!.submit()).data;if(this.disposed)return false;
      const root=receipt.requirement,draft=receipt.manual_draft;
      if(root.id!==this.requirement.id||!['INITIALIZING','ACTIVE'].includes(root.status)||root.document_work_state!=='MANUAL_EDITING'||root.active_operation_type!=='MANUAL_DRAFT'||root.active_operation_id!==draft.id||
        draft.document_type!=='MANUAL_DRAFT'||draft.id===this.current.id||draft.requirement_id!==this.requirement.id||draft.content_version!==1||
        draft.markdown_content!==this.current.markdown_content||canonical(draft.block_state_json)!==canonical(this.current.block_state_json))throw Error('Unconfirmed draft creation receipt');
      this.publish({phase:'STARTED',receipt:capture(receipt),error:null});return true;
    }catch(error){
      if(this.disposed)return false;
      if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS')this.publish({phase:'ERROR',error:error.message});
      else this.publish({phase:'UNKNOWN',error:'开始编辑的结果待核实，请保留原请求并重新确认'});
      return false;
    }
  }
  retryUnknown():Promise<boolean>{
    if(this.disposed||!this.action)return Promise.resolve(false);
    if(this.pending)return this.pending;
    if(this.value.phase!=='UNKNOWN')return Promise.resolve(false);
    return this.run(async()=>{
      this.publish({phase:'CHECKING',error:null});
      const [root,current,draft]=await Promise.allSettled([this.api.getRequirement(this.requirement.id),this.api.getCurrentDocument(this.requirement.id),this.api.getManualDraft(this.requirement.id)]);
      if(this.disposed)return false;
      if(root.status==='rejected'||current.status==='rejected'||draft.status==='rejected'&&!(draft.reason instanceof ApiRejected&&draft.reason.code==='MANUAL_DRAFT_NOT_FOUND')){
        this.publish({phase:'UNKNOWN',error:'暂时无法复查实际资源，原开始编辑请求已保留'});return false;
      }
      this.publish({observed:capture({requirement:root.value.data,current:current.value.data,manual_draft:draft.status==='fulfilled'?draft.value.data:null})});
      return this.submit();
    });
  }
  dispose():void{this.disposed=true;this.listeners.clear();}
}
