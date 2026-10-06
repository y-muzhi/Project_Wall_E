import {positiveInteger} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {RevisionSummary} from '../api/models.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {RequirementEditor} from '../documents/editor.ts';
import {ManualDraftSession} from '../documents/manual-session.ts';
import {DocumentNavigation} from '../documents/navigation.ts';
import {RequirementRevisions} from '../revisions/read.ts';
import {RevisionViewer} from '../revisions/viewer.ts';
import type {Revision} from '../revisions/read.ts';
import type {DocumentReadModel} from '../documents/contracts.ts';
import type {SelectionEvent} from '../documents/selection.ts';
import {selectionFromEditorState} from '../documents/editor-selection.ts';
import {editorViewCtx} from '@milkdown/kit/core';
import {suggestionMarkdown} from '../suggestions/preview.ts';

export type DocumentOwnerState=Readonly<{mode:'LOADING'|'CURRENT'|'MANUAL'|'HISTORY';busy:boolean;detail:DetailSnapshot|null;
  manual:ManualDraftSession|null;navigation:DocumentNavigation|null;revision:Revision|null;error:string|null;save_warning:boolean;restoration_conflict:DetailSnapshot|null;active:boolean;selection:SelectionEvent|null}>;
export type CurrentDocumentBinding=Readonly<{root:HTMLElement;editor:RequirementEditor;navigation:DocumentNavigation}>;
type LiveDocument={host:HTMLElement;editor:RequirementEditor;session:ManualDraftSession|null;navigation:DocumentNavigation;document:DocumentReadModel;release:()=>void;binding:CurrentDocumentBinding};
type HistoryDocument={host:HTMLElement;viewer:RevisionViewer;navigation:DocumentNavigation};
const same=(left:unknown,right:unknown)=>JSON.stringify(left,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])):value)===
  JSON.stringify(right,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])):value);

/** The real detail document lifetime. Owned hosts keep CURRENT/draft and
 * immutable Revision apart. A historical view parks, never recreates, an
 * unfinished manual editor/ledger/cache. Complete actual reads gate restoration.
 * No AI/comment command or fake business state is provided here. */
