import {positiveInteger,snapshotObject} from '../api/client.ts';
import type {PagePagination} from '../api/client.ts';
import {runStatuses,runActions} from '../api/models.ts';
import type {GuideSummary} from '../api/models.ts';
import type {GuideFilters,WalleApi} from '../api/walle.ts';
export type RunHistoryQuery=Readonly<{page:number;status:readonly (typeof runStatuses[number])[];action_type:readonly (typeof runActions[number])[]}>;
export type RunHistoryState=Readonly<{requested:RunHistoryQuery;confirmed:Readonly<{query:RunHistoryQuery;items:readonly GuideSummary[];pagination:PagePagination}>|null;loading:boolean;active:boolean;error:string|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
export function runHistoryQuery(input:GuideFilters={}):RunHistoryQuery{
 const page=positiveInteger(input.page??1);if(page>100000)throw TypeError('Invalid history page');
 const status=input.status??[],actions=input.action_type??[];if(status.some(value=>!runStatuses.includes(value))||actions.some(value=>!runActions.includes(value)))throw TypeError('Invalid history filter');
 return Object.freeze({page,status:Object.freeze(runStatuses.filter(value=>status.includes(value))),action_type:Object.freeze(runActions.filter(value=>actions.includes(value)))});
}
/** Last confirmed page/filter remain paired; an unsuccessful newer request
 * cannot relabel an old page or rewrite its selected run. */
export class RequirementRunHistory{
 private readonly identity:number;private readonly api:Pick<WalleApi,'listGuideRuns'>;private readonly listeners=new Set<()=>void>();
 private value:RunHistoryState=Object.freeze({requested:runHistoryQuery(),confirmed:null,loading:false,active:true,error:null});private generation=0;private closed=false;private controller:AbortController|undefined;private pending:Promise<boolean>|undefined;
 constructor(identity:number,api:Pick<WalleApi,'listGuideRuns'>){this.identity=positiveInteger(identity);this.api=api;}
 getSnapshot=():RunHistoryState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<RunHistoryState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E run history observer failed',error);}}
 refresh(input:GuideFilters=this.value.requested):Promise<boolean>{
  const query=runHistoryQuery(input);if(this.closed)return Promise.resolve(false);if(this.pending&&JSON.stringify(query)===JSON.stringify(this.value.requested))return this.pending;
  const generation=++this.generation,controller=new AbortController();this.controller?.abort();this.controller=controller;const alive=()=>!this.closed&&generation===this.generation;
  const pending=Promise.resolve().then(async()=>{if(!alive())return false;try{
   const response=await this.api.listGuideRuns(this.identity,query,controller.signal);if(!alive())return false;const page=response.meta.pagination,items=response.data.items;
   if(!page||!('page' in page)||page.page!==query.page||page.page_size!==20||page.total_pages!==Math.ceil(page.total/20)||items.length!==Math.max(0,Math.min(20,page.total-(query.page-1)*20)))throw Error('Actual history page required');
   let previous:GuideSummary|undefined;const ids=new Set<number>();for(const item of items){if(item.requirement_id!==this.identity||ids.has(item.id)||query.status.length&&!query.status.includes(item.status)||query.action_type.length&&!query.action_type.includes(item.action_type)||previous&&(previous.created_at<item.created_at||previous.created_at===item.created_at&&previous.id<=item.id))throw Error('Unconfirmed history result');ids.add(item.id);previous=item;}
   this.publish({confirmed:capture({query,items,pagination:page}),loading:false,error:null});return true;
  }catch{if(alive())this.publish({loading:false,error:'运行记录读取失败，已确认的筛选和页面仍保留，请重试'});return false;}}).finally(()=>{if(this.pending===pending)this.pending=undefined;if(this.controller===controller)this.controller=undefined;});
  this.pending=pending;this.publish({requested:query,loading:true,active:true,error:null});return pending;
 }
 pause():void{if(this.closed)return;this.generation++;this.controller?.abort();this.pending=undefined;this.publish({active:false,loading:false});}
 dispose():void{this.closed=true;this.generation++;this.controller?.abort();this.listeners.clear();}
}
