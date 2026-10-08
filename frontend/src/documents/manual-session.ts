import type {WalleApi} from '../api/walle.ts';
import {snapshotObject} from '../api/client.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import type {PollClock} from '../guide/polling.ts';
import {RequirementEditor} from './editor.ts';
import {ManualDraftAutosave} from './autosave.ts';
import {DraftRecoveryStore} from './recovery-store.ts';
import {ManualDraftRecovery} from './manual-recovery.ts';
import {ManualDraftEnd} from './manual-end.ts';
import type {SelectionEvent} from './selection.ts';

type BlockReason='VIEWPORT'|'LEAVING'|'HISTORY'|'READ_CONFLICT';
export type ManualSessionState=Readonly<{active:boolean;valid:boolean;readonly:boolean;blocked:boolean;block_reason:BlockReason|null;error:string|null;selection:SelectionEvent|null}>;
export type ManualLeaveResult=Readonly<{saved:boolean;local_protected:boolean}>;
function canonical(value:unknown):string {
  return JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
}

/** One real manual editor lifetime. Parent supplies a fully confirmed detail
 * bundle and retains this instance through viewport changes/read failures.
 * Fresh facts can unlock only the same confirmed baseline, never overwrite
 * local content or stand in for a save/ending receipt. */
export class ManualDraftSession {
  readonly editor:RequirementEditor;readonly autosave:ManualDraftAutosave;readonly cache:DraftRecoveryStore;
  readonly recovery:ManualDraftRecovery;readonly ending:ManualDraftEnd;
  private readonly initial:DetailSnapshot;private readonly listeners=new Set<()=>void>();private readonly releases:(()=>void)[]=[];
  private value:ManualSessionState;private closed=false;private retiring:Promise<void>|undefined;private saving:Promise<boolean>|undefined;
  private constructor(initial:DetailSnapshot,editor:RequirementEditor,autosave:ManualDraftAutosave,cache:DraftRecoveryStore,api:WalleApi){
    if(initial.activity.kind!=='MANUAL')throw new TypeError('Actual manual detail required');
    this.initial=snapshotObject(initial) as unknown as DetailSnapshot;this.editor=editor;this.autosave=autosave;this.cache=cache;
    this.recovery=new ManualDraftRecovery(initial.requirement,initial.current,initial.activity.draft,api,editor,autosave,cache);
    this.ending=new ManualDraftEnd(initial.current,initial.activity.draft,api,editor,autosave,cache);
    this.value=Object.freeze({active:true,valid:editor.valid,readonly:editor.readonly,blocked:false,block_reason:null,error:null,selection:null});
    this.releases.push(this.recovery.subscribe(()=>this.sync()),this.ending.subscribe(()=>this.sync()),this.autosave.subscribe(()=>this.sync()));
  }
  static async create(root:HTMLElement,initial:DetailSnapshot,api:WalleApi,diagnostic:Readonly<{cacheName?:string;clock?:PollClock}>={}):Promise<ManualDraftSession>{
    if(initial.activity.kind!=='MANUAL')throw new TypeError('Actual manual detail required');let session:ManualDraftSession|undefined,cache:DraftRecoveryStore|undefined;
    const editor=await RequirementEditor.create(root,initial.activity.draft,true,{change:()=>session?.autosave.changed(),
      validity:valid=>session?.publish({valid}),error:error=>{if(error!==null||session?.getSnapshot().block_reason!=='READ_CONFLICT')session?.publish({error});},selection:selection=>session?.publish({selection}),blur:()=>{void session?.flushCurrent();}},initial.requirement.status==='INITIALIZING'?initial.requirement:null);
    try{
      cache=editor.action(ctx=>new DraftRecoveryStore(ctx,diagnostic.cacheName?{name:diagnostic.cacheName}:{}));const id=initial.requirement.id;
      const autosave=new ManualDraftAutosave(initial.activity.draft,editor.ledger!,{read:async()=>(await api.getManualDraft(id)).data,
        save:async ticket=>(await api.prepareSaveManualDraft(id,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data},cache,diagnostic.clock);
      session=new ManualDraftSession(initial,editor,autosave,cache,api);
      const owner=root.ownerDocument,visibility=()=>{if(owner.hidden)void session?.flushCurrent();};owner.addEventListener('visibilitychange',visibility);
      session.releases.push(()=>owner.removeEventListener('visibilitychange',visibility));return session;
    }catch(error){await cache?.settle();await editor.destroy();cache?.close();throw error;}
  }
  getSnapshot=():ManualSessionState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<ManualSessionState>):void {
    if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E manual session observer failed',error);}}
  }
  private sync():void {if(this.closed)return;if(this.value.blocked)this.editor.setReadonly(true);this.publish({valid:this.editor.valid,readonly:this.editor.readonly});}
  private chosen():boolean{return ['RESTORED','SERVER_SELECTED'].includes(this.recovery.getSnapshot().phase);}
  async flushCurrent():Promise<boolean>{
    if(this.closed||this.value.blocked||!this.chosen()||this.ending.getSnapshot().phase!=='EDITING'||!this.editor.flushLocal())return false;
    await this.autosave.flush();return !this.closed&&this.editor.valid&&this.autosave.state.status==='SAVED';
  }
  /** Synchronous input lock precedes the first await. Only the actual latest
   * complete editor snapshot is submitted; an unfinished composition fails. */
  blockAndSave(reason:'VIEWPORT'|'LEAVING'|'HISTORY'='VIEWPORT'):Promise<boolean>{
    if(this.closed)return Promise.resolve(false);
    const conflicted=this.value.block_reason==='READ_CONFLICT',valid=this.editor.flushLocal();this.editor.setReadonly(true);this.publish({blocked:true,block_reason:conflicted?'READ_CONFLICT':reason,readonly:true,valid:this.editor.valid});
    if(conflicted)return Promise.resolve(false);
    if(this.ending.getSnapshot().phase==='CLOSED')return Promise.resolve(true);
    if(this.saving)return this.saving;
    const pending=Promise.resolve().then(async()=>{
      if(this.closed||!valid||!this.chosen()||this.ending.getSnapshot().phase!=='EDITING')return false;
      try{return await this.autosave.freezeAndFlush();}catch{return false;}
    }).finally(()=>{if(this.saving===pending)this.saving=undefined;});this.saving=pending;return pending;
  }
  /** Parent obtains this snapshot with actual complete detail reads AFTER the
   * blocked save settles. Mismatch keeps the original editor/cache frozen. */
  revalidate(actual:DetailSnapshot):boolean {
    if(this.closed||this.saving||this.ending.getSnapshot().phase!=='EDITING')return false;
    const root=actual.requirement,expected=this.initial.requirement;
    if(root.id!==expected.id||root.status==='COMPLETED'||root.document_work_state!=='MANUAL_EDITING'||root.active_operation_type!=='MANUAL_DRAFT'||
      actual.activity.kind!=='MANUAL'||root.active_operation_id!==this.autosave.confirmedDocument.id||
      canonical(actual.current)!==canonical(this.initial.current)||canonical(actual.activity.draft)!==canonical(this.autosave.confirmedDocument)){
      this.editor.setReadonly(true);this.publish({blocked:true,block_reason:'READ_CONFLICT',readonly:true,error:'实际正文或草稿已变化，当前内容仍保留，请对照处理'});return false;
    }
    this.publish({blocked:false,block_reason:null,error:null});if(this.chosen()){this.autosave.resumeEditing();this.editor.setReadonly(false);}this.sync();return true;
  }
  async prepareLeave():Promise<ManualLeaveResult>{
    const saved=await this.blockAndSave('LEAVING');await this.cache.settle();let protectedLocal=false;
    if(!saved&&!this.closed&&this.editor.valid&&this.autosave.state.local_revision>0){
      try{const local=await this.cache.get(this.initial.requirement.id,this.autosave.confirmedDocument.id);protectedLocal=local!==null&&local.local_revision===this.autosave.state.local_revision&&
        local.markdown_content===this.autosave.localSnapshot.markdown_content&&canonical(local.block_state_json)===canonical(this.autosave.localSnapshot.block_state_json);}catch{/* Protection is explicitly unavailable, never guessed. */}
    }
    return Object.freeze({saved,local_protected:protectedLocal});
  }
  continueAfterFailedLeave():boolean {
    if(this.closed||this.saving||this.value.block_reason!=='LEAVING'||this.ending.getSnapshot().phase!=='EDITING')return false;
    this.publish({blocked:false,block_reason:null});if(this.chosen()){this.autosave.resumeEditing();this.editor.setReadonly(false);}this.sync();return true;
  }
  /** Route owner calls only after leave is allowed. This never cancels business
   * or clears an unconfirmed draft. The real parser/context survives pending
   * save and IndexedDB opening/transactions, including a late cache clear. */
  retire():Promise<void>{
    if(this.retiring)return this.retiring;this.editor.setReadonly(true);this.publish({active:false,blocked:true,readonly:true});this.closed=true;
    for(const release of this.releases)release();this.listeners.clear();this.recovery.dispose();this.ending.dispose();
    const retiring=(async()=>{try{await this.autosave.pauseAndWait();await this.cache.settle();this.autosave.dispose();await this.editor.destroy();}finally{this.cache.close();}})();this.retiring=retiring;return retiring;
  }
}
