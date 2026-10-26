import {snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {ModelCalls,ModelCall} from '../api/model-calls.ts';
export type ModelCallApi=Pick<WalleApi,'listModelCalls'|'getModelCall'>;
export type CallListState=Readonly<{data:ModelCalls|null;loading:boolean;error:string|null}>;
const empty:CallListState=Object.freeze({data:null,loading:false,error:null});
/** Provider facts remain readable even when their own totals disagree. */
export function usageWarning(call:ModelCall):string|null{
 if(call.call_status!=='SUCCEEDED')return null;
 if(call.input_tokens===null||call.output_tokens===null||call.total_tokens===null)return '供应方未完整记录用量。';
 if(call.total_tokens!==call.input_tokens+call.output_tokens||call.cached_tokens!==null&&call.cached_tokens>call.input_tokens)return '供应方用量记录不一致，已保留原始数值。';
 return null;
}

/** Terminal display facts shared by the providers of one detail. A running
 * or still-running attempt never becomes a durable empty-usage cache entry. */
export class ModelCallCache{
 private readonly entries=new Map<number,ModelCalls>();readonly requirementId:number;
 constructor(requirementId:number){this.requirementId=requirementId;}
 get(run:number):ModelCalls|null{return this.entries.get(run)??null;}
 remember(data:ModelCalls):void{if(data.requirement_id!==this.requirementId)throw Error('Foreign call cache');if(['COMPLETED','FAILED','CANCELLED'].includes(data.status)&&data.items.every(call=>call.call_status!=='RUNNING'))this.entries.set(data.id,snapshotObject(data) as unknown as ModelCalls);}
 invalidate(run:number):void{this.entries.delete(run);}
 clear():void{this.entries.clear();}
}

/** Deduplicates visible messages sharing one Run; no timer or command API. */
export class ModelCallReader{
 private slots=new Map<number,CallListState>();private listeners=new Set<()=>void>();private versions=new Map<number,string>();private failed=new Map<number,string>();private readonly cache:ModelCallCache|undefined;
 private pending=new Map<number,{controller:AbortController;promise:Promise<void>}>();private active=true;private closed=false;
 readonly api:ModelCallApi;readonly requirementId:number;
 constructor(api:ModelCallApi,requirementId:number,cache?:ModelCallCache){if(cache&&cache.requirementId!==requirementId)throw Error('Foreign call cache');this.api=api;this.requirementId=requirementId;this.cache=cache;}
 subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
 get=(run:number):CallListState=>this.slots.get(run)??empty;
 private publish(run:number,changes:Partial<CallListState>){this.slots.set(run,Object.freeze({...this.get(run),...changes}));for(const listener of this.listeners)listener();}
 setActive(active:boolean){if(this.closed||this.active===active)return;this.active=active;if(!active){this.versions.clear();this.failed.clear();for(const [run,job] of this.pending){job.controller.abort();this.publish(run,{loading:false});}this.pending.clear();}}
 load(run:number,version:string,force=false):Promise<void>{
  if(this.closed||!this.active)return Promise.resolve();
  if(this.pending.has(run))return this.pending.get(run)!.promise;
  if(!force&&(this.versions.get(run)===version||this.failed.get(run)===version))return Promise.resolve();
  if(force){this.cache?.invalidate(run);this.failed.delete(run);}
  const saved=!force?this.cache?.get(run):null;
  if(saved){this.versions.set(run,version);this.publish(run,{data:saved,loading:false,error:null});return Promise.resolve();}
  const controller=new AbortController();this.publish(run,{loading:true,error:null});
  const promise=Promise.resolve().then(async()=>{try{
   const data=(await this.api.listModelCalls(run,controller.signal)).data;
   if(this.closed||!this.active||controller.signal.aborted)return;
   if(data.id!==run||data.requirement_id!==this.requirementId)throw Error('调用记录不属于当前需求');
   this.cache?.remember(data);this.versions.set(run,version);this.failed.delete(run);this.publish(run,{data,error:null});
  }catch(error){if(!this.closed&&this.active&&!controller.signal.aborted&&!(error instanceof DOMException&&error.name==='AbortError')){this.failed.set(run,version);this.publish(run,{error:'调用记录读取失败，已读信息仍保留'});}}
  finally{if(this.pending.get(run)?.controller===controller){this.pending.delete(run);if(!this.closed)this.publish(run,{loading:false});}}});
  this.pending.set(run,{controller,promise});return promise;
 }
 dispose(){this.setActive(false);this.closed=true;this.listeners.clear();}
}
export function tokenTotal(calls:readonly ModelCall[],field:'input_tokens'|'output_tokens'|'total_tokens'|'cached_tokens'|'duration_ms'):number|null{
 if(!calls.length||calls.some(call=>call[field]===null))return null;
 const value=calls.reduce((sum,call)=>sum+call[field]!,0);return Number.isSafeInteger(value)?value:null;
}
