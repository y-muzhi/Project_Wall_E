import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementPropertyEdit} from '../src/requirements/property-edit.ts';
import {detailPermissions} from '../src/requirements/permissions.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-06T02:00:00.000Z';
const root={id:1,requirement_no:'REQ000001',title:'实际标题',requirement_type:'NEW',initialization_mode:'DESIGN',status:'INITIALIZING',document_work_state:'IDLE',
  active_operation_id:null,active_operation_type:null,template_key:'new-requirement',template_version:'v1',created_at:at,updated_at:at,completed_at:null,state_started_at:null};
const detail=(requirement=root)=>({requirement,current:{id:2,requirement_id:1,document_type:'CURRENT'},activity:{kind:'IDLE'},comment_index:{}});
const deferred=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
function fixture(field='title',actual=root){const f={prepares:[],submits:0,reads:0,fail:false,readRoot:actual,response:null};
 const api={prepareUpdateRequirement:(id,body)=>{f.prepares.push({id,body});return {submit:async()=>{f.submits++;if(f.fail)throw new ApiUnknown(true);return {data:f.response??{...actual,...body}};}};},getRequirement:async()=>{f.reads++;return {data:f.readRoot};}};
 const flow=new RequirementPropertyEdit(field,detail(actual),api);return {f,api,flow};}

test('single field PATCH normalizes title by code points, preserves raw input on errors and permits title during manual activity',async()=>{
 const p=fixture('title',{...root,document_work_state:'MANUAL_EDITING',active_operation_id:9,active_operation_type:'MANUAL_DRAFT',state_started_at:at});assert(p.flow.begin());
 for(const bad of ['', 'x\ny','😀'.repeat(21), '\ud800']){p.flow.change(bad);assert(!await p.flow.save());assert.equal(p.f.prepares.length,0);assert.equal(p.flow.getSnapshot().draft,bad);}
 p.flow.change(' \r\n'+ '😀'.repeat(20)+'\u0085');const pending=p.flow.save();assert.equal(p.flow.save(),pending);assert(await pending);
 assert.deepEqual(p.f.prepares[0],{id:1,body:{title:'😀'.repeat(20)}});assert.equal(p.f.submits,1);assert.equal(p.flow.getSnapshot().phase,'CONFIRMED');
 assert(!await p.flow.save());p.flow.adoptDetail(detail({...root,title:'其他页面更新'}));p.flow.finishConfirmed();assert.equal(p.flow.getSnapshot().draft,'其他页面更新');assert(!await p.flow.save());p.flow.dispose();
});
test('unknown PATCH matching GET remains observation and never resends; explicit continue/save is a new prepared intention',async()=>{
 const p=fixture();p.flow.begin();p.flow.change('  新标题😀  ');p.f.fail=true;assert(!await p.flow.save());assert.equal(p.flow.getSnapshot().phase,'UNKNOWN');assert(!p.flow.cancel());assert(!await p.flow.save());
 p.f.readRoot={...root,title:'新标题😀'};const pending=p.flow.inspectUnknown();assert.equal(p.flow.inspectUnknown(),pending);assert(await pending);
 assert.equal(p.flow.getSnapshot().phase,'OBSERVED');assert.equal(p.flow.getSnapshot().receipt,null);assert.equal(p.flow.getSnapshot().draft,'  新标题😀  ');assert.equal(p.f.submits,1);assert(!await p.flow.inspectUnknown());assert.equal(p.f.reads,1);
 assert(p.flow.continueEditing());p.f.fail=false;assert(await p.flow.save());assert.equal(p.f.prepares.length,2);assert.equal(p.f.submits,2);p.flow.dispose();
});
test('initialization mode is creation-only in every lifecycle and occupancy, never preparing or sending PATCH',async()=>{
 for(const actual of [root,{...root,status:'ACTIVE'},{...root,document_work_state:'GUIDE_ACTIVE'},{...root,status:'COMPLETED',completed_at:at}]){
  assert.equal(detailPermissions(detail(actual),true).mode,false);
  assert.throws(()=>fixture('initialization_mode',actual),/Only title/);
 }
});

test('known conflict and actual re-read retain intention but cannot edit completed state; malformed receipt stays unknown',async()=>{
 const p=fixture();p.flow.begin();p.flow.change('保留此输入');p.api.prepareUpdateRequirement=()=>({submit:async()=>{throw new ApiRejected('STATE_CONFLICT','状态冲突',null,'native-id',409);}});
 assert(!await p.flow.save());assert.equal(p.flow.getSnapshot().phase,'EDITING');p.flow.adoptDetail(detail({...root,status:'COMPLETED',completed_at:at}));assert.equal(p.flow.getSnapshot().draft,'保留此输入');assert(!p.flow.allowed);p.flow.change('不能继续改');assert.equal(p.flow.getSnapshot().draft,'保留此输入');assert(!await p.flow.save());assert(p.flow.cancel());p.flow.dispose();
 const q=fixture();q.flow.begin();q.flow.change('新标题');q.f.response={...root,title:'错误回执'};assert(!await q.flow.save());assert.equal(q.flow.getSnapshot().phase,'UNKNOWN');assert.equal(q.flow.getSnapshot().receipt,null);q.api.getRequirement=async()=>{throw Error('read');};assert(!await q.flow.inspectUnknown());assert.equal(q.f.submits,1);q.flow.dispose();
});
test('preparation refusal is not an unknown mutation; raw input survives without a submit',async()=>{
 const p=fixture();p.flow.begin();p.flow.change('保留输入');p.api.prepareUpdateRequirement=()=>{throw TypeError('preparation');};assert(!await p.flow.save());assert.equal(p.flow.getSnapshot().phase,'EDITING');assert.equal(p.flow.getSnapshot().draft,'保留输入');assert.equal(p.f.submits,0);assert(p.flow.cancel());p.flow.dispose();
});
test('owned retirement skips queued writes, never aborts sent PATCH, and aborts only unknown inspection',async()=>{
 const p=fixture();p.flow.begin();p.flow.change('不会发送');const queued=p.flow.save();p.flow.dispose();assert(!await queued);assert.equal(p.f.prepares.length,0);
 const q=fixture(),held=deferred();let args;q.api.prepareUpdateRequirement=()=>({submit:async(...value)=>{args=value;return held.promise;}});q.flow.begin();q.flow.change('已发送');const sent=q.flow.save();await flush();q.flow.dispose();assert.deepEqual(args,[]);held.resolve({data:{...root,title:'已发送'}});assert(!await sent);assert.equal(q.flow.getSnapshot().receipt,null);
 const z=fixture();z.flow.begin();z.flow.change('未知');z.f.fail=true;await z.flow.save();const reading=deferred();let signal;z.api.getRequirement=async(_id,owned)=>{signal=owned;return reading.promise;};const inspect=z.flow.inspectUnknown();await flush();z.flow.dispose();assert(signal.aborted);reading.resolve({data:{...root,title:'未知'}});assert(!await inspect);assert.equal(z.f.submits,1);
});
