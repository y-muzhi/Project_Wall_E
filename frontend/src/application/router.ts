import type {WalleApi} from '../api/walle.ts';
import {RequirementWorkbench} from '../requirements/workbench.ts';
import type {WorkbenchQuery} from '../requirements/workbench.ts';
import {CreateRequirementFlow} from '../requirements/create.ts';
import {WorkbenchHistory,pageRoute,decodeWorkbenchEntry} from '../requirements/workbench-history.ts';
import type {WorkbenchEntry,PageRoute} from '../requirements/workbench-history.ts';
import type {DetailDeparture} from '../requirements/departure.ts';

type DetailEntry=Readonly<{schema_version:1;kind:'WALLE_DETAIL';entry_id:string;id:number;position:number;from:Readonly<{entry:WorkbenchEntry;position:number}>|null}>;
type Destination=Readonly<{path:string;state:unknown;position:number|null}>;
export interface BrowserPort{
 history:Pick<History,'state'|'replaceState'|'pushState'|'go'>&Partial<Pick<History,'scrollRestoration'>>;
 pathname():string;scroll():number;scrollTop():void;
 listen(listener:()=>void):()=>void;
}
export type ApplicationState=Readonly<{route:PageRoute;epoch:number;workbench:RequirementWorkbench|null;creation:CreateRequirementFlow|null;entry:WorkbenchEntry|null;restoreScroll:number|null;warning:string|null}>;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const entryId=(state:unknown):string|null=>{if(state&&typeof state==='object'&&'entry_id' in state&&typeof state.entry_id==='string'&&uuid.test(state.entry_id))return state.entry_id;return null;};
const positionKey=(id:string)=>'walle:v1:route-position:'+id;
/** Real route owner: workbench entries belong to browser history positions.
 * Popstate is restored before asking an active detail to save/leave, so a
 * failed save keeps both the mounted editor and its original browser entry. */
