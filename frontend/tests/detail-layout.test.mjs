import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DetailLayout,DetailViewportGuard,decodeDetailPreferences,preferencesKey} from '../src/requirements/detail-layout.ts';
const store = () => {const values=new Map(),writes=[];return {values,writes,getItem:key=>values.get(key)??null,setItem(key,value){writes.push({key,value});values.set(key,value);}};};
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle = () => new Promise(resolve=>setImmediate(resolve));

test('actual available width selects three columns, drawer and single view without overwriting saved width',()=>{
  const storage=store(),layout=new DetailLayout('READY',1600,storage);
  layout.resizeRight(600);const writes=storage.writes.length;
  for(const available of [1400,1212,1211,1006,1005,824,1212,1400]){
    layout.viewport(1600,available);const s=layout.getSnapshot();
    assert.equal(s.left_drawer,available<1212);assert.equal(s.split_view,available>=1006);
    assert.equal(s.preferences.right_width,600);assert(s.document_width>=640);
    if(s.right_open){assert(s.right_width>=360);assert(s.right_width<=s.right_max);}
    if(available>=1212)assert(s.left_open&&s.right_open);else assert(!s.left_open);
  }
  assert.equal(storage.writes.length,writes);assert.equal(layout.getSnapshot().right_width,548);
  layout.viewport(1600,1568);assert.equal(layout.getSnapshot().right_width,600);
  layout.viewport(1023,1400);assert(!layout.getSnapshot().document_open&&!layout.getSnapshot().right_open);
});
test('drawer overlays the same split and single view preserves panel selection and preferred geometry',()=>{
  const storage=store(),layout=new DetailLayout('PLANNING',1600,storage);layout.viewport(1600,1006);
  const before=layout.getSnapshot();layout.toggleLeft();const drawer=layout.getSnapshot();
  assert(drawer.left_open&&drawer.left_drawer&&drawer.right_open);assert.equal(drawer.document_width,before.document_width);
  layout.toggleLeft();layout.viewport(1600,1005);assert(layout.getSnapshot().document_open&&!layout.getSnapshot().right_open);
  layout.openTab('COMMENTS');assert(layout.getSnapshot().right_open&&!layout.getSnapshot().document_open);
  assert.equal(layout.getSnapshot().right_width,1005);const width=layout.getSnapshot().preferences.right_width;
  layout.resizeRight(360);assert.equal(layout.getSnapshot().preferences.right_width,width);
  layout.showDocument();assert(layout.getSnapshot().document_open);assert(!layout.getSnapshot().right_open);
  layout.openTab('REVISIONS');layout.toggleRight();assert(layout.getSnapshot().document_open);
  layout.viewport(1600,1400);layout.openTab('COMMENTS');layout.resizeRight(99999);
  const saved=JSON.parse(storage.values.get(preferencesKey)),fresh=new DetailLayout('CLOSED',1600,storage);
  assert.deepEqual(fresh.getSnapshot().preferences,saved);assert.equal(fresh.getSnapshot().right_tab,'COMMENTS');
});
test('progress has its own persisted panel and preserves geometry through single view and reopen',()=>{
  const storage=store(),layout=new DetailLayout('PLANNING',1600,storage);
  layout.resizeRight(500);layout.openTab('PROGRESS');
  const fresh=new DetailLayout('PLANNING',1600,storage);
  assert.equal(fresh.getSnapshot().right_tab,'PROGRESS');assert.equal(fresh.getSnapshot().preferences.right_width,500);
  fresh.viewport(1100,980);assert(fresh.getSnapshot().document_open);
  fresh.openTab('PROGRESS');assert(fresh.getSnapshot().right_open&&!fresh.getSnapshot().document_open);
  fresh.toggleRight();assert(fresh.getSnapshot().document_open);
  fresh.toggleRight();assert.equal(fresh.getSnapshot().right_tab,'PROGRESS');
  fresh.openTab('AI');assert.equal(fresh.getSnapshot().right_tab,'AI');
  assert.equal(fresh.getSnapshot().preferences.right_width,500);
});

