import {test} from 'node:test';
import assert from 'node:assert/strict';
import {modelCall,modelCalls,modelCallDetail} from '../src/api/model-calls.ts';
import {ModelCallReader,tokenTotal} from '../src/guide/model-call-reader.ts';
const at='2026-10-11T12:00:00.000Z';
const call=(changes={})=>({id:20,guide_run_id:17,call_no:1,attempt_no:1,model_name:'saved-model',call_status:'SUCCEEDED',parse_status:'SUCCEEDED',validation_status:'FAILED',started_at:at,ended_at:at,user_message_id:37,document_version:2,input_tokens:100,output_tokens:12,total_tokens:112,cached_tokens:50,duration_ms:44,...changes});
const list=(changes={})=>({id:17,requirement_id:3,action_type:'INITIALIZE',status:'WAITING_USER',current_step:'WAITING_USER',trigger_message_id:18,program_processed:false,items:[call()],...changes});
test('actual usage totals exclude overlapping cache; missing usage is not zero',()=>{
 const first=modelCall(call()),second=modelCall(call({id:21,attempt_no:2,input_tokens:20,output_tokens:2,total_tokens:22,cached_tokens:10}));
 assert.equal(tokenTotal([first,second],'total_tokens'),134);assert.equal(tokenTotal([first,second],'cached_tokens'),60);
 assert.equal(tokenTotal([first,call({input_tokens:null,total_tokens:null})],'input_tokens'),null);assert.equal(tokenTotal([],'input_tokens'),null);
 assert.equal(modelCall(call({input_tokens:0,output_tokens:0,total_tokens:0,cached_tokens:0})).total_tokens,0);
 assert.throws(()=>modelCall(call({total_tokens:162})));assert.throws(()=>modelCalls(list({program_processed:true})));
});
test('snapshot decoder retains raw source and nullable legacy fields',()=>{
 const value=modelCallDetail({call:call(),requirement_id:3,action_type:'INITIALIZE',prompt_reference:null,context_reference:null,sections:[],included_history_ids:[],budget_removed_history_ids:[],raw_request_json:'{"messages":[]}',preflight:{input_tokens:null,budget:null,counts:[null,null,null,null,null,null]}});
 assert.equal(value.raw_request_json,'{"messages":[]}');assert.equal(value.preflight.input_tokens,null);
 assert.equal(value.context_strategy,null);assert.equal(value.selection_summary,null);
 assert.throws(()=>modelCalls(list({items:[call(),call()]})));
});
test('phase A diagnostic fields stay separate from actual usage and preserve unknown values',()=>{
 const source={call:call(),requirement_id:3,action_type:'INITIALIZE',prompt_reference:'INITIALIZE_REQUIREMENT@v9',context_reference:'INITIALIZE_CONTEXT@v9',
  context_strategy:'context_projection_v1',selection_summary:{read_blocks:321,history_messages:10,soft_input_target:49152,count_attempts:2,soft_target_exceeded:true},
  sections:[],included_history_ids:[37],budget_removed_history_ids:[],raw_request_json:'{"messages":[]}',preflight:{input_tokens:60000,budget:null,counts:[null,null,null,null,null,null]}};
 const value=modelCallDetail(source);assert.equal(value.call.total_tokens,112);assert.equal(value.selection_summary.count_attempts,2);
 assert.equal(modelCallDetail({...source,selection_summary:{...source.selection_summary,count_attempts:null}}).selection_summary.count_attempts,null);
 assert.throws(()=>modelCallDetail({...source,selection_summary:{...source.selection_summary,private_context_basis:{}}}));
});
test('one GET per run and state revision, never loads detail or counts to display summary',async()=>{
 let reads=0,resolve;const api={listModelCalls:()=>{reads++;return new Promise(done=>resolve=done);},getModelCall:()=>{throw Error('Summary must not request detail');}};
 const reader=new ModelCallReader(api,3),first=reader.load(17,'v1'),duplicate=reader.load(17,'v1');assert.equal(first,duplicate);
 await Promise.resolve();assert.equal(reads,1);resolve({data:list()});await first;
 await reader.load(17,'v1');assert.equal(reads,1);
 const changed=reader.load(17,'v2');await Promise.resolve();resolve({data:list({status:'COMPLETED',current_step:'FINISHED'})});await changed;assert.equal(reads,2);assert.equal(reader.get(17).data.status,'COMPLETED');reader.dispose();
});
test('hidden or retired view ignores late reads and reopens with a fresh GET',async()=>{
 let resolve,reads=0;const reader=new ModelCallReader({listModelCalls:()=>{reads++;return new Promise(done=>resolve=done);}},3);
 const pending=reader.load(17,'v1');await Promise.resolve();reader.setActive(false);resolve({data:list()});await pending;assert.equal(reader.get(17).data,null);assert.equal(reader.get(17).loading,false);
 await reader.load(17,'v1');assert.equal(reads,1);reader.setActive(true);const resumed=reader.load(17,'v1');await Promise.resolve();resolve({data:list()});await resumed;assert.equal(reads,2);reader.dispose();await reader.load(17,'v2');assert.equal(reads,2);
});
test('failure preserves previously read facts and foreign identities are rejected',async()=>{
 let next=list();const reader=new ModelCallReader({listModelCalls:async()=>{if(next===null)throw Error('offline');return {data:next};}},3);
 await reader.load(17,'v1');next=null;await reader.load(17,'v2');assert.equal(reader.get(17).data.items[0].id,20);assert(reader.get(17).error);
 next=list({requirement_id:4});await reader.load(17,'v3');assert.equal(reader.get(17).data.requirement_id,3);assert(reader.get(17).error);
 next=list();await reader.load(17,'v3',true);assert.equal(reader.get(17).error,null);reader.dispose();
});
