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
test('workbench button directly opens the default list; main navigation creates fresh defaults',async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify),first=router.getSnapshot();
 const query={...defaultWorkbenchQuery,keyword:'原提交',status:['PLANNING'],page:3};await first.workbench.query(query);port.setScroll(320);router.saveEntry(query,320);router.openRequirement(17);
 assert.equal(port.pathname(),'/requirements/17');assert.equal(router.getSnapshot().route.id,17);router.backToWorkbench();await port.idle();const restored=router.getSnapshot();
 assert.notEqual(restored.entry.entry_id,first.entry.entry_id);assert.deepEqual(restored.entry.query,defaultWorkbenchQuery);assert.equal(restored.restoreScroll,null);
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
 const refreshed=new ApplicationRouter(api,port,port.storage,port.identify);refreshed.backToWorkbench();await port.idle();assert.notEqual(refreshed.getSnapshot().entry.entry_id,entry.entry_id);assert.deepEqual(refreshed.getSnapshot().entry.query,defaultWorkbenchQuery);refreshed.dispose();
 const direct=browser('/requirements/6'),directRouter=new ApplicationRouter(api,direct,direct.storage,direct.identify);directRouter.backToWorkbench();assert.equal(direct.pathname(),'/requirements');assert.deepEqual(directRouter.getSnapshot().entry.query,defaultWorkbenchQuery);directRouter.dispose();
});
test('invalid route is never turned into a document; disposal stops subsequent browser events',async()=>{
 const port=browser('/requirements/01'),router=new ApplicationRouter(api,port,port.storage,port.identify);assert.equal(router.getSnapshot().route.kind,'NOT_FOUND');router.mainNavigation();assert.equal(router.getSnapshot().route.kind,'WORKBENCH');const snapshot=router.getSnapshot();router.dispose();port.history.go(-1);await port.idle();assert.equal(router.getSnapshot(),snapshot);
});

for (const scenario of ['unavailable', 'blocked', 'cleared', 'stale']) {
 test(`detail refresh directly opens the default workbench when position storage is ${scenario}`, async () => {
  const port = browser();
  const storage = scenario === 'unavailable' ? null : scenario === 'blocked' ? {
   getItem() { throw Error('Storage blocked'); },
   setItem() { throw Error('Storage blocked'); },
  } : port.storage;
  const original = new ApplicationRouter(api, port, storage, port.identify);
  const query = {...defaultWorkbenchQuery, keyword: '保留查询', status: ['READY'], page: 2};
  const entry = original.getSnapshot().entry;
  await original.getSnapshot().workbench.query(query);
  port.setScroll(144);
  original.saveEntry(query, 144);
  original.openRequirement(1);
  original.dispose();
  if (scenario === 'cleared') port.values.clear();
  if (scenario === 'stale') {
   for (const key of port.values.keys()) {
    if (key.includes(':route-position:')) port.values.set(key, '0');
   }
  }
  const restored = new ApplicationRouter(api, port, storage, port.identify);
  let saves = 0;
  const departure = new DetailDeparture({
   async prepareLeave() { saves++; return {saved: true, local_protected: true}; },
   continueAfterFailedLeave: () => true,
  });
  restored.attachDeparture(departure);
  await departure.request(restored.backToWorkbench);
  await port.idle();
  assert.equal(port.pathname(), '/requirements');
  assert.equal(restored.getSnapshot().route.kind, 'WORKBENCH');
  assert.notEqual(restored.getSnapshot().entry.entry_id, entry.entry_id);
  assert.deepEqual(restored.getSnapshot().entry.query, defaultWorkbenchQuery);
  assert.equal(restored.getSnapshot().restoreScroll, null);
  assert.equal(saves, 1);
  restored.openRequirement(2);
  restored.mainNavigation();
  assert.equal(restored.getSnapshot().route.kind, 'WORKBENCH');
  departure.dispose();
  restored.dispose();
 });
}

