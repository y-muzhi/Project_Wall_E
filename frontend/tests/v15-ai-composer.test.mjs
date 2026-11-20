import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {RequirementGuideComposer} from '../src/guide/composer.ts';
import {ComposerDrafts} from '../src/guide/composer-drafts.ts';
import {nextChapter} from '../src/guide/scope.ts';

const root={id:1,discussion_version:7,document_work_state:'IDLE',status:'CLOSED'};
const doc=id=>({id,content_version:3,current_revision_id:20+id,name:'文档'+id,archived_at:null});
const detail=(documents=[doc(2)])=>({selected_document_id:2,requirement:{...root},documents,current:documents.find(row=>row.id===2)??doc(2)});
const receipt={processing:'MODEL',guide_run_id:41,user_message_id:9};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('H06 next chapter skips children and stops before a parent boundary',()=>{
 const chapters=[{block_id:1,level:1},{block_id:2,level:2},{block_id:3,level:3},{block_id:4,level:2},{block_id:5,level:1}];
 assert.equal(nextChapter(chapters,1).block_id,5);assert.equal(nextChapter(chapters,2).block_id,4);
 assert.equal(nextChapter(chapters,3),null);assert.equal(nextChapter(chapters,4),null);assert.equal(nextChapter(chapters,5),null);assert.equal(nextChapter(chapters,99),null);
});
test('H06 selecting a chapter requires explicit send and binds the current version',async()=>{
 const actual={...detail([doc(2)]),current:doc(2)},rig=fixture(actual),target={document_id:2,content_version:3,label:'章节甲',selection:null,scope:{scope_type:'SECTION',scope_ref:{block_id:8}}};
 rig.owner.change('补全本章，保留已确认内容');assert(rig.owner.selectChapter(target));assert.equal(rig.counts.sends,0);assert.equal(rig.owner.getSnapshot().action,'REVISE');
 assert(await rig.owner.submit());assert.equal(rig.counts.sends,1);assert.equal(rig.bodies[0].target.expected_content_version,3);assert.deepEqual(rig.bodies[0].scope,{scope_type:'SECTION',scope_ref:{heading_block_id:8}});
 rig.owner.adopt({...actual,documents:[{...doc(2),content_version:4}],current:{...doc(2),content_version:4}});
 assert.equal(rig.owner.allowed,false);assert.equal(rig.owner.selectChapter(target),false);
 assert(rig.owner.selectChapter({...target,content_version:4,scope:{scope_type:'SECTION',scope_ref:{block_id:9}}}));assert.equal(rig.counts.sends,1);rig.owner.dispose();
});
test('H06 chapter configuration remains frozen while a send result is unknown',async()=>{
 const actual={...detail([doc(2)]),current:doc(2)},rig=fixture(actual,{prepareCreateGuide:()=>({submit:async()=>{throw new ApiUnknown(true);}})});
 const target={document_id:2,content_version:3,label:'章节甲',selection:null,scope:{scope_type:'SECTION',scope_ref:{block_id:8}}};
 assert(rig.owner.selectChapter(target));rig.owner.change('完成本章');assert.equal(await rig.owner.submit(),false);
 assert.equal(rig.owner.selectChapter({...target,scope:{scope_type:'SECTION',scope_ref:{block_id:9}}}),false);assert.equal(rig.owner.getSnapshot().target.scope.scope_ref.block_id,8);rig.owner.dispose();
});
function fixture(actual=detail(),overrides={}){
 const counts={prepares:0,sends:0,reads:0,receives:0},bodies=[],values=new Map();
 const drafts=new ComposerDrafts(()=>({getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)}),2);
 const api={prepareCreateGuide(id,body){counts.prepares++;bodies.push(body);return {async submit(){counts.sends++;return {data:receipt};}};},
  async getGuideRun(){counts.reads++;return {data:{id:41,requirement_id:1,operation:bodies[0]?.operation??'DISCUSS',parent_guide_run_id:null}};},
  async listMessages(){return {data:{items:[]}};},async getRequirementDetail(){return {data:{...actual,discussion:{binding:{target_document_id:actual.selected_document_id,scope:null,source_refs:[]}}}};},...overrides};
 const owner=new RequirementGuideComposer(actual,api,async()=>actual,async()=>{},async()=>{counts.receives++;},async()=>{},drafts);
 owner.setAvailable(true);return {owner,counts,bodies,values,api};
}
test('document discussion sends raw user input once and clears only its accepted draft',async()=>{
 const {owner,counts,bodies,values}=fixture();owner.change('  原话😀\n第二行  ');assert.equal(owner.allowed,true);assert.equal(values.size,1);
 assert.equal(await owner.submit(),true);assert.equal(counts.sends,1);assert.equal(counts.receives,1);assert.equal(values.size,0);
 assert.deepEqual(bodies[0],{expected_discussion_version:7,operation:'DISCUSS',instruction:'  原话😀\n第二行  ',target:{kind:'EXISTING',document_id:2,expected_content_version:3},scope:{scope_type:'DOCUMENT',scope_ref:null},source_refs:[],proposal_ref:null,acknowledge_source_changes:false});owner.dispose();
});
test('reading selection cannot silently change the configured write target or its captured version',async()=>{
 const actual=detail([doc(2),doc(3)]),{owner,bodies}=fixture(actual);owner.choose('REVISE');assert.equal(owner.allowed,false);
 owner.selectDocument(2);owner.change('修订目标 A');owner.adopt({...actual,current:doc(3)});assert.equal(await owner.submit(),true);
 assert.deepEqual(bodies[0].target,{kind:'EXISTING',document_id:2,expected_content_version:3});owner.dispose();
});

