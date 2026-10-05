import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ManualDraftStart} from '../src/documents/manual-start.ts';
import {ApiRejected,ApiUnknown} from '../src/api/client.ts';
const at='2026-10-05T14:00:00.000Z',pair={markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const root={id:1,status:'ACTIVE',document_work_state:'IDLE',active_operation_type:null,active_operation_id:null};
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:7,created_at:at,updated_at:at,...pair};
const draft={...current,id:3,document_type:'MANUAL_DRAFT',content_version:1};
const receipt={requirement:{...root,document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3},manual_draft:draft};
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(){const f={prepare:0,submit:0,reads:0,fail:null,receipt};const action={submit:async()=>{f.submit++;if(f.fail){const e=f.fail;f.fail=null;throw e;}return {data:f.receipt};}};
 const api={prepareStartManualDraft:(id,version)=>{f.prepare++;assert.equal(id,1);assert.equal(version,7);return action;},getRequirement:async()=>{f.reads++;return {data:receipt.requirement};},getCurrentDocument:async()=>{f.reads++;return {data:current};},getManualDraft:async()=>{f.reads++;return {data:draft};}};return {f,api,action};}

test('requires actual idle writable CURRENT; captures source and coalesces double start until the exact independent creation receipt',async()=>{
 for(const changed of [{status:'COMPLETED'},{document_work_state:'MANUAL_EDITING'},{active_operation_id:3}])assert.throws(()=>new ManualDraftStart({...root,...changed},current,{}));
 assert.throws(()=>new ManualDraftStart(root,{...current,document_type:'MANUAL_DRAFT'},{}));
 const p=fixture(),held=deferred();p.action.submit=()=>held.promise;const mutable=structuredClone(current),flow=new ManualDraftStart(root,mutable,p.api);mutable.content_version=88;
 const first=flow.start();assert.equal(flow.start(),first);await flush();assert.equal(flow.getSnapshot().phase,'SUBMITTING');assert.equal(flow.getSnapshot().receipt,null);
 held.resolve({data:receipt});assert(await first);assert.equal(flow.getSnapshot().phase,'STARTED');assert.equal(flow.getSnapshot().receipt.manual_draft.content_version,1);assert(Object.isFrozen(flow.getSnapshot().receipt.manual_draft));assert.equal(p.f.prepare,1);assert(!await flow.start());flow.dispose();
});
test('unknown creation jointly reads resources then replays only original action; existing similar draft cannot itself confirm success',async()=>{
 const p=fixture();p.f.fail=new ApiUnknown(true);const flow=new ManualDraftStart(root,current,p.api);assert(!await flow.start());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert(!await flow.start());assert.equal(p.f.prepare,1);
 const held=deferred();p.action.submit=()=>{p.f.submit++;return held.promise;};const retry=flow.retryUnknown();assert.equal(flow.retryUnknown(),retry);await flush();assert.equal(p.f.reads,3);assert.equal(flow.getSnapshot().receipt,null);assert.equal(flow.getSnapshot().phase,'SUBMITTING');assert.equal(p.f.prepare,1);
 held.resolve({data:receipt});assert(await retry);assert.equal(p.f.submit,2);assert.equal(flow.getSnapshot().observed.manual_draft.id,3);flow.dispose();
});
test('missing draft alone and read failure never resolve unknown; REQUEST_IN_PROGRESS remains locked; known conflict stays a refusal',async()=>{
 const p=fixture();p.f.fail=new ApiRejected('REQUEST_IN_PROGRESS','processing',null,'r',409);const flow=new ManualDraftStart(root,current,p.api);assert(!await flow.start());assert.equal(flow.getSnapshot().phase,'UNKNOWN');
 p.api.getManualDraft=async()=>{throw Error('network');};assert(!await flow.retryUnknown());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert.equal(p.f.submit,1);
 p.api.getManualDraft=async()=>{throw new ApiRejected('MANUAL_DRAFT_NOT_FOUND','missing',null,'r',404);};p.f.fail=new ApiUnknown(true);assert(!await flow.retryUnknown());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert.equal(flow.getSnapshot().observed.manual_draft,null);assert.equal(p.f.prepare,1);
 p.f.fail=new ApiRejected('WORK_STATE_CONFLICT','occupied',null,'r',409);assert(!await flow.retryUnknown());assert.equal(flow.getSnapshot().phase,'ERROR');assert.equal(flow.getSnapshot().receipt,null);flow.dispose();
});
test('wrong creation content or root identity remains unknown; disposed lifetime ignores late native result without cancelling business',async()=>{
 for(const change of [{manual_draft:{...draft,markdown_content:'other'}},{manual_draft:{...draft,id:2}},{requirement:{...receipt.requirement,id:9}},{manual_draft:{...draft,block_state_json:{...pair.block_state_json,next_block_id:4}}}]){
   const p=fixture();p.f.receipt={...receipt,...change};const flow=new ManualDraftStart(root,current,p.api);assert(!await flow.start());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert.equal(flow.getSnapshot().receipt,null);flow.dispose();
 }
 const p=fixture(),held=deferred();p.action.submit=()=>held.promise;const flow=new ManualDraftStart(root,current,p.api),pending=flow.start();await flush();flow.dispose();held.resolve({data:receipt});assert(!await pending);assert.equal(flow.getSnapshot().receipt,null);
 const early=fixture(),closed=new ManualDraftStart(root,current,early.api),notSent=closed.start();closed.dispose();assert(!await notSent);assert.equal(early.f.submit,0);
});

test('valid native lifecycle advancement before start is accepted at the same CURRENT version, not compared to stale loaded status',async()=>{
 const p=fixture(),flow=new ManualDraftStart({...root,status:'INITIALIZING'},current,p.api);
 assert(await flow.start());assert.equal(flow.getSnapshot().receipt.requirement.status,'ACTIVE');assert.equal(flow.getSnapshot().receipt.manual_draft.content_version,1);flow.dispose();
});
