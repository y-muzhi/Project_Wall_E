import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementLifecycle} from '../src/requirements/lifecycle.ts';
import {detailPermissions} from '../src/requirements/permissions.ts';
import {ApiRejected,ApiUnknown} from '../src/api/client.ts';
const statuses=['PLANNING','READY','IMPLEMENTING','COMPLETED','CLOSED'];
const detail=(status='PLANNING')=>({requirement:{id:1,status,metadata_version:4,document_work_state:'IDLE'},current:{id:2,requirement_id:1,document_type:'CURRENT',archived_at:null}});

test('all five manual statuses retain title and idle document permissions; viewport/history and occupancy remain independent',()=>{
 for(const status of statuses){const value=detail(status);assert(detailPermissions(value,true).title);assert(detailPermissions(value,true).manual_start);
  const busy={...value,requirement:{...value.requirement,document_work_state:'GUIDE_ACTIVE'}};assert(detailPermissions(busy,true).title);assert(!detailPermissions(busy,true).manual_start);
  for(const args of [[false,false,false],[true,true,false],[true,false,true]])assert(Object.values(detailPermissions(value,...args)).every(value=>value===false));
 }
 assert(Object.values(detailPermissions(null,true)).every(value=>value===false));
});
test('each manual transition freezes metadata and an unknown command replays only the same prepared action',async()=>{
 for(const from of statuses)for(const to of statuses){let prepares=0,sends=0,body;
  const api={prepareUpdateRequirement(id,input){prepares++;body=input;assert.equal(id,1);return {async submit(){if(++sends===1)throw new ApiUnknown(true);return {data:{...detail(to).requirement,metadata_version:5}};}};}};
  const flow=new RequirementLifecycle(from,detail(from),api);if(from===to){assert(!await flow.select(to));assert.equal(prepares,0);}else{
   assert(!await flow.select(to));assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert(!await flow.select(from));assert(await flow.retryUnknown());assert.equal(prepares,1);assert.equal(sends,2);
   assert.deepEqual(body,{expected_metadata_version:4,changes:{status:to}});assert.equal(flow.getSnapshot().outcome.requirement.status,to);
  }flow.dispose();
 }
});
test('definite rejection stays ERROR and malformed receipt cannot confirm; REQUEST_IN_PROGRESS retains original action',async()=>{
 for(const code of ['METADATA_VERSION_CONFLICT','REQUEST_IN_PROGRESS']){let sends=0;
  const flow=new RequirementLifecycle('READY',detail(),{prepareUpdateRequirement(){return {async submit(){if(++sends===1)throw new ApiRejected(code,'冲突',null,'r',409);return {data:detail('READY').requirement};}};}});
  assert(!await flow.submit());assert.equal(flow.getSnapshot().phase,code==='REQUEST_IN_PROGRESS'?'UNKNOWN':'ERROR');if(code==='REQUEST_IN_PROGRESS')assert(await flow.retryUnknown());flow.dispose();
 }
 const flow=new RequirementLifecycle('READY',detail(),{prepareUpdateRequirement:()=>({submit:async()=>({data:detail('CLOSED').requirement})})});assert(!await flow.submit());assert.equal(flow.getSnapshot().phase,'UNKNOWN');flow.dispose();
});
test('retirement before the send microtask prevents IO; an already sent status command is never aborted or adopted after disposal',async()=>{
 let sends=0,resolve;const api={prepareUpdateRequirement:()=>({submit:()=>{sends++;return new Promise(yes=>resolve=yes);}})};
 const queued=new RequirementLifecycle('READY',detail(),api),first=queued.submit();queued.dispose();assert(!await first);assert.equal(sends,0);
 const sent=new RequirementLifecycle('READY',detail(),api),pending=sent.submit();await Promise.resolve();assert.equal(sends,1);sent.dispose();resolve({data:detail('READY').requirement});assert(!await pending);assert.equal(sent.getSnapshot().outcome,null);
});
