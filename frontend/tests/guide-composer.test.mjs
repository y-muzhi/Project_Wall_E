import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiClient,ApiUnknown,ApiRejected,API_REQUEST_TIMEOUT_MS} from '../src/api/client.ts';
import {RequirementGuideComposer} from '../src/guide/composer.ts';
import {documentTarget,reviewTarget,uniqueSelectionRange} from '../src/guide/scope.ts';
const at='2026-10-06T08:00:00.000Z';

test('H04 timed-out send becomes recoverable UNKNOWN and reuses the original action',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const rig=fixture(),sent=[];let late;
 const settle=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
 const client=new ApiClient(async(_url,options)=>{sent.push(options);if(sent.length===1)return new Promise(resolve=>{late=resolve;});return new Response(JSON.stringify({success:true,data:{processing:'MODEL',guide_run_id:7,user_message_id:9},error:null,meta:{request_id:'00000000-0000-4000-8000-00000000000b'}}),{status:202,headers:{'Content-Type':'application/json'}});},()=> '00000000-0000-4000-8000-00000000000a');
 rig.api.prepareCreateGuide=(_id,body)=>{rig.f.body=body;const action=client.prepare('POST','/api/v1/requirements/1/guide-runs',body,{idempotent:true,success_status:202});return {submit:()=>client.commit(action,x=>x)};};
 try{
  rig.owner.change('原始输入');const pending=rig.owner.submit();await settle();assert.equal(rig.owner.getSnapshot().phase,'SUBMITTING');
  t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);assert.equal(await pending,false);assert.equal(rig.owner.getSnapshot().phase,'UNKNOWN');assert.equal(rig.owner.getSnapshot().instruction,'原始输入');assert.equal(sent.length,1);
  assert(await rig.owner.recover());assert.equal(sent.length,2);assert.equal(sent[0].headers['Idempotency-Key'],sent[1].headers['Idempotency-Key']);assert.equal(sent[0].body,sent[1].body);assert.equal(rig.owner.getSnapshot().phase,'READY');
  late(new Response('{}'));await settle();assert.equal(rig.owner.getSnapshot().phase,'READY');assert.equal(rig.f.receives,1);
 }finally{rig.owner.dispose();}
});
const run=(id=6,status='COMPLETED',action_type='ASK')=>({id,requirement_id:1,status,current_step:status==='RUNNING'?'PREPARING':'FINISHED',action_type,created_at:at,final_result:status==='COMPLETED'?{summary:'真实端口检查'}:null,scope:{scope_type:'DOCUMENT',scope_ref:null}});
const detail=(status='PLANNING',waiting=null,version=3)=>({requirement:{id:1,status,discussion_version:5,document_work_state:waiting?'GUIDE_ACTIVE':'IDLE',active_operation_type:waiting?'GUIDE_RUN':null,active_operation_id:waiting?.id??null},current:{id:2,requirement_id:1,document_type:'CURRENT',archived_at:null,name:'当前稿',content_version:version,block_state_json:{blocks:[{block_id:10,block_type:'heading'},{block_id:11,block_type:'paragraph'}]}},documents:[{id:2,name:'当前稿',content_version:version,current_revision_id:7,archived_at:null}],activity:waiting?{kind:'GUIDE',run:waiting}:{kind:'IDLE'}});
function fixture(initial=detail()){
 const f={detail:initial,prepares:0,sends:0,reads:0,messages:0,queries:0,receives:0,adopts:0,messageRefresh:0,drop:false,readDrop:false,adoptDrop:false,messageDrop:false,reject:null,kind:null,body:null,sequence:[]};
 const prepare=(kind,body)=>{f.prepares++;f.kind=kind;f.body=structuredClone(body);return {submit:async()=>{f.sends++;f.sequence.push('send');if(f.reject)throw f.reject;const data={processing:'MODEL',guide_run_id:7,user_message_id:9};if(f.drop){f.drop=false;throw new ApiUnknown(true);}return {data};}};};
 const api={prepareCreateGuide:(_id,body)=>prepare('CREATE',body),prepareContinueGuide:(id,instruction,discussionVersion)=>prepare('CONTINUE',{id,instruction,expected_discussion_version:discussionVersion}),getGuideRun:async id=>{f.queries++;return {data:{...run(id,'RUNNING'),operation:f.body.operation??'DISCUSS',parent_guide_run_id:f.kind==='CONTINUE'?f.body.id:null}};},listMessages:async()=>{f.messages++;f.sequence.push('messages');return {data:{items:[]}};}};
 const read=async()=>{f.reads++;f.sequence.push('detail');if(f.readDrop)throw Error('Actual read unavailable');return f.detail;},adopt=async()=>{f.adopts++;if(f.adoptDrop)throw Error('Actual adoption unavailable');},receive=async()=>{f.receives++;},messages=async()=>{f.messageRefresh++;if(f.messageDrop)throw Error('Actual message refresh unavailable');};
 const owner=new RequirementGuideComposer(initial,api,read,adopt,receive,messages);owner.setAvailable(true);owner.select(documentTarget(initial.current));return {f,api,read,adopt,receive,messages,owner};
}
test('Unicode exact anchor alternatives include overlap and literal empty contexts, never trim or widen a selection',()=>{
 assert.deepEqual(uniqueSelectionRange('甲😀乙',{selected_text:'😀',prefix_text:'甲',suffix_text:'乙'}),{start:1,end:3});assert.equal(uniqueSelectionRange('aaa',{selected_text:'aa',prefix_text:'',suffix_text:''}),null);assert.equal(uniqueSelectionRange(' a ',{selected_text:' a ',prefix_text:'',suffix_text:''})?.end,3);assert.equal(uniqueSelectionRange('甲😀乙',{selected_text:'😀',prefix_text:'乙',suffix_text:''}),null);
});
test('actual editor selection event retains private snapshot/offset fields while matching only the three public anchor fragments',()=>{
 const event={document_id:2,content_version:3,block_id:26,start_offset:1,end_offset:2,selected_text:'😀',prefix_text:'甲',suffix_text:'乙'};assert.deepEqual(uniqueSelectionRange('甲😀乙',event),{start:1,end:3});assert.deepEqual(event,{document_id:2,content_version:3,block_id:26,start_offset:1,end_offset:2,selected_text:'😀',prefix_text:'甲',suffix_text:'乙'});
});
test('a REVIEW section whose original heading changed type is rejected instead of widening to a different preceding section',()=>{
 let parsed=0;const editor={loadedDocument:detail().current,action:()=>{parsed++;throw Error('Should not resolve another ancestor');}};assert.throws(()=>reviewTarget(editor,{scope_type:'SECTION',scope_ref:{block_id:11}}),/章节标题已失效/);assert.equal(parsed,0);
});
test('five manual statuses preserve explicit sending choices and stale versions require a new target selection',async()=>{
 const {f,owner}=fixture();owner.change('  补充😀\r\n正文　');assert(owner.allowed);assert(await owner.submit());assert.equal(f.body.operation,'DISCUSS');assert.equal(f.body.expected_discussion_version,5);assert.equal(f.body.instruction,'  补充😀\r\n正文　');
 owner.choose('REVISE');owner.adopt(detail('CLOSED',null,4));owner.change('明确修改');assert(!owner.allowed);f.detail=detail('CLOSED',null,4);assert(owner.select(documentTarget(f.detail.current)));assert(owner.allowed);owner.dispose();
});
test('10000 Unicode codepoints and newlines are accepted, 10001/empty/invalid surrogate retain raw input without any request',async()=>{
 const {f,owner}=fixture();owner.change('😀'.repeat(10001));assert(!await owner.submit());assert.equal(f.prepares,0);assert.equal([...owner.getSnapshot().instruction].length,10001);owner.change('😀'.repeat(10000));assert(await owner.submit());assert.equal([...f.body.instruction].length,10000);owner.change(' \n ');assert(!await owner.submit());owner.change('\ud800');assert(!await owner.submit());assert.equal(f.prepares,1);owner.dispose();
});
test('unknown creation cannot replace input/action/scope/version or infer its own new Run from matching resource reads',async()=>{
 const {f,owner}=fixture();owner.change(' 保留原始😀 ');f.drop=true;assert(!await owner.submit());const original=owner.getSnapshot().submitted;owner.change('other');owner.choose('REVISE');owner.adopt(detail('PLANNING',null,4));assert(!owner.select(documentTarget(detail('PLANNING',null,4).current)));assert(!await owner.submit());f.readDrop=true;assert(!await owner.recover());assert.equal(f.sends,1);f.readDrop=false;f.sequence=[];assert(await owner.recover());assert.equal(f.prepares,1);assert.equal(f.sends,2);assert.equal(f.body.expected_discussion_version,5);assert.equal(f.body.instruction,' 保留原始😀 ');assert.equal(original.raw,' 保留原始😀 ');assert.deepEqual(f.sequence.slice(0,3),['detail','messages','send']);assert.equal(f.receives,1);owner.dispose();
});
test('continuing an ended parent creates a new DISCUSS round and freezes only its original instruction and discussion version',async()=>{
 const {f,owner}=fixture();owner.continueFrom(run(6,'COMPLETED'));owner.change(' 普通文本😀\r\n补充 ');f.drop=true;assert(!await owner.submit());assert.equal(f.kind,'CONTINUE');assert.deepEqual(f.body,{id:6,instruction:' 普通文本😀\r\n补充 ',expected_discussion_version:5});
 owner.adopt(detail('CLOSED',null,4));assert(await owner.recover());assert.equal(f.body.id,6);assert.equal(f.prepares,1);assert.equal(f.sends,2);assert.equal(owner.getSnapshot().instruction,'');owner.dispose();
});
test('confirmed receipt and failed actual messages keep raw input protected, finish retries reads only and delivery remains once',async()=>{
 const {f,owner}=fixture();owner.change(' 原始输入 ');f.messageDrop=true;assert(!await owner.submit());assert.equal(owner.getSnapshot().phase,'CONFIRMED');assert.equal(owner.getSnapshot().instruction,' 原始输入 ');owner.setAvailable(false);assert(!await owner.finish());owner.setAvailable(true);f.messageDrop=false;assert(await owner.finish());assert.equal(f.sends,1);assert.equal(f.receives,1);assert.equal(f.messageRefresh,2);assert.equal(owner.getSnapshot().instruction,'');owner.dispose();
});
test('known version/source/scope refusal retains raw input, requires actual read, explicit new scope and a fresh action',async()=>{
 const {f,owner}=fixture();owner.change('原输入');f.reject=new ApiRejected('CONTENT_VERSION_CONFLICT','版本冲突',null,'r',409);assert(!await owner.submit());assert(owner.getSnapshot().needs_refresh);assert(!owner.allowed);f.detail=detail('PLANNING',null,4);assert(await owner.refresh());assert.equal(owner.getSnapshot().instruction,'原输入');owner.choose('REVISE');assert(!owner.allowed);owner.select(documentTarget(f.detail.current));f.reject=null;assert(await owner.submit());assert.equal(f.prepares,2);assert.equal(f.body.target.expected_content_version,4);owner.dispose();
});
test('completed owned REVIEW becomes MODIFY source only; invalid ownership/status or target never falls back to plain instruction',async()=>{
 const {f,owner}=fixture();assert(!owner.useReview(run(5,'WAITING_USER','REVIEW'),documentTarget(f.detail.current)));assert(owner.useReview(run(5,'COMPLETED','REVIEW'),documentTarget(f.detail.current)));owner.change('按此检查修改');assert(await owner.submit());assert.equal(f.body.operation,'REVISE');assert.deepEqual(f.body.source_refs,[{kind:'RUN_RESULT',guide_run_id:5}]);owner.dispose();
});
test('REQUEST_IN_PROGRESS retains original action; response ownership mismatch never announces acceptance',async()=>{
 const {f,owner}=fixture();owner.change('原始文字');f.reject=new ApiRejected('REQUEST_IN_PROGRESS','处理中',null,'r',409);assert(!await owner.submit());assert.equal(owner.getSnapshot().phase,'UNKNOWN');f.reject=null;assert(await owner.recover());assert.equal(f.prepares,1);owner.dispose();
 const other=fixture(),bad={...other.api,prepareCreateGuide:()=>({submit:async()=>({data:{guide_run:{id:8,requirement_id:9,status:'RUNNING',current_step:'PREPARING'},user_message:{}}})})},faulty=new RequirementGuideComposer(other.f.detail,bad,other.read,other.adopt,other.receive,other.messages);faulty.setAvailable(true);faulty.change('原文');assert(!await faulty.submit());assert.equal(faulty.getSnapshot().phase,'UNKNOWN');assert.equal(other.f.receives,0);faulty.dispose();other.owner.dispose();
});
test('queued duplicate send coalesces, retiring before queue runs sends nothing and hide/reopen rejects late observation',async()=>{
 const {f,owner}=fixture();owner.change('原文');const pending=owner.submit();assert.equal(owner.submit(),pending);owner.dispose();assert(!await pending);assert.equal(f.prepares,0);
 const other=fixture();let release,hold=false;const read=async()=>hold?new Promise(resolve=>release=resolve):other.f.detail,kept=new RequirementGuideComposer(other.f.detail,other.api,read,other.adopt,other.receive,other.messages);kept.setAvailable(true);kept.change('保留');other.f.drop=true;await kept.submit();hold=true;const recovering=kept.recover();for(let i=0;i<10;i++)await Promise.resolve();kept.setAvailable(false);kept.setAvailable(true);release(other.f.detail);assert(!await recovering);assert.equal(other.f.sends,1);assert.equal(other.f.messages,0);assert.equal(kept.getSnapshot().phase,'UNKNOWN');kept.dispose();other.owner.dispose();
});
