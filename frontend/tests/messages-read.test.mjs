import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementMessages} from '../src/messages/read.ts';
const at='2026-10-06T04:00:00.000Z';
const item=sequence=>({id:sequence+100,requirement_id:1,guide_run_id:2,sequence_no:sequence,role:'USER',content:'正式消息 '+sequence,message_type:'TEXT',structured_content:null,reply_to_message_id:null,created_at:at,card_state:null});
function fixture(count=25){const facts={items:Array.from({length:count},(_,i)=>item(i+1)),calls:[],drop:false};const api={listMessages:async(_id,before)=>{facts.calls.push(before);if(facts.drop){facts.drop=false;throw Error('Read failed');}const eligible=facts.items.filter(row=>before===null||row.sequence_no<before),items=eligible.slice(-20),more=eligible.length>20;return {data:{items},meta:{pagination:{page_size:20,has_more:more,next_cursor:more?items[0].sequence_no:null}}};}};return {facts,api};}
const defer=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
test('actual fixed cursor, exclusive older window, immutable ID dedupe and preserved conversation on repeat latest',async()=>{
 const f=fixture(),reader=new RequirementMessages(1,f.api);assert(await reader.refresh());assert.deepEqual(f.facts.calls,[null]);assert.equal(reader.getSnapshot().items.length,20);assert.equal(reader.getSnapshot().next_cursor,6);
 assert(await reader.older());assert.deepEqual(f.facts.calls,[null,6]);assert.equal(reader.getSnapshot().items.length,25);assert(!reader.getSnapshot().has_more);assert(await reader.refresh());assert.deepEqual(f.facts.calls,[null,6,null,6]);assert.equal(reader.getSnapshot().items.length,25);assert.equal(reader.getSnapshot().items[0].id,101);reader.dispose();
});
test('latest refresh bridges more than 20 new arrivals back through displayed history instead of losing an unseen middle',async()=>{
 const f=fixture(),reader=new RequirementMessages(1,f.api);await reader.refresh();await reader.older();f.facts.items=Array.from({length:70},(_,i)=>item(i+1));assert(await reader.refresh());
 assert.deepEqual(f.facts.calls.slice(2),[null,51,31,11]);assert.equal(reader.getSnapshot().items.length,70);assert.deepEqual(reader.getSnapshot().items.map(row=>row.sequence_no),Array.from({length:70},(_,i)=>i+1));reader.dispose();
});
test('failed older window retains original cursor and exact visible objects; retry does not pretend end of history',async()=>{
 const f=fixture(),reader=new RequirementMessages(1,f.api);await reader.refresh();const saved=reader.getSnapshot().items;f.facts.drop=true;assert(!await reader.older());assert.equal(reader.getSnapshot().items,saved);assert.equal(reader.getSnapshot().next_cursor,6);assert(reader.getSnapshot().has_more);assert.match(reader.getSnapshot().error,/更早/);
 assert(await reader.older());assert.deepEqual(f.facts.calls,[null,6,6]);reader.dispose();
});
test('refresh adoption rejects immutable content/sequence ownership collisions without discarding old messages',async()=>{
 const f=fixture(3),reader=new RequirementMessages(1,f.api);await reader.refresh();const saved=reader.getSnapshot().items;f.facts.items[1]={...item(2),content:'伪造历史改写'};assert(!await reader.refresh());assert.equal(reader.getSnapshot().items,saved);
 f.facts.items=[item(1),{...item(2),requirement_id:9},item(3)];assert(!await reader.refresh());assert.equal(reader.getSnapshot().items,saved);f.facts.items=[item(1),{...item(2),id:999,sequence_no:1},item(3)];assert(!await reader.refresh());reader.dispose();
});
test('actual derived card state changes are adopted, damaged structure remains null, and empty initial window is distinct from unread',async()=>{
 const f=fixture(1);f.facts.items=[{...item(1),role:'ASSISTANT',message_type:'INTERACTION_CARDS',structured_content:{schema_version:1},card_state:'AVAILABLE'}];const reader=new RequirementMessages(1,f.api);assert.equal(reader.getSnapshot().items,null);await reader.refresh();
 f.facts.items=[{...f.facts.items[0],card_state:'EXPIRED'}];assert(await reader.refresh());assert.equal(reader.getSnapshot().items[0].card_state,'EXPIRED');f.facts.items=[{...f.facts.items[0],structured_content:null,card_state:null}];assert(await reader.refresh());assert.equal(reader.getSnapshot().items[0].content,'正式消息 1');reader.dispose();
 const empty=new RequirementMessages(1,fixture(0).api);assert(await empty.refresh());assert.deepEqual(empty.getSnapshot().items,[]);assert(!await empty.older());empty.dispose();
});
test('pause aborts only owned GET and suppresses old windows; retired queued read sends nothing',async()=>{
 const f=fixture(2),hold=defer();let signal;const reader=new RequirementMessages(1,{listMessages:async(_id,_before,owned)=>{signal=owned;return hold.promise;}}),pending=reader.refresh();await flush();reader.pause();assert(signal.aborted);hold.resolve(await f.api.listMessages(1,null));assert(!await pending);assert.equal(reader.getSnapshot().items,null);reader.dispose();
 const retired=new RequirementMessages(1,f.api),queued=retired.refresh();retired.dispose();assert(!await queued);assert.deepEqual(f.facts.calls,[null]);
});