test('browser Back after a storage-free detail refresh preserves a failed draft until explicit leave', async () => {
 const port = browser();
 const original = new ApplicationRouter(api, port, null, port.identify);
 const entry = original.getSnapshot().entry;
 original.openRequirement(1);
 original.dispose();
 const restored = new ApplicationRouter(api, port, null, port.identify);
 let saves = 0;
 const departure = new DetailDeparture({
  async prepareLeave() { saves++; return {saved: false, local_protected: true}; },
  continueAfterFailedLeave: () => true,
 });
 restored.attachDeparture(departure);
 port.history.go(-1);
 await port.idle();
 assert.equal(port.pathname(), '/requirements/1');
 assert.equal(restored.getSnapshot().route.kind, 'DETAIL');
 assert.equal(departure.getSnapshot().phase, 'WARNING');
 assert.equal(saves, 1);
 assert.equal(departure.continueEditing(), true);
 port.history.go(-1);
 await port.idle();
 assert.equal(port.pathname(), '/requirements/1');
 assert.equal(departure.confirmLeave(), true);
 await port.idle();
 assert.equal(port.pathname(), '/requirements');
 assert.equal(restored.getSnapshot().route.kind, 'WORKBENCH');
 assert.equal(restored.getSnapshot().entry.entry_id, entry.entry_id);
 assert.equal(saves, 2);
 departure.dispose();
 restored.dispose();
});


test('workbench button never traverses browser history even when its saved source points outside the actual stack', async () => {
 const port = browser();
 const original = new ApplicationRouter(api, port, port.storage, port.identify);
 original.openRequirement(1);
 original.dispose();
 // A valid persisted app record does not prove that the previous real page is still the workbench.
 port.entries[0] = {path: 'browser-home', state: null};
 let traversals = 0;
 port.history.go = () => { traversals++; throw Error('Must not traverse outside the app'); };
 const router = new ApplicationRouter(api, port, port.storage, port.identify);
 const departure = new DetailDeparture({
  prepareLeave: async () => ({saved: true, local_protected: true}),
  continueAfterFailedLeave: () => true,
 });
 router.attachDeparture(departure);
 const length = port.entries.length;
 await departure.request(router.backToWorkbench);
 assert.equal(traversals, 0);
 assert.equal(port.pathname(), '/requirements');
 assert.equal(port.entries.length, length);
 assert.equal(router.getSnapshot().route.kind, 'WORKBENCH');
 assert.deepEqual(router.getSnapshot().entry.query, defaultWorkbenchQuery);
 departure.dispose();
 router.dispose();
});

test('direct workbench return still waits for a draft save and preserves the page on failure', async () => {
 const port = browser('/requirements/1');
 const router = new ApplicationRouter(api, port, null, port.identify);
 let finishSave;
 const departure = new DetailDeparture({
  prepareLeave: () => new Promise(resolve => { finishSave = resolve; }),
  continueAfterFailedLeave: () => true,
 });
 router.attachDeparture(departure);
 const pending = departure.request(router.backToWorkbench);
 await port.idle();
 assert.equal(port.pathname(), '/requirements/1');
 assert.equal(departure.getSnapshot().phase, 'SAVING');
 finishSave({saved: false, local_protected: true});
 await pending;
 assert.equal(port.pathname(), '/requirements/1');
 assert.equal(departure.getSnapshot().phase, 'WARNING');
 assert.equal(departure.continueEditing(), true);
 assert.equal(port.pathname(), '/requirements/1');
 const retry = departure.request(router.backToWorkbench);
 await port.idle();
 finishSave({saved: false, local_protected: true});
 await retry;
 assert.equal(departure.confirmLeave(), true);
 assert.equal(port.pathname(), '/requirements');
 assert.equal(router.getSnapshot().route.kind, 'WORKBENCH');
 departure.dispose();
 router.dispose();
});

test('settings navigation uses the active detail departure and never guesses a document', async()=>{
 const port=browser(),router=new ApplicationRouter(api,port,port.storage,port.identify);
 router.openRequirement(4);
 let complete;
 const departure=new DetailDeparture({prepareLeave:()=>new Promise(resolve=>{complete=resolve;}),continueAfterFailedLeave:()=>true});
 router.attachDeparture(departure);
 router.openCodeSettings();
 await port.idle();
 assert.equal(router.getSnapshot().route.kind,'DETAIL');
 complete({saved:true,local_protected:true});
 await port.idle();
 assert.equal(port.pathname(),'/settings/code');
 assert.equal(router.getSnapshot().route.kind,'CODE_SETTINGS');
 assert.equal(router.getSnapshot().workbench,null);
 router.dispose();
});


