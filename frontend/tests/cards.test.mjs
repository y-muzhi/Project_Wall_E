import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiRejected,ApiUnknown} from '../src/api/client.ts';
import {cards as decodeCards} from '../src/api/models.ts';
import {blankAnswers,checkAnswers,formalAnswerText} from '../src/guide/card-answers.ts';
import {CardDrafts} from '../src/guide/card-drafts.ts';
import {InteractionCards} from '../src/guide/cards.ts';
const at='2026-10-06T04:00:00.000Z';
const option=key=>({option_key:key,label:'选项'+key,description:'说明',impact:'影响',risks:'风险'});
const card=(key,type='SINGLE_SELECT',required=true)=>({card_key:key,card_type:type,question:'问题'+key,context:'原上下文',required,options:[option('a'),option('b')],selection_rule:{min:1,max:type==='MULTI_SELECT'?3:1},custom_answer:{enabled:type!=='CONFIRM',max_length:type==='CONFIRM'?0:2000},recommendation:{option_keys:['a'],reason:'只是推荐'},related_spec_context:[{block_id:10,content_snapshot:'原文😀'}]});
const definition=()=>decodeCards({schema_version:1,intro:'待用户确认',cards:[card('single'),card('multi','MULTI_SELECT'),card('confirm','CONFIRM'),card('optional','SINGLE_SELECT',false)]});
const source=(action_type='INITIALIZE',status=action_type==='INITIALIZE'?'COMPLETED':'WAITING_USER')=>({id:6,requirement_id:1,action_type,status});
const detail=run=>({requirement:{id:1,status:run.action_type==='INITIALIZE'?'INITIALIZING':'ACTIVE',document_work_state:run.status==='WAITING_USER'?'GUIDE_ACTIVE':'IDLE',active_operation_type:run.status==='WAITING_USER'?'GUIDE_RUN':null,active_operation_id:run.status==='WAITING_USER'?run.id:null},current:{id:2,requirement_id:1,document_type:'CURRENT',content_version:3},activity:run.status==='WAITING_USER'?{kind:'GUIDE',run}:{kind:'IDLE'}});
const message=(cards=definition(),state='AVAILABLE')=>({id:8,requirement_id:1,guide_run_id:6,sequence_no:2,role:'ASSISTANT',content:'正式卡片',message_type:'INTERACTION_CARDS',structured_content:cards,reply_to_message_id:null,created_at:at,card_state:state});
function fixture(action='INITIALIZE',stored=null){
 const memory=new Map(stored?[['walle:v1:cards:1:8',stored]]:[]),f={prepares:0,sends:0,reads:0,adopts:0,receives:0,refreshes:0,cursors:[],order:[],drop:false,readDrop:false,messageDrop:false,refreshDrop:false,storageDrop:false,reject:null,wrongCustom:false,body:null};
 const storage={getItem:key=>{if(f.storageDrop)throw Error('storage');return memory.get(key)??null;},setItem:(key,value)=>{if(f.storageDrop)throw Error('storage');memory.set(key,value);},removeItem:key=>{if(f.storageDrop)throw Error('storage');memory.delete(key);}},drafts=new CardDrafts(()=>storage,()=>at);f.source=source(action);f.detail=detail(f.source);f.message=message();f.formal=null;
 const api={prepareCardResponses:(id,body)=>{f.prepares++;assert.equal(id,8);f.body=structuredClone(body);return {submit:async()=>{f.sends++;f.order.push('send');if(f.reject)throw f.reject;const run={id:action==='INITIALIZE'?7:6,requirement_id:1,status:'RUNNING',current_step:'PREPARING'},formal={id:9,requirement_id:1,guide_run_id:run.id,sequence_no:3,role:'USER',content:formalAnswerText(definition(),body),message_type:'CARD_RESPONSE',structured_content:structuredClone(body),reply_to_message_id:8,created_at:at,card_state:null};f.formal=formal;f.message={...f.message,card_state:'ANSWERED'};f.source={...f.source,status:action==='INITIALIZE'?'COMPLETED':'FAILED'};f.detail=detail(f.source);if(f.drop){f.drop=false;throw new ApiUnknown(true);}if(f.wrongCustom)formal.structured_content.responses[0].custom_answer='错误';return {data:{response_message:formal,guide_run:run,card_state:'ANSWERED'}};}};},getGuideRun:async id=>{assert.equal(id,6);f.order.push('run');return {data:f.source};},listMessages:async(_id,cursor)=>{f.cursors.push(cursor);f.order.push('messages');if(f.messageDrop)throw Error('messages');return {data:{items:[f.message,...(f.formal?[f.formal]:[])]},meta:{pagination:{page_size:20,has_more:false,next_cursor:null}}};}};
 const read=async()=>{f.reads++;f.order.push('detail');if(f.readDrop)throw Error('detail');return f.detail;},adopt=async()=>{f.adopts++;},receive=async()=>{f.receives++;},refresh=async()=>{f.refreshes++;if(f.refreshDrop)throw Error('actual refresh');};
 const owner=new InteractionCards(f.message,f.source,f.detail,api,drafts,read,adopt,receive,refresh);owner.setAvailable(true);return {f,owner,api,drafts,memory,storage,read,adopt,receive,refresh};
}
function answer(owner){owner.custom('single','  定义😀\r\n边界  ');owner.toggle('multi','b',true);owner.custom('multi','补充');owner.toggle('confirm','b',true);owner.skip('optional',true);}
test('whole group starts blank, never adopts recommendations, and requires explicit optional skips',()=>{
 const cards=definition(),answers=blankAnswers(cards);assert(answers.responses.every(row=>row.selected_option_keys.length===0&&row.custom_answer===null&&!row.skipped));assert.throws(()=>checkAnswers(cards,answers),error=>error.card_key==='single');
 const {owner}=fixture();answer(owner);owner.skip('optional',false);assert.throws(()=>checkAnswers(cards,owner.getSnapshot().answers),error=>error.card_key==='optional');owner.dispose();
});
test('all cards, option uniqueness, required skip, custom availability and selection count reject the whole group',()=>{
 const {owner}=fixture();answer(owner);const good=owner.getSnapshot().answers,cards=definition();assert.equal(checkAnswers(cards,good).responses[0].custom_answer,'定义😀\n边界');
 for(const transform of [rows=>rows.slice(1),rows=>[...rows.slice(0,3),rows[0]],rows=>rows.map((row,i)=>i===0?{...row,selected_option_keys:['outside']}:row),rows=>rows.map((row,i)=>i===1?{...row,selected_option_keys:['a','a']}:row),rows=>rows.map((row,i)=>i===0?{...row,selected_option_keys:[],custom_answer:null,skipped:true}:row),rows=>rows.map((row,i)=>i===2?{...row,custom_answer:'自定'}:row),rows=>rows.map((row,i)=>i===0?{...row,selected_option_keys:['a'],custom_answer:'两份'}:row)])assert.throws(()=>checkAnswers(cards,{schema_version:1,responses:transform(good.responses)}));
 owner.dispose();
});
test('custom input uses normalized Unicode codepoint limits, preserves invalid raw input and never truncates',async()=>{
 const {owner,f}=fixture();answer(owner);owner.custom('single','😀'.repeat(2001));assert(!await owner.submit());assert.equal(f.prepares,0);assert.equal(owner.getSnapshot().answers.responses[0].custom_answer,'😀'.repeat(2001));assert(owner.getSnapshot().storage_error);
 owner.custom('single','  '+'😀'.repeat(2000)+'  ');assert(await owner.submit());assert.equal([...f.body.responses[0].custom_answer].length,2000);owner.dispose();
 const bad=fixture();answer(bad.owner);bad.owner.custom('single','\ud800');assert(!await bad.owner.submit());assert.equal(bad.f.prepares,0);bad.owner.dispose();
});
test('one real INITIALIZE receipt creates a new Run, formal answers persist even when the model fails',async()=>{
 const {owner,f,memory}=fixture();answer(owner);assert(owner.allowed);assert(await owner.submit());assert.equal(f.prepares,1);assert.equal(f.sends,1);assert.equal(f.receives,1);assert.equal(owner.getSnapshot().phase,'RESOLVED');assert.equal(owner.getSnapshot().formal.guide_run_id,7);assert.equal(owner.getSnapshot().message.card_state,'ANSWERED');assert.equal(memory.size,0);assert(!await owner.submit());owner.dispose();
});
test('WAITING ASK/REVIEW/MODIFY answers resume exactly the same original Run, never a new operation',async()=>{
 for(const type of ['ASK','REVIEW','MODIFY']){const {f,owner}=fixture(type);answer(owner);assert(await owner.submit());assert.equal(owner.getSnapshot().formal.guide_run_id,6);assert.equal(f.prepares,1);owner.dispose();}
});
test('single selection/custom are mutually exclusive, multi combines, skip is explicit and removes previous answers',()=>{
 const {owner}=fixture();owner.custom('single','自定');owner.toggle('single','b',true);assert.equal(owner.getSnapshot().answers.responses[0].custom_answer,null);owner.custom('single','写入');assert.deepEqual(owner.getSnapshot().answers.responses[0].selected_option_keys,[]);owner.toggle('multi','a',true);owner.custom('multi','一起');assert.deepEqual(owner.getSnapshot().answers.responses[1].selected_option_keys,['a']);owner.toggle('optional','a',true);owner.skip('optional',true);assert.deepEqual(owner.getSnapshot().answers.responses[3],{card_key:'optional',selected_option_keys:[],custom_answer:null,skipped:true});owner.skip('single',true);assert(!owner.getSnapshot().answers.responses[0].skipped);owner.dispose();
});
test('sessionStorage is isolated by requirement/message and restores raw AVAILABLE drafts only',()=>{
 const {owner,memory,api,drafts,f,read,adopt,receive,refresh}=fixture();answer(owner);const raw=JSON.parse(memory.get('walle:v1:cards:1:8'));assert.equal(raw.schema_version,1);assert.equal(raw.updated_at,at);assert.equal(raw.responses[0].custom_answer,'  定义😀\r\n边界  ');assert.equal(drafts.load(2,8,definition()).answers,null);
 const restored=new InteractionCards(f.message,f.source,f.detail,api,drafts,read,adopt,receive,refresh);assert.deepEqual(restored.getSnapshot().answers,owner.getSnapshot().answers);restored.dispose();owner.dispose();
 const expired=new InteractionCards({...f.message,card_state:'EXPIRED'},f.source,f.detail,api,drafts,read,adopt,receive,refresh);assert.equal(expired.getSnapshot().answers.responses[0].custom_answer,null);assert.equal(memory.size,0);expired.dispose();
});
test('storage corruption and quota failures remain explicit without blocking real server submission',async()=>{
 const {owner,f,memory}=fixture('INITIALIZE','{"bad":true}');assert(owner.getSnapshot().storage_error);assert.equal(memory.get('walle:v1:cards:1:8'),'{'+'"bad":true}');f.storageDrop=true;answer(owner);assert(owner.getSnapshot().storage_error);assert(await owner.submit());assert.equal(owner.getSnapshot().phase,'RESOLVED');assert(owner.getSnapshot().storage_error);f.storageDrop=false;owner.retryStorage();assert.equal(owner.getSnapshot().storage_error,null);owner.dispose();
});
test('lost acceptance retains one original body/key; matching ANSWERED reads never prove the original request',async()=>{
 const {owner,f,memory}=fixture();answer(owner);f.drop=true;assert(!await owner.submit());assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(memory.size,1);const frozen=owner.getSnapshot().answers;owner.custom('single','换一份');owner.skip('optional',false);assert.deepEqual(owner.getSnapshot().answers,frozen);assert(!await owner.submit());f.readDrop=true;assert(!await owner.recover());assert.equal(f.sends,1);assert.equal(memory.size,1);f.readDrop=false;f.order=[];assert(await owner.recover());assert.deepEqual(f.order.slice(0,4),['detail','run','messages','send']);assert.equal(f.prepares,1);assert.equal(f.sends,2);assert.equal(f.receives,1);assert.equal(memory.size,0);owner.dispose();
});
test('known already-answered conflict reads actual safe response, does not resend or pretend to receive its Run',async()=>{
 const {owner,f}=fixture();answer(owner);f.reject=new ApiRejected('CARD_ALREADY_ANSWERED','其他会话已回答',{response_message_id:9},'r',409);assert(!await owner.submit());assert(owner.getSnapshot().needs_refresh);assert.equal(owner.getSnapshot().answers.responses[0].custom_answer,'  定义😀\r\n边界  ');
 const answers=checkAnswers(definition(),owner.getSnapshot().answers);f.formal={id:9,requirement_id:1,guide_run_id:7,sequence_no:3,role:'USER',content:formalAnswerText(definition(),answers),message_type:'CARD_RESPONSE',structured_content:answers,reply_to_message_id:8,created_at:at,card_state:null};f.message={...f.message,card_state:'ANSWERED'};assert(await owner.refresh());assert.equal(owner.getSnapshot().phase,'RESOLVED');assert.equal(owner.getSnapshot().formal.id,9);assert.equal(f.sends,1);assert.equal(f.receives,0);owner.dispose();
});
test('safe already-answer reference mismatch or actual read failure keeps conflict and original answers',async()=>{
 const {owner,f}=fixture();answer(owner);f.reject=new ApiRejected('CARD_ALREADY_ANSWERED','已有回答',{response_message_id:999},'r',409);assert(!await owner.submit());f.reject=null; // An answer observed elsewhere cannot replace the explicit response reference.
 const answers=checkAnswers(definition(),owner.getSnapshot().answers);f.formal={id:9,requirement_id:1,guide_run_id:7,sequence_no:3,role:'USER',content:formalAnswerText(definition(),answers),message_type:'CARD_RESPONSE',structured_content:answers,reply_to_message_id:8,created_at:at,card_state:null};
 f.message={...f.message,card_state:'ANSWERED'};assert(!await owner.refresh());assert(owner.getSnapshot().needs_refresh);assert.equal(owner.getSnapshot().answers.responses[0].custom_answer,'  定义😀\r\n边界  ');assert.equal(f.sends,1);owner.dispose();
});
test('CARD_EXPIRED requires actual read before read-only state and local draft clearing; later AVAILABLE can start blank',async()=>{
 const {owner,f,memory}=fixture();answer(owner);f.reject=new ApiRejected('CARD_EXPIRED','已失效',null,'r',409);assert(!await owner.submit());assert.equal(memory.size,1);f.message={...f.message,card_state:'EXPIRED'};assert(await owner.refresh());assert.equal(memory.size,0);assert.equal(owner.getSnapshot().phase,'RESOLVED');assert(!owner.editable);owner.adopt({...f.message,card_state:'AVAILABLE'},f.source,f.detail);assert.equal(owner.getSnapshot().phase,'READY');assert.equal(owner.getSnapshot().answers.responses[0].custom_answer,null);owner.dispose();
});
test('confirmed answer plus failed message adoption retries GET only, never submits again or redelivers',async()=>{
 const {owner,f}=fixture();answer(owner);f.refreshDrop=true;assert(!await owner.submit());assert.equal(owner.getSnapshot().phase,'CONFIRMED');assert.equal(owner.getSnapshot().formal.id,9);owner.setAvailable(false);assert(!await owner.finish());owner.setAvailable(true);f.refreshDrop=false;assert(await owner.finish());assert.equal(f.sends,1);assert.equal(f.receives,1);assert.equal(f.refreshes,2);owner.dispose();
});
test('unsubmitted local choices disappear from expired memory; unknown original action still retains its exact answers',async()=>{
 const {owner,f}=fixture();answer(owner);owner.adopt({...f.message,card_state:'EXPIRED'},f.source,f.detail);assert(owner.getSnapshot().answers.responses.every(row=>row.custom_answer===null&&row.selected_option_keys.length===0&&!row.skipped));owner.dispose();
 const other=fixture();answer(other.owner);const before=other.owner.getSnapshot().answers;other.f.drop=true;await other.owner.submit();other.owner.adopt({...other.f.message,card_state:'EXPIRED'},other.f.source,other.f.detail);assert.deepEqual(other.owner.getSnapshot().answers,before);assert.equal(other.owner.getSnapshot().phase,'UNKNOWN');other.owner.dispose();
});
test('formal answer structures must already be normalized, and corrupted history remains readable without invented options',async()=>{
 const {owner,f}=fixture();answer(owner);const normalized=checkAnswers(definition(),owner.getSnapshot().answers);f.message={...f.message,card_state:'ANSWERED'};f.formal={id:9,requirement_id:1,guide_run_id:7,sequence_no:3,role:'USER',content:formalAnswerText(definition(),normalized),message_type:'CARD_RESPONSE',structured_content:{...normalized,responses:normalized.responses.map((row,index)=>index===0?{...row,custom_answer:' '+row.custom_answer+' '}:row)},reply_to_message_id:8,created_at:at,card_state:null};assert(!await owner.refresh());assert.equal(owner.getSnapshot().message.card_state,'AVAILABLE');f.formal={...f.formal,structured_content:null,content:'历史正式回答结构损坏，保留原始可读摘要'};assert(await owner.refresh());assert.equal(owner.getSnapshot().formal.structured_content,null);assert.equal(owner.getSnapshot().phase,'RESOLVED');owner.dispose();
});
test('original card and response may be outside latest20; actual cursor is followed without a fabricated direct GET',async()=>{
 const other=fixture(),{f,api,drafts,read,adopt,receive,refresh}=other;answer(other.owner);const answers=checkAnswers(definition(),other.owner.getSnapshot().answers);f.formal={id:9,requirement_id:1,guide_run_id:7,sequence_no:3,role:'USER',content:formalAnswerText(definition(),answers),message_type:'CARD_RESPONSE',structured_content:answers,reply_to_message_id:8,created_at:at,card_state:null};f.message={...f.message,card_state:'ANSWERED'};
 const cursors=[],pages={...api,listMessages:async(_id,cursor)=>{cursors.push(cursor);return cursor===null?{data:{items:[{id:90,requirement_id:1,sequence_no:40,message_type:'TEXT',reply_to_message_id:null}]},meta:{pagination:{page_size:20,has_more:true,next_cursor:40}}}:{data:{items:[f.message,f.formal]},meta:{pagination:{page_size:20,has_more:false,next_cursor:null}}};}};
 const owner=new InteractionCards({...f.message,card_state:'AVAILABLE'},f.source,f.detail,pages,drafts,read,adopt,receive,refresh);owner.setAvailable(true);assert(await owner.refresh());assert.deepEqual(cursors,[null,40]);assert.equal(owner.getSnapshot().formal.id,9);owner.dispose();other.owner.dispose();
});
test('REQUEST_IN_PROGRESS and changed receipt custom answer remain UNKNOWN; original version is not reconstructed',async()=>{
 const {f,owner}=fixture();answer(owner);f.reject=new ApiRejected('REQUEST_IN_PROGRESS','处理中',null,'r',409);assert(!await owner.submit());assert.equal(owner.getSnapshot().phase,'UNKNOWN');f.reject=null;assert(await owner.recover());assert.equal(f.prepares,1);owner.dispose();
 const bad=fixture();answer(bad.owner);bad.f.wrongCustom=true;assert(!await bad.owner.submit());assert.equal(bad.owner.getSnapshot().phase,'UNKNOWN');assert.equal(bad.f.receives,0);bad.owner.dispose();
});
test('unsupported lifecycles/foreign occupancy block submission; retiring before queued work never sends',async()=>{
 const {f,owner}=fixture('MODIFY');answer(owner);owner.adoptDetail({...f.detail,requirement:{...f.detail.requirement,status:'COMPLETED'}});assert(!owner.allowed);assert(!await owner.submit());assert.equal(f.prepares,0);owner.dispose();
 const other=fixture();answer(other.owner);const pending=other.owner.submit();assert.equal(other.owner.submit(),pending);other.owner.dispose();assert(!await pending);assert.equal(other.f.prepares,0);
});
test('hide/reopen fences old recovery reads, preserves local drafts and never sends a late original request',async()=>{
 const other=fixture();answer(other.owner);other.f.drop=true;await other.owner.submit();let release;const owner=new InteractionCards(message(),source(),detail(source()),other.api,other.drafts,()=>new Promise(resolve=>release=resolve),other.adopt,other.receive,other.refresh);owner.setAvailable(true);answer(owner);other.f.drop=true;await owner.submit(); // positive receipt is dropped before a reconciliation read
 const recovering=owner.recover();for(let i=0;i<10;i++)await Promise.resolve();owner.setAvailable(false);owner.setAvailable(true);release(other.f.detail);assert(!await recovering);assert.equal(other.f.sends,2);assert.equal(owner.getSnapshot().phase,'UNKNOWN');owner.dispose();other.owner.dispose();
});
