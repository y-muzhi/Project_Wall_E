import {ApiRejected,snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {Requirement} from '../api/models.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {detailPermissions} from './permissions.ts';
import {ordinaryInput} from '../shared/text.ts';

export type RequirementProperty='title'|'initialization_mode';
export type PropertyEditState=Readonly<{phase:'VIEW'|'EDITING'|'SUBMITTING'|'UNKNOWN'|'READING'|'OBSERVED'|'CONFIRMED';
  actual:Requirement;draft:string;error:string|null;error_code:string|null;receipt:Requirement|null;
  submitted:Readonly<{field:RequirementProperty;value:string}>|null}>;
type Api=Pick<WalleApi,'prepareUpdateRequirement'|'getRequirement'>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** I04 has no idempotency key. Unknown PATCH is never replayed automatically.
 * A GET confirms present attributes only; the original intention remains
 * visible until explicit continue/cancel, and each Save is a new action. */
export class RequirementPropertyEdit {
  readonly field:RequirementProperty;private readonly api:Api;private detail:DetailSnapshot;
  private value:PropertyEditState;private readonly listeners=new Set<()=>void>();private disposed=false;
  private pending:Promise<boolean>|undefined;private pendingKind:'SAVE'|'READ'|undefined;private controller:AbortController|undefined;
  constructor(field:RequirementProperty,detail:DetailSnapshot,api:Api){
    this.field=field;this.detail=capture(detail);this.api=api;this.check(detail);
    this.value=Object.freeze({phase:'VIEW',actual:this.detail.requirement,draft:this.detail.requirement[field],error:null,error_code:null,receipt:null,submitted:null});
  }
  private check(detail:DetailSnapshot):void{
    if(detail.requirement.id!==this.detail.requirement.id||detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Owned actual detail required');
  }
  getSnapshot=():PropertyEditState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  get allowed():boolean{const p=detailPermissions({...this.detail,requirement:this.value.actual},true);return this.field==='title'?p.title:p.mode;}
  private publish(changes:Partial<PropertyEditState>):void{if(this.disposed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E property observer failed',error);}}}
  begin():boolean{
    if(this.disposed||this.pending||this.value.phase!=='VIEW'||!this.allowed)return false;
    this.publish({phase:'EDITING',draft:this.value.actual[this.field],error:null,error_code:null,receipt:null,submitted:null});return true;
  }
  change(draft:string):void{if(!this.disposed&&!this.pending&&this.value.phase==='EDITING'&&this.allowed)this.publish({draft,error:null,error_code:null});}
  cancel():boolean{
    if(this.disposed||this.pending||!['EDITING','OBSERVED'].includes(this.value.phase))return false;
    this.publish({phase:'VIEW',draft:this.value.actual[this.field],error:null,error_code:null,submitted:null});return true;
  }
  continueEditing():boolean{
    if(this.disposed||this.pending||this.value.phase!=='OBSERVED'||!this.allowed)return false;
    this.publish({phase:'EDITING',error:null,error_code:null,submitted:null});return true;
  }
  /** Caller passes an actual complete read, preserving any unsent intention. */
  adoptDetail(detail:DetailSnapshot):void{if(this.disposed)return;this.check(detail);this.detail=capture(detail);this.publish({actual:this.detail.requirement});}
  finishConfirmed():void{if(!this.disposed&&this.value.phase==='CONFIRMED')this.publish({phase:'VIEW',draft:this.value.actual[this.field],submitted:null});}
  private run(kind:'SAVE'|'READ',work:()=>Promise<boolean>):Promise<boolean>{
    if(this.disposed)return Promise.resolve(false);if(this.pending)return this.pendingKind===kind?this.pending:Promise.resolve(false);
    const pending=Promise.resolve().then(()=>this.disposed?false:work()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.pendingKind=kind;return pending;
  }
  save():Promise<boolean>{
    if(this.value.phase!=='EDITING'&&!(this.pending&&this.pendingKind==='SAVE'))return Promise.resolve(false);
    return this.run('SAVE',async()=>{
      if(!this.allowed){this.publish({error:'当前状态不允许修改此属性，请重新读取详情',error_code:'STATE_CONFLICT'});return false;}
      let value:string;
      try{value=this.field==='title'?ordinaryInput(this.value.draft,'title',1,20,false):this.value.draft;
        if(this.field==='initialization_mode'&&!['IDEATION','DESIGN'].includes(value))throw Error('请选择灵感模式或设计模式');
      }catch(error){this.publish({error:error instanceof Error?error.message:'属性输入不合法',error_code:'INVALID_INPUT'});return false;}
      const submitted=Object.freeze({field:this.field,value});
      const body=this.field==='title'?{title:value}:{initialization_mode:value as 'IDEATION'|'DESIGN'};
      let action:ReturnType<Api['prepareUpdateRequirement']>;
      try{action=this.api.prepareUpdateRequirement(this.value.actual.id,body);}
      catch{this.publish({error:'暂时无法准备保存，输入已保留',error_code:'INVALID_INPUT'});return false;}
      this.publish({phase:'SUBMITTING',submitted,error:null,error_code:null,receipt:null});
      try{
        const actual=(await action.submit()).data;if(this.disposed)return false;
        if(actual.id!==this.detail.requirement.id||actual[this.field]!==value)throw Error('Unconfirmed attribute receipt');
        this.publish({phase:'CONFIRMED',actual:capture(actual),receipt:capture(actual),error:null,error_code:null});return true;
      }catch(error){
        if(this.disposed)return false;
        if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS')this.publish({phase:'EDITING',error:error.message,error_code:error.code});
        else this.publish({phase:'UNKNOWN',submitted,error:'保存结果待核实，请先读取实际属性；本次请求不会自动重发',error_code:null});return false;
      }
    });
  }
  inspectUnknown():Promise<boolean>{
    if(this.value.phase!=='UNKNOWN'&&!(this.pending&&this.pendingKind==='READ'))return Promise.resolve(false);
    return this.run('READ',async()=>{
      const controller=new AbortController();this.controller=controller;this.publish({phase:'READING',error:null});
      try{const actual=(await this.api.getRequirement(this.detail.requirement.id,controller.signal)).data;if(this.disposed)return false;
        if(actual.id!==this.detail.requirement.id)throw Error('Unconfirmed ownership');
        this.publish({phase:'OBSERVED',actual:capture(actual),receipt:null,error:null,error_code:null});return true;
      }catch{this.publish({phase:'UNKNOWN',error:'暂时无法读取实际属性，本次输入和未知结果已保留'});return false;}
      finally{if(this.controller===controller)this.controller=undefined;}
    });
  }
  dispose():void{this.disposed=true;this.controller?.abort();this.listeners.clear();}
}
