import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementAiRead} from '../src/guide/read-owner.ts';
import {guideRun} from '../src/api/models.ts';
const at='2026-10-06T04:00:00.000Z',detail={requirement:{id:1},current:{id:2,requirement_id:1,document_type:'CURRENT'},activity:{kind:'IDLE'}};
function run(id=3,status='FAILED'){return guideRun({id,requirement_id:1,action_type:'ASK',function_type:'ANSWER_REQUIREMENT',source_type:'USER_INSTRUCTION',source_id:null,scope:{scope_type:'DOCUMENT',scope_ref:null},status,current_step:status==='RUNNING'?'PREPARING':'FINISHED',final_result:null,suggestion_batch_id:null,latest_assistant_message_id:null,error_code:status==='FAILED'?'CONFIG_INVALID':null,error_message:status==='FAILED'?'配置缺失':null,cancel_reason:null,retry_of_guide_run_id:null,created_at:at,started_at:at,waiting_user_at:null,ended_at:status==='FAILED'?at:null,updated_at:at});}
const flush=async()=>{for(let i=0;i<120;i++)await Promise.resolve();};
function fixture(){const facts={run:run(),queries:0,parents:0,adopts:0,opens:0,drop:false,queryDrop:false};const timing={schedule:()=>()=>{}};
 const api={getGuideRun:async()=>{facts.queries++;if(facts.queryDrop)throw Error('Network');return {data:facts.run};},listMessages:async()=>{if(facts.drop)throw Error('Messages');return {data:{items:[]},meta:{pagination:{page_size:20,has_more:false,next_cursor:null}}};},listGuideRuns:async()=>({data:{items:[(({final_result,...row})=>row)(facts.run)]},meta:{pagination:{page:1,page_size:20,total:1,total_pages:1}}})};
 const read=async()=>{facts.parents++;return detail;},adopt=async()=>{facts.adopts++;},open=()=>{facts.opens++;};return {facts,api,timing,read,adopt,open};}
test('acceptance receiver selects actual identity only, idempotently keeps one polling owner, and native FAILED remains a successful query',async()=>{
 const f=fixture(),owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);assert.equal(owner.getSnapshot().run,null);await owner.receive({id:3,requirement_id:1,status:'RUNNING',current_step:'PREPARING'});await flush();assert.equal(owner.getSnapshot().run.status,'FAILED');assert(!owner.getSnapshot().connection_error);assert.equal(f.facts.queries,1);
 await owner.receive({id:3,requirement_id:1});await flush();assert.equal(f.facts.queries,1);assert.equal(owner.getSnapshot().selected,3);assert.equal(f.facts.opens,2);await assert.rejects(owner.receive({id:8,requirement_id:99}),/another/);owner.dispose();
});
test('owned I16 connection failure preserves last successful RUNNING rather than inventing FAILED; explicit read restores',async()=>{
 const f=fixture();f.facts.run=run(3,'RUNNING');const owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);await owner.receive({id:3,requirement_id:1});await flush();f.facts.queryDrop=true;owner.readRun();await flush();assert.equal(owner.getSnapshot().run.status,'RUNNING');assert(owner.getSnapshot().connection_error);f.facts.queryDrop=false;f.facts.run=run();owner.readRun();await flush();assert.equal(owner.getSnapshot().run.status,'FAILED');assert(!owner.getSnapshot().connection_error);owner.dispose();
});
test('failed resource refresh keeps actual run/acknowledged owner; same receipt retry does not create a second poll',async()=>{
 const f=fixture();f.facts.drop=true;const owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);await owner.receive({id:3,requirement_id:1});await flush();assert.equal(owner.getSnapshot().run.status,'FAILED');assert(owner.getSnapshot().error);f.facts.drop=false;await owner.receive({id:3,requirement_id:1});await owner.refresh();assert.equal(f.facts.queries,1);assert.equal(owner.getSnapshot().error,null);owner.dispose();
});
test('hide/reopen during old parent read ignores that adoption and performs a fresh read without clearing conversation',async()=>{
 const f=fixture();let resolve;const hold=new Promise(yes=>resolve=yes);let first=true;const owner=new RequirementAiRead(detail,f.api,async()=>{f.facts.parents++;if(first){first=false;return hold;}return detail;},f.adopt,f.open,f.timing);owner.setVisible(true);await flush();owner.setVisible(false);owner.setVisible(true);resolve(detail);await flush();assert.equal(f.facts.parents,2);assert.equal(f.facts.adopts,1);assert.deepEqual(owner.messages.getSnapshot().items,[]);assert(owner.getSnapshot().visible);owner.dispose();
});
test('actual history selection reads I16 and retirement before queued reconciliation/poll suppresses every GET',async()=>{
 const f=fixture(),owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);owner.setVisible(true);await flush();owner.open({...run(),id:3});await flush();assert.equal(owner.getSnapshot().selection,'HISTORY');assert.equal(f.facts.queries,1);owner.dispose();
 const retired=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing),before={...f.facts},accepting=retired.receive({id:3,requirement_id:1}),rejected=assert.rejects(accepting,/retired/);retired.dispose();await rejected;await flush();assert.equal(f.facts.queries,before.queries);assert.equal(f.facts.parents,before.parents);await assert.rejects(retired.receive({id:3,requirement_id:1}),/retired/);
});
test('receiving a continuation for the same WAITING run starts an actual fresh read without replacing its polling lifetime',async()=>{
 const f=fixture();f.facts.run=guideRun({...run(3,'RUNNING'),status:'WAITING_USER',current_step:'WAITING_USER',waiting_user_at:at});const owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);await owner.receive({id:3,requirement_id:1});await flush();assert.equal(owner.getSnapshot().run.status,'WAITING_USER');assert(!owner.getSnapshot().polling);
 f.facts.run=run(3,'RUNNING');await owner.receive({id:3,requirement_id:1});await flush();assert.equal(f.facts.queries,2);assert.equal(owner.getSnapshot().selected,3);assert.equal(owner.getSnapshot().run.status,'RUNNING');assert(owner.getSnapshot().polling);owner.dispose();
});
test('fresh actual activity replaces an accepted old selection, while an explicitly viewed historical run remains independent',async()=>{
 const f=fixture(),owner=new RequirementAiRead(detail,f.api,f.read,f.adopt,f.open,f.timing);await owner.receive({id:3,requirement_id:1});await flush();const active=run(4,'RUNNING');f.facts.run=active;owner.adopt({...detail,activity:{kind:'GUIDE',run:active}});await flush();assert.equal(owner.getSnapshot().selected,4);assert.equal(owner.getSnapshot().selection,'ACTIVITY');assert.equal(owner.getSnapshot().run.id,4);
 owner.open(run());owner.adopt({...detail,activity:{kind:'GUIDE',run:active}});assert.equal(owner.getSnapshot().selected,3);assert.equal(owner.getSnapshot().selection,'HISTORY');owner.dispose();
});

