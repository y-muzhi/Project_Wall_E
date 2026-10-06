import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
import {guideRun} from '../src/api/models.ts';
import {RequirementRunActions} from '../src/guide/run-actions.ts';
const at='2026-10-06T06:00:00.000Z';
function run(id=3,status='FAILED',step=status==='RUNNING'?'PREPARING':status==='WAITING_USER'?'WAITING_USER':'FINISHED'){
 return guideRun({id,requirement_id:1,action_type:'ASK',function_type:'ANSWER_REQUIREMENT',source_type:'USER_INSTRUCTION',source_id:null,scope:{scope_type:'DOCUMENT',scope_ref:null},status,current_step:step,final_result:null,suggestion_batch_id:null,latest_assistant_message_id:null,error_code:status==='FAILED'?'CONFIG_INVALID':null,error_message:status==='FAILED'?'配置缺失':null,cancel_reason:status==='CANCELLED'?'USER_REQUESTED':null,retry_of_guide_run_id:null,created_at:at,started_at:at,waiting_user_at:status==='WAITING_USER'?at:null,ended_at:['FAILED','CANCELLED'].includes(status)?at:null,updated_at:at});
}
function detail(actual=run(),status='ACTIVE'){
 const active=['RUNNING','WAITING_USER'].includes(actual.status);return {requirement:{id:1,status,document_work_state:active?'GUIDE_ACTIVE':'IDLE',active_operation_type:active?'GUIDE_RUN':null,active_operation_id:active?actual.id:null},current:{id:2,requirement_id:1,document_type:'CURRENT',content_version:1},activity:active?{kind:'GUIDE',run:actual}:{kind:'IDLE'},comment_index:{}};
}
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function fixture(initial=run()){
 const f={actual:initial,selected:initial,detail:detail(initial),prepares:0,sends:0,reads:0,queries:0,messages:0,adopts:0,receives:0,drop:false,readDrop:false,adoptDrop:false,receiveDrop:false,rejection:null,sequence:[]};
 const prepared=kind=>{f.prepares++;const original=f.selected;return {submit:async()=>{f.sends++;f.sequence.push('send');if(f.rejection)throw f.rejection;const receipt=kind==='CANCEL'?{id:original.id,requirement_id:1,status:'CANCELLED',current_step:'FINISHED'}:{...run(4,'RUNNING'),retry_of_guide_run_id:original.id};f.actual=kind==='CANCEL'?run(original.id,'CANCELLED'):run(4);f.detail=detail(f.actual);if(f.drop){f.drop=false;throw new ApiUnknown(true);}return {data:receipt};}};};
 const api={prepareCancelGuide:()=>prepared('CANCEL'),prepareRetryGuide:()=>prepared('RETRY'),getGuideRun:async identity=>{f.queries++;f.sequence.push('run');return {data:identity===3&&f.actual.id!==3?initial:f.actual};},listMessages:async()=>{f.messages++;f.sequence.push('messages');return {data:{items:[]}};}};
 const read=async()=>{f.reads++;f.sequence.push('detail');if(f.readDrop)throw Error('Parent read failed');return f.detail;};
 const adopt=async()=>{f.adopts++;if(f.adoptDrop)throw Error('Actual adoption failed');};
 const receive=async()=>{f.receives++;if(f.receiveDrop)throw Error('Actual receiver unavailable');};
 const owner=new RequirementRunActions(f.detail,api,read,adopt,receive);owner.adopt(f.detail,initial);owner.setAvailable(true);return {f,api,read,adopt,receive,owner};
}
test('actual lifecycle/action/occupancy and PERSISTING gate cancellation/retry independently of history selection',()=>{
 const {owner}=fixture();assert(owner.allowed('RETRY'));assert(!owner.allowed('CANCEL'));owner.adopt(detail(run(),'INITIALIZING'),run());assert(!owner.allowed('RETRY'));owner.adopt(detail(run(),'COMPLETED'),run());assert(owner.allowed('RETRY'));
 for(const status of ['RUNNING','WAITING_USER']){const actual=run(3,status);owner.adopt(detail(actual),actual);assert(owner.allowed('CANCEL'));assert(!owner.allowed('RETRY'));}
 const submitting=run(3,'RUNNING','PERSISTING');owner.adopt(detail(submitting),submitting);assert(!owner.allowed('CANCEL'));
 owner.adopt(detail(run(5,'RUNNING')),run(3,'RUNNING'));assert(!owner.allowed('CANCEL'));owner.setAvailable(false);assert(!owner.allowed('CANCEL'));owner.dispose();
});
test('retry acceptance creates independent identity, original FAILED is immutable, receipt only delivered before actual adoption',async()=>{
 const {f,owner}=fixture();const origin=owner.getSnapshot().run;assert(await owner.start('RETRY'));assert.equal(f.prepares,1);assert.equal(f.sends,1);assert.equal(f.receives,1);assert.equal(f.adopts,1);assert.equal(origin.status,'FAILED');assert.equal(origin.id,3);assert.equal(owner.getSnapshot().phase,'READY');owner.dispose();
});
test('lost retry receipt retains original action across new history selection and reads actual resources before original replay',async()=>{
 const {f,owner}=fixture();f.drop=true;assert(!await owner.start('RETRY'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');owner.adopt(detail(run(9)),run(9));assert(!await owner.start('RETRY'));f.readDrop=true;assert(!await owner.recover());assert.equal(f.sends,1);f.readDrop=false;f.sequence=[];
 assert(await owner.recover());assert.equal(f.prepares,1);assert.equal(f.sends,2);assert.equal(owner.getSnapshot().phase,'READY');assert.deepEqual(f.sequence.slice(0,4),['detail','run','messages','send']);assert.equal(f.receives,1);owner.dispose();
});
test('lost cancellation receipt observes real CANCELLED without using that GET as proof of own completion',async()=>{
 const {f,owner}=fixture(run(3,'WAITING_USER'));f.drop=true;assert(!await owner.start('CANCEL'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(f.receives,0);assert.equal(owner.getSnapshot().run.status,'WAITING_USER');assert(await owner.recover());assert.equal(f.sends,2);assert.equal(f.prepares,1);assert.equal(f.receives,1);assert.equal(f.actual.status,'CANCELLED');owner.dispose();
});
test('confirmed receipt plus failed actual adoption retries reads only; acknowledged receiver does not repeat',async()=>{
 const {f,owner}=fixture();f.adoptDrop=true;assert(!await owner.start('RETRY'));const outcome=owner.getSnapshot().outcome;assert.equal(outcome.id,4);assert.equal(owner.getSnapshot().phase,'CONFIRMED');owner.setAvailable(false);assert(!await owner.finish());owner.setAvailable(true);f.adoptDrop=false;assert(await owner.finish());assert.equal(f.prepares,1);assert.equal(f.sends,1);assert.equal(f.receives,1);assert.equal(f.adopts,2);owner.dispose();
});
test('unacknowledged receiver is retried with same receipt; REQUEST_IN_PROGRESS retains original action, safe rejection retains FAILED',async()=>{
 const {f,owner}=fixture();f.receiveDrop=true;assert(!await owner.start('RETRY'));assert.equal(owner.getSnapshot().phase,'CONFIRMED');f.receiveDrop=false;assert(await owner.finish());assert.equal(f.receives,2);assert.equal(f.sends,1);owner.dispose();
 const second=fixture();second.f.rejection=new ApiRejected('REQUEST_IN_PROGRESS','处理中',null,'r',409);assert(!await second.owner.start('RETRY'));assert.equal(second.owner.getSnapshot().phase,'UNKNOWN');second.f.rejection=null;assert(await second.owner.recover());assert.equal(second.f.prepares,1);second.owner.dispose();
 const third=fixture();third.f.rejection=new ApiRejected('SOURCE_INVALID','来源已失效',null,'r',422);assert(!await third.owner.start('RETRY'));assert.equal(third.owner.getSnapshot().phase,'ERROR');assert.equal(third.owner.getSnapshot().run.status,'FAILED');assert(await third.owner.refresh());assert.equal(third.f.sends,1);third.owner.dispose();
});
test('same queued action coalesces, retirement before microtask sends nothing, hidden recovery never sends or clears intention',async()=>{
 const {f,owner}=fixture();const first=owner.start('RETRY');assert.equal(owner.start('RETRY'),first);owner.dispose();assert(!await first);assert.equal(f.prepares,0);assert.equal(f.sends,0);
 const other=fixture();other.f.drop=true;await other.owner.start('RETRY');other.owner.setAvailable(false);assert(!await other.owner.recover());assert.equal(other.f.sends,1);assert.equal(other.owner.getSnapshot().phase,'UNKNOWN');other.owner.setAvailable(true);assert(await other.owner.recover());other.owner.dispose();
});
test('hide/reopen during unknown observation rejects late actual result and preserves original request',async()=>{
 const {f,api,adopt,receive}=fixture();let release;let held=false;const read=async()=>{if(held)return new Promise(resolve=>release=resolve);return f.detail;};const owner=new RequirementRunActions(f.detail,api,read,adopt,receive);owner.adopt(f.detail,run());owner.setAvailable(true);f.drop=true;await owner.start('RETRY');held=true;const recovering=owner.recover();await flush();owner.setAvailable(false);owner.setAvailable(true);release(f.detail);assert(!await recovering);assert.equal(f.sends,1);assert.equal(f.queries,0);assert.equal(owner.getSnapshot().phase,'UNKNOWN');owner.dispose();
});
test('cancel loses the persistence race, shows the actual submitting phase after read and never forces a second cancel',async()=>{
 const {f,owner}=fixture(run(3,'RUNNING'));f.rejection=new ApiRejected('STATE_CONFLICT','当前结果正在提交',null,'r',409);assert(!await owner.start('CANCEL'));assert.equal(owner.getSnapshot().run.current_step,'PREPARING');f.actual=run(3,'RUNNING','PERSISTING');f.detail=detail(f.actual);assert(await owner.refresh());assert.equal(owner.getSnapshot().run.current_step,'PERSISTING');assert(!owner.allowed('CANCEL'));assert(!await owner.start('CANCEL'));assert.equal(f.sends,1);assert.equal(f.receives,0);owner.dispose();
});
test('unconfirmed foreign receipts/Run origins retain UNKNOWN and do not deliver or replay after a corrupt observation',async()=>{
 const f=fixture(),api={...f.api,prepareRetryGuide:()=>({submit:async()=>({data:{...run(4,'RUNNING'),requirement_id:99,retry_of_guide_run_id:3}})}),getGuideRun:async()=>({data:{...run(),source_type:'REVIEW_RESULT',source_id:20}})};
 const owner=new RequirementRunActions(f.f.detail,api,f.read,f.adopt,f.receive);owner.adopt(f.f.detail,run());owner.setAvailable(true);assert(!await owner.start('RETRY'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert(!await owner.recover());assert.equal(f.f.receives,0);assert.equal(owner.getSnapshot().phase,'UNKNOWN');owner.dispose();f.owner.dispose();
});