test('a mode switch preserves the draft and each send uses its explicitly selected scope', async () => {
  const { owner, bodies, counts } = fixture();
  const chapter = {
    document_id: 2, content_version: 3, label: '第 1 章', selection: null,
    scope: { scope_type: 'SECTION', scope_ref: { block_id: 8 } },
  };
  owner.change('请比较这些方案');
  owner.choose('REVISE');
  assert.equal(owner.getSnapshot().instruction, '请比较这些方案');
  assert.equal(owner.allowed, false);
  assert(owner.selectChapter(chapter));
  owner.choose('DISCUSS');
  assert.equal(counts.prepares, 0);
  assert(await owner.submit());
  assert.equal(bodies[0].operation, 'DISCUSS');
  assert.deepEqual(bodies[0].scope, { scope_type: 'DOCUMENT', scope_ref: null });
  owner.dispose();

  const write = fixture();
  write.owner.choose('REVISE');
  write.owner.change('为当前文档写一份初稿');
  assert.equal(await write.owner.submit(), false);
  assert.equal(write.counts.prepares, 0);
  write.owner.selectDocument(2);
  assert(await write.owner.submit());
  assert.equal(write.bodies[0].operation, 'REVISE');
  assert.deepEqual(write.bodies[0].scope, { scope_type: 'DOCUMENT', scope_ref: null });
  write.owner.dispose();
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
test('a binding read synchronizes sources without replacing an explicit target',async()=>{
 const pending=deferred(),{owner}=fixture(detail([doc(2),doc(3)]),{getRequirementDetail:()=>pending.promise});
 const read=owner.loadBinding();owner.selectDocument(2);pending.resolve({data:{requirement:root,discussion:{binding:{target_document_id:3,scope:null,source_refs:[]}}}});
 assert.equal(await read,true);assert.equal(owner.getSnapshot().target.document_id,2);owner.dispose();
});
test('the existing guide route transports a strict receipt and a frozen body/key on unknown replay',async()=>{
 const requests=[],key='00000000-0000-4000-8000-000000000001';let lost=true;
 const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});if(lost){lost=false;throw Error('lost response');}return new Response(JSON.stringify({success:true,data:receipt,error:null,meta:{request_id:key}}),{status:202,headers:{'Content-Type':'application/json'}});},()=>key),null).forDocumentAssistant(2);
 const body={expected_discussion_version:7,operation:'DISCUSS',instruction:' 原话 ',target:null,scope:null,source_refs:[],proposal_ref:null,acknowledge_source_changes:false},action=api.prepareCreateGuide(1,body);
 await assert.rejects(action.submit(),ApiUnknown);body.instruction='改变';assert.deepEqual((await action.submit()).data,receipt);
 assert.equal(requests[0].path,'/api/v1/requirements/1/guide-runs');assert.equal(requests[0].init.body,requests[1].init.body);assert.equal(JSON.parse(requests[0].init.body).instruction,' 原话 ');
});


