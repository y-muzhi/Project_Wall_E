import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementDetailRead} from '../src/requirements/detail-read.ts';
import {ApiRejected} from '../src/api/client.ts';
const at='2026-10-05T13:00:00.000Z';
const root=(changes={})=>({id:1,requirement_no:'REQ000001',title:'读取诊断',requirement_type:'NEW',initialization_mode:'DESIGN',template_key:'new-requirement',template_version:'v1',status:'PLANNING',document_work_state:'IDLE',active_operation_type:null,active_operation_id:null,created_at:at,updated_at:at,completed_at:null,state_started_at:null,...changes});
const doc=(changes={})=>({id:2,requirement_id:1,document_type:'CURRENT',archived_at:null,markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]},content_version:7,created_at:at,updated_at:at,...changes});
const index=(changes={})=>({requirement_id:1,document_id:2,content_version:7,total_count:0,open_count:0,blocks:[],comments:[],...changes});
const run=(changes={})=>({id:9,requirement_id:1,action_type:'ASK',function_type:'ANSWER_REQUIREMENT',source_type:'USER_INSTRUCTION',source_id:null,scope:{scope_type:'DOCUMENT',scope_ref:null},status:'RUNNING',current_step:'PREPARING',final_result:null,suggestion_batch_id:null,latest_assistant_message_id:null,error_code:null,error_message:null,cancel_reason:null,retry_of_guide_run_id:null,created_at:at,started_at:at,waiting_user_at:null,ended_at:null,updated_at:at,...changes});
const deferred=()=>{let resolve;const promise=new Promise(accept=>{resolve=accept;});return {promise,resolve};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function port(changes={}){const calls=[];let input={root:root(),current:doc(),index:index(),draft:doc({id:3,document_type:'MANUAL_DRAFT',content_version:2,target_document_id:2,base_content_version:7}),run:run(),batch:{id:10,requirement_id:1,status:'PENDING',base_content_version:7},...changes};
 const bundle=(requirement=input.root)=>({requirement,documents:[{id:2,requirement_id:1,archived_at:null,content_version:7}],active_operation:requirement.active_operation_id===null?null:{type:requirement.active_operation_type,id:requirement.active_operation_id,summary:'活动',target_document_id:2}});
 const api=Object.fromEntries([['getRequirementDetail','root'],['getCurrentDocument','current'],['getCommentIndex','index'],['getManualDraft','draft'],['getGuideRun','run'],['getBatch','batch']].map(([method,key])=>[method,async(id,documentOrSignal,owned)=>{const signal=owned??documentOrSignal;calls.push({method,id,signal});if(input[key] instanceof Error)throw input[key];return {data:key==='root'?bundle():input[key]};}]));return {input,calls,api,bundle};}

test('complete detail bundle loads only actual referenced activity, independent draft version, required index and latest metadata; caller objects cannot mutate confirmed facts',async()=>{
  for(const [state,type,id,phase] of [['IDLE',null,null,'IDLE_VIEW'],['MANUAL_EDITING','MANUAL_DRAFT',3,'MANUAL_EDITING'],['GUIDE_ACTIVE','GUIDE_RUN',9,'GUIDE_RUNNING'],['SUGGESTION_REVIEWING','SUGGESTION_BATCH',10,'BATCH_REVIEW']]){
    const p=port({root:root({document_work_state:state,active_operation_type:type,active_operation_id:id,state_started_at:type?at:null})}),reader=new RequirementDetailRead(1,p.api);
    assert(await reader.refresh());assert.equal(reader.phase,phase);assert(reader.writeReady);assert.equal(p.calls.filter(c=>c.method==='getRequirementDetail').length,2);assert(p.calls.some(c=>c.method==='getCommentIndex'));
    const actual=p.calls.filter(c=>['getManualDraft','getGuideRun','getBatch'].includes(c.method));assert.equal(actual.length,state==='IDLE'?0:1);if(actual.length)assert.equal(actual[0].id,state==='MANUAL_EDITING'?1:id);
    const before=reader.getSnapshot().confirmed;p.input.root.title='外部误改';p.input.current.markdown_content='外部误改';assert.equal(before.requirement.title,'读取诊断');assert.equal(before.current.markdown_content,'');assert(Object.isFrozen(before.current.block_state_json.blocks));
    if(state==='MANUAL_EDITING')assert.equal(before.activity.draft.content_version,2);reader.dispose();
  }

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
 const p=port(),first=deferred();let reads=0;p.api.getRequirementDetail=async()=>{reads++;return reads===1?first.promise:{data:p.bundle(root())};};const reader=new RequirementDetailRead(1,p.api);
 const old=reader.refresh();assert.equal(reader.refresh(),old);await settle();const latest=reader.refresh(true);assert(await latest);first.resolve({data:p.bundle(root({title:'迟到'}))});assert(!await old);assert.equal(reader.getSnapshot().confirmed.requirement.title,'读取诊断');assert.equal(p.calls.filter(c=>c.method==='getCurrentDocument').length,1);
 reader.pause();assert(!reader.writeReady);assert(await reader.refresh());reader.dispose();
 const q=port();let count=0;q.api.getRequirementDetail=async()=>({data:q.bundle(count++===0?root():root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3,state_started_at:at}))});const changing=new RequirementDetailRead(1,q.api);
 assert(!await changing.refresh());assert.equal(changing.phase,'CONTENT_VERSION_CONFLICT');changing.dispose();
 const held=deferred(),s=port();s.api.getRequirementDetail=async()=>held.promise;const retired=new RequirementDetailRead(1,s.api);const pending=retired.refresh();await settle();retired.pause();held.resolve({data:s.bundle(root())});assert(!await pending);assert.equal(s.calls.length,0);retired.dispose();
});


