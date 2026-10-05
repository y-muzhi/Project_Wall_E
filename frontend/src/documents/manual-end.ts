import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {Requirement} from '../api/models.ts';
import type {DocumentReadModel} from './contracts.ts';
import type {EditedSnapshot} from './edited-snapshot.ts';
import type {ManualDraftAutosave} from './autosave.ts';
import type {RequirementEditor} from './editor.ts';
import type {DraftRecoveryStore} from './recovery-store.ts';

type Api = Pick<WalleApi,'getRequirement'|'getCurrentDocument'|'getManualDraft'|'prepareCompleteManualDraft'|'prepareCancelManualDraft'>;
type Editor = Pick<RequirementEditor,'flushLocal'|'setReadonly'>;
type Autosave = Pick<ManualDraftAutosave,'state'|'localSnapshot'|'freezeAndFlush'|'pauseAndWait'|'resumeEditing'|'dispose'>;
type Cache = Pick<DraftRecoveryStore,'clearClosedDraft'>;
type Complete = Readonly<{kind:'COMPLETE';action:ReturnType<WalleApi['prepareCompleteManualDraft']>;version:number;snapshot:EditedSnapshot}>;
type Cancel = Readonly<{kind:'CANCEL';action:ReturnType<WalleApi['prepareCancelManualDraft']>;version:number}>;
export type ManualEndObservation = Readonly<{requirement:Requirement;current:DocumentReadModel;manual_draft:DocumentReadModel|null}>;
export type ManualEndOutcome = Readonly<{kind:'COMPLETED';current:DocumentReadModel}|{kind:'CANCELLED';manual_draft_id:number}>;
export type ManualEndState = Readonly<{phase:'EDITING'|'PREPARING'|'SUBMITTING'|'UNKNOWN'|'CHECKING'|'ERROR'|'CLOSED';
  operation:'COMPLETE'|'CANCEL'|null;error:string|null;observed:ManualEndObservation|null;outcome:ManualEndOutcome|null;local_cleanup_error:boolean}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** One loaded manual session's ending action. Cancellation requires the parent
 * to obtain explicit discard confirmation. GET facts never by themselves
 * prove which ending command committed; original opaque action is replayed. */
