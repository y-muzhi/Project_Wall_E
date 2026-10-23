import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {cards,message} from '../src/api/models.ts';
import {InteractionCards} from '../src/guide/cards.ts';
import {CardDrafts} from '../src/guide/card-drafts.ts';
const at='2026-10-22T00:00:00.000Z',key='00000000-0000-4000-8000-000000000001';
const definition=(program=false)=>cards({schema_version:1,intro:'',purpose:program?'PHASE_CHANGE':'CLARIFICATION',cards:[{card_key:'c1',card_type:program?'CONFIRM':'SINGLE_SELECT',question:'选择',context:'',required:true,
 options:(program?['accept','defer']:['a','b']).map(value=>({option_key:value,label:value,description:'不回传',impact:'',risks:''})),selection_rule:{min:1,max:1},custom_answer:{enabled:false,max_length:0},recommendation:null,related_spec_context:[]}],
 action_payload:program?{phase_kind:'SOLUTION',closure_summary:'进入方案',unresolved_refs:[],basis_discussion_version:2}:null,program_binding:{discussion_version:3,target_content_version:null,source_heads:[]}});
const base=(changes={})=>({id:20,requirement_id:1,guide_run_id:10,sequence_no:2,role:'ASSISTANT',content:'提问',message_type:'INTERACTION_CARDS',structured_content:definition(),reply_to_message_id:null,created_at:at,card_state:'AVAILABLE',phase_ref:'p1',topic_refs:[],document_ids:[],program_receipt:null,...changes});
const detail=version=>({requirement:{id:1,discussion_version:version,document_work_state:'IDLE',active_operation_id:null,active_operation_type:null,status:'CLOSED'},current:null,documents:[],activity:{kind:'IDLE'}});
const programReceipt={processing:'PROGRAM',user_message_id:21,requirement_id:1,discussion_version:4,purpose:'PHASE_CHANGE',result:'APPLIED',document_effect:null};
const modelReceipt={processing:'MODEL',user_message_id:21,guide_run_id:11};
function fixture({program=false,unknown=false,loseRead=false}={}){
 let committed=false;const counts={prepares:0,sends:0,receives:0,runReads:0},source={id:10,requirement_id:1,status:'COMPLETED',operation:'DISCUSS'},group=definition(program),original=message(base({structured_content:group}));
 const receipt=program?programReceipt:modelReceipt,answers={schema_version:1,responses:[{card_key:'c1',selected_option_keys:[program?'accept':'a'],custom_answer:null,skipped:false}],execution_selection:null};
 const formal=()=>message(base({id:21,guide_run_id:program?null:11,sequence_no:3,role:'USER',content:'选择\n'+(program?'accept':'a'),message_type:'CARD_RESPONSE',structured_content:answers,reply_to_message_id:20,card_state:null,program_receipt:program?programReceipt:null}));
 const api={prepareCardResponses(id,body,version){counts.prepares++;assert.equal(id,20);assert.equal(version,3);assert.deepEqual(body,answers);return {async submit(){counts.sends++;committed=true;if(unknown&&counts.sends===1)throw new ApiUnknown(true);return {data:receipt};}};},
  async listMessages(){return {data:{items:[message(base({structured_content:group,card_state:committed?'ANSWERED':'AVAILABLE'})),...(committed?[formal()]:[])]},meta:{pagination:{has_more:false,page_size:20,next_cursor:null}}};},
  async getGuideRun(id){counts.runReads++;if(id===11&&loseRead){loseRead=false;throw new ApiUnknown(false);}return {data:id===10?source:{id:11,requirement_id:1,parent_guide_run_id:10,operation:'DISCUSS'}};}};
 const drafts=new CardDrafts(()=>({getItem:()=>null,setItem:()=>{},removeItem:()=>{}})),owner=new InteractionCards(original,source,detail(3),api,drafts,async()=>detail(committed?4:3),async()=>{},async()=>{counts.receives++;},async()=>{});
 owner.setAvailable(true);owner.toggle('c1',program?'accept':'a',true);return {owner,counts};
}
test('MODEL answer observes its actual new run and formal answer; PROGRAM never invents or reads a new run',async()=>{
 for(const program of [false,true]){const {owner,counts}=fixture({program});assert.equal(owner.allowed,true);assert.equal(await owner.submit(),true);assert.equal(owner.getSnapshot().phase,'RESOLVED');
  assert.equal(counts.sends,1);assert.equal(counts.receives,program?0:1);assert.equal(owner.getSnapshot().formal.guide_run_id,program?null:11);owner.dispose();}
});
test('declared execution choices persist with whole answers and restore in the same requirement/message namespace',()=>{
 const definitionValue=structuredClone(definition(true));definitionValue.purpose='DOCUMENT_ACTION';definitionValue.action_payload={operation:'GENERATE',target:{kind:'NEW',name:'建议稿',document_kind:'brief',template_ref:null},scope:null,source_refs:[],basis_discussion_version:2,unresolved_impacts:[],selectable_fields:['target','source_refs']};
 const group=cards(definitionValue),original=message(base({structured_content:group})),source={id:10,requirement_id:1,status:'COMPLETED',operation:'DISCUSS'};
 const memory=new Map(),storage={getItem:key=>memory.get(key)??null,setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)};
 const drafts=new CardDrafts(()=>storage,()=>at),make=()=>new InteractionCards(original,source,detail(3),{},drafts,async()=>detail(3),async()=>{},async()=>{},async()=>{});
 const owner=make();owner.setAvailable(true);
 assert(owner.configureExecution({target:{kind:'NEW',name:'用户选择的新稿',document_kind:'design',template_ref:{key:'structure.design',version:'v1'}}}));
 assert(!owner.configureExecution({scope:{scope_type:'DOCUMENT',scope_ref:null}}));
 owner.toggle('c1','accept',true);
 const saved=JSON.parse(memory.get('walle:v1.5:cards:1:20'));assert.equal(saved.schema_version,2);assert.equal(saved.execution_selection.target.name,'用户选择的新稿');
 const restored=make();assert.deepEqual(restored.getSnapshot().answers,owner.getSnapshot().answers);
 assert.equal(drafts.load(2,20,group).answers,null);restored.dispose();owner.dispose();
});
test('unknown whole-group response keeps the original prepared request and can recover an already processed program action',async()=>{
 const {owner,counts}=fixture({program:true,unknown:true});assert.equal(await owner.submit(),false);assert.equal(owner.getSnapshot().phase,'UNKNOWN');
 assert.equal(await owner.recover(),true);assert.equal(counts.prepares,1);assert.equal(counts.sends,2);assert.equal(counts.receives,0);assert.equal(owner.getSnapshot().formal.program_receipt.purpose,'PHASE_CHANGE');owner.dispose();
});
test('accepted MODEL receipt followed by a failed read retries reads without another formal submission',async()=>{
 const {owner,counts}=fixture({loseRead:true});assert.equal(await owner.submit(),false);assert.equal(owner.getSnapshot().phase,'CONFIRMED');assert.equal(await owner.finish(),true);
 assert.equal(counts.prepares,1);assert.equal(counts.sends,1);assert.equal(counts.receives,1);owner.dispose();
});
test('StoredCardGroup/Message reject missing program binding and mismatched program answer identity',()=>{
 const group=definition(true),copy=JSON.parse(JSON.stringify(group));delete copy.program_binding;assert.throws(()=>cards(copy));
 assert.throws(()=>message(base({program_receipt:programReceipt})));assert.throws(()=>message(base({phase_ref:undefined})));
});
test('the original responses route accepts only the status matching MODEL or PROGRAM and transports the discussion version',async()=>{
 const answers={schema_version:1,responses:[{card_key:'c1',selected_option_keys:['accept'],custom_answer:null,skipped:false}],execution_selection:null};
 for(const receipt of [modelReceipt,programReceipt])for(const wrong of [false,true]){
  const requests=[];const expected=receipt.processing==='MODEL'?202:200,status=wrong?(expected===200?202:200):expected;
  const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});return new Response(JSON.stringify({success:true,data:receipt,error:null,meta:{request_id:key}}),{status,headers:{'Content-Type':'application/json'}});},()=>key),null);
  const action=api.prepareCardResponses(20,answers,3);
  if(wrong)await assert.rejects(action.submit(),ApiUnknown);else assert.deepEqual((await action.submit()).data,receipt);
  assert.equal(requests[0].path,'/api/v1/conversation-messages/20/responses');assert.equal(JSON.parse(requests[0].init.body).expected_discussion_version,3);
 }
});
