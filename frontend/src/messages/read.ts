import {positiveInteger,snapshotObject} from '../api/client.ts';
import type {CursorPagination} from '../api/client.ts';
import type {Message} from '../api/models.ts';
import type {WalleApi} from '../api/walle.ts';
export type MessageReadState=Readonly<{items:readonly Message[]|null;next_cursor:number|null;has_more:boolean;loading:boolean;active:boolean;error:string|null;request:'LATEST'|'OLDER';revision:number}>;
const origin=(row:Message)=>JSON.stringify([row.id,row.requirement_id,row.guide_run_id,row.sequence_no,row.role,row.content,row.message_type,row.reply_to_message_id,row.created_at]);
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** Actual cursor windows; refresh rereads through the already displayed
 * earliest message so a large arrival cannot silently leave a gap. No total,
 * optimistic messages or inference of card availability is introduced. */
export class RequirementMessages{
 private readonly identity:number;private readonly api:Pick<WalleApi,'listMessages'>;private readonly listeners=new Set<()=>void>();
 private value:MessageReadState=Object.freeze({items:null,next_cursor:null,has_more:false,loading:false,active:true,error:null,request:'LATEST',revision:0});
 private generation=0;private closed=false;private controller:AbortController|undefined;private pending:Promise<boolean>|undefined;
 constructor(identity:number,api:Pick<WalleApi,'listMessages'>){this.identity=positiveInteger(identity);this.api=api;}
 getSnapshot=():MessageReadState=>this.value;
 subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<MessageReadState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E message observer failed',error);}}
 refresh():Promise<boolean>{return this.read('LATEST');}
 older():Promise<boolean>{if(this.pending)return this.pending;if(!this.value.active||!this.value.has_more||this.value.next_cursor===null)return Promise.resolve(false);return this.read('OLDER');}
 private read(kind:MessageReadState['request']):Promise<boolean>{
  if(this.closed)return Promise.resolve(false);if(this.pending&&this.value.request===kind)return this.pending;
  const generation=++this.generation,controller=new AbortController(),before=this.value.items,initialCursor=kind==='OLDER'?this.value.next_cursor:null;
  this.controller?.abort();this.controller=controller;const alive=()=>!this.closed&&generation===this.generation;
  const pending=Promise.resolve().then(async()=>{
   if(!alive())return false;
   try{
    const received:Message[]=[],bound=kind==='LATEST'?before?.[0]?.sequence_no:undefined;let cursor=initialCursor,pagination:CursorPagination;
    for(;;){
     const response=await this.api.listMessages(this.identity,cursor,controller.signal);if(!alive())return false;
     const meta=response.meta.pagination;if(!meta||!('has_more' in meta)||meta.page_size!==20||response.data.items.length>20)throw Error('Actual message cursor required');pagination=meta;
     const rows=response.data.items;let previous=0;const ids=new Set<number>();
     for(const row of rows){if(row.requirement_id!==this.identity||row.sequence_no<=previous||cursor!==null&&row.sequence_no>=cursor||ids.has(row.id))throw Error('Unconfirmed message window');positiveInteger(row.id);positiveInteger(row.sequence_no);ids.add(row.id);previous=row.sequence_no;}
     if(meta.has_more?rows.length===0||meta.next_cursor!==rows[0]!.sequence_no:meta.next_cursor!==null)throw Error('Unconfirmed continuation');
     received.push(...rows);
     if(kind==='OLDER'||bound===undefined||rows.some(row=>row.sequence_no===bound)||!meta.has_more)break;
     if(rows[0]!.sequence_no<bound)throw Error('Previously visible message missing');cursor=meta.next_cursor;
    }
    if(bound!==undefined&&!received.some(row=>row.sequence_no===bound))throw Error('Previously visible message missing');
    const merged=new Map<number,Message>((before??[]).map(row=>[row.id,row]));
    for(const row of received){const previous=merged.get(row.id);if(previous&&origin(previous)!==origin(row))throw Error('Immutable message changed');merged.set(row.id,capture(row));}
    const items=[...merged.values()].sort((a,b)=>a.sequence_no-b.sequence_no);if(new Set(items.map(row=>row.sequence_no)).size!==items.length)throw Error('Sequence identity collision');
    this.publish({items:Object.freeze(items),next_cursor:pagination.next_cursor,has_more:pagination.has_more,loading:false,error:null,revision:this.value.revision+1});return true;
   }catch{if(alive())this.publish({loading:false,error:kind==='OLDER'?'更早消息读取失败，当前会话及原游标仍保留，请重试':'消息读取失败，已显示会话仍保留，请重试'});return false;}
  }).finally(()=>{if(this.pending===pending)this.pending=undefined;if(this.controller===controller)this.controller=undefined;});
  this.pending=pending;this.publish({loading:true,active:true,error:null,request:kind});return pending;
 }
 pause():void{if(this.closed)return;this.generation++;this.controller?.abort();this.pending=undefined;this.publish({active:false,loading:false});}
 dispose():void{this.closed=true;this.generation++;this.controller?.abort();this.listeners.clear();}
}