export class ManualDraftEnd {
  private readonly api:Api;private readonly editor:Editor;private readonly autosave:Autosave;private readonly cache:Cache;
  private readonly current:DocumentReadModel;private readonly draft:DocumentReadModel;
  private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private pendingOperation:'COMPLETE'|'CANCEL'|undefined;private action:Complete|Cancel|undefined;
  private disposed=false;private value:ManualEndState=Object.freeze({phase:'EDITING',operation:null,error:null,observed:null,outcome:null,local_cleanup_error:false});
  constructor(current:DocumentReadModel,draft:DocumentReadModel,api:Api,editor:Editor,autosave:Autosave,cache:Cache){
    if(current.document_type!=='CURRENT'||draft.document_type!=='MANUAL_DRAFT'||current.id===draft.id||current.requirement_id!==draft.requirement_id||autosave.state.confirmed_version!==draft.content_version)throw new TypeError('Actual current/draft session required');
    this.current=capture(current);this.draft=capture(draft);this.api=api;this.editor=editor;this.autosave=autosave;this.cache=cache;
  }
  getSnapshot=():ManualEndState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<ManualEndState>):void{if(this.disposed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E manual ending observer failed',error);}}}
  private lock():boolean{const valid=this.editor.flushLocal();this.editor.setReadonly(true);return valid;}
  private run(operation:'COMPLETE'|'CANCEL',work:()=>Promise<boolean>):Promise<boolean>{
    if(this.pending)return this.pendingOperation===operation?this.pending:Promise.resolve(false);if(this.disposed||this.value.phase==='CLOSED')return Promise.resolve(false);
    const pending=Promise.resolve().then(work).catch(error=>{if(!this.disposed)this.publish({phase:'ERROR',error:error instanceof ApiRejected?error.message:'暂时无法结束编辑，请保留草稿并重试'});return false;}).finally(()=>{if(this.pending===pending)this.pending=undefined;});
    this.pending=pending;this.pendingOperation=operation;return pending;
  }
  complete():Promise<boolean>{
    if(this.value.phase==='UNKNOWN'||this.value.phase==='CHECKING')return Promise.resolve(false);
    return this.run('COMPLETE',async()=>{
      this.publish({phase:'PREPARING',operation:'COMPLETE',error:null});
      if(!this.lock()){this.publish({phase:'ERROR',error:'当前输入尚未形成有效完整快照，请继续编辑后再完成'});return false;}
      if(!await this.autosave.freezeAndFlush()){this.publish({phase:'ERROR',error:'最新草稿尚未确认保存，请先处理保存状态'});return false;}
      if(this.disposed)return false;await this.autosave.pauseAndWait();if(this.disposed)return false;
      const version=this.autosave.state.confirmed_version,snapshot=capture(this.autosave.localSnapshot);
      this.action=Object.freeze({kind:'COMPLETE',version,snapshot,action:this.api.prepareCompleteManualDraft(this.draft.requirement_id,version)});
      return this.submit();
    });
  }
  cancelConfirmed():Promise<boolean>{
    if(this.value.phase==='UNKNOWN'||this.value.phase==='CHECKING')return Promise.resolve(false);
    return this.run('CANCEL',async()=>{
      this.publish({phase:'PREPARING',operation:'CANCEL',error:null});this.lock();await this.autosave.pauseAndWait();if(this.disposed)return false;
      // Read actual latest version after stopping new saves and waiting the
      // owned in-flight save. An old unknown save may still race; native I13
      // version/occupancy guards decide, never a client assumption of rollback.
      const [root,draft]=await Promise.all([this.api.getRequirement(this.draft.requirement_id),this.api.getManualDraft(this.draft.requirement_id)]);
      if(this.disposed)return false;
      if(root.data.document_work_state!=='MANUAL_EDITING'||root.data.active_operation_id!==this.draft.id||draft.data.id!==this.draft.id)throw Error('Manual occupancy changed');
      const version=draft.data.content_version;
      this.action=Object.freeze({kind:'CANCEL',version,action:this.api.prepareCancelManualDraft(this.draft.requirement_id,version)});
      return this.submit();
    });
  }
  private async observe():Promise<ManualEndObservation>{
    const identity=this.draft.requirement_id;
    const [requirement,current,draft]=await Promise.allSettled([this.api.getRequirement(identity),this.api.getCurrentDocument(identity),this.api.getManualDraft(identity)]);
    if(requirement.status==='rejected')throw requirement.reason;if(current.status==='rejected')throw current.reason;
    if(draft.status==='rejected'&&!(draft.reason instanceof ApiRejected&&draft.reason.code==='MANUAL_DRAFT_NOT_FOUND'))throw draft.reason;
    return capture({requirement:requirement.value.data,current:current.value.data,manual_draft:draft.status==='fulfilled'?draft.value.data:null});
  }
  retryUnknown():Promise<boolean>{
    if(this.value.phase!=='UNKNOWN'||!this.action)return Promise.resolve(false);
    return this.run(this.action.kind,async()=>{
      this.publish({phase:'CHECKING',error:null});
      try{const observed=await this.observe();if(this.disposed)return false;this.publish({observed});}
      catch{this.publish({phase:'UNKNOWN',error:'结果仍待核实，暂时无法读取实际资源；原请求和内容已保留'});return false;}
      return this.submit();
    });
  }
  private async submit():Promise<boolean>{
    const original=this.action!;this.publish({phase:'SUBMITTING',error:null});
    let outcome:ManualEndOutcome;
    try{
      if(original.kind==='COMPLETE'){
        const result=(await original.action.submit()).data;if(this.disposed)return false;
        if(result.document_type!=='CURRENT'||result.id!==this.current.id||result.requirement_id!==this.draft.requirement_id||result.content_version!==this.current.content_version+1||
          result.markdown_content!==original.snapshot.markdown_content||result.block_state_json.next_block_id!==original.snapshot.block_state_json.next_block_id||
          JSON.stringify(result.block_state_json.blocks.map(block=>block.block_id))!==JSON.stringify(original.snapshot.block_state_json.blocks.map(block=>block.block_id)))throw Error('Unconfirmed complete receipt');
        outcome=Object.freeze({kind:'COMPLETED',current:capture(result)});
      }else{
        const result=(await original.action.submit()).data;if(this.disposed)return false;
        if(!result.cancelled||result.requirement_id!==this.draft.requirement_id||result.manual_draft_id!==this.draft.id)throw Error('Unconfirmed cancel receipt');
        outcome=Object.freeze({kind:'CANCELLED',manual_draft_id:result.manual_draft_id});
      }
    }catch(error){
      if(this.disposed)return false;
      if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message});}
      else this.publish({phase:'UNKNOWN',error:'本次结束操作结果待核实，原请求和草稿内容已保留'});
      return false;
    }
    // Confirmed native ending remains confirmed even if browser cache cleanup
    // fails. Never label a successful native commit as a submission failure.
    this.autosave.dispose();this.action=undefined;this.publish({phase:'CLOSED',outcome,error:null});await this.clearLocal();return true;
  }
  async clearLocal():Promise<boolean>{
    if(this.disposed||this.value.phase!=='CLOSED')return false;
    try{await this.cache.clearClosedDraft(this.draft.requirement_id,this.draft.id);this.publish({local_cleanup_error:false});return true;}
    catch{this.publish({local_cleanup_error:true});return false;}
  }
  continueEditing():boolean{
    if(this.disposed||this.pending||this.value.phase!=='ERROR')return false;
    this.action=undefined;this.autosave.resumeEditing();this.editor.setReadonly(false);this.publish({phase:'EDITING',operation:null,error:null});return true;
  }
  dispose():void{this.disposed=true;this.listeners.clear();}
}
