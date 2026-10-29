import {test} from 'node:test';
import assert from 'node:assert/strict';
import {getEventListeners} from 'node:events';
import {ApiClient, ApiUnknown, ApiRejected, API_REQUEST_TIMEOUT_MS} from '../src/api/client.ts';

const KEY='00000000-0000-4000-8000-00000000000a';
const REQUEST='00000000-0000-4000-8000-00000000000b';
const settle=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const envelope={success:true,data:{id:1},error:null,meta:{request_id:REQUEST}};
const response=()=>new Response(JSON.stringify(envelope),{headers:{'Content-Type':'application/json'}});
const command=client=>client.prepare('POST','/api/v1/requirements',{}, {idempotent:true,success_status:200});
const isUnknown=mutation=>error=>error instanceof ApiUnknown&&error.mutation===mutation;

for(const mutation of [false,true])test(`H04 ${mutation?'write':'read'} deadline ends even an abort-ignoring header wait`,async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const held=deferred(),caller=new AbortController();let sent,decoded=0,finished=false;
 const client=new ApiClient(async(_url,options)=>{sent=options;return held.promise;},()=>KEY);
 const decode=value=>{decoded++;return value;};
 const pending=mutation?client.commit(command(client),decode,caller.signal):client.read('/api/v1/requirements/1',decode,[],caller.signal);
 const rejected=assert.rejects(pending,isUnknown(mutation)).then(()=>{finished=true;});
 await settle();t.mock.timers.tick(API_REQUEST_TIMEOUT_MS-1);await settle();assert(!finished);assert(!sent.signal.aborted);
 t.mock.timers.tick(1);await rejected;assert(sent.signal.aborted);assert(!caller.signal.aborted);assert.equal(getEventListeners(caller.signal,'abort').length,0);
 let cancelled=false;held.resolve(new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'Content-Type':'application/json'}}));
 await settle();assert(cancelled);assert.equal(decoded,0);
});

test('H04 body shares the original deadline, including partial native Response content',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const headers=deferred();let stream,owned,decoded=0,finished=false;
 const client=new ApiClient(async(_url,options)=>{owned=options.signal;return headers.promise;});
 const rejected=assert.rejects(client.read('/api/v1/requirements/1',value=>{decoded++;return value;}),isUnknown(false)).then(()=>{finished=true;});
 t.mock.timers.tick(20_000);
 headers.resolve(new Response(new ReadableStream({start(controller){stream=controller;controller.enqueue(new TextEncoder().encode('{'));}}),{headers:{'Content-Type':'application/json'}}));
 await settle();t.mock.timers.tick(9_999);await settle();assert(!finished);
 t.mock.timers.tick(1);await rejected;assert(owned.aborted);
 // A deliberately abort-ignoring body must not decode even if it later completes.
 stream.enqueue(new TextEncoder().encode(JSON.stringify(envelope).slice(1)));stream.close();await settle();assert.equal(decoded,0);
});

test('H04 external abort promptly ends headers or body; pre-aborted requests never send',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const phase of ['before','headers','body']){
  const caller=new AbortController(),held=deferred();let sends=0,owned;
  if(phase==='before')caller.abort();
  const client=new ApiClient(async(_url,options)=>{sends++;owned=options.signal;return phase==='body'?{headers:new Headers({'Content-Type':'application/json'}),text:()=>held.promise}:held.promise;},()=>KEY);
  const rejected=assert.rejects(client.commit(command(client),x=>x,caller.signal),isUnknown(true));
  await settle();caller.abort();await rejected;assert.equal(sends,phase==='before'?0:1);if(owned)assert(owned.aborted);
  assert.equal(getEventListeners(caller.signal,'abort').length,0);if(sends)held.reject(Error('late transport rejection'));await settle();
 }
 t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);
});

test('H04 successful, rejected and malformed exchanges remove timers/listeners without late abort',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const outcome of ['success','rejected','malformed','network']){
  let owned;const caller=new AbortController();
  const client=new ApiClient(async(_url,options)=>{owned=options.signal;
   if(outcome==='network')throw Error('network');
   if(outcome==='success')return response();
   if(outcome==='malformed')return new Response('{',{headers:{'Content-Type':'application/json'}});
   return new Response(JSON.stringify({success:false,data:null,error:{code:'STATE_CONFLICT',message:'conflict',details:null},meta:{request_id:REQUEST}}),{status:409,headers:{'Content-Type':'application/json'}});
  });
  const pending=client.read('/api/v1/requirements/1',x=>x,[],caller.signal);
  if(outcome==='success')assert.equal((await pending).data.id,1);else await assert.rejects(pending,outcome==='rejected'?ApiRejected:ApiUnknown);
  assert.equal(getEventListeners(caller.signal,'abort').length,0);caller.abort();t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);assert(!owned.aborted);
 }
});

test('H04 recovery keeps exact original key/body and owns a new independent deadline',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const first=deferred(),second=deferred(),sent=[];let keys=0;
 const client=new ApiClient(async(_url,options)=>{sent.push(options);return sent.length===1?first.promise:second.promise;},()=>{keys++;return KEY;});
 const body={instruction:'original',expected_version:1},action=client.prepare('POST','/api/v1/requirements',body,{idempotent:true,success_status:200});body.instruction='changed';
 const failed=assert.rejects(client.commit(action,x=>x),isUnknown(true));t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);await failed;
 const retry=client.commit(action,x=>x);await settle();t.mock.timers.tick(API_REQUEST_TIMEOUT_MS-1);assert(!sent[1].signal.aborted);
 second.resolve(response());assert.equal((await retry).data.id,1);assert.equal(keys,1);assert.equal(sent[0].body,sent[1].body);assert.equal(sent[1].headers['Idempotency-Key'],KEY);
 first.reject(Error('late failure'));await settle();t.mock.timers.tick(1);assert(!sent[1].signal.aborted);
});
