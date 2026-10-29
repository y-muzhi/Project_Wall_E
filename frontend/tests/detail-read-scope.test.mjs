import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DetailReadScope} from '../src/api/detail-read-scope.ts';
import {WalleApi} from '../src/api/walle.ts';
import {ApiClient,ApiUnknown,API_REQUEST_TIMEOUT_MS} from '../src/api/client.ts';
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('H04 overlapping timed-out writes release scoped reads only after both settle',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const sent=[];
 const client=new ApiClient(async(_url,options)=>{sent.push(options);if(options.method==='GET')throw Error('isolated read ended');return new Promise(()=>{});},()=> '00000000-0000-4000-8000-00000000000a');
 const api=new WalleApi(client,{}).forDetailReads();
 try{
  const first=assert.rejects(api.prepareCancelGuide(8).submit(),ApiUnknown);await flush();t.mock.timers.tick(10_000);
  const second=assert.rejects(api.prepareCancelGuide(9).submit(),ApiUnknown);let released=false;const gate=api.waitForDetailWrites().then(()=>{released=true;});
  const reading=assert.rejects(api.getGuideRun(8),ApiUnknown);await flush();assert.deepEqual(sent.map(x=>x.method),['POST','POST']);
  t.mock.timers.tick(API_REQUEST_TIMEOUT_MS-10_000);await first;await flush();assert(!released);assert.equal(sent.length,2);
  t.mock.timers.tick(10_000);await second;await gate;await reading;assert(released);assert.deepEqual(sent.map(x=>x.method),['POST','POST','GET']);
 }finally{api.disposeDetailReads();}
});

test('ten consumers share one in-flight fact, then a later observation reads again',async()=>{
 const scope=new DetailReadScope(),held=deferred();let reads=0;
 const load=()=>{reads++;return held.promise;};
 const pending=Array.from({length:10},()=>scope.read('run:8',undefined,load));await flush();assert.equal(reads,1);
 held.resolve('actual');assert.deepEqual(await Promise.all(pending),Array(10).fill('actual'));
 assert.equal(await scope.read('run:8',undefined,async()=>{reads++;return 'new';}),'new');assert.equal(reads,2);scope.dispose();
});
test('one cancellation cannot abort another consumer; the final consumer releases the actual read',async()=>{
 const scope=new DetailReadScope(),held=deferred(),a=new AbortController(),b=new AbortController();let owned;
 const load=signal=>{owned=signal;return held.promise;};
 const first=scope.read('run:8',a.signal,load),second=scope.read('run:8',b.signal,load),rejected=assert.rejects(first,{name:'AbortError'});
 await flush();a.abort();await rejected;assert(!owned.aborted);held.resolve(8);assert.equal(await second,8);
 const last=new AbortController(),waiting=scope.read('run:9',last.signal,signal=>{owned=signal;return new Promise(()=>{});}),stopped=assert.rejects(waiting,{name:'AbortError'});
 await flush();last.abort();await stopped;assert(owned.aborted);scope.dispose();
});
test('a write barrier rejects a late pre-write response and cannot delete a newer job with the same key',async()=>{
 const scope=new DetailReadScope(),old=deferred(),fresh=deferred();
 const before=scope.read('detail:1',undefined,()=>old.promise),rejected=assert.rejects(before,{name:'AbortError'});await flush();scope.invalidate();
 let reads=0;const after=scope.read('detail:1',undefined,()=>{reads++;return fresh.promise;});await flush();old.resolve('old');await rejected;
 const joined=scope.read('detail:1',undefined,()=>{reads++;return Promise.resolve('wrong');});fresh.resolve('new');assert.equal(await after,'new');assert.equal(await joined,'new');assert.equal(reads,1);scope.dispose();
});
test('resource keys, independent detail lifetimes, errors, and retirement never cross reuse boundaries',async()=>{
 const a=new DetailReadScope(),b=new DetailReadScope();let count=0;const load=async()=>++count;
 assert.deepEqual(await Promise.all([a.read('detail:1',undefined,load),a.read('detail:1:expanded',undefined,load),b.read('detail:1',undefined,load)]),[1,2,3]);
 await assert.rejects(a.read('run:8',undefined,async()=>{throw Error('offline');}),/offline/);
 assert.equal(await a.read('run:8',undefined,async()=>8),8);a.dispose();await assert.rejects(a.read('run:8',undefined,load),{name:'AbortError'});b.dispose();
});
test('the actual API keeps read results immutable and a failed command also fences reads before and after its send',async()=>{
 const old=deferred(),commit=deferred();let reads=0;
 const client={read:()=>{reads++;return reads===1?old.promise:Promise.resolve({data:{id:8},meta:{}});},prepare:()=>({}),commit:()=>commit.promise};
 const api=new WalleApi(client,{}).forDetailReads();const before=api.getGuideRun(8),retired=assert.rejects(before,{name:'AbortError'});await flush();
 const epoch=api.detailReadEpoch,command=api.prepareCancelGuide(8).submit(),failed=assert.rejects(command,/offline/);assert(api.detailReadEpoch>epoch);
 old.resolve({data:{id:8},meta:{}});await retired;commit.reject(Error('offline'));await failed;assert.equal(api.detailReadEpoch,epoch+2);
 const [one,two]=await Promise.all([api.getGuideRun(8),api.getGuideRun(8)]);assert.equal(reads,2);assert(Object.isFrozen(one.data));assert.equal(one,two);api.disposeDetailReads();
});

test('the actual API merges equal message windows and keeps cursors and document indices distinct',async()=>{
 const held=deferred();let reads=0;
 const api=new WalleApi({read:async path=>{reads++;await held.promise;return {data:{items:[]},meta:path.endsWith('/messages')?{pagination:{page_size:20,has_more:false,next_cursor:null}}:{}};}},{}).forDetailReads();
 const latest=api.listMessages(1),same=api.listMessages(1),older=api.listMessages(1,8),index=api.getCommentIndex(1,2),other=api.getCommentIndex(1,3);
 await flush();assert.equal(reads,4);held.resolve();await Promise.all([latest,same,older,index,other]);api.disposeDetailReads();
});

test('reads started during a write wait for its result; overlapping writes do not release the barrier early',async()=>{
 const first=deferred(),second=deferred();let reads=0,commits=0;
 const api=new WalleApi({prepare:()=>({}),commit:()=>++commits===1?first.promise:second.promise,read:async()=>{reads++;return {data:{id:8},meta:{}};}},{}).forDetailReads();
 const one=api.prepareCancelGuide(8).submit(),two=api.prepareCancelGuide(9).submit(),read=api.getGuideRun(8);
 await flush();assert.equal(reads,0);first.resolve({data:{},meta:{}});await one;await flush();assert.equal(reads,0);
 second.resolve({data:{},meta:{}});await two;await read;assert.equal(reads,1);api.disposeDetailReads();
});
