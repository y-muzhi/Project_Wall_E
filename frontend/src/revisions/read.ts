import {positiveInteger,snapshotObject} from '../api/client.ts';
import type {PagePagination} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {RevisionSummary} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
export type Revision=Awaited<ReturnType<WalleApi['getRevision']>>['data'];
type Api=Pick<WalleApi,'listRevisions'|'getRevision'>;
type List=Readonly<{items:readonly RevisionSummary[];pagination:PagePagination}>;
export type RevisionReadState=Readonly<{list:List|null;page:number;loading:boolean;error:string|null;active:boolean;
  history:Readonly<{phase:'CLOSED'|'LOADING'|'OPEN'|'ERROR'|'EXITING'|'RESTORING';requested:RevisionSummary|null;snapshot:Revision|null;error:string|null;restored:DetailSnapshot|null}>}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const sameSummary=(summary:RevisionSummary,revision:Revision)=>Object.keys(summary).every(key=>summary[key as keyof RevisionSummary]===revision[key as keyof RevisionSummary]);

/** Separate owners for list and immutable history reads. Retained results
 * stay labelled with their actual page/identity on failures or newer reads. */
export class RequirementRevisions {
  private readonly identity:number;private readonly api:Api;private readonly listeners=new Set<()=>void>();private closed=false;
  private value:RevisionReadState=Object.freeze({list:null,page:1,loading:false,error:null,active:true,history:Object.freeze({phase:'CLOSED',requested:null,snapshot:null,error:null,restored:null})});
  private listGeneration=0;private historyGeneration=0;private listController:AbortController|undefined;private historyController:AbortController|undefined;
  private listPending:Promise<boolean>|undefined;private historyPending:Promise<boolean>|undefined;private exitPending:Promise<DetailSnapshot|null>|undefined;
  constructor(identity:number,api:Api){this.identity=positiveInteger(identity);this.api=api;}
  getSnapshot=():RevisionReadState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private publish(changes:Partial<RevisionReadState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E revision read observer failed',error);}}}
  refresh(page=this.value.page,force=false):Promise<boolean>{
    positiveInteger(page);if(page>100000)throw TypeError('Invalid page');if(this.closed)return Promise.resolve(false);if(this.listPending&&!force&&page===this.value.page)return this.listPending;
    const generation=++this.listGeneration,controller=new AbortController();this.listController?.abort();this.listController=controller;
    const pending=Promise.resolve().then(async()=>{if(this.closed||generation!==this.listGeneration)return false;
      try{const response=await this.api.listRevisions(this.identity,page,controller.signal);if(this.closed||generation!==this.listGeneration)return false;
        const pagination=response.meta.pagination;if(!pagination||!('page' in pagination)||pagination.page!==page||response.data.items.some((row,index,rows)=>row.requirement_id!==this.identity||(index>0&&rows[index-1]!.version_no<=row.version_no)))throw Error('Unconfirmed page');
        this.publish({list:capture({items:response.data.items,pagination}),loading:false,error:null});return true;
      }catch{if(!this.closed&&generation===this.listGeneration)this.publish({loading:false,error:'版本列表读取失败，已显示的实际列表仍保留'});return false;}
    }).finally(()=>{if(this.listPending===pending)this.listPending=undefined;});this.listPending=pending;this.publish({page,loading:true,error:null,active:true});return pending;
  }
  open(summary:RevisionSummary):Promise<boolean>{
    if(this.closed||this.exitPending||this.value.history.phase==='RESTORING')return Promise.resolve(false);if(summary.requirement_id!==this.identity)throw TypeError('Owned revision required');
    const selected=capture(summary),generation=++this.historyGeneration,controller=new AbortController();this.historyController?.abort();this.historyController=controller;
    const pending=Promise.resolve().then(async()=>{if(this.closed||generation!==this.historyGeneration)return false;
      try{const revision=(await this.api.getRevision(selected.id,controller.signal)).data;if(this.closed||generation!==this.historyGeneration)return false;
        if(revision.requirement_id!==this.identity||revision.id!==selected.id||!sameSummary(selected,revision))throw Error('Unconfirmed immutable revision');
        this.publish({history:Object.freeze({phase:'OPEN',requested:selected,snapshot:capture(revision),error:null,restored:null})});return true;
      }catch{if(!this.closed&&generation===this.historyGeneration)this.publish({history:Object.freeze({...this.value.history,phase:'ERROR',error:'历史版本读取失败，请重试或退出历史'})});return false;}
    }).finally(()=>{if(this.historyPending===pending)this.historyPending=undefined;});this.historyPending=pending;
    this.publish({history:Object.freeze({...this.value.history,phase:'LOADING',requested:selected,error:null,restored:null})});return pending;
  }
  exit(refresh:()=>Promise<DetailSnapshot>):Promise<DetailSnapshot|null>{
    if(this.closed||this.value.history.phase==='CLOSED')return Promise.resolve(null);if(this.exitPending)return this.exitPending;
    const generation=++this.historyGeneration;this.historyController?.abort();this.publish({history:Object.freeze({...this.value.history,phase:'EXITING',error:null})});
    const pending=Promise.resolve().then(async()=>{if(this.closed)return null;
      try{const actual=await refresh();if(this.closed||generation!==this.historyGeneration)return null;if(actual.requirement.id!==this.identity||actual.current.requirement_id!==this.identity||actual.current.document_type!=='CURRENT')throw Error('Unconfirmed actual detail');
        const restored=capture(actual);this.publish({history:Object.freeze({...this.value.history,phase:'RESTORING',error:null,restored})});return restored;
      }catch{if(!this.closed&&generation===this.historyGeneration)this.publish({history:Object.freeze({...this.value.history,phase:'ERROR',error:'当前详情读取失败，历史视图仍保留，请重试退出'})});return null;}
    }).finally(()=>{if(this.exitPending===pending)this.exitPending=undefined;});this.exitPending=pending;return pending;
  }
  finishExit(actual:DetailSnapshot):boolean{if(this.closed||this.value.history.phase!=='RESTORING'||actual!==this.value.history.restored)return false;
    this.publish({history:Object.freeze({phase:'CLOSED',requested:null,snapshot:null,error:null,restored:actual})});return true;}
  pause():void{if(this.closed)return;this.listGeneration++;this.listController?.abort();this.listPending=undefined;this.publish({loading:false,active:false});}
  dispose():void{this.closed=true;this.listGeneration++;this.historyGeneration++;this.listController?.abort();this.historyController?.abort();this.listeners.clear();}
}
