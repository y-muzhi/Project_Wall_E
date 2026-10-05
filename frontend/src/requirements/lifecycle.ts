import type {WalleApi} from '../api/walle.ts';
import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {Requirement,RevisionSummary} from '../api/models.ts';
import type {DocumentReadModel} from '../documents/contracts.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {detailPermissions} from './permissions.ts';

export type LifecycleOperation='INITIALIZATION'|'COMPLETE'|'REACTIVATE';
type Init=Awaited<ReturnType<ReturnType<WalleApi['prepareCompleteInitialization']>['submit']>>['data'];
export type LifecycleOutcome=Readonly<{kind:'INITIALIZATION';result:Init}|{kind:'COMPLETE'|'REACTIVATE';requirement:Requirement}>;
export type LifecycleState=Readonly<{phase:'READY'|'SUBMITTING'|'READING'|'UNKNOWN'|'ERROR'|'CONFIRMED';error:string|null;outcome:LifecycleOutcome|null;
  observed:Readonly<{requirement:Requirement;current:DocumentReadModel;revisions:readonly RevisionSummary[]|null}>|null}>;
type Api=Pick<WalleApi,'getRequirement'|'getCurrentDocument'|'listRevisions'|'prepareCompleteInitialization'|'prepareCompleteRequirement'|'prepareReactivateRequirement'>;
type Action=Readonly<{kind:'INITIALIZATION';action:ReturnType<WalleApi['prepareCompleteInitialization']>}|{kind:'COMPLETE';action:ReturnType<WalleApi['prepareCompleteRequirement']>}|{kind:'REACTIVATE';action:ReturnType<WalleApi['prepareReactivateRequirement']>}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** One explicit lifecycle intention. The same opaque original action is used
 * after unknown outcomes. Reads are observations, never proof that this
 * command committed; parent reloads actual complete detail after confirmation. */
export class RequirementLifecycle {
  readonly operation:LifecycleOperation;private readonly initial:DetailSnapshot;private readonly api:Api;
  private value:LifecycleState=Object.freeze({phase:'READY',error:null,outcome:null,observed:null});private readonly listeners=new Set<()=>void>();
  private action:Action|undefined;private pending:Promise<boolean>|undefined;private pendingOperation:'SUBMIT'|'RECHECK'|undefined;private disposed=false;private readController:AbortController|undefined;
  constructor(operation:LifecycleOperation,initial:DetailSnapshot,api:Api){
    const permission=detailPermissions(initial,true),allowed={INITIALIZATION:permission.complete_initialization,COMPLETE:permission.complete_requirement,REACTIVATE:permission.reactivate};
    if(!allowed[operation]||initial.activity.kind!=='IDLE'||initial.current.requirement_id!==initial.requirement.id||initial.current.document_type!=='CURRENT')throw new TypeError('Actual eligible idle detail required');
    this.operation=operation;this.initial=capture(initial);this.api=api;
  }
  getSnapshot=():LifecycleState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<LifecycleState>):void{if(this.disposed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E lifecycle observer failed',error);}}}
  private run(operation:'SUBMIT'|'RECHECK',work:()=>Promise<boolean>):Promise<boolean>{
    if(this.disposed||this.value.phase==='CONFIRMED')return Promise.resolve(false);if(this.pending)return this.pendingOperation===operation?this.pending:Promise.resolve(false);
    const pending=Promise.resolve().then(()=>this.disposed?false:work()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.pendingOperation=operation;return pending;
  }
  submit():Promise<boolean>{
    if(this.value.phase==='UNKNOWN'||this.value.phase==='READING')return Promise.resolve(false);
    return this.run('SUBMIT',async()=>{
      const id=this.initial.requirement.id,version=this.initial.current.content_version;
      if(!this.action){
        try{this.action=this.operation==='INITIALIZATION'?{kind:'INITIALIZATION',action:this.api.prepareCompleteInitialization(id,version)}:
          this.operation==='COMPLETE'?{kind:'COMPLETE',action:this.api.prepareCompleteRequirement(id,version)}:{kind:'REACTIVATE',action:this.api.prepareReactivateRequirement(id)};}
        catch{this.publish({phase:'ERROR',error:'暂时无法准备变更，请重新读取当前详情'});return false;}
      }
      return this.send();
    });
  }
  retryUnknown():Promise<boolean>{
    if(this.value.phase!=='UNKNOWN'||!this.action)return Promise.resolve(false);
    return this.run('RECHECK',async()=>{
      const controller=new AbortController();this.readController=controller;this.publish({phase:'READING',error:null});
      try{
        const id=this.initial.requirement.id,[root,current,revisions]=await Promise.all([this.api.getRequirement(id,controller.signal),this.api.getCurrentDocument(id,controller.signal),
          this.operation==='INITIALIZATION'?this.api.listRevisions(id,1,controller.signal):Promise.resolve(null)]);
        if(this.disposed)return false;
        if(root.data.id!==id||current.data.id!==this.initial.current.id||current.data.requirement_id!==id||current.data.document_type!=='CURRENT')throw Error('Unconfirmed ownership');
        this.publish({observed:capture({requirement:root.data,current:current.data,revisions:revisions?.data.items??null})});
      }catch{this.publish({phase:'UNKNOWN',error:'变更结果仍待核实，暂时无法读取当前资源；原请求已保留'});return false;}
      finally{if(this.readController===controller)this.readController=undefined;}
      return this.send();
    });
  }
  private async send():Promise<boolean>{
    const original=this.action!;this.publish({phase:'SUBMITTING',error:null});
    try{
      let outcome:LifecycleOutcome;const id=this.initial.requirement.id;
      if(original.kind==='INITIALIZATION'){
        const result=(await original.action.submit()).data;if(this.disposed)return false;
        if(result.requirement.id!==id||result.requirement.status!=='ACTIVE'||result.requirement.document_work_state!=='IDLE'||result.current_document.id!==this.initial.current.id||
          result.current_document.content_version!==this.initial.current.content_version||result.baseline_revision.requirement_id!==id||result.baseline_revision.revision_type!=='BASELINE'||
          result.baseline_revision.version_no!==1||result.baseline_revision.description!=='初始化基线'||result.baseline_revision.source_content_version!==this.initial.current.content_version)throw Error('Unconfirmed baseline receipt');
        outcome=capture({kind:'INITIALIZATION',result});
      }else{
        const root=(await original.action.submit()).data;if(this.disposed)return false;
        if(root.id!==id||root.document_work_state!=='IDLE'||root.status!==(original.kind==='COMPLETE'?'COMPLETED':'ACTIVE')||
          (original.kind==='COMPLETE')!==(root.completed_at!==null))throw Error('Unconfirmed lifecycle receipt');
        outcome=capture({kind:original.kind,requirement:root});
      }
      this.publish({phase:'CONFIRMED',outcome,error:null});this.action=undefined;return true;
    }catch(error){
      if(this.disposed)return false;
      if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message});}
      else this.publish({phase:'UNKNOWN',error:'本次变更结果待核实，请保留原请求并重新确认'});return false;
    }
  }
  dispose():void{this.disposed=true;this.readController?.abort();this.listeners.clear();}
}