export class ApplicationRouter{
 private readonly api:WalleApi;private readonly browser:BrowserPort;private readonly storage:Pick<Storage,'getItem'|'setItem'>|null;private readonly identify:()=>string;private readonly history:WorkbenchHistory;
 private readonly lists=new Map<string,RequirementWorkbench>();private readonly positions=new Map<string,number>();private readonly listeners=new Set<()=>void>();private release:()=>void;
 private position=0;private currentPath:string;private currentState:unknown;private detailEntry:DetailEntry|null=null;private departure:DetailDeparture|null=null;private blocked=false;private closed=false;
 private restoration:Readonly<{original:Destination;target:Destination}>|null=null;private approved:Destination|null=null;
 private value:ApplicationState=Object.freeze({route:{kind:'NOT_FOUND' as const},epoch:0,workbench:null,creation:null,entry:null,restoreScroll:null,warning:null});
 constructor(api:WalleApi,browser:BrowserPort,storage:Pick<Storage,'getItem'|'setItem'>|null,identify=()=>crypto.randomUUID()){
  this.api=api;this.browser=browser;this.storage=storage;this.identify=identify;this.history=new WorkbenchHistory(browser.history,storage,identify);this.currentPath=browser.pathname();this.currentState=browser.history.state;
  this.position=this.readPosition(this.currentState)??0;this.apply(this.currentPath,true);this.release=browser.listen(this.pop);
 }
 getSnapshot=():ApplicationState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 get applicationApi():WalleApi{return this.api;}
 private publish(changes:Partial<ApplicationState>){if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)listener();}
 private readPosition(state:unknown):number|null{const identity=entryId(state);if(!identity)return null;const known=this.positions.get(identity);if(known!==undefined)return known;
  try{const raw=this.storage?.getItem(positionKey(identity));if(raw!==null&&raw!==undefined){const value=JSON.parse(raw);if(Number.isSafeInteger(value)&&value>=0){this.positions.set(identity,value);return value;}}}catch{/* Actual route remains usable; no guessed predecessor. */}return null;
 }
 private remember(state:unknown,position:number){const identity=entryId(state);if(!identity)return;this.positions.set(identity,position);try{this.storage?.setItem(positionKey(identity),JSON.stringify(position));}catch{this.publish({warning:'浏览器返回位置暂存不可用，刷新后可能无法恢复。'});}}
 private decodeDetail(state:unknown,id:number):DetailEntry|null{try{if(!state||typeof state!=='object')return null;const row=state as DetailEntry;if(row.kind!=='WALLE_DETAIL'||row.schema_version!==1||row.id!==id||!uuid.test(row.entry_id)||!Number.isSafeInteger(row.position)||row.position<0)return null;
  if(row.from!==null){if(!row.from||!Number.isSafeInteger(row.from.position)||row.from.position<0||row.from.position>=row.position)return null;
   // Use the same strict public browser-entry decoder, not a second query definition.
   decodeWorkbenchEntry(row.from.entry);}
  return Object.freeze({...row,from:row.from?Object.freeze({...row.from,entry:decodeWorkbenchEntry(row.from.entry)}):null});}catch{return null;}}
 private apply(path:string,restore:boolean){
  const prior=this.value;prior.workbench?.pause();prior.creation?.dispose();this.departure=null;this.blocked=false;const route=pageRoute(path);let workbench:RequirementWorkbench|null=null,creation:CreateRequirementFlow|null=null,entry:WorkbenchEntry|null=null;this.detailEntry=null;
  if(route.kind==='WORKBENCH'){
   if(path==='/'){this.browser.history.replaceState(this.browser.history.state,'','/requirements');path='/requirements';}
   entry=this.history.enter(restore?'RESTORE':'DEFAULT');workbench=this.lists.get(entry.entry_id)??new RequirementWorkbench(this.api,entry.query);this.lists.set(entry.entry_id,workbench);creation=new CreateRequirementFlow(this.api);this.remember(entry,this.position);
  }else if(route.kind==='DETAIL'){
   this.detailEntry=this.decodeDetail(this.browser.history.state,route.id)??Object.freeze({schema_version:1,kind:'WALLE_DETAIL',entry_id:this.identify(),id:route.id,position:this.position,from:null});
   this.browser.history.replaceState(this.detailEntry,'',path);this.remember(this.detailEntry,this.position);
  }
  this.currentPath=path;this.currentState=this.browser.history.state;this.browser.scrollTop();this.publish({route,workbench,creation,entry,restoreScroll:restore&&entry?entry.scroll:null,epoch:prior.epoch+1,warning:this.history.storageWarning});
 }
 saveEntry=(query:WorkbenchQuery,scroll:number):void=>{const entry=this.value.entry;if(this.closed||this.value.route.kind!=='WORKBENCH'||!entry||entryId(this.browser.history.state)!==entry.entry_id)return;const saved=this.history.save(entry,query,scroll);this.currentState=this.browser.history.state;this.publish({entry:saved,warning:this.history.storageWarning});};
 navigationGuard=(blocked:boolean):void=>{this.blocked=blocked;};
 attachDeparture=(departure:DetailDeparture):void=>{this.departure=departure;};
 discardCreation=():void=>{if(!this.value.creation||this.value.creation.state.busy||this.value.creation.state.unknown)return;this.value.creation.dispose();this.publish({creation:new CreateRequirementFlow(this.api)});};
 private allowed(next:()=>void){if(this.closed)return;if(this.value.route.kind==='DETAIL'&&this.departure){void this.departure.request(next);return;}if(this.blocked&&!this.value.creation?.state.result){this.publish({warning:'请先在新建需求抽屉中确认输入或恢复原请求。'});return;}next();}
 openRequirement=(id:number):void=>{if(pageRoute('/requirements/'+id).kind!=='DETAIL')throw TypeError('Canonical requirement ID required');this.allowed(()=>{
  if(this.value.entry&&this.value.workbench)this.saveEntry(this.value.workbench.state.requested,this.browser.scroll());const from=this.value.entry?Object.freeze({entry:this.value.entry,position:this.position}):null;
  const entry:DetailEntry=Object.freeze({schema_version:1,kind:'WALLE_DETAIL',entry_id:this.identify(),id,position:this.position+1,from});this.browser.history.pushState(entry,'','/requirements/'+id);this.position++;this.apply('/requirements/'+id,true);
 });};
 mainNavigation=():void=>{this.allowed(()=>{this.browser.history.pushState(null,'','/requirements');this.position++;this.apply('/requirements',false);});};
 /** Called by the detail component only after its own departure succeeded. */
 backToWorkbench=():void=>{const from=this.detailEntry?.from;if(from){this.approved={path:'/requirements',state:from.entry,position:from.position};this.browser.history.go(from.position-this.position);}else{this.browser.history.pushState(null,'','/requirements');this.position++;this.apply('/requirements',false);}};
 private pop=():void=>{
  if(this.closed)return;const target:Destination={path:this.browser.pathname(),state:this.browser.history.state,position:this.readPosition(this.browser.history.state)};
  if(this.restoration){const pending=this.restoration;if(target.path!==pending.original.path||entryId(target.state)!==entryId(pending.original.state)){this.publish({warning:'浏览器返回位置尚未恢复，请保持当前页面。'});return;}this.restoration=null;this.allowed(()=>{this.approved=pending.target;this.browser.history.go(pending.target.position!-this.position);});return;}
  if(this.approved){const approved=this.approved;this.approved=null;if(target.path===approved.path&&(approved.position===null||target.position===approved.position)){if(approved.state&&pageRoute(target.path).kind==='WORKBENCH')this.browser.history.replaceState(approved.state,'',target.path);this.position=target.position??this.position;this.apply(target.path,true);return;}}
  const guarded=this.value.route.kind==='DETAIL'&&this.departure||this.blocked;
  if(guarded){const original:Destination={path:this.currentPath,state:this.currentState,position:this.position};
   if(target.position!==null&&target.position!==this.position){this.restoration={original,target};this.browser.history.go(this.position-target.position);return;}
   // Unowned/corrupt history cannot justify a guessed history.go direction.
   this.browser.history.replaceState(original.state,'',original.path);this.allowed(()=>{this.browser.history.replaceState(target.state,'',target.path);this.position=target.position??this.position;this.apply(target.path,true);});return;
  }
  this.position=target.position??this.position;this.apply(target.path,true);
 };
 dispose():void{this.closed=true;this.release();for(const list of this.lists.values())list.dispose();this.value.creation?.dispose();this.listeners.clear();}
}