test('malformed or unavailable preference storage is visible without preventing in-memory interaction or writing defaults on mount',()=>{
  for(const v of [{schema_version:1,left_open:true,right_open:true,right_tab:'INVALID',right_width:420},{schema_version:1,left_open:true,right_open:true,right_tab:'AI',right_width:359},{schema_version:1,left_open:true,right_open:true,right_tab:'AI',right_width:Infinity},{schema_version:2,left_open:true,right_open:true,right_tab:'AI',right_width:420}])assert.throws(()=>decodeDetailPreferences(v));
  const storage=store();storage.values.set(preferencesKey,'broken');const layout=new DetailLayout('READY',1280,storage);assert(layout.getSnapshot().warning);assert.equal(storage.writes.length,0);
  layout.openTab('REVISIONS');assert.equal(layout.getSnapshot().warning,null);
  const denied={getItem(){throw Error('denied');},setItem(){throw Error('denied');}},other=new DetailLayout('READY',1280,denied);
  other.openTab('COMMENTS');assert(other.getSnapshot().right_open);assert.match(other.getSnapshot().warning,/暂存不可用/);
});
test('narrow guard freezes immediately once per crossing, preserves failed save, then waits actual save before re-read and supports explicit retry',async()=>{
  const save=deferred(),read=deferred();let freezes=0,reads=0,fail=false;
  const guard=new DetailViewportGuard(1280,{blockAndSave(){freezes++;return save.promise;},readAfterSupport(){reads++;return fail?Promise.reject(Error('read')):reads===1?read.promise:Promise.resolve();}});
  guard.activate();guard.viewport(1023);assert.equal(freezes,1);assert.equal(guard.getSnapshot().phase,'BLOCKED');guard.viewport(900);assert.equal(freezes,1);
  guard.viewport(1024);assert.equal(guard.getSnapshot().phase,'RESTORING');await settle();assert.equal(reads,0);
  save.reject(Error('actual save rejected'));await settle();assert.equal(reads,1);assert(guard.getSnapshot().save_failed);
  read.reject(Error('actual read rejected'));await settle();assert.equal(guard.getSnapshot().phase,'RESTORE_FAILED');fail=true;guard.retry();await settle();assert.equal(reads,2);assert.equal(guard.getSnapshot().phase,'RESTORE_FAILED');
  fail=false;guard.retry();await settle();assert.equal(reads,3);assert.equal(guard.getSnapshot().phase,'SUPPORTED');assert(guard.getSnapshot().save_failed);guard.dispose();
});
test('returning narrow during re-read aborts only owned read and ignores old completion; disposed guard cannot reopen operations',async()=>{
  const reads=[];let saves=0;const guard=new DetailViewportGuard(900,{blockAndSave(){saves++;return Promise.resolve();},readAfterSupport(signal){const d=deferred();reads.push({...d,signal});return d.promise;}});
  guard.activate();guard.activate();assert.equal(saves,1);guard.viewport(1280);await settle();assert.equal(reads.length,1);
  guard.viewport(1000);assert(reads[0].signal.aborted);reads[0].resolve();await settle();assert.equal(guard.getSnapshot().phase,'BLOCKED');assert.equal(saves,2);
  guard.viewport(1280);await settle();reads[1].resolve();await settle();assert.equal(guard.getSnapshot().phase,'SUPPORTED');
  guard.viewport(900);guard.viewport(1280);await settle();guard.dispose();assert(reads[2].signal.aborted);reads[2].resolve();await settle();assert.equal(guard.getSnapshot().phase,'RESTORING');
});

