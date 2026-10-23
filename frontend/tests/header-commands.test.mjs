import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementHeaderCommands} from '../src/requirements/header-commands.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-23T00:00:00.000Z',root={id:1,title:'实际标题',status:'PLANNING',metadata_version:1,document_work_state:'IDLE',active_operation_type:null,active_operation_id:null};
const current={id:2,requirement_id:1,document_type:'CURRENT',archived_at:null,content_version:1,markdown_content:'',created_at:at,updated_at:at,block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const detail=(requirement=root,document=current)=>({requirement,current:document,activity:{kind:'IDLE'}});
const api=()=>({prepareUpdateRequirement:()=>({submit:async()=>{throw new ApiUnknown(true);}}),prepareStartManualDraft:()=>({submit:async()=>{throw new ApiUnknown(true);}})});

test('actual metadata rebases idle header owners while unsent title text remains independent',()=>{
 const h=new RequirementHeaderCommands(detail(),api()),life=h.getSnapshot().lifecycle;h.title.begin();h.title.change('未提交标题');h.adopt(detail({...root,title:'其他页面',metadata_version:2}));
 assert.equal(h.title.getSnapshot().draft,'未提交标题');assert.notEqual(h.getSnapshot().lifecycle,life);assert.equal(h.getSnapshot().detail.requirement.title,'其他页面');h.dispose();
});
test('unknown status retains original owner despite actual changes; only original receipt then actual adoption establishes new controls',async()=>{
 const port=api(),h=new RequirementHeaderCommands(detail(),port),life=h.getSnapshot().lifecycle;assert(!await life.select('COMPLETED'));assert(h.blockedFor('TITLE'));assert(!h.blockedFor('LIFECYCLE'));
 const completed={...root,status:'COMPLETED',metadata_version:3};h.adopt(detail(completed));assert.equal(h.getSnapshot().lifecycle,life);assert.equal(life.getSnapshot().phase,'UNKNOWN');port.prepareUpdateRequirement=()=>({submit:async()=>({data:completed})});assert(!await life.retryUnknown());h.dispose();
 const confirmed=new RequirementHeaderCommands(detail(),port),old=confirmed.getSnapshot().lifecycle;assert(await old.select('COMPLETED'));confirmed.adopt(detail(completed));assert.notEqual(confirmed.getSnapshot().lifecycle,old);assert.equal(confirmed.getSnapshot().lifecycle.operation,'COMPLETED');assert(confirmed.getSnapshot().manual);confirmed.dispose();
});
test('unknown manual start keeps its original target while reading another document; no document still permits metadata',async()=>{
 const h=new RequirementHeaderCommands(detail(),api()),start=h.getSnapshot().manual;h.title.begin();h.title.change('未提交标题');assert(!await start.start());
 const active=detail({...root,document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3},{...current,id:4});active.activity={kind:'MANUAL',draft:{...current,id:3,document_type:'MANUAL_DRAFT',target_document_id:2,base_content_version:1}};
 h.adopt(active);assert.equal(h.getSnapshot().manual,start);assert(h.getSnapshot().lifecycle);assert(h.title.allowed);assert.equal(h.title.getSnapshot().draft,'未提交标题');h.dispose();
 const empty=new RequirementHeaderCommands(detail(root,null),api());assert.equal(empty.getSnapshot().manual,null);assert(empty.title.allowed);assert(empty.getSnapshot().lifecycle);empty.dispose();
});
test('definite status rejection rebases only from actual metadata; independent unknown commands do not deadlock original recovery',async()=>{
 const port=api();port.prepareUpdateRequirement=()=>({submit:async()=>{throw new ApiRejected('METADATA_VERSION_CONFLICT','已变化',null,'r',409);}});const h=new RequirementHeaderCommands(detail(),port),old=h.getSnapshot().lifecycle;assert(!await old.select('READY'));h.adopt(detail({...root,metadata_version:2}));assert.notEqual(h.getSnapshot().lifecycle,old);h.dispose();
 const q=new RequirementHeaderCommands(detail(),api());q.title.begin();q.title.change('原意图');await q.title.save();await q.getSnapshot().manual.start();assert(!q.blockedFor('TITLE'));assert(!q.blockedFor('MANUAL'));assert(q.blockedFor('LIFECYCLE'));q.dispose();
});
