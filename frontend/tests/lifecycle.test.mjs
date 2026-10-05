import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementLifecycle} from '../src/requirements/lifecycle.ts';
import {detailPermissions} from '../src/requirements/permissions.ts';
import {ApiRejected,ApiUnknown} from '../src/api/client.ts';
const at='2026-10-06T01:10:00.000Z';
const root=status=>({id:1,status,title:'实际标题',requirement_no:'REQ000001',requirement_type:'NEW',initialization_mode:'DESIGN',template_key:'new-requirement',template_version:'v1',
 document_work_state:'IDLE',active_operation_id:null,active_operation_type:null,created_at:at,updated_at:at,completed_at:status==='COMPLETED'?at:null,state_started_at:null});
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:7,created_at:at,updated_at:at,markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const detail=status=>({requirement:root(status),current,activity:{kind:'IDLE'},comment_index:{requirement_id:1,document_id:2,content_version:7,total_count:0,open_count:0,blocks:[],comments:[]}});
const baseline={id:3,requirement_id:1,version_no:1,revision_type:'BASELINE',description:'初始化基线',source_content_version:7,created_at:at};
const initResult={requirement:root('ACTIVE'),current_document:{id:2,content_version:7},baseline_revision:baseline};
const deferred=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {resolve,promise};};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(operation,status){const f={prepares:[],submits:0,reads:[],readRoot:root(operation==='COMPLETE'?'COMPLETED':'ACTIVE'),readCurrent:{...current,content_version:99},response:operation==='INITIALIZATION'?initResult:root(operation==='COMPLETE'?'COMPLETED':'ACTIVE'),fail:true};
 const prepare=(...args)=>{f.prepares.push(args);return {submit:async()=>{f.submits++;if(f.fail){f.fail=false;throw new ApiUnknown(true);}return {data:f.response};}};};
 const api={prepareCompleteInitialization:prepare,prepareCompleteRequirement:prepare,prepareReactivateRequirement:prepare,
  getRequirement:async(id,signal)=>{f.reads.push(['ROOT',id,signal]);return {data:f.readRoot};},getCurrentDocument:async(id,signal)=>{f.reads.push(['CURRENT',id,signal]);return {data:f.readCurrent};},
  listRevisions:async(id,page,signal)=>{f.reads.push(['REVISIONS',id,page,signal]);return {data:{items:[baseline]}};}};
 return {f,api,flow:new RequirementLifecycle(operation,detail(status),api)};}
test('title has no extra IDLE restriction, mode does; lifecycle/read/viewport/history conditions use actual state',()=>{
 for(const work of ['MANUAL_EDITING','GUIDE_ACTIVE','SUGGESTION_REVIEWING']){
  const snapshot=detail('INITIALIZING');snapshot.requirement.document_work_state=work;const p=detailPermissions(snapshot,true);assert(p.title);assert(!p.mode&&!p.complete_initialization&&!p.manual_start);
 }
 assert(detailPermissions(detail('ACTIVE'),true).complete_requirement);assert(detailPermissions(detail('COMPLETED'),true).ask);assert(!detailPermissions(detail('COMPLETED'),true).title);
 for(const args of [[false,false,false],[true,true,false],[true,false,true]])assert(Object.values(detailPermissions(detail('ACTIVE'),...args)).every(value=>value===false));
 assert(Object.values(detailPermissions(null,true)).every(value=>value===false));
});
test('each unknown lifecycle observes resources then replays the original prepared action and preserves independent source version',async()=>{
 for(const [op,status] of [['INITIALIZATION','INITIALIZING'],['COMPLETE','ACTIVE'],['REACTIVATE','COMPLETED']]){
  const p=fixture(op,status),pending=p.flow.submit();assert.equal(p.flow.submit(),pending);assert(!await pending);assert.equal(p.flow.getSnapshot().phase,'UNKNOWN');assert(!await p.flow.submit());
  const retry=p.flow.retryUnknown();assert.equal(p.flow.retryUnknown(),retry);assert(await retry);assert.equal(p.f.prepares.length,1);assert.equal(p.f.submits,2);
  assert.deepEqual(p.f.prepares[0],op==='REACTIVATE'?[1]:[1,7]);assert.equal(p.flow.getSnapshot().observed.current.content_version,99);assert.equal(p.flow.getSnapshot().phase,'CONFIRMED');
  assert.equal(p.f.reads.length,op==='INITIALIZATION'?3:2);if(op==='INITIALIZATION')assert.equal(p.flow.getSnapshot().outcome.result.current_document.content_version,7);p.flow.dispose();
 }
});
test('read failure and malformed baseline receipt cannot confirm; original action remains for unknown recovery',async()=>{
 const p=fixture('INITIALIZATION','INITIALIZING');await p.flow.submit();p.api.getCurrentDocument=async()=>{throw Error('read');};assert(!await p.flow.retryUnknown());assert.equal(p.f.submits,1);assert.equal(p.flow.getSnapshot().phase,'UNKNOWN');
 p.api.getCurrentDocument=async()=>({data:current});p.f.response={...initResult,baseline_revision:{...baseline,source_content_version:99}};assert(!await p.flow.retryUnknown());assert.equal(p.flow.getSnapshot().outcome,null);assert.equal(p.f.prepares.length,1);
 p.f.response=initResult;assert(await p.flow.retryUnknown());p.flow.dispose();
});
test('known rejection stays ERROR, REQUEST_IN_PROGRESS stays unknown; retired lifetime never sends before microtask and aborts only reads',async()=>{
 const p=fixture('COMPLETE','ACTIVE');p.api.prepareCompleteRequirement=()=>({submit:async()=>{throw new ApiRejected('STATE_CONFLICT','状态冲突',null,'req-id',409);}});
 assert(!await p.flow.submit());assert.equal(p.flow.getSnapshot().phase,'ERROR');assert.equal(p.flow.getSnapshot().outcome,null);p.flow.dispose();
 const inProgress=fixture('COMPLETE','ACTIVE');let attempts=0;
 inProgress.api.prepareCompleteRequirement=()=>({submit:async()=>{if(++attempts===1)throw new ApiRejected('REQUEST_IN_PROGRESS','正在执行',null,'req-id',409);return {data:inProgress.f.response};}});
 assert(!await inProgress.flow.submit());assert.equal(inProgress.flow.getSnapshot().phase,'UNKNOWN');assert(await inProgress.flow.retryUnknown());assert.equal(attempts,2);inProgress.flow.dispose();
 const q=fixture('REACTIVATE','COMPLETED');const pending=q.flow.submit();q.flow.dispose();assert(!await pending);assert.equal(q.f.prepares.length,0);
 const z=fixture('COMPLETE','ACTIVE');await z.flow.submit();const held=deferred();let signal;
 z.api.getRequirement=async(_id,owned)=>{signal=owned;return held.promise;};const reading=z.flow.retryUnknown();await flush();z.flow.dispose();assert(signal.aborted);held.resolve({data:root('COMPLETED')});assert(!await reading);assert.equal(z.f.submits,1);assert.equal(z.flow.getSnapshot().outcome,null);
});