test('code task entry awaits document departure and restores the original list and reading', async () => {
 const port = browser('/requirements/1');
 const router = new ApplicationRouter(api, port, port.storage, port.identify);
 let mayLeave = false;
 const departure = new DetailDeparture({
  prepareLeave: async () => ({saved: mayLeave, local_protected: true}),
  continueAfterFailedLeave: () => true,
 });
 router.attachDeparture(departure);
 const reading = {documentId: 41, revisionId: 24, scroll: 117};
 router.openCodeTaskList(2, reading);
 assert.equal(departure.getSnapshot().phase, 'IDLE');
 router.openCodeTaskList(1, reading);
 await port.idle();
 assert.equal(departure.getSnapshot().phase, 'WARNING');
 assert.equal(port.pathname(), '/requirements/1');
 assert.equal(departure.continueEditing(), true);
 mayLeave = true;
 router.openCodeTaskList(1, reading);
 await port.idle();
 assert.equal(port.pathname(), '/requirements/1/documents/41/code-tasks');
 const query = {page: 2, statuses: ['PENDING'], revisionId: 24};
 router.saveCodeTaskList(query, 10);
 port.setScroll(160);
 router.openCodeTask(31, 1, 99);
 assert.equal(router.getSnapshot().route.kind, 'CODE_TASK_LIST');
 router.openCodeTask(31, 1, 41);
 assert.equal(port.pathname(), '/code-tasks/31');
 router.returnToTaskList(1, 41);
 await port.idle();
 assert.deepEqual(router.getSnapshot().taskList.query, query);
 assert.equal(router.getSnapshot().taskList.scroll, 160);
 router.returnToCodeDocument(1, 41);
 await port.idle();
 assert.deepEqual(router.getSnapshot().documentReading, reading);
 assert.equal(port.pathname(), '/requirements/1');
 router.dispose();
});

test('code task route rejects noncanonical IDs and reload reconstructs the original document route', () => {
 const invalid = browser('/requirements/1/documents/041/code-tasks');
 const badRouter = new ApplicationRouter(api, invalid, invalid.storage, invalid.identify);
 assert.equal(badRouter.getSnapshot().route.kind, 'CODE_PARAMETERS');
 badRouter.dispose();
 const port = browser('/requirements/1');
 const initial = new ApplicationRouter(api, port, port.storage, port.identify);
 initial.openCodeTaskList(1, {documentId: 41, revisionId: 24, scroll: 0});
 initial.dispose();
 port.history.go = () => { throw Error('Reloaded source cannot prove previous browser page'); };
 const reload = new ApplicationRouter(api, port, port.storage, port.identify);
 reload.returnToCodeDocument(1, 41);
 assert.equal(port.pathname(), '/requirements/1');
 assert.deepEqual(reload.getSnapshot().documentReading, {documentId: 41, revisionId: 24, scroll: 0});
 reload.dispose();
});

