import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementHeaderCommands} from '../src/requirements/header-commands.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-06T03:00:00.000Z';
const root={id:1,requirement_no:'REQ000001',title:'实际标题',requirement_type:'NEW',initialization_mode:'DESIGN',status:'ACTIVE',document_work_state:'IDLE',
 active_operation_id:null,active_operation_type:null,template_key:'new-requirement',template_version:'v1',created_at:at,updated_at:at,completed_at:null,state_started_at:null};
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:1,created_at:at,updated_at:at,markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const detail=(requirement=root,version=1)=>({requirement,current:{...current,content_version:version},activity:{kind:'IDLE'},comment_index:{}});
const api=()=>({getRequirement:async()=>({data:root}),getCurrentDocument:async()=>({data:current}),getManualDraft:async()=>({data:null}),listRevisions:async()=>({data:{items:[]}}),
 prepareUpdateRequirement:()=>({submit:async()=>{throw new ApiUnknown(true);}}),prepareStartManualDraft:()=>({submit:async()=>{throw new ApiUnknown(true);}}),
 prepareCompleteRequirement:()=>({submit:async()=>{throw new ApiUnknown(true);}}),prepareCompleteInitialization:()=>({submit:async()=>{throw new ApiUnknown(true);}}),prepareReactivateRequirement:()=>({submit:async()=>{throw new ApiUnknown(true);}})});

test('actual header facts update independently of raw title intention and unchanged lifecycle identity/generation',()=>{
 const h=new RequirementHeaderCommands(detail(),api()),first=h.getSnapshot(),life=first.lifecycle;h.title.begin();h.title.change('保留输入');h.adopt(detail({...root,title:'另一页更新'}));
 assert.equal(h.title.getSnapshot().draft,'保留输入');assert.equal(h.getSnapshot().detail.requirement.title,'另一页更新');assert.equal(h.title.getSnapshot().actual.title,'另一页更新');assert.equal(h.getSnapshot().lifecycle,life);assert.equal(h.getSnapshot().lifecycle_generation,first.lifecycle_generation);
 h.adopt(detail(root,2));assert.notEqual(h.getSnapshot().lifecycle,life);assert.equal(h.getSnapshot().lifecycle_generation,first.lifecycle_generation+1);assert.equal(h.title.getSnapshot().draft,'保留输入');h.dispose();
});
test('unknown lifecycle survives actual completed read and version changes, only original positive receipt then actual read establishes next controls',async()=>{
 const port=api(),h=new RequirementHeaderCommands(detail(),port),life=h.getSnapshot().lifecycle;assert(!await life.submit());assert(h.blockedFor('TITLE'));assert(!h.blockedFor('LIFECYCLE'));
 const completed={...root,status:'COMPLETED',completed_at:at};h.adopt(detail(completed,9));assert.equal(h.getSnapshot().lifecycle,life);assert.equal(life.getSnapshot().phase,'UNKNOWN');assert(!h.title.allowed);assert.equal(h.getSnapshot().detail.current.content_version,9);
 let sends=0;port.prepareCompleteRequirement=()=>({submit:async()=>({data:completed})}); // Replacement cannot affect original opaque action.
 assert(!await life.retryUnknown());assert.equal(life.getSnapshot().phase,'UNKNOWN');assert.equal(sends,0);h.dispose();
 const q=api();q.prepareCompleteRequirement=()=>({submit:async()=>({data:completed})});const confirmed=new RequirementHeaderCommands(detail(),q),old=confirmed.getSnapshot().lifecycle;assert(await old.submit());assert(confirmed.blockedFor('TITLE'));confirmed.adopt(detail(completed));
 assert.notEqual(confirmed.getSnapshot().lifecycle,old);assert.equal(confirmed.getSnapshot().lifecycle.operation,'REACTIVATE');assert.equal(confirmed.getSnapshot().manual,null);assert(!confirmed.blockedFor('TITLE'));confirmed.dispose();
});
test('unknown start is retained during actual manual occupancy, unsent title persists, retired owners never update',async()=>{
 const h=new RequirementHeaderCommands(detail(),api()),start=h.getSnapshot().manual;h.title.begin();h.title.change('未提交标题');assert(!await start.start());assert(h.blockedFor('TITLE'));assert(!h.blockedFor('MANUAL'));
 const draft={...current,id:3,document_type:'MANUAL_DRAFT'};const manual=detail({...root,document_work_state:'MANUAL_EDITING',active_operation_id:3,active_operation_type:'MANUAL_DRAFT',state_started_at:at});manual.activity={kind:'MANUAL',draft};h.adopt(manual);
 assert.equal(h.getSnapshot().manual,start);assert.equal(start.getSnapshot().phase,'UNKNOWN');assert.equal(h.getSnapshot().lifecycle,null);assert.equal(h.title.getSnapshot().draft,'未提交标题');assert(h.title.allowed);const before=h.getSnapshot();h.dispose();h.adopt(detail());assert.equal(h.getSnapshot(),before);
});
test('known lifecycle conflict rebuilds baseline only after actual complete read; multiple unknowns do not mutually prevent recovery',async()=>{
 const p=api();p.prepareCompleteRequirement=()=>({submit:async()=>{throw new ApiRejected('CONTENT_VERSION_CONFLICT','版本冲突',null,'actual-id',409);}});const h=new RequirementHeaderCommands(detail(),p),old=h.getSnapshot().lifecycle;
 assert(!await old.submit());assert.equal(old.getSnapshot().phase,'ERROR');h.adopt(detail(root,2));assert.notEqual(h.getSnapshot().lifecycle,old);assert.equal(h.getSnapshot().lifecycle.getSnapshot().phase,'READY');h.dispose();
 const q=new RequirementHeaderCommands(detail(),api());q.title.begin();q.title.change('原意图');await q.title.save();await q.getSnapshot().manual.start();assert.equal(q.title.getSnapshot().phase,'UNKNOWN');assert(!q.blockedFor('TITLE'));assert(!q.blockedFor('MANUAL'));assert.equal(q.mode,undefined);assert(q.blockedFor('LIFECYCLE'));q.dispose();
});
