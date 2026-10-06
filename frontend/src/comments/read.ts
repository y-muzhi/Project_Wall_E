import {positiveInteger,snapshotObject} from '../api/client.ts';
import type {PagePagination} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {CommentItem} from '../api/models.ts';
import type {DocumentReadModel} from '../documents/contracts.ts';

export type CommentIndex=Awaited<ReturnType<WalleApi['getCommentIndex']>>['data'];
type Api=Pick<WalleApi,'listComments'|'getComment'|'getCommentIndex'>;
export type CommentBundle=Readonly<{current:DocumentReadModel;index:CommentIndex;items:readonly CommentItem[];pagination:PagePagination}>;
export type CommentReadState=Readonly<{confirmed:CommentBundle|null;page:number;selected:number|null;loading:boolean;active:boolean;error:string|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
class Changed extends Error{}
const same=(left:unknown,right:unknown)=>JSON.stringify(left)===JSON.stringify(right);

/** I37 is complete; I27 is a real page and I28 can include soft-deleted rows.
 * Independent HTTP snapshots are checked, never advertised as one transaction.
 * A changed ordering/location is reread once, then rejected without replacing
 * the last successful page. No synthetic insertion or status filtering. */
export class RequirementComments{
  private current:DocumentReadModel;private readonly api:Api;private readonly listeners=new Set<()=>void>();
  private value:CommentReadState=Object.freeze({confirmed:null,page:1,selected:null,loading:false,active:true,error:null});
  private generation=0;private closed=false;private controller:AbortController|undefined;private pending:Promise<boolean>|undefined;
  constructor(current:DocumentReadModel,api:Api){this.current=this.ownedCurrent(current);this.api=api;}
  private ownedCurrent(current:DocumentReadModel):DocumentReadModel{positiveInteger(current.id);positiveInteger(current.requirement_id);positiveInteger(current.content_version);if(current.document_type!=='CURRENT')throw TypeError('Actual CURRENT required');return capture(current);}
  getSnapshot=():CommentReadState=>this.value;
  subscribe=(callback:()=>void):(()=>void)=>{this.listeners.add(callback);return()=>this.listeners.delete(callback);};
  get ready():boolean{return !this.closed&&this.value.active&&!this.value.loading&&!this.value.error&&this.value.confirmed!==null&&same(this.current,this.value.confirmed.current);}
  private publish(changes:Partial<CommentReadState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E comment read observer failed',error);}}
  private index(current:DocumentReadModel,index:CommentIndex):void{
    if(index.requirement_id!==current.requirement_id||index.document_id!==current.id)throw Error('Comment index belongs to another document');
    if(index.content_version!==current.content_version)throw new Changed('当前正文已变化，请重新读取详情');
    const ids=new Set(current.block_state_json.blocks.map(block=>block.block_id));
    if(index.blocks.some(block=>!ids.has(block.block_id))||index.comments.some(row=>row.location.status==='ATTACHED'&&!ids.has(row.location.block_id!)))throw Error('Comment index has an unknown block');
  }
  /** Parent has already adopted a fresh complete detail; never use a draft or
   * historical Revision as the anchor document. Old page remains labelled. */
  setCurrent(current:DocumentReadModel):void{
    const next=this.ownedCurrent(current);if(next.requirement_id!==this.current.requirement_id)throw TypeError('Owned requirement required');if(this.closed||same(next,this.current))return;
    this.generation++;this.controller?.abort();this.pending=undefined;this.current=next;this.publish({loading:false,error:'当前正文已更新，请刷新评论',selected:null});
  }
  refresh(page=this.value.page,force=false):Promise<boolean>{
    positiveInteger(page);if(page>100000)throw TypeError('Invalid page');return this.read(page,null,force);
  }
  select(identity:number):Promise<boolean>{positiveInteger(identity);return this.read(null,identity,true);}
  private read(page:number|null,target:number|null,force:boolean):Promise<boolean>{
    if(this.closed)return Promise.resolve(false);if(this.pending&&!force&&page===this.value.page)return this.pending;
    const generation=++this.generation,controller=new AbortController(),current=this.current;this.controller?.abort();this.controller=controller;
    const alive=()=>!this.closed&&generation===this.generation;
    const pending=Promise.resolve().then(async()=>{
      if(!alive())return false;
      try{
        for(let attempt=0;attempt<2;attempt++){
          try{
            const index=(await this.api.getCommentIndex(current.requirement_id,controller.signal)).data;if(!alive())return false;this.index(current,index);
            let desired=page!;
            if(target!==null){
              const actual=(await this.api.getComment(target,controller.signal)).data;if(!alive())return false;
              if(actual.id!==target||actual.requirement_id!==current.requirement_id)throw Error('Comment belongs to another requirement');
              if(actual.deleted_at!==null)throw Error('该评论已删除，请刷新列表');
              const ordinal=index.comments.findIndex(row=>row.id===target);if(ordinal<0)throw new Changed('评论列表已变化，请重试定位');desired=Math.floor(ordinal/20)+1;
            }
            const response=await this.api.listComments(current.requirement_id,desired,controller.signal);if(!alive())return false;
            const latest=(await this.api.getCommentIndex(current.requirement_id,controller.signal)).data;if(!alive())return false;this.index(current,latest);
            const pagination=response.meta.pagination,items=response.data.items,window=index.comments.slice((desired-1)*20,desired*20);
            if(!pagination||!('page' in pagination)||pagination.page!==desired||pagination.page_size!==20||pagination.total!==index.total_count||pagination.total_pages!==Math.ceil(index.total_count/20)||!same(index,latest)||items.length!==window.length)throw new Changed('评论列表读取期间发生变化，请重试');
            for(let i=0;i<items.length;i++){
              const item=items[i]!,projection=window[i]!;
              if(item.requirement_id!==current.requirement_id||item.deleted_at!==null)throw Error('Unconfirmed comment ownership');
              if(item.id!==projection.id||item.status!==projection.status||item.anchor_status!==projection.anchor_status||!same(item.location,projection.location))throw new Changed('评论位置或顺序已变化，请重试');
              const previous=items[i-1];if(previous&&(previous.created_at>item.created_at||previous.created_at===item.created_at&&previous.id>=item.id))throw Error('Unconfirmed comment ordering');
            }
            const confirmed=capture({current,index:latest,items,pagination});
            this.publish({confirmed,page:desired,selected:target??(items.some(row=>row.id===this.value.selected)?this.value.selected:null),loading:false,error:null});return true;
          }catch(error){if(error instanceof Changed&&attempt===0&&alive())continue;throw error;}
        }
        return false;
      }catch(error){if(alive())this.publish({loading:false,error:error instanceof Changed?error.message:error instanceof Error&&error.message.startsWith('该评论已删除')?error.message:'评论读取失败，已显示的实际列表仍保留，请重试'});return false;}
    }).finally(()=>{if(this.pending===pending)this.pending=undefined;if(this.controller===controller)this.controller=undefined;});
    this.pending=pending;this.publish({page:page??this.value.page,loading:true,active:true,error:null});return pending;
  }
  located(identity:number):Readonly<{current:DocumentReadModel;comment:CommentItem}>|null{
    if(!this.ready)return null;const bundle=this.value.confirmed!,comment=bundle.items.find(row=>row.id===identity);
    return comment?.location.status==='ATTACHED'?Object.freeze({current:bundle.current,comment}):null;
  }
  pause():void{if(this.closed)return;this.generation++;this.controller?.abort();this.pending=undefined;this.publish({active:false,loading:false});}
  dispose():void{this.closed=true;this.generation++;this.controller?.abort();this.listeners.clear();}
}