export class RequirementDocumentOwner{
  readonly revisions:RequirementRevisions;private readonly identity:number;private readonly api:WalleApi;private readonly root:HTMLElement;
  private readonly scrollport:HTMLElement|null;private readonly readActual:()=>Promise<DetailSnapshot>;private live:LiveDocument|undefined;private history:HistoryDocument|undefined;
  private readonly listeners=new Set<()=>void>();private tail:Promise<unknown>=Promise.resolve();private jobs=0;private closed=false;private retiring:Promise<void>|undefined;private refreshing:Promise<DetailSnapshot>|undefined;
  private value:DocumentOwnerState=Object.freeze({mode:'LOADING',busy:false,detail:null,manual:null,navigation:null,revision:null,error:null,save_warning:false,restoration_conflict:null,active:true,selection:null});
  constructor(root:HTMLElement,identity:number,api:WalleApi,readActual:()=>Promise<DetailSnapshot>,scrollport:HTMLElement|null=null){
    this.root=root;this.identity=positiveInteger(identity);this.api=api;this.readActual=readActual;this.scrollport=scrollport;this.revisions=new RequirementRevisions(identity,api);
  }
  getSnapshot=():DocumentOwnerState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  get historical():boolean{return this.revisions.getSnapshot().history.phase!=='CLOSED';}
  get writeReady():boolean{return !this.closed&&!this.value.busy&&!this.value.error&&!this.historical&&this.live!==undefined&&!this.live.session?.getSnapshot().blocked;}
  get currentBinding():CurrentDocumentBinding|null{return this.writeReady&&this.value.mode==='CURRENT'&&this.live?.document.document_type==='CURRENT'?this.live.binding:null;}
  previewMarkdown(markdown:string,columns?:number):DocumentFragment{if(this.closed||!this.live)throw Error('Actual parser is unavailable');return this.live.editor.action(ctx=>suggestionMarkdown(ctx,markdown,columns));}
  private publish(changes:Partial<DocumentOwnerState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E document owner observer failed',error);}}
  private enqueue<T>(operation:()=>Promise<T>):Promise<T>{
    if(this.closed)return Promise.reject(Error('Document owner is closed'));this.jobs++;this.publish({busy:true});
    const pending=this.tail.then(async()=>{if(this.closed)throw Error('Document owner is closed');return operation();});this.tail=pending.catch(()=>undefined);
    return pending.finally(()=>{this.jobs--;if(!this.jobs)this.publish({busy:false});});
  }
  private owned(actual:DetailSnapshot):void{if(actual.requirement.id!==this.identity||actual.current.requirement_id!==this.identity||actual.current.document_type!=='CURRENT')throw TypeError('Actual owned detail required');}
  private container():HTMLElement{const host=document.createElement('div');host.className='document-owner-host';host.hidden=true;host.inert=true;this.root.append(host);return host;}
  private async retireLive(live:LiveDocument):Promise<void>{live.release();live.navigation.dispose();if(live.session)await live.session.retire();else await live.editor.destroy();live.host.remove();}
  private async retireHistory(history:HistoryDocument):Promise<void>{history.navigation.dispose();await history.viewer.destroy();history.host.remove();}
  private async makeLive(actual:DetailSnapshot):Promise<LiveDocument>{
    const host=this.container();let editor:RequirementEditor|undefined,session:ManualDraftSession|undefined,navigation:DocumentNavigation|undefined;
    try{const document=actual.activity.kind==='MANUAL'?actual.activity.draft:actual.current;
      if(actual.activity.kind==='MANUAL'){session=await ManualDraftSession.create(host,actual,this.api);editor=session.editor;}else editor=await RequirementEditor.create(host,document,true,{selection:selected=>{if(!this.closed&&this.live?.host===host&&this.value.mode==='CURRENT')this.publish({selection:selected});}});
      navigation=DocumentNavigation.forEditor(host,editor,this.scrollport);const result:LiveDocument={host,editor,session:session??null,navigation,document,release:()=>undefined,binding:Object.freeze({root:host,editor,navigation})};
      if(session){const owned=session;result.release=owned.subscribe(()=>{if(this.closed||this.live!==result)return;navigation?.refresh();this.publish({manual:owned});});await owned.recovery.inspect();}
      if(this.closed)throw Error('Retired creation');return result;
    }catch(error){navigation?.dispose();if(session)await session.retire();else await editor?.destroy();host.remove();throw error;}
  }
  private async adoptLive(actual:DetailSnapshot):Promise<void>{
    this.owned(actual);const previous=this.live;
    if(previous?.session&&previous.session.ending.getSnapshot().phase!=='CLOSED'){
      // Existing local content is the authority for this editor. A fresh GET
      // may confirm its saved baseline, but may never replace it.
      if(!previous.session.revalidate(actual))throw Error('实际正文或草稿已变化，本地编辑器仍保留，请对照处理');
      previous.navigation.refresh();this.publish({detail:actual,manual:previous.session,error:null});return;
    }
    if(previous&&!previous.session&&actual.activity.kind!=='MANUAL'&&same(previous.document,actual.current)){
      this.publish({detail:actual,error:null,manual:null});return;
    }
    const created=await this.makeLive(actual);if(this.closed){await this.retireLive(created);throw Error('Retired creation');}
    this.live=created;if(previous)await this.retireLive(previous);this.publish({detail:actual,manual:created.session,error:null});
  }
  private revealLive():void{if(!this.live)return;this.live.host.hidden=false;this.live.host.inert=false;this.live.navigation.setVisible(true);this.live.navigation.refresh();
    let selection:SelectionEvent|null=null;if(!this.live.session)try{const input=this.live.document;selection=this.live.editor.action(ctx=>selectionFromEditorState(ctx.get(editorViewCtx).state,{document_id:input.id,content_version:input.content_version}));}catch{}
    this.publish({mode:this.live.session?'MANUAL':'CURRENT',navigation:this.live.navigation,revision:null,save_warning:false,restoration_conflict:null,selection});}
  adopt(actual:DetailSnapshot):Promise<void>{return this.enqueue(async()=>{
    if(this.historical)throw Error('History must be restored with a fresh exit read');
    try{await this.adoptLive(actual);this.revealLive();}catch(error){this.publish({error:error instanceof Error?error.message:'实际正文暂时无法展示，现有内容仍保留'});throw error;}
  });}
  refresh():Promise<DetailSnapshot>{
    if(this.refreshing)return this.refreshing;
    const pending=this.enqueue(async()=>{try{const actual=await this.readActual();if(this.closed)throw Error('Retired read');if(this.historical)throw Error('Use fresh history exit');await this.adoptLive(actual);this.revealLive();return actual;}
      catch(error){this.publish({error:'实际详情暂时无法采用，现有正文和编辑内容仍保留'});throw error;}}).finally(()=>{if(this.refreshing===pending)this.refreshing=undefined;});this.refreshing=pending;return pending;
  }
  openHistory(summary:RevisionSummary):Promise<boolean>{return this.enqueue(async()=>{
    if(summary.requirement_id!==this.identity)throw TypeError('Owned revision required');
    const live=this.live;if(!live)throw Error('Actual document must be loaded first');
    let saved=true;if(live.session)saved=await live.session.blockAndSave('HISTORY');
    if(this.closed)return false;live.navigation.setVisible(false);live.host.hidden=true;live.host.inert=true;
    this.publish({mode:'HISTORY',navigation:this.history?.navigation??null,error:null,save_warning:!saved,selection:null});
    if(!await this.revisions.open(summary)){this.publish({error:'历史读取失败，草稿和原正文仍保留'});return false;}
    const snapshot=this.revisions.getSnapshot().history.snapshot!;
    if(this.history?.viewer.snapshot.id===snapshot.id){this.publish({revision:snapshot,navigation:this.history.navigation});return true;}
    const host=this.container();let viewer:RevisionViewer|undefined,navigation:DocumentNavigation|undefined;
    try{viewer=await RevisionViewer.create(host,snapshot);navigation=DocumentNavigation.forRevision(host,viewer,this.scrollport);if(this.closed)throw Error('Retired history');
      const previous=this.history;this.history={host,viewer,navigation};host.hidden=false;host.inert=false;navigation.refresh();if(previous)await this.retireHistory(previous);
      this.publish({revision:snapshot,navigation,error:null});return true;
    }catch{navigation?.dispose();await viewer?.destroy();host.remove();this.publish({error:'历史正文暂时无法展示，原正文和草稿仍保留，请重试读取'});return false;}
  });}
  exitHistory():Promise<boolean>{return this.enqueue(async()=>{
    const actual=await this.revisions.exit(this.readActual);if(actual===null){this.publish({error:'实际详情读取失败，历史和草稿仍保留'});return false;}
    try{await this.adoptLive(actual);if(this.closed)return false;
      // Adoption completes before the history controller records CLOSED.
      if(!this.revisions.finishExit(actual))throw Error('History restoration was retired');
      const previous=this.history;this.history=undefined;if(previous)await this.retireHistory(previous);this.revealLive();return true;
    }catch(error){this.publish({error:error instanceof Error?error.message:'实际视图无法恢复，历史和草稿仍保留',restoration_conflict:this.live?.session?.getSnapshot().block_reason==='READ_CONFLICT'?actual:null});return false;}
  });}
  async blockAndSave():Promise<void>{this.value.navigation?.setVisible(false);if(this.live?.session&&!await this.live.session.blockAndSave('VIEWPORT'))throw Error('草稿尚未同步');}
  async restoreSupported():Promise<void>{if(!this.historical){await this.refresh();return;}await this.enqueue(async()=>{const actual=await this.readActual();this.owned(actual);if(this.closed)throw Error('Retired viewport read');this.publish({detail:actual});this.history?.navigation.setVisible(true);});}
  prepareLeave(){return this.live?.session?.prepareLeave()??Promise.resolve(Object.freeze({saved:true,local_protected:true}));}
  continueAfterFailedLeave():boolean{return this.live?.session?.continueAfterFailedLeave()??true;}
  retire():Promise<void>{if(this.retiring)return this.retiring;this.live?.editor.setReadonly(true);this.publish({active:false,busy:false});this.closed=true;this.revisions.dispose();this.listeners.clear();
    const pending=(async()=>{await this.tail;if(this.history)await this.retireHistory(this.history);if(this.live)await this.retireLive(this.live);this.history=undefined;this.live=undefined;})();this.retiring=pending;return pending;
  }
}
