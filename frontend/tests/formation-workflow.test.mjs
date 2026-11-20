import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiRejected, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import { formationSelection, acceptedSelection, proposalView } from '../src/api/formation-workflow.ts';

const key='00000000-0000-4000-8000-000000000001';
const target={discussion_step_ref:'s1',discussion_branch_ref:'b1',branch_intent:'RESUME',branch_resume_basis:{expected_branch_status:'RESOLVED',expected_branch_event_id:23}};
const accepted={...target,branch_intent:'ENTER',branch_resume_basis:null};
const input=()=>({expected_discussion_version:7,operation:'DISCUSS',instruction:'  保留原始用户输入  ',target:structuredClone(target),scope:null,source_refs:[],proposal_ref:null,proposal_intent:null,acknowledge_source_changes:false});
const receipt={processing:'MODEL',guide_run_id:9,user_message_id:20,accepted_target:accepted};
const envelope=(data,status=202)=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:key}}),{status,headers:{'Content-Type':'application/json'}});
const api=send=>new WalleApi(new ApiClient(send,()=>key),null).forDocumentAssistant(2);

test('formation acceptance freezes original resume proof, text and key across transport uncertainty',async()=>{
 const requests=[];let lost=true;
 const body=input(),service=api(async(path,init)=>{
  requests.push({path,body:init.body,key:new Headers(init.headers).get('Idempotency-Key')});
  if(lost){lost=false;throw Error('lost reply');}return envelope(receipt);
 });
 const action=service.prepareFormationDiscuss(1,body);
 await assert.rejects(action.submit(),ApiUnknown);
 body.target.branch_resume_basis.expected_branch_event_id=99;body.target.discussion_step_ref='s2';body.instruction='不得替代原请求';
 assert.deepEqual((await action.submit()).data,receipt);
 assert.deepEqual(requests[0],requests[1]);
 assert.equal(requests[0].path,'/api/v1/requirements/1/guide-runs');
 assert.equal(requests[0].key,key);
 assert.deepEqual(JSON.parse(requests[0].body),{...input(),document_id:2});
});

test('acceptance reply must confirm exactly the normalized target and consumed resume basis',async()=>{
 for(const different of [
  {...accepted,discussion_step_ref:'s2'},
  {...accepted,discussion_branch_ref:'b2'},
  target,
  {...accepted,branch_resume_basis:target.branch_resume_basis},
  {...accepted,private_binding:{}},
 ]){
  await assert.rejects(api(async()=>envelope({...receipt,accepted_target:different})).prepareFormationDiscuss(1,input()).submit(),ApiUnknown);
 }
 assert.throws(()=>acceptedSelection(target));
 assert.deepEqual(acceptedSelection(accepted),accepted);
});

test('incomplete target, wrong temporary identity and private replacement fields never reach transport',()=>{
 let sends=0;const service=api(async()=>{sends++;return envelope(receipt);});
 const mutations=[
  body=>{delete body.target.branch_resume_basis;},
  body=>{body.target.discussion_step_ref=null;},
  body=>{body.target.discussion_step_ref='new_step_1';},
  body=>{body.target.branch_intent='ENTER';},
  body=>{body.target.branch_resume_basis.expected_branch_status='OPEN';},
  body=>{body.target.private_binding={};},
  body=>{body.operation='REVISE';},
  body=>{body.proposal_intent='ADJUST_WRITE';},
  body=>{body.action_payload={markdown_content:'replace'};},
 ];
 for(const change of mutations){const body=input();change(body);assert.throws(()=>service.prepareFormationDiscuss(1,body));}
 assert.equal(sends,0);
});

test('verified formation conflicts are rejected while damaged replies stay unknown',async()=>{
 const conflict={reason:'BRANCH_STATE_CHANGED',step_ref:'s1',proposal:null};
 const failure=(details,status=409)=>new Response(JSON.stringify({success:false,data:null,error:{code:'STATE_CONFLICT',message:'支线状态已变化',details},meta:{request_id:key}}),{status,headers:{'Content-Type':'application/json'}});
 await assert.rejects(api(async()=>failure(conflict)).prepareFormationDiscuss(1,input()).submit(),error=>error instanceof ApiRejected&&error.code==='STATE_CONFLICT'&&error.details.reason==='BRANCH_STATE_CHANGED');
 await assert.rejects(api(async()=>failure({...conflict,publication_binding:{}})).prepareFormationDiscuss(1,input()).submit(),ApiUnknown);
 await assert.rejects(api(async()=>failure(conflict,500)).prepareFormationDiscuss(1,input()).submit(),ApiUnknown);
});

