import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {ApiUnknown,ApiRejected,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {RequirementDiscussion} from '../src/requirements/discussion.ts';
import {discussionState} from '../src/api/models.ts';
const manifest=JSON.parse(readFileSync(new URL('../../backend/resources/v9/manifest.json',import.meta.url),'utf8'));
const guide=manifest.files.find(file=>file.resource_ref.key==='collaboration.discovery').resource_ref;
const state=()=>({schema_version:1,phase:{phase_ref:'p1',kind:'DISCOVERY',guide_ref:guide,closure:null},focus_topic_ref:null,topics:[],evidence:[],pending_user_message_ids:[],binding:{target_document_id:null,source_refs:[],scope:null,document_kind:null},dispositions:[],last_step:null,counters:{phase:2,topic:1,evidence:1}});
const detail=(version=1,discussion=null)=>({requirement:{id:1,discussion_version:version,document_work_state:'IDLE',status:'CLOSED'},discussion});
const command=()=>({type:'CHANGE_PHASE',phase_kind:'SOLUTION',closure_message:null,unresolved_refs:[]});
const changed=()=>({...state(),phase:{...state().phase,phase_ref:'p2',kind:'SOLUTION'},counters:{phase:3,topic:1,evidence:1}});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('progress loads only explicitly and an unknown program command keeps the original body/key',async()=>{
 let reads=0,prepared=0,sent=0;const bodies=[];
 const api={async getRequirementDetail(){reads++;return {data:detail(sent>1?2:1,sent>1?changed():state())};},prepareUpdateDiscussion(id,body){prepared++;bodies.push(body);return {async submit(){sent++;if(sent===1)throw new ApiUnknown(true);return {data:{requirement_id:1,discussion_version:2,discussion:discussionState(changed())}};}};}};
 const flow=new RequirementDiscussion(detail(),api,async()=>detail(2));assert.equal(reads,0);assert.equal(await flow.load(),true);
 const body=command();assert.equal(await flow.submit(body),false);body.phase_kind='REVIEW';assert.equal(flow.getSnapshot().phase,'UNKNOWN');
 assert.equal(await flow.submit(command()),false);assert.equal(await flow.retryUnknown(),true);assert.equal(prepared,1);assert.equal(sent,2);assert.equal(bodies[0].discussion_command.phase_kind,'SOLUTION');flow.dispose();
});
test('confirmed discussion change followed by failed refresh retries only reads',async()=>{
 let writes=0,refreshes=0;const flow=new RequirementDiscussion(detail(),{async getRequirementDetail(){return {data:detail(writes?2:1,writes?changed():state())};},prepareUpdateDiscussion(){return {async submit(){writes++;return {data:{requirement_id:1,discussion_version:2,discussion:discussionState(changed())}};}};}},async()=>{if(++refreshes===1)throw Error('GET failed');return detail(2);});
 await flow.load();assert.equal(await flow.submit(command()),false);assert.equal(flow.getSnapshot().phase,'CONFIRMED');assert.equal(await flow.finish(),true);assert.equal(writes,1);assert.equal(refreshes,2);flow.dispose();
});
test('closing the progress reader ignores old GET completion and does not cancel its program command',async()=>{
 const pending=deferred();const flow=new RequirementDiscussion(detail(),{getRequirementDetail:()=>pending.promise},async()=>detail());
 const read=flow.load();flow.pauseRead();pending.resolve({data:detail(1,state())});assert.equal(await read,false);assert.equal(flow.getSnapshot().discussion,null);flow.dispose();
});
test('new detail version or active occupancy requires fresh progress and never guesses a write target',async()=>{
 let writes=0;const flow=new RequirementDiscussion(detail(),{async getRequirementDetail(){return {data:detail(1,state())};},prepareUpdateDiscussion(){writes++;throw Error('Must not send');}},async()=>detail());
 await flow.load();flow.adopt(detail(2));assert.equal(await flow.submit(command()),false);assert.equal(writes,0);
 flow.adopt({...detail(),requirement:{...detail().requirement,document_work_state:'MANUAL_EDITING'}});assert.equal(await flow.submit(command()),false);flow.dispose();
});
test('the existing PATCH carries a strict discussion receipt and accepts reordered JSON keys',async()=>{
 const requests=[],key='00000000-0000-4000-8000-000000000001';
 const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});const discussion=state();discussion.binding.source_refs=[{message_id:1,kind:'MESSAGE'}];
  return new Response(JSON.stringify({success:true,data:{requirement_id:1,discussion_version:2,discussion},error:null,meta:{request_id:key}}),{status:200,headers:{'Content-Type':'application/json'}});},()=>key),null);
 const action=api.prepareUpdateDiscussion(1,{expected_discussion_version:1,discussion_command:{type:'SET_BINDING',target_document_id:null,source_refs:[{kind:'MESSAGE',message_id:1}],scope:null}});
 const result=await action.submit();assert.equal(result.data.discussion_version,2);assert.equal(requests[0].path,'/api/v1/requirements/1');assert.equal(requests[0].init.method,'PATCH');assert.equal(JSON.parse(requests[0].init.body).discussion_command.type,'SET_BINDING');
});
