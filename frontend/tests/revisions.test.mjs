import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementRevisionSave} from '../src/revisions/save.ts';
import {RequirementRevisions} from '../src/revisions/read.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-06T04:00:00.000Z';
const requirement={id:1,status:'ACTIVE',document_work_state:'IDLE'};
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:7};
const detail={requirement,current,activity:{kind:'IDLE'},comment_index:{}};
const summary=(id=3,version_no=2)=>({id,requirement_id:1,version_no,revision_type:version_no===1?'BASELINE':'MANUAL',description:null,source_content_version:7,created_at:at});
const revision=(id=3,version_no=2)=>({...summary(id,version_no),markdown_content:'历史实际正文',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}});
const paged=(items,page=1,total=items.length)=>({data:{items},meta:{pagination:{page,page_size:20,total,total_pages:Math.ceil(total/20)}}});
const deferred=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};

test('revision description 1000 code points/multiline/blank normalization and exact CURRENT expected version; no BASELINE creation',async()=>{
 const prepared=[];const api={prepareCreateRevision:(id,body)=>{prepared.push({id,body});return {submit:async()=>({data:{...summary(),description:body.description}})};}};
 const flow=new RequirementRevisionSave(detail,api);flow.change('😀'.repeat(1001));assert(!await flow.save());assert.equal(prepared.length,0);flow.change('  '+ '😀'.repeat(999)+'\r\nx  ');assert(!await flow.save()); // newline plus x makes 1001
 flow.change(' \r\n'+ '😀'.repeat(999)+'x\u0085');const pending=flow.save();assert.equal(flow.save(),pending);assert(await pending);assert.equal([...prepared[0].body.description].length,1000);assert.equal(prepared[0].body.expected_version,7);assert.equal(flow.getSnapshot().receipt.version_no,2);assert(!await flow.save());flow.dispose();
 const blank=new RequirementRevisionSave(detail,api);blank.change(' \r\n\u0085 ');assert(await blank.save());assert.equal(prepared[1].body.description,null);blank.dispose();
 assert.throws(()=>new RequirementRevisionSave({...detail,requirement:{...requirement,status:'INITIALIZING'}},api));
});
test('unknown revision observes matching list but confirms only original positive receipt, read failure never resends',async()=>{
 let prepares=0,sends=0,reads=0,readFails=false;const receipt={...summary(),description:'同样说明'};
 const api={prepareCreateRevision:()=>{prepares++;return {submit:async()=>{sends++;if(sends===1)throw new ApiUnknown(true);return {data:receipt};}};},listRevisions:async()=>{reads++;if(readFails)throw Error('read');return paged([receipt]);}};
 const flow=new RequirementRevisionSave(detail,api);flow.change(' 同样说明 ');assert(!await flow.save());assert(!flow.rebase({...detail,current:{...current,content_version:99}}));assert(!await flow.save());readFails=true;assert(!await flow.retryUnknown());assert.equal(sends,1);readFails=false;assert(await flow.retryUnknown());assert.equal(prepares,1);assert.equal(sends,2);assert.equal(reads,2);assert.equal(flow.getSnapshot().receipt.source_content_version,7);assert.equal(flow.getSnapshot().description,' 同样说明 ');flow.dispose();
});
test('known conflict retains input until actual rebase; preparation and retired queued writes do not send',async()=>{
 let calls=0;const api={prepareCreateRevision:(_id,body)=>({submit:async()=>{calls++;if(body.expected_version===7)throw new ApiRejected('CONTENT_VERSION_CONFLICT','版本冲突',null,'id',409);return {data:{...summary(),source_content_version:9,description:body.description}};}})};
 const flow=new RequirementRevisionSave(detail,api);flow.change('原说明');assert(!await flow.save());assert(flow.rebase({...detail,current:{...current,content_version:9}}));assert.equal(flow.getSnapshot().description,'原说明');assert(await flow.save());assert.equal(calls,2);flow.dispose();
 const retired=new RequirementRevisionSave(detail,api);const queued=retired.save();retired.dispose();assert(!await queued);assert.equal(calls,2);
});
test('actual pagination keeps old result on errors and aborts retired GETs; page labels are actual, not the pending request',async()=>{
 const first=deferred(),second=deferred();let signal;const api={listRevisions:async(_id,page,owned)=>{if(page===1){signal=owned;return first.promise;}return second.promise;}};
 const flow=new RequirementRevisions(1,api),old=flow.refresh(1);await flush();const latest=flow.refresh(2);await flush();assert(signal.aborted);second.resolve(paged([summary(23,22),summary(22,21)],2,22));assert(await latest);first.resolve(paged([summary()],1));assert(!await old);assert.equal(flow.getSnapshot().list.pagination.page,2);
 api.listRevisions=async()=>{throw Error('read');};assert(!await flow.refresh(3));assert.equal(flow.getSnapshot().page,3);assert.equal(flow.getSnapshot().list.pagination.page,2);flow.pause();assert(!flow.getSnapshot().active);assert.throws(()=>flow.refresh(100001));flow.dispose();
});
test('history checks immutable summary/owner, retires older reads, and never closes before actual parent adoption',async()=>{
 const one=deferred(),two=deferred();let signal;const api={getRevision:async(id,owned)=>{if(id===3){signal=owned;return one.promise;}return two.promise;}};
 const flow=new RequirementRevisions(1,api),old=flow.open(summary());await flush();const latest=flow.open(summary(4,3));await flush();assert(signal.aborted);two.resolve({data:revision(4,3)});assert(await latest);one.resolve({data:revision()});assert(!await old);assert.equal(flow.getSnapshot().history.snapshot.id,4);
 assert.equal(await flow.exit(async()=>{throw Error('actual read');}),null);assert.equal(flow.getSnapshot().history.snapshot.id,4);assert.equal(flow.getSnapshot().history.phase,'ERROR');
 const actual=await flow.exit(async()=>({...detail,current:{...current,content_version:9}}));assert.equal(flow.getSnapshot().history.phase,'RESTORING');assert.equal(flow.getSnapshot().history.snapshot.id,4);assert(!flow.finishExit({...actual}));assert(!await flow.open(summary()));assert(flow.finishExit(actual));assert.equal(flow.getSnapshot().history.phase,'CLOSED');assert.equal(flow.getSnapshot().history.restored.current.content_version,9);flow.dispose();
 const bad=new RequirementRevisions(1,{getRevision:async()=>({data:{...revision(),description:'不同的不可变说明'}})});assert(!await bad.open(summary()));assert.equal(bad.getSnapshot().history.snapshot,null);bad.dispose();
});
