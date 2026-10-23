import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {RequirementGuideComposer} from '../src/guide/composer.ts';
import {ComposerDrafts} from '../src/guide/composer-drafts.ts';

const root={id:1,discussion_version:7,document_work_state:'IDLE',status:'CLOSED'};
const doc=id=>({id,content_version:3,current_revision_id:20+id,name:'文档'+id,archived_at:null});
const detail=(documents=[])=>({requirement:{...root},documents,current:null});
const receipt={processing:'MODEL',guide_run_id:41,user_message_id:9};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function fixture(actual=detail(),overrides={}){
 const counts={prepares:0,sends:0,reads:0,receives:0},bodies=[],values=new Map();
 const drafts=new ComposerDrafts(()=>({getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)}));
 const api={prepareCreateGuide(id,body){counts.prepares++;bodies.push(body);return {async submit(){counts.sends++;return {data:receipt};}};},
  async getGuideRun(){counts.reads++;return {data:{id:41,requirement_id:1,operation:bodies[0]?.operation??'DISCUSS',parent_guide_run_id:null}};},
  async listMessages(){return {data:{items:[]}};},...overrides};
 const owner=new RequirementGuideComposer(actual,api,async()=>actual,async()=>{},async()=>{counts.receives++;},async()=>{},drafts);
 owner.setAvailable(true);return {owner,counts,bodies,values,api};
}
test('zero-document discussion sends raw user input once and clears draft only after actual acceptance',async()=>{
 const {owner,counts,bodies,values}=fixture();owner.change('  原话😀\n第二行  ');assert.equal(owner.allowed,true);assert.equal(values.size,1);
 assert.equal(await owner.submit(),true);assert.equal(counts.sends,1);assert.equal(counts.receives,1);assert.equal(values.size,0);
 assert.deepEqual(bodies[0],{expected_discussion_version:7,operation:'DISCUSS',instruction:'  原话😀\n第二行  ',target:null,scope:null,source_refs:[],proposal_ref:null,acknowledge_source_changes:false});owner.dispose();
});
test('reading selection cannot silently change the configured write target or its captured version',async()=>{
 const actual=detail([doc(2),doc(3)]),{owner,bodies}=fixture(actual);owner.choose('REVISE');assert.equal(owner.allowed,false);
 owner.selectDocument(2);owner.change('修订目标 A');owner.adopt({...actual,current:doc(3)});assert.equal(await owner.submit(),true);
 assert.deepEqual(bodies[0].target,{kind:'EXISTING',document_id:2,expected_content_version:3});owner.dispose();
});
test('generation has a concrete new target and canonical SECTION scope uses heading_block_id',async()=>{
 const first=fixture();first.owner.choose('GENERATE');first.owner.configureNew('新方案','solution',true);first.owner.change('生成');assert.equal(await first.owner.submit(),true);
 assert.deepEqual(first.bodies[0].target,{kind:'NEW',name:'新方案',document_kind:'solution',template_ref:{key:'structure.solution',version:'v1'}});assert.equal(first.bodies[0].scope,null);first.owner.dispose();
 const actual={...detail([doc(2)]),current:doc(2)},second=fixture(actual);second.owner.choose('REVISE');assert.equal(second.owner.select({document_id:2,content_version:3,label:'章节',selection:null,scope:{scope_type:'SECTION',scope_ref:{block_id:8}}}),true);
 second.owner.change('改章节');assert.equal(await second.owner.submit(),true);assert.deepEqual(second.bodies[0].scope,{scope_type:'SECTION',scope_ref:{heading_block_id:8}});second.owner.dispose();
});
test('unknown acceptance retains the original prepared action across detail changes and panel hiding',async()=>{
 const {owner,counts,bodies,api,values}=fixture();api.prepareCreateGuide=(id,body)=>{counts.prepares++;bodies.push(body);return {async submit(){counts.sends++;if(counts.sends===1)throw new ApiUnknown(true);return {data:receipt};}};};
 owner.change('不可重写的输入');assert.equal(await owner.submit(),false);assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(values.size,1);
 owner.adopt({...detail(),requirement:{...root,discussion_version:8,document_work_state:'GUIDE_ACTIVE'}});owner.setAvailable(false);assert.equal(await owner.recover(),false);owner.setAvailable(true);
 assert.equal(await owner.recover(),true);assert.equal(counts.prepares,1);assert.equal(counts.sends,2);assert.equal(bodies[0].expected_discussion_version,7);owner.dispose();
});
test('accepted receipt followed by failed GET retries reads and never resubmits the instruction',async()=>{
 const {owner,counts,api}=fixture();api.getGuideRun=async()=>{if(++counts.reads===1)throw new ApiUnknown(false);return {data:{id:41,requirement_id:1,operation:'DISCUSS'}};};
 owner.change('继续讨论');assert.equal(await owner.submit(),false);assert.equal(owner.getSnapshot().phase,'CONFIRMED');assert.equal(await owner.finish(),true);assert.equal(counts.sends,1);assert.equal(counts.prepares,1);assert.equal(counts.reads,2);owner.dispose();
});
test('a late binding read cannot replace an explicit target selected while GET was in flight',async()=>{
 const pending=deferred(),{owner}=fixture(detail([doc(2),doc(3)]),{getRequirementDetail:()=>pending.promise});
 const read=owner.loadBinding();owner.selectDocument(3);pending.resolve({data:{requirement:root,discussion:{binding:{target_document_id:2,scope:null,source_refs:[]}}}});
 assert.equal(await read,false);assert.equal(owner.getSnapshot().target.document_id,3);owner.dispose();
});
test('the existing guide route transports a strict receipt and a frozen body/key on unknown replay',async()=>{
 const requests=[],key='00000000-0000-4000-8000-000000000001';let lost=true;
 const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});if(lost){lost=false;throw Error('lost response');}return new Response(JSON.stringify({success:true,data:receipt,error:null,meta:{request_id:key}}),{status:202,headers:{'Content-Type':'application/json'}});},()=>key),null);
 const body={expected_discussion_version:7,operation:'DISCUSS',instruction:' 原话 ',target:null,scope:null,source_refs:[],proposal_ref:null,acknowledge_source_changes:false},action=api.prepareCreateGuide(1,body);
 await assert.rejects(action.submit(),ApiUnknown);body.instruction='改变';assert.deepEqual((await action.submit()).data,receipt);
 assert.equal(requests[0].path,'/api/v1/requirements/1/guide-runs');assert.equal(requests[0].init.body,requests[1].init.body);assert.equal(JSON.parse(requests[0].init.body).instruction,' 原话 ');
});
