import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {requirementDetail,sourceRef,revisionSummary} from '../src/api/models.ts';
import {RequirementDetailRead} from '../src/requirements/detail-read.ts';

const at='2026-10-22T00:00:00.000Z',key='00000000-0000-4000-8000-000000000001';
const root=(changes={})=>({id:1,requirement_no:'REQ000001',title:'需求',requirement_type:'NEW',status:'PLANNING',metadata_version:1,initial_message_id:1,discussion_version:1,
 document_work_state:'IDLE',active_operation_type:null,active_operation_id:null,created_at:at,updated_at:at,completed_at:null,closed_at:null,state_started_at:null,...changes});
const summary=id=>({id,requirement_id:1,name:'文档'+id,document_kind:'REQUIREMENT_BRIEF',document_type:'CURRENT',metadata_version:1,content_version:1,current_revision_id:id,
 confirmed_revision_id:null,archived_at:null,updated_at:at,source_status:'UNCHANGED'});
const view=id=>({...summary(id),markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]},template_ref:null,created_at:at});
const detail=(changes={})=>({requirement:root(),documents:[],discussion_summary:{discussion_version:1,phase_ref:'p1',phase_kind:'DISCOVERY',focus_topic_ref:null,focus_title:null,next_step:null,pending_count:0},discussion:null,active_operation:null,...changes});
const index=id=>({requirement_id:1,document_id:id,content_version:1,total_count:0,open_count:0,blocks:[],comments:[]});
const result=data=>({data,meta:{request_id:key},status:200});
const response=data=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:key}}),{status:200,headers:{'Content-Type':'application/json'}});

test('strict detail accepts zero documents and verifies actual active edit target ownership',()=>{
 assert.equal(requirementDetail(detail()).documents.length,0);
 const active={type:'MANUAL_DRAFT',id:9,summary:'人工编辑中',target_document_id:2};
 const input=detail({documents:[summary(2)],requirement:root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:9,state_started_at:at}),active_operation:active});
 assert.equal(requirementDetail(input).active_operation.target_document_id,2);
 assert.throws(()=>requirementDetail({...input,active_operation:{...active,target_document_id:3}}));
 assert.throws(()=>requirementDetail({...input,active_operation:{...active,target_document_id:null}}));
});

test('v9 named definitions retain strict SourceRef and nested uppercase references',()=>{
 const ref={kind:'REVISION',document_id:2,revision_id:3,block_ids:[7]};
 assert.deepEqual(sourceRef(ref),ref);assert.throws(()=>sourceRef({...ref,document_id:0}));
 assert.throws(()=>sourceRef({...ref,unknown:true}));
 assert.throws(()=>sourceRef({...ref,block_ids:[0]}));
 const manifest=JSON.parse(readFileSync(new URL('../../backend/resources/v9/manifest.json',import.meta.url),'utf8'));
 const guide=manifest.files.find(item=>item.resource_ref.key==='collaboration.discovery').resource_ref;
 const discussion={schema_version:1,phase:{phase_ref:'p1',kind:'DISCOVERY',guide_ref:guide,closure:null},focus_topic_ref:null,topics:[],evidence:[],pending_user_message_ids:[],binding:{target_document_id:null,source_refs:[],scope:null,document_kind:null},dispositions:[],last_step:null,counters:{phase:2,topic:1,evidence:1}};
 assert.deepEqual(requirementDetail(detail({discussion})).discussion,discussion);
 assert.throws(()=>requirementDetail(detail({discussion:{...discussion,counters:{phase:0,topic:1,evidence:1}}})));
});

test('zero-document read performs only summary GETs and returns a legal empty workspace',async()=>{
 const calls=[];
 const reader=new RequirementDetailRead(1,{async getRequirementDetail(id){calls.push(['detail',id]);return result(detail());}});
 assert.equal(await reader.refresh(),true);assert.equal(reader.phase,'IDLE_VIEW');assert.equal(reader.writeReady,true);
 assert.equal(reader.getSnapshot().confirmed.current,null);assert.equal(reader.getSnapshot().confirmed.comment_index,null);
 assert.deepEqual(calls,[['detail',1],['detail',1]]);reader.dispose();
});

