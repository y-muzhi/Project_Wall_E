import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiRejected,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {RequirementDiscussion} from '../src/requirements/discussion.ts';
import {discussionState} from '../src/api/models.ts';
const state=()=>({schema_version:2,focus_topic_ref:null,topics:[],evidence:[],pending_user_message_ids:[],binding:{target_document_id:null,source_refs:[],scope:null,document_kind:null},dispositions:[],last_step:null,counters:{topic:1,evidence:1}});
const detail=(version=1,discussion=null)=>({requirement:{id:1,discussion_version:version,document_work_state:'IDLE',status:'CLOSED'},discussion});
const command=()=>({type:'SET_BINDING',target_document_id:2,source_refs:[],scope:null});
const changed=()=>({...state(),binding:{...state().binding,target_document_id:2,document_kind:'design'}});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('progress loads only explicitly and an unknown program command keeps the original body/key',async()=>{
 let reads=0,prepared=0,sent=0;const bodies=[];
 const api={async getRequirementDetail(){reads++;return {data:detail(sent>1?2:1,sent>1?changed():state())};},prepareUpdateDiscussion(id,body){prepared++;bodies.push(body);return {async submit(){sent++;if(sent===1)throw new ApiUnknown(true);return {data:{requirement_id:1,discussion_version:2,discussion:discussionState(changed())}};}};}};
 const flow=new RequirementDiscussion(detail(),api,async()=>detail(2));assert.equal(reads,0);assert.equal(await flow.load(),true);
 const body=command();assert.equal(await flow.submit(body),false);body.target_document_id=3;assert.equal(flow.getSnapshot().phase,'UNKNOWN');
 assert.equal(await flow.submit(command()),false);assert.equal(await flow.retryUnknown(),true);assert.equal(prepared,1);assert.equal(sent,2);assert.equal(bodies[0].discussion_command.target_document_id,2);flow.dispose();
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

test('topic switching sends only the current document focus command and rereads on a conflict', async () => {
  const topic = (topic_ref, title) => ({
    topic_ref, title, mainline_ref: 'target', purpose: title,
    expected_outcomes: [{ outcome_ref: 'outcome', text: title, criterion: title }],
    assessment: 'DISCUSSING', evidence_refs: [], dependencies: [], unresolved_impacts: [],
    updated_by_message_id: 1,
  });
  const topics = [topic('t1', '使用者'), topic('t2', '主流程')];
  const current = ref => ({ ...state(), focus_topic_ref: ref, topics });
  let actual = detail(1, current('t1'));
  let failRefresh = false;
  const commands = [];
  const reader = new RequirementDiscussion(actual, {
    async getRequirementDetail() { return { data: actual }; },
    prepareUpdateDiscussion(id, body) {
      commands.push({ id, ...body });
      return { async submit() {
        if (commands.length === 1) {
          actual = detail(2, current('t1'));
          throw new ApiRejected('DISCUSSION_VERSION_CONFLICT', '版本变化', null, 'request-id', 409);
        }
        actual = detail(3, current('t2'));
        return { data: {requirement_id: 1, discussion_version: 3, discussion: actual.discussion} };
      }};
    },
  }, async () => {
    if (failRefresh) throw Error('detail GET failed');
    return actual;
  });

  try {
    assert(await reader.load());
    assert.equal(commands.length, 0);
    const change = {type: 'SET_FOCUS', topic_ref: 't2'};
    assert.equal(await reader.submit(change), false);
    assert.equal(reader.getSnapshot().discussion.focus_topic_ref, 't1');
    failRefresh = true;
    assert.equal(await reader.reread(), false);
    assert.equal(reader.getSnapshot().discussion.focus_topic_ref, 't1');
    failRefresh = false;
    assert(await reader.reread());
    assert.equal(reader.getSnapshot().version, 2);
    assert(await reader.submit(change));
    assert.equal(reader.getSnapshot().discussion.focus_topic_ref, 't2');
    assert.deepEqual(commands, [1, 2].map(expected_discussion_version => ({
      id: 1, expected_discussion_version, discussion_command: change,
    })));
  } finally {
    reader.dispose();
  }
});

test('the existing PATCH carries a strict discussion receipt and accepts reordered JSON keys',async()=>{
 const requests=[],key='00000000-0000-4000-8000-000000000001';
 const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});const discussion=state();discussion.binding.source_refs=[{message_id:1,kind:'MESSAGE'}];
  return new Response(JSON.stringify({success:true,data:{requirement_id:1,discussion_version:2,discussion},error:null,meta:{request_id:key}}),{status:200,headers:{'Content-Type':'application/json'}});},()=>key),null).forDocumentAssistant(2);
 const action=api.prepareUpdateDiscussion(1,{expected_discussion_version:1,discussion_command:{type:'SET_BINDING',target_document_id:null,source_refs:[{kind:'MESSAGE',message_id:1}],scope:null}});
 const result=await action.submit();assert.equal(result.data.discussion_version,2);assert.equal(requests[0].path,'/api/v1/requirements/1');assert.equal(requests[0].init.method,'PATCH');assert.equal(JSON.parse(requests[0].init.body).discussion_command.type,'SET_BINDING');
});