test('actual page restoration freezes once, waits for save and coalesces lifecycle events until real revalidation finishes',async()=>{
  const save=deferred(),read=deferred();let saves=0,reads=0;
  const guard=new DetailViewportGuard(1600,{blockAndSave(){saves++;return save.promise;},readAfterSupport(){reads++;return read.promise;}});
  guard.activate();guard.resumePage();assert.equal(saves,0);assert.equal(guard.getSnapshot().phase,'SUPPORTED');
  guard.suspendPage();guard.suspendPage();guard.resumePage();guard.resumePage();
  assert.equal(saves,1);assert.equal(guard.getSnapshot().phase,'RESTORING');await settle();assert.equal(reads,0);
  save.resolve();await settle();assert.equal(reads,1);guard.resumePage();assert.equal(saves,1);
  read.resolve();await settle();assert.equal(guard.getSnapshot().phase,'SUPPORTED');guard.dispose();
});

test('page restoration respects narrow width and failed read stays blocked until explicit retry succeeds',async()=>{
  const read=deferred();let saves=0,reads=0;
  const guard=new DetailViewportGuard(1600,{blockAndSave(){saves++;return Promise.resolve();},readAfterSupport(){reads++;return reads===1?read.promise:Promise.resolve();}});
  guard.activate();guard.suspendPage();guard.viewport(900);guard.resumePage();await settle();assert.equal(saves,1);assert.equal(reads,0);assert.equal(guard.getSnapshot().phase,'BLOCKED');
  guard.viewport(1600);await settle();assert.equal(reads,1);
  read.reject(Error('offline'));await settle();assert.equal(guard.getSnapshot().phase,'RESTORE_FAILED');
  guard.resumePage();assert.equal(reads,1);assert.equal(guard.getSnapshot().phase,'RESTORE_FAILED');
  guard.retry();await settle();assert.equal(reads,2);assert.equal(saves,1);assert.equal(guard.getSnapshot().phase,'SUPPORTED');guard.dispose();
});


test('review selection persists without changing width and old panel preferences remain valid',()=>{
 const storage=store(),layout=new DetailLayout('PLANNING',1600,storage);layout.resizeRight(480);layout.openTab('SUGGESTIONS');
 const restored=new DetailLayout('PLANNING',1600,storage);assert.equal(restored.getSnapshot().right_tab,'SUGGESTIONS');assert.equal(restored.getSnapshot().preferences.right_width,480);
 restored.viewport(1100,980);restored.openTab('SUGGESTIONS');assert(restored.getSnapshot().right_open&&!restored.getSnapshot().document_open);
 restored.toggleRight();restored.toggleRight();assert.equal(restored.getSnapshot().right_tab,'SUGGESTIONS');
 for(const right_tab of ['AI','PROGRESS','COMMENTS','REVISIONS'])assert.equal(decodeDetailPreferences({...restored.getSnapshot().preferences,right_tab}).right_tab,right_tab);
});


test('records opened from More return to prior primary panel and preserve old stored records selection',()=>{
 const storage=store(),layout=new DetailLayout('PLANNING',1600,storage);layout.resizeRight(510);
 for(const primary of ['AI','PROGRESS','SUGGESTIONS','COMMENTS']){
  layout.openTab(primary);layout.openTab('REVISIONS');layout.openTab('REVISIONS');
  layout.returnFromRecords();assert.equal(layout.getSnapshot().right_tab,primary);assert.equal(layout.getSnapshot().preferences.right_width,510);
 }
 layout.openTab('REVISIONS');const fresh=new DetailLayout('PLANNING',1600,storage);assert.equal(fresh.getSnapshot().right_tab,'REVISIONS');
 fresh.returnFromRecords();assert.equal(fresh.getSnapshot().right_tab,'AI');
 layout.viewport(1023);layout.returnFromRecords();assert.equal(layout.getSnapshot().right_tab,'REVISIONS');
 layout.viewport(1600);layout.returnFromRecords();assert.equal(layout.getSnapshot().right_tab,'COMMENTS');
});
