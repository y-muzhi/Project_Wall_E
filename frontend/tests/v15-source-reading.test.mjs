import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readSource} from '../src/requirements/source-reading.ts';
const signal=()=>new AbortController().signal;
const revision={id:8,requirement_id:1,document_id:2,source_content_version:3,markdown_content:'# 原始版本\n\n原文',block_state_json:{blocks:[{block_id:4}]}};
test('revision source reads its explicit immutable version and rejects foreign document or absent subset without commands',async()=>{
 let reads=0;const api={getRevision:async id=>{assert.equal(id,8);reads++;return {data:revision};}};
 const source={kind:'REVISION',document_id:2,revision_id:8,block_ids:[4]};
 const actual=await readSource(1,source,api,signal());assert.equal(reads,1);assert(actual.content.includes(revision.markdown_content));assert(actual.content.includes('#4'));
 await assert.rejects(readSource(1,{...source,document_id:3},api,signal()));
 await assert.rejects(readSource(1,{...source,block_ids:[99]},api,signal()));
 await assert.rejects(readSource(2,source,api,signal()));
});
test('formal answer source uses the actual parent question and selected labels, without unselected descriptions',async()=>{
 const pages=[];const api={listMessages:async(req,cursor)=>{assert.equal(req,1);pages.push(cursor);return {data:{items:cursor===null?[{
  id:21,requirement_id:1,role:'USER',message_type:'CARD_RESPONSE',reply_to_message_id:20,structured_content:{responses:[{card_key:'c1',selected_option_keys:['a'],custom_answer:'自定义说明',skipped:false}]}}]:[{
  id:20,requirement_id:1,role:'ASSISTANT',structured_content:{cards:[{card_key:'c1',question:'原问题',options:[{option_key:'a',label:'正式选项',description:'不应作为选择'},{option_key:'b',label:'未选内容'}]}]}}]},meta:{pagination:cursor===null?{has_more:true,next_cursor:21}:{has_more:false,next_cursor:null}}};}};
 const result=await readSource(1,{kind:'CARD_ANSWER',message_id:21,card_key:'c1'},api,signal());
 assert.equal(result.content,'原问题\n正式选项\n自定义说明');assert(!result.content.includes('未选内容'));assert(pages.includes(21));
});
test('saved run material exposes only actually selected Wire units and cannot read a private basis as material',async()=>{
 const request={message_id:2,message_ref:'m2',content:'已实际发送的用户原话',formal_answers:null,operation:'DISCUSS',target:null,scope:null,source_refs:[],basis_ref:{discussion_version:2,phase_ref:'p1',guide_key:'collaboration.discovery',guide_version:'v1'}};
 const wire={schema_version:1,structure:null,goal_and_decisions:[],project_position:{phase_kind:'DISCOVERY',phase_ref:'p1',focus_topic_ref:null,mainlines:[],dispositions:[]},current_topic:null,documents:[],recent_history:[],current_request:request};
 const api={getGuideRun:async()=>({data:{id:9,requirement_id:1,status:'COMPLETED'}}),listModelCalls:async()=>({data:{id:9,requirement_id:1,items:[{id:7}]}}),getModelCall:async()=>({data:{requirement_id:1,call:{id:7,guide_run_id:9},selection_summary:{selected_materials:[{ref:'m2',document_id:null,revision_id:null,block_ids:[],message_ids:[2],source_refs:[{kind:'MESSAGE',message_id:2}]}]},raw_request_json:JSON.stringify({messages:[{role:'user',content:JSON.stringify(wire)}],private_basis:'private-grant-not-material'})}})};
 const result=await readSource(1,{kind:'RUN_MATERIAL',guide_run_id:9,material_ref:'m2'},api,signal());
 assert(result.content.includes(request.content));assert(!result.content.includes('private-grant-not-material'));
 await assert.rejects(readSource(1,{kind:'RUN_MATERIAL',guide_run_id:9,material_ref:'authorization'},api,signal()));
});
test('abort before a source read has no network effects',async()=>{
 const controller=new AbortController();controller.abort();
 await assert.rejects(readSource(1,{kind:'MESSAGE',message_id:1},{listMessages:()=>{throw Error('should not be reached');}},controller.signal));
});
test('run result reads the saved complete Analysis rather than substituting a message summary',async()=>{
 const value={conclusion:'RESULT',summary:'分析正文',findings:[{ref:'f1',severity:'WARNING',message:'具体范围差异',source_refs:['m2']}],covered_refs:['m2'],unresolved:[]};
 const run={id:9,requirement_id:1,status:'COMPLETED',final_result:{summary:'不能代替分析的消息摘要',analysis:value}};
 const api={getGuideRun:async()=>({data:run})};
 const actual=await readSource(1,{kind:'RUN_RESULT',guide_run_id:9},api,signal());
 assert.deepEqual(JSON.parse(actual.content),value);assert(!actual.content.includes(run.final_result.summary));
 await assert.rejects(readSource(1,{kind:'RUN_RESULT',guide_run_id:9},{getGuideRun:async()=>({data:{...run,final_result:{analysis:null}}})},signal()));
});
