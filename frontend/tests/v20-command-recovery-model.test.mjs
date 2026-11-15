import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiClient} from '../src/api/client.ts';
import {prepareCodeCommand,commandSha256} from '../src/api/code-command-snapshot.ts';
import {registeredCommand} from '../src/api/code-command-registry.ts';
import {pendingSummary, verifiedSummary, pendingSize, receiptLocal, persistedReceipt,
 verifiedFrozen, COMMAND_METADATA_BYTES} from '../src/code-tasks/command-recovery-model.ts';
import {CommandRecoveryStore,CommandStorageError} from '../src/code-tasks/command-recovery-store.ts';
const ORIGIN='http://localhost:5173',KEY='00000000-0000-4000-8000-000000000001';
const PATH='/api/v1/code-tasks/7/start';
async function record(){
 const original=registeredCommand('POST',PATH,KEY);
 const action=await prepareCodeCommand(new ApiClient(()=>assert.fail('offline'),()=>KEY),PATH,{},
  {decoder_kind:original.decoder_kind,success_status:[202],errors:[],validate_input:()=>{},decode:v=>v},ORIGIN);
 return {...action.frozen,schema_version:4,recovery_mode:'REPLAY_SAME_KEY',intent_key:'POST '+PATH,
 close_state:'NONE',close_requested_at:null,status:'PREPARED',task_id:null,testing_task_id:null,
 operation_id:null,created_at:'2026-11-05T01:00:00.000Z',updated_at:'2026-11-05T01:00:00.000Z',
 submitted_at:null,dispatch_count:0,dispatch_owner_id:null,record_revision:1,lookup_status:null};
}
test('list metadata omits body and validates original route/owner/observation',async()=>{
 const value=await record();const summary=await verifiedSummary(value,ORIGIN);
 assert.equal(summary.task_id,null);assert.equal(summary.owner_module,'CODING');
 assert.ok(Object.isFrozen(summary));assert.equal(Object.hasOwn(summary,'body_json'),false);
 for(const [field,change] of [['schema_version',3],['owner_module','TESTING'],['intent_key','POST /api/v1/test-plans'],
 ['dispatch_count',1],['record_revision',0],['close_state','REQUESTED'],['status','ACCEPTED'],
 ['task_id',8],['testing_task_id',7],['operation_id',true],['lookup_status','MISSING'],
 ['created_at','2026-02-31T01:00:00.000Z'],['decoder_kind','evil']])
  assert.throws(()=>pendingSummary({...value,[field]:change},ORIGIN),TypeError,field);
 await assert.rejects(verifiedSummary({...value,identity_sha256:'a'.repeat(64)},ORIGIN),TypeError);
 assert.throws(()=>pendingSummary({...value,extra:1},ORIGIN),TypeError);
});
test('body damage preserves safe metadata for query/close, not replay or capacity admission',async()=>{
 const value=await record();
 assert.equal((await verifiedSummary({...value,body_json:null,body_sha256:'bad'},ORIGIN)).key,KEY);
 const fields=['origin','owner_module','method','path','key','identity_sha256','decoder_kind','body_json','body_sha256'];
 const original=Object.fromEntries(fields.map(field=>[field,value[field]]));
 await assert.rejects(verifiedFrozen({...original,body_json:'{"unknown":1}'},ORIGIN),TypeError);
 assert.throws(()=>pendingSize({...value,body_json:null}),TypeError);
 assert.throws(()=>pendingSize({...value,recovery_mode:'x'.repeat(COMMAND_METADATA_BYTES)}),TypeError);
 const verified=await verifiedFrozen(original,ORIGIN);
 assert.equal(verified.recovery_mode,'REPLAY_SAME_KEY');
 assert.equal(verified.frozen.body_sha256,await commandSha256('{}'));
});
test('terminal projection has no body/decoder code and closed/unsent facts stay distinct',async()=>{
 const row=await record();
 const persisted={schema_version:4,owner_module:row.owner_module,origin:row.origin,key:row.key,
 method:row.method,path:row.path,identity_sha256:row.identity_sha256,body_sha256:null,
 final_state:'CLOSED_UNEXECUTED',task_id:null,testing_task_id:null,operation_id:null,http_status:409,
 result_code:'COMMAND_CLOSED',resolved_at:row.updated_at};
 const terminal=receiptLocal(persisted,ORIGIN);
 assert.equal(Object.hasOwn(persistedReceipt(terminal),'decoder_kind'),false);
 assert.deepEqual(persistedReceipt(terminal),persisted);
 for(const change of [{http_status:200},{result_code:null},{body_json:'{}'},{owner_module:'TESTING'},
 {final_state:'CONFIRMED'},{final_state:'CANCELLED_UNSENT'}])
  assert.throws(()=>receiptLocal({...persisted,...change},ORIGIN),TypeError);
 const cancelled={...persisted,body_sha256:row.body_sha256,final_state:'CANCELLED_UNSENT',
 http_status:null,result_code:null};
 assert.equal(receiptLocal(cancelled,ORIGIN).final_state,'CANCELLED_UNSENT');
 assert.throws(()=>receiptLocal({...cancelled,operation_id:1},ORIGIN),TypeError);
});
test('unavailable/closed store never sends or fabricates records; old doc database is untouched',async()=>{
 let opens=0;const store=new CommandRecoveryStore({origin:ORIGIN,factory:()=>{opens++;throw Error('storage unavailable');}});
 await assert.rejects(store.list(),error=>error instanceof CommandStorageError&&error.reason==='UNAVAILABLE');
 assert.equal(opens,1);store.close();await store.settle();
 await assert.rejects(store.detail(KEY),CommandStorageError);assert.equal(opens,1);
 assert.throws(()=>new CommandRecoveryStore({origin:'null'}),TypeError);
});