test('observation reuses only matching last-known content while explicit reads still refresh the comment index',async()=>{
 const p=port(),reader=new RequirementDetailRead(1,p.api);assert(await reader.refresh());p.calls.length=0;
 p.input.root=root({discussion_version:2});assert(await reader.observe());
 assert.deepEqual(p.calls.map(row=>row.method),['getRequirementDetail','getRequirementDetail']);
 const before=reader.getSnapshot().confirmed.current;p.calls.length=0;p.input.index=index({total_count:1});
 assert(await reader.refresh());assert(p.calls.some(row=>row.method==='getCommentIndex'));assert.equal(reader.getSnapshot().confirmed.comment_index.total_count,1);
 p.calls.length=0;p.input.current=doc({content_version:8});p.input.index=index({content_version:8});
 p.api.getRequirementDetail=async()=>{p.calls.push({method:'getRequirementDetail'});return {data:{...p.bundle(),documents:[{id:2,requirement_id:1,archived_at:null,content_version:8}]}};};
 assert(await reader.observe());assert.equal(reader.getSnapshot().confirmed.current.content_version,8);assert.notEqual(reader.getSnapshot().confirmed.current,before);assert(p.calls.some(row=>row.method==='getCurrentDocument'));reader.dispose();
});
test('an explicit read supersedes advisory work and a write epoch cannot join a read started before the command',async()=>{
 const p=port(),reader=new RequirementDetailRead(1,p.api);p.api.detailReadEpoch=0;assert(await reader.refresh());
 const held=deferred(),read=p.api.getRequirementDetail;let first=true;
 p.api.getRequirementDetail=async(...args)=>{if(first){first=false;return held.promise;}return read(...args);};
 const old=reader.observe();await settle();p.api.detailReadEpoch++;
 const after=reader.refresh();assert(await after);held.resolve({data:p.bundle()});assert(!await old);assert(reader.writeReady);
 first=true;const waiting=deferred();p.api.getRequirementDetail=async(...args)=>{if(first){first=false;return waiting.promise;}return read(...args);};
 const advisory=reader.observe();await settle();assert(await reader.refresh());waiting.resolve({data:p.bundle()});assert(!await advisory);reader.dispose();
});
test('a changed summary at the end of an advisory read cannot publish mismatched metadata with reused content',async()=>{
 const p=port(),reader=new RequirementDetailRead(1,p.api);assert(await reader.refresh());const previous=reader.getSnapshot().confirmed;
 let count=0;p.api.getRequirementDetail=async()=>({data:{...p.bundle(),documents:[{id:2,requirement_id:1,archived_at:null,content_version:7,...(++count===2?{metadata_version:2}:{})}]}});
 assert(!await reader.observe());assert.equal(reader.getSnapshot().confirmed,previous);assert.equal(reader.phase,'CONTENT_VERSION_CONFLICT');reader.dispose();
});

test('updating another document cannot cause a read of A, but mutable metadata and manual occupancy require a full read',async()=>{
 const p=port(),read=p.api.getRequirementDetail;let otherVersion=1;
 p.api.getRequirementDetail=async(...args)=>{const response=await read(...args);return {data:{...response.data,documents:[...response.data.documents,{id:9,requirement_id:1,content_version:otherVersion,archived_at:null}]}};};
 const reader=new RequirementDetailRead(1,p.api);assert(await reader.refresh());p.calls.length=0;otherVersion=2;
 assert(await reader.observe());assert(!p.calls.some(row=>row.method==='getCurrentDocument'));assert.equal(reader.getSnapshot().confirmed.current.id,2);
 p.input.root=root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3,state_started_at:at});p.calls.length=0;
 assert(await reader.observe());assert(p.calls.some(row=>row.method==='getCurrentDocument'));assert(p.calls.some(row=>row.method==='getManualDraft'));reader.dispose();
});
