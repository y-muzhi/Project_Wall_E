import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {WalleApi,CreateDocument,DocumentChange,ApiAction} from '../api/walle.ts';
import type {DocumentSummary} from '../api/models.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {ordinaryInput} from '../shared/text.ts';

type CreateResult=Awaited<ReturnType<ReturnType<WalleApi['prepareCreateDocument']>['submit']>>['data'];
type MetadataResult=Awaited<ReturnType<ReturnType<WalleApi['prepareUpdateDocument']>['submit']>>['data'];
type Intent=Readonly<{kind:'CREATE';body:CreateDocument;selected:number|null}|{kind:'METADATA';document:DocumentSummary;change:DocumentChange}>;
export type DirectoryState=Readonly<{phase:'READY'|'SUBMITTING'|'UNKNOWN'|'ERROR'|'CONFIRMED';intent:Intent|null;error:string|null;result:CreateResult|MetadataResult|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** The requirement owns a single retained document maintenance action. A
 * changed reading selection never edits the target or body of that action. */
export class DocumentDirectoryCommands{
 private readonly api:Pick<WalleApi,'prepareCreateDocument'|'prepareUpdateDocument'>;
 private readonly read:()=>Promise<DetailSnapshot>;private readonly select:(identity:number)=>Promise<void>;
 private detail:DetailSnapshot;private action:ApiAction<CreateResult>|ApiAction<MetadataResult>|undefined;
 private value:DirectoryState=Object.freeze({phase:'READY',intent:null,error:null,result:null});
 private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private finishing:Promise<boolean>|undefined;private closed=false;
 constructor(detail:DetailSnapshot,api:Pick<WalleApi,'prepareCreateDocument'|'prepareUpdateDocument'>,read:()=>Promise<DetailSnapshot>,select:(identity:number)=>Promise<void>){this.detail=capture(detail);this.api=api;this.read=read;this.select=select;}
 getSnapshot=():DirectoryState=>this.value;
 subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 get allowed():boolean{return !this.closed&&!this.pending&&['READY','ERROR'].includes(this.value.phase)&&this.detail.requirement.document_work_state==='IDLE';}
 adopt(actual:DetailSnapshot):void{if(actual.requirement.id!==this.detail.requirement.id)throw TypeError('Owned requirement required');this.detail=capture(actual);}
 private publish(changes:Partial<DirectoryState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E directory observer failed',error);}}
 create(body:CreateDocument):Promise<boolean>{
  if(!this.allowed)return Promise.resolve(false);
  const normalized={...body,name:ordinaryInput(body.name,'name',1,80,false)};
  this.action=this.api.prepareCreateDocument(this.detail.requirement.id,normalized);
  this.publish({intent:capture({kind:'CREATE',body:normalized,selected:this.detail.selected_document_id}),result:null,error:null});
  return this.send();
 }
 metadata(document:DocumentSummary,change:DocumentChange):Promise<boolean>{
  if(!this.allowed)return Promise.resolve(false);
  const actual=this.detail.documents.find(item=>item.id===document.id);if(!actual||document.requirement_id!==this.detail.requirement.id)throw TypeError('Actual owned document required');
  if(actual.metadata_version!==document.metadata_version)throw Error('文档属性已更新，请重新读取后操作');
  if(document.archived_at!==null&&change.type!=='RESTORE')throw Error('归档文档仅可阅读或恢复');
  const normalized=change.type==='RENAME'?{...change,name:ordinaryInput(change.name,'name',1,80,false)}:change;
  this.action=this.api.prepareUpdateDocument(document.id,{expected_metadata_version:document.metadata_version,change:normalized});
  this.publish({intent:capture({kind:'METADATA',document,change:normalized}),result:null,error:null});return this.send();
 }
 private send():Promise<boolean>{
  if(this.closed||!this.action)return Promise.resolve(false);if(this.pending)return this.pending;
  const action=this.action;
  const pending=Promise.resolve().then(async()=>{
   this.publish({phase:'SUBMITTING',error:null});
   try{const result=(await action.submit()).data;if(this.closed)return false;this.publish({phase:'CONFIRMED',result:capture(result),error:null});this.action=undefined;return await this.finish();}
   catch(error){if(this.closed)return false;if(this.value.phase==='CONFIRMED'){this.publish({error:'文档操作已保存，暂时无法读取最新详情'});return false;}
    if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message});}
    else this.publish({phase:'UNKNOWN',error:'文档操作结果待核实，原请求与输入已保留'});return false;}
  }).finally(()=>{if(this.pending===pending){this.pending=undefined;this.publish({});}});this.pending=pending;return pending;
 }
 retryUnknown():Promise<boolean>{return this.value.phase==='UNKNOWN'?this.send():Promise.resolve(false);}
 finish():Promise<boolean>{
  if(this.finishing)return this.finishing;if(this.closed||this.value.phase!=='CONFIRMED'||this.value.result===null)return Promise.resolve(false);
  const intent=this.value.intent,result=this.value.result;
  const pending=Promise.resolve().then(async()=>{const actual=await this.read();if(this.closed)return false;this.adopt(actual);
   if(intent?.kind==='CREATE'&&actual.selected_document_id===intent.selected)await this.select(result.document.id);
   if(this.closed)return false;this.publish({phase:'READY',intent:null,result:null,error:null});return true;
  }).finally(()=>{if(this.finishing===pending)this.finishing=undefined;});this.finishing=pending;return pending;
 }
 dispose():void{this.closed=true;this.listeners.clear();}
}
