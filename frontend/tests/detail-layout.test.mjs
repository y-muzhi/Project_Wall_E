import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DetailLayout,DetailViewportGuard,decodeDetailPreferences,preferencesKey} from '../src/requirements/detail-layout.ts';
const store = () => {const values=new Map(),writes=[];return {values,writes,getItem:key=>values.get(key)??null,setItem(key,value){writes.push({key,value});values.set(key,value);}};};
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle = () => new Promise(resolve=>setImmediate(resolve));

test('full viewport geometry preserves editor minimum/right half bound, temporary clamp and original preferences through all breakpoints',()=>{
  const storage=store(),layout=new DetailLayout('INITIALIZING',1600,storage);
  assert.equal(layout.getSnapshot().right_width,420);layout.resizeRight(600);assert.equal(layout.getSnapshot().preferences.right_width,600);
  const writes=storage.writes.length;
  for(const width of [1280,1279,1024,1023,900,1024,1279,1280,1600]){
    layout.viewport(width);const s=layout.getSnapshot();assert.equal(s.preferences.right_width,600);
    if(width>=1024){assert(s.document_width>=640);if(s.right_open){assert(s.right_width>=360);assert(s.right_width<=s.right_max);}if(width<1280)assert(!(s.left_open&&s.right_open));}
    else assert(!s.left_open&&!s.right_open);
  }
  assert.equal(storage.writes.length,writes);assert.equal(layout.getSnapshot().right_width,600);
  assert(layout.getSnapshot().left_open&&layout.getSnapshot().right_open);
});
test('explicit compact open selects one side without persisting automatic collapse; tabs and legitimate user width survive a fresh browser owner',()=>{
  const storage=store(),layout=new DetailLayout('INITIALIZING',1024,storage);
  assert(!layout.getSnapshot().left_open&&layout.getSnapshot().right_open);
  layout.toggleLeft();assert(layout.getSnapshot().left_open&&!layout.getSnapshot().right_open);assert(layout.getSnapshot().preferences.right_open);
  layout.openTab('COMMENTS');assert(!layout.getSnapshot().left_open&&layout.getSnapshot().right_open);assert(layout.getSnapshot().preferences.left_open);
  layout.viewport(1600);assert(layout.getSnapshot().left_open&&layout.getSnapshot().right_open);layout.resizeRight(99999);
  const saved=JSON.parse(storage.values.get(preferencesKey)),fresh=new DetailLayout('ACTIVE',1600,storage);assert.deepEqual(fresh.getSnapshot().preferences,saved);
  assert.equal(fresh.getSnapshot().right_tab,'COMMENTS');layout.toggleRight();assert(!layout.getSnapshot().right_open);assert(layout.getSnapshot().left_open);
  assert(new DetailLayout('ACTIVE',1600,store()).getSnapshot().left_open);assert(!new DetailLayout('ACTIVE',1600,store()).getSnapshot().right_open);
});
test('malformed or unavailable preference storage is visible without preventing in-memory interaction or writing defaults on mount',()=>{
  for(const v of [{schema_version:1,left_open:true,right_open:true,right_tab:'INVALID',right_width:420},{schema_version:1,left_open:true,right_open:true,right_tab:'AI',right_width:359},{schema_version:1,left_open:true,right_open:true,right_tab:'AI',right_width:Infinity},{schema_version:2,left_open:true,right_open:true,right_tab:'AI',right_width:420}])assert.throws(()=>decodeDetailPreferences(v));
  const storage=store();storage.values.set(preferencesKey,'broken');const layout=new DetailLayout('ACTIVE',1280,storage);assert(layout.getSnapshot().warning);assert.equal(storage.writes.length,0);
  layout.openTab('REVISIONS');assert.equal(layout.getSnapshot().warning,null);
  const denied={getItem(){throw Error('denied');},setItem(){throw Error('denied');}},other=new DetailLayout('ACTIVE',1280,denied);
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
