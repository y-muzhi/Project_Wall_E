import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementRunHistory,runHistoryQuery} from '../src/guide/history.ts';
const at='2026-10-06T04:00:00.000Z',item=id=>({id,requirement_id:1,created_at:at,action_type:'ASK',status:'FAILED'});
function fixture(){const facts={rows:Array.from({length:25},(_,i)=>item(25-i)),calls:[],drop:false};const api={listGuideRuns:async(_id,query)=>{facts.calls.push(query);if(facts.drop)throw Error('Failed');const rows=facts.rows.filter(row=>(!query.status.length||query.status.includes(row.status))&&(!query.action_type.length||query.action_type.includes(row.action_type)));return {data:{items:rows.slice((query.page-1)*20,query.page*20)},meta:{pagination:{page:query.page,page_size:20,total:rows.length,total_pages:Math.ceil(rows.length/20)}}};}};return {facts,api};}
test('actual descending history keeps complete pagination/filter pair and canonical OR/AND query without altering selected run',async()=>{
 const f=fixture(),reader=new RequirementRunHistory(1,f.api);assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.items.length,20);assert(await reader.refresh({page:2,status:['FAILED','FAILED'],action_type:['ASK']}));assert.deepEqual(reader.getSnapshot().confirmed.items.map(row=>row.id),[5,4,3,2,1]);assert.deepEqual(f.facts.calls[1],{page:2,status:['FAILED'],action_type:['ASK']});
 assert(await reader.refresh({status:['COMPLETED'],action_type:['REVIEW']}));assert.equal(reader.getSnapshot().confirmed.pagination.total,0);assert.deepEqual(reader.getSnapshot().confirmed.items,[]);reader.dispose();assert.throws(()=>runHistoryQuery({page:100001}));assert.throws(()=>runHistoryQuery({status:['OTHER']}));
});
test('failed filter/page retains old actual labels and page; exact requested query can be retried',async()=>{
 const f=fixture(),reader=new RequirementRunHistory(1,f.api);await reader.refresh();const saved=reader.getSnapshot().confirmed;f.facts.drop=true;assert(!await reader.refresh({page:2,status:['FAILED']}));assert.equal(reader.getSnapshot().confirmed,saved);assert.equal(reader.getSnapshot().requested.page,2);f.facts.drop=false;assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.query.page,2);reader.dispose();
});
test('wrong ownership, unknown ordering and duplicate identities fail rather than replacing a confirmed history',async()=>{
 const f=fixture(),reader=new RequirementRunHistory(1,f.api);await reader.refresh();const saved=reader.getSnapshot().confirmed;f.facts.rows[0]={...item(25),requirement_id:99};assert(!await reader.refresh());assert.equal(reader.getSnapshot().confirmed,saved);f.facts.rows=[item(1),item(2)];assert(!await reader.refresh());f.facts.rows=[item(2),item(2)];assert(!await reader.refresh());reader.dispose();
});
test('retired queued history makes no HTTP request',async()=>{const f=fixture(),reader=new RequirementRunHistory(1,f.api),pending=reader.refresh();reader.dispose();assert(!await pending);assert.equal(f.facts.calls.length,0);});
