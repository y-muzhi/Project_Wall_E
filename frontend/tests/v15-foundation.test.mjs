import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiClient,ApiUnknown,ApiRejected} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {requirement,requirementSummary} from '../src/api/models.ts';
import {RequirementLifecycle} from '../src/requirements/lifecycle.ts';
import {RequirementPropertyEdit} from '../src/requirements/property-edit.ts';
import {detailPermissions} from '../src/requirements/permissions.ts';

const at='2026-10-22T00:00:00.000Z',key='00000000-0000-4000-8000-000000000001';
const root=(changes={})=>({id:1,requirement_no:'REQ000001',title:'需求',requirement_type:'NEW',status:'PLANNING',metadata_version:1,
 initial_message_id:1,discussion_version:1,document_work_state:'IDLE',active_operation_type:null,active_operation_id:null,
 created_at:at,updated_at:at,completed_at:null,closed_at:null,state_started_at:null,...changes});
const detail=(changes={})=>({requirement:root(changes),current:{id:5,requirement_id:1,document_type:'CURRENT',archived_at:null},documents:[],activity:{kind:'IDLE'}});
const envelope=data=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:key}}),{status:201,headers:{'Content-Type':'application/json'}});

test('creation uses the real three-field wire and strict zero-operation response',async()=>{
 const wires=[];
 const api=new WalleApi(new ApiClient(async(path,options)=>{wires.push({path,options});return envelope({requirement:root(),initial_message_id:1,documents:[]});},()=>key),{});
 const action=api.prepareCreateRequirement({title:'需求',requirement_type:'NEW',initial_idea:'原始想法'});
 const one=await action.submit();await action.submit();
 assert.equal(one.data.documents.length,0);assert.equal(one.data.requirement.status,'PLANNING');
 assert.equal(wires.length,2);assert.deepEqual(wires[0],wires[1]);
 assert.deepEqual(JSON.parse(wires[0].options.body),{title:'需求',requirement_type:'NEW',initial_idea:'原始想法'});
 assert.equal(new Headers(wires[0].options.headers).get('Idempotency-Key'),key);
});

test('new root rejects obsolete fields and permits all five statuses independently of occupancy',()=>{
 for(const status of ['PLANNING','READY','IMPLEMENTING','COMPLETED','CLOSED']){
  const value=root({status,completed_at:status==='COMPLETED'?at:null,closed_at:status==='CLOSED'?at:null,
   document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:8,state_started_at:at});
  assert.equal(requirement(value).status,status);
  assert.equal(detailPermissions({...detail(),requirement:value},true).title,true);
  assert.equal(detailPermissions({...detail(),requirement:root({status,completed_at:value.completed_at,closed_at:value.closed_at})},true).manual_start,true);
  assert.equal(requirementSummary({id:1,requirement_no:'REQ000001',title:'需求',requirement_type:'NEW',status,updated_at:at}).status,status);
 }
 assert.throws(()=>requirement({...root(),template_key:'旧模板'}));
 assert.throws(()=>requirement(root({status:'ACTIVE'})));
 assert.throws(()=>requirement(root({status:'CLOSED',closed_at:null})));
});

test('manual status switch keeps the exact original action across an unknown outcome',async()=>{
 let prepares=0,submits=0;const bodies=[];
 const value=detail({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:8,state_started_at:at});
 const flow=new RequirementLifecycle('PLANNING',value,{prepareUpdateRequirement(identity,body){prepares++;bodies.push(body);return {async submit(){submits++;if(submits===1)throw new ApiUnknown(true);return {data:root({...value.requirement,status:'CLOSED',closed_at:at,metadata_version:2})};}};}});
 assert.equal(await flow.select('PLANNING'),false);assert.equal(prepares,0);
 assert.equal(await flow.select('CLOSED'),false);assert.equal(flow.getSnapshot().phase,'UNKNOWN');
 assert.equal(await flow.select('READY'),false);
 assert.equal(await flow.retryUnknown(),true);assert.equal(prepares,1);assert.equal(submits,2);
 assert.deepEqual(bodies,[{expected_metadata_version:1,changes:{status:'CLOSED'}}]);
 assert.equal(flow.getSnapshot().actual.active_operation_id,8);flow.dispose();
});

test('version conflict is a definite rejection and preserves the intended status',async()=>{
 const flow=new RequirementLifecycle('PLANNING',detail(),{prepareUpdateRequirement(){return {async submit(){throw new ApiRejected('METADATA_VERSION_CONFLICT','属性已更新',null,key,409);}};}});
 assert.equal(await flow.select('IMPLEMENTING'),false);assert.equal(flow.getSnapshot().phase,'ERROR');assert.equal(flow.operation,'IMPLEMENTING');flow.dispose();
});

test('title unknown result replays the same original keyed PATCH and confirms its actual receipt',async()=>{
 let prepared=0,sent=0;const bodies=[];
 const flow=new RequirementPropertyEdit('title',detail(),{prepareUpdateRequirement(_id,body){prepared++;bodies.push(body);return {async submit(){sent++;if(sent===1)throw new ApiUnknown(true);return {data:root({title:'新标题',metadata_version:2})};}};}});
 assert.equal(flow.begin(),true);flow.change(' 新标题 ');assert.equal(await flow.save(),false);
 assert.equal(await flow.inspectUnknown(),true);assert.equal(prepared,1);assert.equal(sent,2);
 assert.deepEqual(bodies,[{expected_metadata_version:1,changes:{title:'新标题'}}]);
 assert.equal(flow.getSnapshot().receipt.title,'新标题');flow.dispose();
});