test('reading B while editing A uses the actual draft target without changing reading selection',async()=>{
 const calls=[],active={type:'MANUAL_DRAFT',id:9,summary:'人工编辑中',target_document_id:1};
 const input=detail({documents:[summary(1),summary(2)],requirement:root({document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:9,state_started_at:at}),active_operation:active});
 const reader=new RequirementDetailRead(1,{
  async getRequirementDetail(){return result(input);},
  async getCurrentDocument(req,id){calls.push(['current',req,id]);return result(view(id));},
  async getCommentIndex(req,id){calls.push(['comments',req,id]);return result(index(id));},
  async getManualDraft(req,id){calls.push(['draft',req,id]);return result({...view(id),id:9,document_type:'MANUAL_DRAFT',target_document_id:1,base_content_version:1});}
 });
 assert.equal(await reader.refresh(),true);calls.length=0;
 assert.equal(await reader.selectDocument(2),true);
 const actual=reader.getSnapshot().confirmed;
 assert.equal(actual.current.id,2);assert.equal(actual.activity.target.id,1);assert.equal(actual.activity.draft.id,9);
 assert(calls.some(call=>call[0]==='draft'&&call[2]===1));assert(!calls.some(call=>call[0]==='draft'&&call[2]===2));
 assert.throws(()=>reader.selectDocument(999));reader.dispose();
});
test('last confirmed reading document restores per requirement and missing or corrupt preferences never become a work target',async()=>{
 const memory=new Map(),storage=()=>({getItem:key=>memory.get(key)??null,setItem:(key,value)=>memory.set(key,value)});
 const input=detail({documents:[summary(1),summary(2)]}),api={getRequirementDetail:async()=>result(input),getCurrentDocument:async(req,id)=>result(view(id)),getCommentIndex:async(req,id)=>result(index(id))};
 let reader=new RequirementDetailRead(1,api,storage);assert(await reader.refresh());assert(await reader.selectDocument(2));reader.dispose();
 reader=new RequirementDetailRead(1,api,storage);assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.current.id,2);assert.equal(reader.getSnapshot().confirmed.activity.kind,'IDLE');reader.dispose();
 memory.set('walle:v1.5:reading:1',JSON.stringify({schema_version:1,requirement_id:1,document_id:999}));reader=new RequirementDetailRead(1,api,storage);assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.current.id,1);reader.dispose();
 memory.set('walle:v1.5:reading:1',JSON.stringify({schema_version:1,requirement_id:2,document_id:2}));reader=new RequirementDetailRead(1,api,storage);assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.current.id,1);reader.dispose();
});
test('the first actual generated document replaces the zero-document reading state without changing any AI binding',async()=>{
 let actual=detail();const api={getRequirementDetail:async()=>result(actual),getCurrentDocument:async(req,id)=>result(view(id)),getCommentIndex:async(req,id)=>result(index(id))};
 const reader=new RequirementDetailRead(1,api);assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.current,null);
 actual=detail({documents:[summary(1)]});assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.current.id,1);assert.equal(reader.getSnapshot().confirmed.selected_document_id,1);reader.dispose();
});

test('client query serialization carries explicit document IDs and expand without changing the safe path policy',async()=>{
 const calls=[];
 const api=new WalleApi(new ApiClient(async path=>{calls.push(path);return response(path.includes('comment-index')?index(7):detail());},()=>key),{});
 await api.getRequirement(1);await api.getCommentIndex(1,7);
 assert.deepEqual(calls,['/api/v1/requirements/1','/api/v1/requirements/1/comment-index?document_id=7']);
 assert.throws(()=>api.prepareCreateRevision(1,{expected_version:1}));
});

test('content history has fixed source versions and separate chronological marker events',()=>{
 const value={id:3,requirement_id:1,document_id:7,version_no:2,source_content_version:2,created_at:at,change_summary:'人工编辑',source_refs:[],markers:[{event_id:4,description:'复核通过',created_at:at}]};
 assert.equal(revisionSummary(value).markers[0].event_id,4);
 assert.throws(()=>revisionSummary({...value,version_no:3}));
 assert.throws(()=>revisionSummary({...value,revision_type:'MANUAL'}));
 assert.throws(()=>revisionSummary({...value,markers:[...value.markers,...value.markers]}));
});