test('switching during preflight and an unknown result preserves the original chapter write', async () => {
  const pending = deferred();
  const actual = detail();
  const { owner, api, counts, bodies } = fixture(actual, { getRequirementDetail: () => pending.promise });
  api.prepareCreateGuide = (_id, body) => {
    counts.prepares++;
    bodies.push(body);
    return {async submit() {
      counts.sends++;
      if (counts.sends === 1) throw new ApiUnknown(true);
      return { data: receipt };
    }};
  };

  owner.choose('REVISE');
  owner.change('保存第一章');
  assert(owner.selectChapter({
    document_id: 2, content_version: 3, label: '第一章', selection: null,
    scope: { scope_type: 'SECTION', scope_ref: { block_id: 8 } },
  }));
  const sending = owner.submit();
  await Promise.resolve();
  assert.equal(owner.getSnapshot().phase, 'READING');
  owner.choose('DISCUSS');
  assert.equal(owner.getSnapshot().action, 'DISCUSS');
  assert.equal(owner.getSnapshot().instruction, '保存第一章');
  pending.resolve({data:{...actual,discussion:{binding:{source_refs:[]}}}});
  assert.equal(await sending, false);
  assert.equal(owner.getSnapshot().phase, 'UNKNOWN');
  assert.equal(bodies[0].operation, 'REVISE');
  assert.deepEqual(bodies[0].scope, { scope_type: 'SECTION', scope_ref: { heading_block_id: 8 } });

  owner.choose('REVISE');
  assert.equal(owner.getSnapshot().target, null);
  assert(await owner.recover());
  assert.equal(counts.prepares, 1);
  assert.equal(counts.sends, 2);
  assert.equal(owner.allowed, false);
  owner.dispose();
});

test('a changed discussion during preflight cannot grant a send with a new focus', async () => {
  const pending = deferred();
  const actual = detail();
  const { owner, counts } = fixture(actual, { getRequirementDetail: () => pending.promise });
  owner.change('按原主题继续');
  const sending = owner.submit();
  await Promise.resolve();
  const updated = { ...actual, requirement: { ...actual.requirement, discussion_version: 8 } };
  owner.adopt(updated);
  pending.resolve({data:{...updated,discussion:{binding:{source_refs:[]}}}});
  assert.equal(await sending, false);
  assert.equal(counts.prepares, 0);
  assert.equal(owner.getSnapshot().instruction, '按原主题继续');
  owner.dispose();
});

test('without a selected document the composer cannot prepare an AI operation',async()=>{
 const {owner,counts}=fixture({...detail(),selected_document_id:null,current:null,documents:[]});
 owner.change('not sent');assert.equal(owner.allowed,false);assert.equal(await owner.submit(),false);assert.equal(counts.prepares,0);owner.dispose();
});

test('a document assistant rejects an existing work target from another document before preparing a command',()=>{
 const {owner,counts}=fixture(detail([doc(2),doc(3)]));
 assert.throws(()=>owner.selectDocument(3),TypeError);assert.equal(owner.getSnapshot().target.document_id,2);assert.equal(counts.prepares,0);owner.dispose();
});
