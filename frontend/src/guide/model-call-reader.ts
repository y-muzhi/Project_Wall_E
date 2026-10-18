import type {WalleApi} from '../api/walle.ts';
import type {ModelCalls,ModelCall} from '../api/model-calls.ts';
export type ModelCallApi=Pick<WalleApi,'listModelCalls'|'getModelCall'>;
export type CallListState=Readonly<{data:ModelCalls|null;loading:boolean;error:string|null}>;
const empty:CallListState=Object.freeze({data:null,loading:false,error:null});

/** Deduplicates visible messages sharing one Run; no timer or command API. */
export class ModelCallReader{
 private slots=new Map<number,CallListState>();private listeners=new Set<()=>void>();private versions=new Map<number,string>();
 private pending=new Map<number,{controller:AbortController;promise:Promise<void>}>();private active=true;private closed=false;
 readonly api:ModelCallApi;readonly requirementId:number;
 constructor(api:ModelCallApi,requirementId:number){this.api=api;this.requirementId=requirementId;}
 subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
 get=(run:number):CallListState=>this.slots.get(run)??empty;
 private publish(run:number,changes:Partial<CallListState>){this.slots.set(run,Object.freeze({...this.get(run),...changes}));for(const listener of this.listeners)listener();}
 setActive(active:boolean){if(this.closed||this.active===active)return;this.active=active;if(!active){this.versions.clear();for(const [run,job] of this.pending){job.controller.abort();this.publish(run,{loading:false});}this.pending.clear();}}
 load(run:number,version:string,force=false):Promise<void>{
  if(this.closed||!this.active)return Promise.resolve();
  if(this.pending.has(run))return this.pending.get(run)!.promise;
  if(!force&&this.versions.get(run)===version)return Promise.resolve();
  this.versions.set(run,version);const controller=new AbortController();this.publish(run,{loading:true,error:null});
  const promise=Promise.resolve().then(async()=>{try{
   const data=(await this.api.listModelCalls(run,controller.signal)).data;
   if(this.closed||!this.active||controller.signal.aborted)return;
   if(data.id!==run||data.requirement_id!==this.requirementId)throw Error('调用记录不属于当前需求');
   this.publish(run,{data,error:null});
  }catch{if(!this.closed&&this.active&&!controller.signal.aborted)this.publish(run,{error:'调用记录读取失败，已读信息仍保留'});}
  finally{if(this.pending.get(run)?.controller===controller){this.pending.delete(run);if(!this.closed)this.publish(run,{loading:false});}}});
  this.pending.set(run,{controller,promise});return promise;
 }
 dispose(){this.setActive(false);this.closed=true;this.listeners.clear();}
}
export function tokenTotal(calls:readonly ModelCall[],field:'input_tokens'|'output_tokens'|'total_tokens'|'cached_tokens'|'duration_ms'):number|null{
 if(!calls.length||calls.some(call=>call[field]===null))return null;
 const value=calls.reduce((sum,call)=>sum+call[field]!,0);return Number.isSafeInteger(value)?value:null;
}
