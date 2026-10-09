import {snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {Requirement} from '../api/models.ts';
import type {DocumentReadModel} from './contracts.ts';
import type {RequirementEditor} from './editor.ts';
import type {ManualDraftAutosave} from './autosave.ts';
import type {DraftRecoveryStore,LocalDraftSnapshot} from './recovery-store.ts';

type Api=Pick<WalleApi,'getRequirement'|'getCurrentDocument'|'getManualDraft'>;
type Editor=Pick<RequirementEditor,'restoreLocal'|'setReadonly'>;
type Autosave=Pick<ManualDraftAutosave,'state'|'restoreLocal'|'localSnapshot'>;
type Cache=Pick<DraftRecoveryStore,'get'|'clearIfRevision'>;
export type ManualRecoveryState=Readonly<{phase:'LOADING'|'AVAILABLE'|'COMPARE'|'ERROR'|'RESTORED'|'SERVER_SELECTED';
  checking:boolean;local:LocalDraftSnapshot|null;server:DocumentReadModel|null;error:string|null;storage_error:boolean}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const pairSame=(a:Pick<DocumentReadModel,'markdown_content'|'block_state_json'>,b:Pick<DocumentReadModel,'markdown_content'|'block_state_json'>)=>
  a.markdown_content===b.markdown_content&&JSON.stringify(a.block_state_json)===JSON.stringify(b.block_state_json);

/** Fresh actual manual session. A verified unchanged server baseline with no
 * local snapshot resumes automatically; local recovery remains an explicit choice. No HTTP mutation,
 * guessed receipts, auto merge, cache deletion on 404, or server version
 * adoption from local content. Parent renders both snapshots for comparison. */
export class ManualDraftRecovery {
  private readonly current:DocumentReadModel;private readonly draft:DocumentReadModel;private readonly api:Api;
  private readonly editor:Editor;private readonly autosave:Autosave;private readonly cache:Cache;
  private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private pendingOperation:'INSPECT'|'RESTORE'|'DISCARD'|undefined;private disposed=false;private confirmedFacts=false;
  private value:ManualRecoveryState=Object.freeze({phase:'LOADING',checking:false,local:null,server:null,error:null,storage_error:false});
  constructor(root:Requirement,current:DocumentReadModel,draft:DocumentReadModel,api:Api,editor:Editor,autosave:Autosave,cache:Cache){
    if(root.document_work_state!=='MANUAL_EDITING'||root.status==='COMPLETED'||root.active_operation_type!=='MANUAL_DRAFT'||root.active_operation_id!==draft.id||
      current.document_type!=='CURRENT'||draft.document_type!=='MANUAL_DRAFT'||current.id===draft.id||current.requirement_id!==root.id||draft.requirement_id!==root.id||
      autosave.state.confirmed_version!==draft.content_version||autosave.state.local_revision!==0||!pairSame(autosave.localSnapshot,draft))throw new TypeError('Fresh actual manual session required');
    this.current=capture(current);this.draft=capture(draft);this.api=api;this.editor=editor;this.autosave=autosave;this.cache=cache;editor.setReadonly(true);
  }
  getSnapshot=():ManualRecoveryState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<ManualRecoveryState>):void{
    if(this.disposed)return;this.value=Object.freeze({...this.value,...changes});
    for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E draft recovery observer failed',error);}}
  }
  private run(operation:'INSPECT'|'RESTORE'|'DISCARD',work:()=>Promise<boolean>):Promise<boolean>{
    if(this.disposed||['RESTORED','SERVER_SELECTED'].includes(this.value.phase))return Promise.resolve(false);if(this.pending)return this.pendingOperation===operation?this.pending:Promise.resolve(false);
    const pending=Promise.resolve().then(()=>this.disposed?false:work()).finally(()=>{if(this.pending===pending){this.pending=undefined;this.publish({});}});this.pending=pending;this.pendingOperation=operation;return pending;
  }
  private sameLoaded(draft:DocumentReadModel):boolean{return draft.content_version===this.draft.content_version&&pairSame(draft,this.draft);}
  private async read():Promise<boolean>{
    this.confirmedFacts=false;this.publish({checking:true,error:null});
    const id=this.draft.requirement_id;
    const [root,current,draft,local]=await Promise.allSettled([this.api.getRequirement(id),this.api.getCurrentDocument(id),this.api.getManualDraft(id),this.cache.get(id,this.draft.id)]);
    if(this.disposed)return false;
    if(root.status==='rejected'||current.status==='rejected'||draft.status==='rejected'){
      this.publish({phase:'ERROR',checking:false,error:'暂时无法确认实际编辑会话，本地内容仍保留'});return false;
    }
    const r=root.value.data,c=current.value.data,d=draft.value.data;
    if(r.id!==id||r.status==='COMPLETED'||r.document_work_state!=='MANUAL_EDITING'||r.active_operation_type!=='MANUAL_DRAFT'||r.active_operation_id!==this.draft.id||
      c.document_type!=='CURRENT'||c.id!==this.current.id||c.requirement_id!==id||c.content_version!==this.current.content_version||
      d.document_type!=='MANUAL_DRAFT'||d.id!==this.draft.id||d.requirement_id!==id||d.created_at!==this.draft.created_at){
      this.publish({phase:'ERROR',checking:false,error:'编辑会话或正式正文已变化，请重新读取详情；本地内容仍保留'});return false;
    }
    const saved=capture(d);
    this.confirmedFacts=true;
    if(local.status==='rejected'){
      this.publish({phase:'ERROR',checking:false,server:saved,storage_error:true,error:'本地暂存不可读取；可以继续后端草稿，但跨刷新保护可能不足'});return true;
    }
    const cached=local.value===null?null:capture(local.value),same=this.sameLoaded(saved);
    // Once local recovery content was discovered, its disappearance during a
    // recheck is a change to reconcile, not proof that no choice was needed.
    if(cached===null&&this.value.local!==null){
      this.publish({phase:'ERROR',checking:false,server:saved,storage_error:false,error:'本地暂存已变化，原恢复内容仍保留，请对照并重新检查'});return false;
    }
    // There is no recovery choice when the local store was read successfully,
    // no snapshot exists and the loaded draft is still the verified baseline.
    // Do not apply this shortcut to storage errors or newer server versions.
    if(cached===null&&same&&this.pendingOperation==='INSPECT'){
      this.editor.setReadonly(false);
      this.publish({checking:false,local:null,server:saved,storage_error:false,error:null,phase:'SERVER_SELECTED'});return true;
    }
    this.publish({checking:false,local:cached,server:saved,storage_error:false,error:null,
      phase:cached!==null&&cached.base_confirmed_version===saved.content_version&&same?'AVAILABLE':'COMPARE'});return true;
  }
  inspect():Promise<boolean>{return this.run('INSPECT',()=>this.read());}
  restore():Promise<boolean>{
    if(this.value.phase!=='AVAILABLE'||!this.value.local)return Promise.resolve(false);
    const chosen=this.value.local;
    return this.run('RESTORE',async()=>{
      if(!await this.read()||this.disposed)return false;
      const latest=this.value.local;
      if(this.value.phase!=='AVAILABLE'||!latest)return false;
      if(JSON.stringify(latest)!==JSON.stringify(chosen)){
        this.publish({error:'本地内容已更新，请检查后重新选择恢复'});return false;
      }
      try{this.autosave.restoreLocal(latest,()=>this.editor.restoreLocal(latest));this.editor.setReadonly(false);this.publish({phase:'RESTORED',error:null});return true;}
      catch{this.publish({phase:'ERROR',error:'本地快照无法安全恢复，内容仍保留，可与后端草稿对照'});return false;}
    });
  }
  /** Caller obtains explicit discard confirmation. Revision CAS prevents
   * erasing a newer cache written while the confirmation was open. */
  discardLocalConfirmed():Promise<boolean>{
    if(!this.value.local)return Promise.resolve(false);const chosen=this.value.local;
    return this.run('DISCARD',async()=>{
      if(!await this.read()||this.disposed)return false;
      if(!this.value.local||JSON.stringify(this.value.local)!==JSON.stringify(chosen)){
        this.publish({error:'本地内容已更新，尚未放弃，请重新检查'});return false;
      }
      try{if(!await this.cache.clearIfRevision(this.draft.requirement_id,this.draft.id,chosen.local_revision)){
        await this.read();if(!this.disposed)this.publish({error:'本地暂存已变化，尚未放弃，请重新检查'});return false;
      }}catch{this.publish({storage_error:true,error:'本地内容尚未清除，请保留页面并重试'});return false;}
      if(this.disposed)return false;
      // If another page advanced the draft, the parent mounts this latest
      // server object before permitting input; the old host stays frozen.
      if(this.sameLoaded(this.value.server!))this.editor.setReadonly(false);
      this.publish({phase:'SERVER_SELECTED',local:null,error:null});return true;
    });
  }
  continueServerWithoutLocal():boolean{
    if(!this.canContinueServer)return false;
    this.editor.setReadonly(false);this.publish({phase:'SERVER_SELECTED'});return true;
  }
  get canContinueServer():boolean{return !this.disposed&&!this.pending&&this.confirmedFacts&&this.value.local===null&&this.value.server!==null&&this.sameLoaded(this.value.server)&&
    this.value.phase==='ERROR'&&this.value.storage_error;}
  dispose():void{this.disposed=true;this.listeners.clear();}
}
