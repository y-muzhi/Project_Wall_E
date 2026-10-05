import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementDetailRead} from '../src/requirements/detail-read.ts';
import {ApiRejected} from '../src/api/client.ts';
const at='2026-10-05T13:00:00.000Z';
const root=(changes={})=>({id:1,requirement_no:'REQ000001',title:'读取诊断',requirement_type:'NEW',initialization_mode:'DESIGN',template_key:'new-requirement',template_version:'v1',status:'ACTIVE',document_work_state:'IDLE',active_operation_type:null,active_operation_id:null,created_at:at,updated_at:at,completed_at:null,state_started_at:null,...changes});
const doc=(changes={})=>({id:2,requirement_id:1,document_type:'CURRENT',markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]},content_version:7,created_at:at,updated_at:at,...changes});
const index=(changes={})=>({requirement_id:1,document_id:2,content_version:7,total_count:0,open_count:0,blocks:[],comments:[],...changes});
const run=(changes={})=>({id:9,requirement_id:1,action_type:'ASK',function_type:'ANSWER_REQUIREMENT',source_type:'USER_INSTRUCTION',source_id:null,scope:{scope_type:'DOCUMENT',scope_ref:null},status:'RUNNING',current_step:'PREPARING',final_result:null,suggestion_batch_id:null,latest_assistant_message_id:null,error_code:null,error_message:null,cancel_reason:null,retry_of_guide_run_id:null,created_at:at,started_at:at,waiting_user_at:null,ended_at:null,updated_at:at,...changes});
const deferred=()=>{let resolve;const promise=new Promise(accept=>{resolve=accept;});return {promise,resolve};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function port(changes={}){const calls=[];let input={root:root(),current:doc(),index:index(),draft:doc({id:3,document_type:'MANUAL_DRAFT',content_version:2}),run:run(),batch:{id:10,requirement_id:1,status:'PENDING',base_content_version:7},...changes};
 const api=Object.fromEntries([['getRequirement','root'],['getCurrentDocument','current'],['getCommentIndex','index'],['getManualDraft','draft'],['getGuideRun','run'],['getBatch','batch']].map(([method,key])=>[method,async(id,signal)=>{calls.push({method,id,signal});if(input[key] instanceof Error)throw input[key];return {data:input[key]};}]));return {input,calls,api};}

test('complete detail bundle loads only actual referenced activity, independent draft version, required index and latest metadata; caller objects cannot mutate confirmed facts',async()=>{
  for(const [state,type,id,phase] of [['IDLE',null,null,'IDLE_VIEW'],['MANUAL_EDITING','MANUAL_DRAFT',3,'MANUAL_EDITING'],['GUIDE_ACTIVE','GUIDE_RUN',9,'GUIDE_RUNNING'],['SUGGESTION_REVIEWING','SUGGESTION_BATCH',10,'BATCH_REVIEW']]){
    const p=port({root:root({document_work_state:state,active_operation_type:type,active_operation_id:id,state_started_at:type?at:null})}),reader=new RequirementDetailRead(1,p.api);
    assert(await reader.refresh());assert.equal(reader.phase,phase);assert(reader.writeReady);assert.equal(p.calls.filter(c=>c.method==='getRequirement').length,2);assert(p.calls.some(c=>c.method==='getCommentIndex'));
    const actual=p.calls.filter(c=>['getManualDraft','getGuideRun','getBatch'].includes(c.method));assert.equal(actual.length,state==='IDLE'?0:1);if(actual.length)assert.equal(actual[0].id,state==='MANUAL_EDITING'?1:id);
    const before=reader.getSnapshot().confirmed;p.input.root.title='外部误改';p.input.current.markdown_content='外部误改';assert.equal(before.requirement.title,'读取诊断');assert.equal(before.current.markdown_content,'');assert(Object.isFrozen(before.current.block_state_json.blocks));
    if(state==='MANUAL_EDITING')assert.equal(before.activity.draft.content_version,2);reader.dispose();
  }
  const p=port({root:root({document_work_state:'GUIDE_ACTIVE',active_operation_type:'GUIDE_RUN',active_operation_id:9,state_started_at:at}),run:run({status:'WAITING_USER',current_step:'WAITING_USER',waiting_user_at:at})}),reader=new RequirementDetailRead(1,p.api);
  assert(await reader.refresh());assert.equal(reader.phase,'GUIDE_WAITING');reader.dispose();
});
test('wrong ownership, dangling activity, completed active run, wrong index document or attached block never create a writable partial bundle; version mismatch retains conflict',async()=>{
 const cases=[{current:doc({requirement_id:8})},{index:index({document_id:88})},{index:index({blocks:[{block_id:1,open_count:1,comment_ids:[1]}]})},
   {root:root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:4,state_started_at:at})},
   {root:root({document_work_state:'GUIDE_ACTIVE',active_operation_type:'GUIDE_RUN',active_operation_id:9,state_started_at:at}),run:run({requirement_id:8})},
   {root:root({document_work_state:'GUIDE_ACTIVE',active_operation_type:'GUIDE_RUN',active_operation_id:9,state_started_at:at}),run:run({status:'COMPLETED'})}];
 for(const input of cases){const reader=new RequirementDetailRead(1,port(input).api);assert(!await reader.refresh());assert.equal(reader.phase,'WORK_STATE_INCONSISTENT');assert.equal(reader.getSnapshot().confirmed,null);assert(!reader.writeReady);reader.dispose();}
 const reader=new RequirementDetailRead(1,port({index:index({content_version:8})}).api);assert(!await reader.refresh());assert.equal(reader.phase,'CONTENT_VERSION_CONFLICT');reader.dispose();
});
test('mandatory read failures preserve entire previous bundle but block new actions; root missing differs from dangling activity and re-read can recover',async()=>{
 const p=port(),reader=new RequirementDetailRead(1,p.api);assert(await reader.refresh());const confirmed=reader.getSnapshot().confirmed;
 p.input.index=Error('transport failed');assert(!await reader.refresh());assert.equal(reader.getSnapshot().confirmed,confirmed);assert(!reader.writeReady);assert.equal(reader.phase,'DETAIL_ERROR');
 p.input.index=index();assert(await reader.refresh());assert(reader.writeReady);
 p.input.root=new ApiRejected('NOT_FOUND','不存在',null,'request',404);assert(!await reader.refresh());assert.equal(reader.phase,'DETAIL_MISSING');assert.equal(reader.getSnapshot().confirmed.current.content_version,7);
 p.input.root=root();p.input.current=new ApiRejected('WORK_STATE_INCONSISTENT','错误',null,'request',409);assert(!await reader.refresh());assert.equal(reader.phase,'WORK_STATE_INCONSISTENT');reader.dispose();
});
test('whole-read coalescing, force supersession and pause ignore retired results without launching dependent reads; occupancy change before final root is a conflict',async()=>{
 const p=port(),first=deferred();let reads=0;p.api.getRequirement=async()=>{reads++;return reads===1?first.promise:{data:root()};};const reader=new RequirementDetailRead(1,p.api);
 const old=reader.refresh();assert.equal(reader.refresh(),old);await settle();const latest=reader.refresh(true);assert(await latest);first.resolve({data:root({title:'迟到'})});assert(!await old);assert.equal(reader.getSnapshot().confirmed.requirement.title,'读取诊断');assert.equal(p.calls.filter(c=>c.method==='getCurrentDocument').length,1);
 reader.pause();assert(!reader.writeReady);assert(await reader.refresh());reader.dispose();
 const q=port();let count=0;q.api.getRequirement=async()=>({data:count++===0?root():root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3,state_started_at:at})});const changing=new RequirementDetailRead(1,q.api);
 assert(!await changing.refresh());assert.equal(changing.phase,'CONTENT_VERSION_CONFLICT');changing.dispose();
 const held=deferred(),s=port();s.api.getRequirement=async()=>held.promise;const retired=new RequirementDetailRead(1,s.api);const pending=retired.refresh();await settle();retired.pause();held.resolve({data:root()});assert(!await pending);assert.equal(s.calls.length,0);retired.dispose();
});