test('whole-document discussion has no implicit branch entry or resume authority',async()=>{
 const body=input();body.target={discussion_step_ref:null,discussion_branch_ref:null,branch_intent:null,branch_resume_basis:null};
 const result={...receipt,accepted_target:body.target};
 assert.deepEqual((await api(async()=>envelope(result)).prepareFormationDiscuss(1,body).submit()).data.accepted_target,body.target);
 assert.throws(()=>formationSelection({...body.target,branch_intent:'ENTER'}));
});

const proposal=()=>({
 message_id:20,card_key:'c1',purpose:'STAGED_WRITE',
 payload:{step_ref:'s1',result_refs:['s1.o1'],write_mode:'FILL_EMPTY',document_revision_id:1,content_version:1,goal_version:1,definition_version:1,scope:{scope_type:'DOCUMENT',scope_ref:null},markdown_content:'原文\n',patches:[],change_summary:'精确保存',source_refs:[]},
 disposition:'PENDING',needs_revision:false,can_apply:true,reasons:[],
 availability:[{action:'apply',available:true,reason:null},{action:'preview',available:true,reason:null}],
 expiry_reason:null,source_run_id:9,
});
test('proposal read rejects drifting availability, private bindings and a payload from the other purpose',()=>{
 assert.equal(proposalView(proposal()).can_apply,true);
 for(const mutate of [
  value=>{value.availability[0].available=false;value.availability[0].reason='DEFERRED';},
  value=>{value.disposition='APPLIED';},
  value=>{value.needs_revision=true;},
  value=>{value.reasons=['CONTENT_CHANGED'];},
  value=>{value.binding={};},
  value=>{value.payload.private_digest='fake';},
  value=>{value.purpose='FORMATION_PATH_CHANGE';},
 ]){
  const value=proposal();mutate(value);assert.throws(()=>proposalView(value));
 }
});

import { InteractionCards } from '../src/guide/cards.ts';
import { CardDrafts } from '../src/guide/card-drafts.ts';
import { cards, message } from '../src/api/models.ts';

test('temporary document occupancy preserves a new proposal selection and its local record',async()=>{
 const at='2026-11-16T09:00:00.000Z',definition=cards({
  schema_version:1,intro:'',purpose:'STAGED_WRITE',action_payload:proposal().payload,
  program_binding:{discussion_version:3,target_content_version:1,source_heads:[]},
  cards:[{card_key:'c1',card_type:'SINGLE_SELECT',question:'采用原文？',context:'',required:true,
   options:[{option_key:'apply',label:'采用',description:'',impact:'',risks:''}],selection_rule:{min:1,max:1},
   custom_answer:{enabled:false,max_length:0},recommendation:null,related_spec_context:[]}],
 });
 const original=message({id:20,requirement_id:1,document_id:2,guide_run_id:10,sequence_no:2,role:'ASSISTANT',content:'原提案',message_type:'INTERACTION_CARDS',structured_content:definition,reply_to_message_id:null,created_at:at,card_state:'AVAILABLE',phase_ref:null,topic_refs:[],document_ids:[],program_receipt:null});
 const source={id:10,requirement_id:1,status:'COMPLETED',operation:'DISCUSS'};
 const idle={requirement:{id:1,discussion_version:7,document_work_state:'IDLE',active_operation_id:null,active_operation_type:null},current:null,documents:[],activity:{kind:'IDLE'}};
 const busy={...idle,requirement:{...idle.requirement,discussion_version:8,document_work_state:'GUIDE_ACTIVE',active_operation_id:11,active_operation_type:'GUIDE_RUN'},activity:{kind:'GUIDE',run:{id:11}}};
 const memory=new Map(),storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
 let prepares=0;
 const transport={prepareCardResponses(){prepares++;throw Error('Occupied document must not prepare');}};
 const drafts=new CardDrafts(()=>storage,()=>at,2);
 const make=detail=>new InteractionCards(original,source,detail,transport,drafts,async()=>idle,async()=>{},async()=>{},async()=>{},async()=>idle);
 const owner=make(idle);owner.setAvailable(true);owner.toggle('c1','apply',true);
 const chosen=owner.getSnapshot().answers;assert.equal(memory.size,1);
 owner.adopt(original,source,busy);
 assert.equal(owner.allowed,false);assert.equal(await owner.submit(),false);assert.equal(prepares,0);
 assert.deepEqual(owner.getSnapshot().answers,chosen);assert.equal(memory.size,1);
 owner.dispose();
 const reopened=make(busy);reopened.setAvailable(true);
 assert.deepEqual(reopened.getSnapshot().answers,chosen);assert.equal(reopened.allowed,false);
 reopened.adopt(original,source,{...idle,requirement:{...idle.requirement,discussion_version:9}});
 assert.equal(reopened.allowed,true);assert.deepEqual(reopened.getSnapshot().answers,chosen);
 reopened.dispose();
});