test('global Coding opens an explicit document chooser and preserves its own history', async () => {
  const port = browser();
  const router = new ApplicationRouter(api, port, port.storage, port.identify);
  router.openCodeDevelopment();
  assert.equal(port.pathname(), '/requirements');
  assert.equal(port.history.state.nav_intent, 'CHOOSE_CODE_DOCUMENT');
  assert.equal(router.getSnapshot().navIntent, 'CHOOSE_CODE_DOCUMENT');

  const query = {...defaultWorkbenchQuery, keyword: '当前筛选'};
  await router.getSnapshot().workbench.query(query);
  port.setScroll(70);
  router.saveEntry(query, 70);
  router.openRequirement(7);
  assert.equal(router.getSnapshot().navIntent, 'CHOOSE_CODE_DOCUMENT');
  router.openCodeTaskList(7, {documentId: 11, revisionId: null, scroll: 0}, {
    documentId: 8,
    revisionId: 23,
    scroll: 52,
  });
  assert.equal(port.pathname(), '/requirements/7/documents/11/code-tasks');
  assert.equal(router.getSnapshot().navIntent, null);

  port.history.go(-1);
  await port.idle();
  assert.equal(router.getSnapshot().navIntent, 'CHOOSE_CODE_DOCUMENT');
  assert.deepEqual(router.getSnapshot().documentReading, {
    documentId: 8, revisionId: 23, scroll: 52,
  });
  port.history.go(-1);
  await port.idle();
  assert.equal(router.getSnapshot().entry.query.keyword, '当前筛选');
  assert.equal(router.getSnapshot().restoreScroll, 70);
  router.dispose();

  const restored = new ApplicationRouter(api, port, port.storage, port.identify);
  assert.equal(restored.getSnapshot().navIntent, 'CHOOSE_CODE_DOCUMENT');
  restored.mainNavigation();
  assert.equal(restored.getSnapshot().navIntent, null);
  restored.dispose();
});

test('Coding workspace owns its file and page history without remounting the original task', async () => {
 const port = browser('/requirements/1');
 const rawPath = port.pathname;
 port.pathname = () => rawPath().split('?')[0];
 port.search = () => {
  const query = rawPath().indexOf('?');
  return query === -1 ? '' : rawPath().slice(query);
 };
 const router = new ApplicationRouter(api, port, port.storage, port.identify);
 router.openCodeTaskList(1, {documentId: 41, revisionId: 24, scroll: 0});
 port.setScroll(160);
 router.openCodeTask(31, 1, 41);
 const original = router.getSnapshot();
 const file = {tab: 'code', candidateId: 201, filePath: 'src/原文件.txt', page: 3};
 port.setScroll(370);
 router.openCodeTaskWorkspace(file);
 assert.deepEqual(router.getSnapshot().taskWorkspace, file);
 assert.equal(router.getSnapshot().epoch, original.epoch);
 const count = port.entries.length;
 router.openCodeTaskWorkspace(file);
 assert.equal(port.entries.length, count);
 port.setScroll(480);
 router.openCodeTaskWorkspace({tab: 'usage', page: 2});
 port.history.go(-1);
 await port.idle();
 assert.deepEqual(router.getSnapshot().taskWorkspace, file);
 assert.equal(router.getSnapshot().restoreScroll, 480);
 assert.equal(router.getSnapshot().epoch, original.epoch);
 port.history.go(1);
 await port.idle();
 assert.deepEqual(router.getSnapshot().taskWorkspace, {tab: 'usage', page: 2});
 router.returnToTaskList(1, 41);
 await port.idle();
 assert.equal(port.pathname(), '/requirements/1/documents/41/code-tasks');
 assert.equal(router.getSnapshot().taskList.scroll, 160);
 router.dispose();
});

test('Coding pins a path-only route to its original verified owner without adding history', () => {
 const port = browser('/code-tasks/31?tab=delivery&path=a.txt');
 const rawPath = port.pathname;
 port.pathname = () => rawPath().split('?')[0];
 port.search = () => {
  const query = rawPath().indexOf('?');
  return query === -1 ? '' : rawPath().slice(query);
 };
 const router = new ApplicationRouter(api, port, port.storage, port.identify);
 const original = router.getSnapshot().taskWorkspace;
 router.pinCodeTaskFileScope({...original}, 41);
 assert.equal(router.getSnapshot().taskWorkspace, original);
 router.pinCodeTaskFileScope(original, 41);
 const pinned = router.getSnapshot().taskWorkspace;
 assert.deepEqual(pinned, {tab: 'delivery', filePath: 'a.txt', planId: 41});
 assert.equal(port.entries.length, 1);
 router.pinCodeTaskFileScope(original, 42);
 assert.equal(router.getSnapshot().taskWorkspace, pinned);
 assert.equal(new URLSearchParams(port.search()).get('plan_id'), '41');
 router.dispose();
});
