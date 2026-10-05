import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {RevisionSummary} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {detailPermissions} from '../requirements/permissions.ts';
import {ordinaryInput} from '../shared/text.ts';
type Api=Pick<WalleApi,'prepareCreateRevision'|'listRevisions'>;
export type RevisionSaveState=Readonly<{phase:'READY'|'SUBMITTING'|'READING'|'UNKNOWN'|'ERROR'|'CONFIRMED';description:string;error:string|null;error_code:string|null;receipt:RevisionSummary|null;observed:readonly RevisionSummary[]|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** One explicit MANUAL revision intention. CURRENT version is independent
 * of version_no. Similar descriptions in a list never prove this creation. */
export class RequirementRevisionSave {
  private detail:DetailSnapshot;private readonly api:Api;private action:ReturnType<WalleApi['prepareCreateRevision']>|undefined;private submittedDescription:string|null=null;
  private value:RevisionSaveState=Object.freeze({phase:'READY',description:'',error:null,error_code:null,receipt:null,observed:null});
  private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private kind:'SAVE'|'READ'|undefined;private controller:AbortController|undefined;private closed=false;
  constructor(detail:DetailSnapshot,api:Api){if(!detailPermissions(detail,true).revision_save||detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Actual active idle CURRENT required');this.detail=capture(detail);this.api=api;}
  getSnapshot=():RevisionSaveState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  get allowed():boolean{return !this.closed&&detailPermissions(this.detail,true).revision_save;}
  private publish(changes:Partial<RevisionSaveState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E revision save observer failed',error);}}}
  change(description:string):void{if(!this.closed&&!this.pending&&['READY','ERROR'].includes(this.value.phase))this.publish({description,error:null,error_code:null});}
  rebase(actual:DetailSnapshot):boolean{if(this.closed||this.pending||!['READY','ERROR'].includes(this.value.phase))return false;if(actual.requirement.id!==this.detail.requirement.id||actual.current.requirement_id!==actual.requirement.id||actual.current.document_type!=='CURRENT')throw TypeError('Owned actual CURRENT required');this.detail=capture(actual);this.action=undefined;return true;}
  private run(kind:'SAVE'|'READ',work:()=>Promise<boolean>):Promise<boolean>{if(this.closed)return Promise.resolve(false);if(this.pending)return this.kind===kind?this.pending:Promise.resolve(false);const pending=Promise.resolve().then(()=>this.closed?false:work()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.kind=kind;return pending;}
  save():Promise<boolean>{
    if(!['READY','ERROR'].includes(this.value.phase)&&!(this.pending&&this.kind==='SAVE'))return Promise.resolve(false);
    return this.run('SAVE',async()=>{
      if(!this.allowed){this.publish({phase:'ERROR',error:'当前状态不允许保存版本，请重新读取详情',error_code:'STATE_CONFLICT'});return false;}
      try{const text=ordinaryInput(this.value.description,'description',0,1000);this.submittedDescription=text||null;this.action=this.api.prepareCreateRevision(this.detail.requirement.id,{expected_version:this.detail.current.content_version,description:this.submittedDescription});}
      catch(error){this.publish({phase:'ERROR',error:error instanceof Error?error.message:'无法准备保存版本',error_code:'INVALID_INPUT'});return false;}
      return this.send();
    });
  }
  retryUnknown():Promise<boolean>{
    if(this.value.phase!=='UNKNOWN'||!this.action)return Promise.resolve(false);
    return this.run('READ',async()=>{const controller=new AbortController();this.controller=controller;this.publish({phase:'READING',error:null});
      try{const rows=(await this.api.listRevisions(this.detail.requirement.id,1,controller.signal)).data.items;if(this.closed)return false;if(rows.some(row=>row.requirement_id!==this.detail.requirement.id))throw Error('Ownership');this.publish({observed:capture({rows}).rows});}
      catch{this.publish({phase:'UNKNOWN',error:'版本结果仍待核实，暂时无法读取列表；原请求和说明已保留'});return false;}
      finally{if(this.controller===controller)this.controller=undefined;}return this.send();});
  }
  private async send():Promise<boolean>{this.publish({phase:'SUBMITTING',error:null,error_code:null});
    try{const receipt=(await this.action!.submit()).data;if(this.closed)return false;if(receipt.requirement_id!==this.detail.requirement.id||receipt.revision_type!=='MANUAL'||receipt.source_content_version!==this.detail.current.content_version||receipt.description!==this.submittedDescription)throw Error('Unconfirmed revision');
      this.publish({phase:'CONFIRMED',receipt:capture(receipt),error:null,error_code:null});this.action=undefined;return true;
    }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message,error_code:error.code});}
      else this.publish({phase:'UNKNOWN',error:'保存版本结果待核实，请保留原请求并重新确认'});return false;}
  }
  dispose():void{this.closed=true;this.controller?.abort();this.listeners.clear();}
}
