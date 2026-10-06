import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApplicationRouter} from '../src/application/router.ts';
import {DetailDeparture} from '../src/requirements/departure.ts';
import {defaultWorkbenchQuery} from '../src/requirements/workbench.ts';
function browser(path='/requirements'){
 const entries=[{path,state:null}],listeners=new Set(),values=new Map();let index=0,scroll=0,serial=0;
 const history={get state(){return entries[index].state;},scrollRestoration:'auto',replaceState(state,_title,path){entries[index]={path:path??entries[index].path,state};},pushState(state,_title,path){entries.splice(++index);entries.push({state,path});},go(delta){const next=index+delta;if(next<0||next>=entries.length)return;index=next;queueMicrotask(()=>{for(const listener of listeners)listener();});}};
 return {history,entries,values,pathname:()=>entries[index].path,scroll:()=>scroll,scrollTop:()=>{scroll=0;},setScroll:value=>{scroll=value;},listen:listener=>{listeners.add(listener);return()=>listeners.delete(listener);},storage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)},identify:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,'0')}`,idle:()=>new Promise(resolve=>setImmediate(resolve))};
}
const api={listRequirements:async filters=>({data:{items:[]},meta:{pagination:{page:filters.page,page_size:20,total:0,total_pages:0}}})};
test('actual history entry restores committed filters/page/scroll and retained list; main navigation creates fresh defaults',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify),first=router.getSnapshot();
 const query={...defaultWorkbenchQuery,keyword:'原提交',status:['ACTIVE'],page:3};await first.workbench.query(query);port.setScroll(320);router.saveEntry(query,320);router.openRequirement(17);
 assert.equal(port.pathname(),'/requirements/17');assert.equal(router.getSnapshot().route.id,17);router.backToWorkbench();await port.idle();const restored=router.getSnapshot();
 assert.equal(restored.entry.entry_id,first.entry.entry_id);assert.equal(restored.workbench,first.workbench);assert.deepEqual(restored.entry.query,query);assert.equal(restored.restoreScroll,320);
 router.mainNavigation();assert.notEqual(router.getSnapshot().entry.entry_id,first.entry.entry_id);assert.deepEqual(router.getSnapshot().entry.query,defaultWorkbenchQuery);router.dispose();
});
test('browser Back restores editor route before failed-save warning; continue keeps it, explicit leave goes to original destination exactly once',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify);router.openRequirement(2);let saves=0,resumes=0;
 const departure=new DetailDeparture({async prepareLeave(){saves++;return {saved:false,local_protected:true};},continueAfterFailedLeave(){resumes++;return true;}});router.attachDeparture(departure);
 port.history.go(-1);await port.idle();assert.equal(saves,1);assert.equal(departure.getSnapshot().phase,'WARNING');assert.equal(port.pathname(),'/requirements/2');assert.equal(router.getSnapshot().route.kind,'DETAIL');
 assert.equal(departure.continueEditing(),true);assert.equal(resumes,1);port.history.go(-1);await port.idle();assert.equal(saves,2);assert.equal(port.pathname(),'/requirements/2');assert.equal(departure.confirmLeave(),true);await port.idle();assert.equal(port.pathname(),'/requirements');assert.equal(router.getSnapshot().route.kind,'WORKBENCH');assert.equal(saves,2);router.dispose();
});
test('main navigation also uses real departure, successful save is awaited before route change',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify);router.openRequirement(4);let complete;
 const departure=new DetailDeparture({prepareLeave:()=>new Promise(resolve=>{complete=resolve;}),continueAfterFailedLeave:()=>true});router.attachDeparture(departure);router.mainNavigation();await port.idle();assert.equal(port.pathname(),'/requirements/4');assert.equal(departure.getSnapshot().phase,'SAVING');complete({saved:true,local_protected:true});await port.idle();assert.equal(port.pathname(),'/requirements');router.dispose();
});
test('unsubmitted and unknown creation remain in the mounted original flow on browser Back or main navigation',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify);router.mainNavigation();const creation=router.getSnapshot().creation;router.navigationGuard(true);
 router.mainNavigation();assert.equal(router.getSnapshot().creation,creation);assert.match(router.getSnapshot().warning,/原请求/);port.history.go(-1);await port.idle();assert.equal(router.getSnapshot().creation,creation);assert.equal(port.history.state.entry_id,router.getSnapshot().entry.entry_id);router.navigationGuard(false);router.dispose();
});
test('detail refresh retains only a validated original workbench entry; direct canonical detail returns to defaults',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify);const entry=router.getSnapshot().entry;const query={...defaultWorkbenchQuery,keyword:'刷新恢复'};await router.getSnapshot().workbench.query(query);router.saveEntry(query,77);router.openRequirement(3);router.dispose();
 const refreshed=new ApplicationRouter(api,port,port.storage,port.identify);refreshed.backToWorkbench();await port.idle();assert.equal(refreshed.getSnapshot().entry.entry_id,entry.entry_id);assert.equal(refreshed.getSnapshot().entry.query.keyword,'刷新恢复');refreshed.dispose();
 const direct=browser('/requirements/6'),directRouter=new ApplicationRouter(api,direct,direct.storage,direct.identify);directRouter.backToWorkbench();assert.equal(direct.pathname(),'/requirements');assert.deepEqual(directRouter.getSnapshot().entry.query,defaultWorkbenchQuery);directRouter.dispose();
});
test('invalid route is never turned into a document; disposal stops subsequent browser events',async()=>{
 const port=browser('/requirements/01'),router=new ApplicationRouter(api,port,port.storage,port.identify);assert.equal(router.getSnapshot().route.kind,'NOT_FOUND');router.mainNavigation();assert.equal(router.getSnapshot().route.kind,'WORKBENCH');const snapshot=router.getSnapshot();router.dispose();port.history.go(-1);await port.idle();assert.equal(router.getSnapshot(),snapshot);
});