test('a reopened panel caller awaits its current read instead of inheriting the retired visibility failure',async()=>{
 const f=fixture();let resolve;const hold=new Promise(yes=>resolve=yes);let first=true;
 const owner=new RequirementAiRead(detail,f.api,async()=>{f.facts.parents++;if(first){first=false;return hold;}return detail;},f.adopt,f.open,f.timing);
 owner.setVisible(true);await flush();owner.setVisible(false);owner.setVisible(true);
 const reopened=owner.refresh();resolve(detail);await reopened;await flush();
 assert.equal(f.facts.parents,2);assert.equal(f.facts.adopts,1);assert.equal(owner.getSnapshot().error,null);owner.dispose();
});

test('reopened panel request retired again before its predecessor settles does not adopt or start a hidden read',async()=>{
 const f=fixture();let resolve;const hold=new Promise(yes=>resolve=yes);
 const owner=new RequirementAiRead(detail,f.api,async()=>{f.facts.parents++;return hold;},f.adopt,f.open,f.timing);
 owner.setVisible(true);await flush();owner.setVisible(false);owner.setVisible(true);
 const reopened=owner.refresh(),rejected=assert.rejects(reopened,/hidden|retired/);owner.setVisible(false);resolve(detail);await rejected;await flush();
 assert.equal(f.facts.parents,1);assert.equal(f.facts.adopts,0);owner.dispose();
});

test('current visibility network failure remains a real failure after an obsolete read settles',async()=>{
 const f=fixture();let resolve;const hold=new Promise(yes=>resolve=yes);let first=true;
 const owner=new RequirementAiRead(detail,f.api,async()=>{f.facts.parents++;if(first){first=false;return hold;}throw Error('Current connection failure');},f.adopt,f.open,f.timing);
 owner.setVisible(true);await flush();owner.setVisible(false);owner.setVisible(true);
 const reopened=owner.refresh(),rejected=assert.rejects(reopened,/Current connection failure/);resolve(detail);await rejected;await flush();
 assert.equal(f.facts.parents,2);assert.equal(f.facts.adopts,0);assert.equal(owner.getSnapshot().error,'Current connection failure');owner.dispose();
});
