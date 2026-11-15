import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiClient, ApiUnknown, ApiRejected, exact, positiveInteger} from '../src/api/client.ts';
import {prepareCodeCommand, restoreCodeCommand, commandSha256, identityText,
  commandRecoveryMode} from '../src/api/code-command-snapshot.ts';
import {prepareCloseOriginalCommand} from '../src/api/code-command-close.ts';
import {registeredCommand} from '../src/api/code-command-registry.ts';
import {ERROR_MESSAGES} from '../src/api/code-errors.ts';
import {WalleApi} from '../src/api/walle.ts';

const ORIGIN='http://localhost:5173';
const KEY='00000000-0000-4000-8000-00000000000a';
const REQUEST='00000000-0000-4000-8000-00000000000b';
const PATH='/api/v1/code-tasks/7/start';
const scope=registeredCommand('POST',PATH,KEY);
// Explicit test-only native binding: transport tests do not register business DTOs.
const binding={
 decoder_kind:scope.decoder_kind, success_status:[202],errors:['INVALID_STATE'],
 validate_input(value) {const row=exact(value,['expected_state_version']);positiveInteger(row.expected_state_version);},
 decode(value, original, input) {
  const row=exact(value,['task_id','operation_id']);
  assert.equal(row.task_id,original.parameters.task_id);
  assert.equal(input.expected_state_version,1);
  return {task_id:positiveInteger(row.task_id),operation_id:positiveInteger(row.operation_id)};
 }
};
const response=(data,status=200)=>new Response(JSON.stringify({
 success:true,data,error:null,meta:{request_id:REQUEST}}),
 {status,headers:{'Content-Type':'application/json'}});
const missing=()=>({lookup_status:'NOT_FOUND',record_status:null,original_http_status:null,
 original_outcome:null,task_id:null,testing_task_id:null,operation_id:null});
const closed=()=>({...missing(),lookup_status:'FOUND',record_status:'CLOSED',original_http_status:409,
 original_outcome:{success:false,data:null,error:{code:'COMMAND_CLOSED',
 message:ERROR_MESSAGES.COMMAND_CLOSED,details:{method:'POST',path:PATH,closed_at:'2026-11-05T01:02:03.000Z'}}}});
async function prepared() {
 return prepareCodeCommand(new ApiClient(()=>assert.fail('prepare sends nothing'),()=>KEY),
 PATH,{expected_state_version:1},binding,ORIGIN);
}
test('export belongs to its client and restore retains actual bytes and key without UUID',async()=>{
 let ids=0;const calls=[];
 const client=new ApiClient(async(path,options)=>{
  calls.push({path,...options});return response({task_id:7,operation_id:9},202);
 },()=>{ids++;return KEY;});
 const body={expected_state_version:1};
 const first=await prepareCodeCommand(client,PATH,body,binding,ORIGIN);
 body.expected_state_version=3;
 assert.equal(ids,1);assert.equal(calls.length,0);
 assert.equal(first.frozen.body_json,'{"expected_state_version":1}');
 assert.ok(Object.isFrozen(first.frozen));
 const secondClient=new ApiClient(async(path,options)=>{
  calls.push({path,...options});return response({task_id:7,operation_id:9},202);
 },()=>assert.fail('restore must not mint a key'));
 const restored=await restoreCodeCommand(secondClient,first.frozen,binding,ORIGIN);
 await first.submit();await restored.submit();
 assert.equal(calls.length,2);assert.equal(calls[0].body,calls[1].body);
 assert.equal(calls[1].headers['Idempotency-Key'],KEY);
 assert.equal(calls[1].credentials,'same-origin');assert.equal(calls[1].redirect,'error');
 const handle=client.prepare('POST',PATH,{expected_state_version:1},
  {idempotent:true,success_status:202});
 assert.throws(()=>secondClient.exportPrepared(handle),TypeError);
 assert.deepEqual(client.exportPrepared(handle),{method:'POST',path:PATH,
  body:'{"expected_state_version":1}',key:KEY});
});
test('origin, module, registration, digest and native input are all independently required',async()=>{
 const {frozen}=await prepared();
 const client=new ApiClient(()=>assert.fail('no invalid dispatch'),()=>assert.fail('no UUID'));
 for(const [field,value] of [
  ['origin','http://localhost:8000'],['owner_module','TESTING'],['method','GET'],
  ['path','/api/v1/command-intents/close'],['key',KEY.toUpperCase()],
  ['decoder_kind','APP-TEST-CMD-C01'],['identity_sha256','a'.repeat(64)],
  ['body_json','{"expected_state_version":2}'],['body_sha256','a'.repeat(64)],
 ]) await assert.rejects(restoreCodeCommand(client,{...frozen,[field]:value},binding,ORIGIN),TypeError,field);
 await assert.rejects(restoreCodeCommand(client,{...frozen,unknown:true},binding,ORIGIN),TypeError);
 await assert.rejects(restoreCodeCommand(client,frozen,binding,'https://other.test'),TypeError);
 const invalid='{"expected_state_version":1,"actor":"model"}';
 await assert.rejects(restoreCodeCommand(client,{...frozen,body_json:invalid,
  body_sha256:await commandSha256(invalid)},binding,ORIGIN),TypeError);
 for(const origin of [ORIGIN+'/',ORIGIN+'/path','file:///tmp','null','HTTP://localhost:5173'])
  await assert.rejects(restoreCodeCommand(client,frozen,binding,origin),TypeError);
});
test('restoration rejects ambiguous JSON rather than changing frozen wire bytes',async()=>{
 const {frozen}=await prepared();const client=new ApiClient(()=>assert.fail('no send'));
 for (const body of [' {"expected_state_version":1}','{"expected_state_version":1,"expected_state_version":1}',
  '{"expected_state_version":1e0}','{"expected_state_version":9007199254740992}',
  '{"expected_state_version":NaN}','{"expected_state_version":"\\ud800"}','[]','null']) {
  await assert.rejects(restoreCodeCommand(client,{...frozen,body_json:body,
   body_sha256:await commandSha256(body)},binding,ORIGIN),undefined,body);
 }
});
test('frozen input and native policy are captured before asynchronous digest completion',async()=>{
 const first=await prepared();const frozen={...first.frozen};
 const mutable={...binding,success_status:[202],errors:['INVALID_STATE']};
 const client=new ApiClient(async()=>response({task_id:7,operation_id:9},202),()=>assert.fail('no key'));
 const pending=restoreCodeCommand(client,frozen,mutable,ORIGIN);
 frozen.path='/api/v1/test-plans';frozen.body_json='{}';
 mutable.decode=()=>assert.fail('mutable replacement decoder');
 mutable.validate_input=()=>assert.fail('mutable replacement validator');
 mutable.success_status[0]=201;mutable.errors.length=0;
 const restored=await pending;
 assert.equal((await restored.submit()).data.operation_id,9);
});
test('cooperation-window requests are query-only after restoration; baseline remains replayable',async()=>{
 const fakeNative=(path)=>({...binding,decoder_kind:registeredCommand('POST',path,KEY).decoder_kind,
  validate_input:()=>{},decode:value=>value});
 const client=new ApiClient(()=>assert.fail('query only never sends'),()=>KEY);
 for(const path of ['/api/v1/code-tasks/7/accept','/api/v1/code-tasks/7/resume']) {
  const native=fakeNative(path);
  const input=path.endsWith('resume')?{repository_quiescent_confirmed:true}:{};
  const first=await prepareCodeCommand(client,path,input,native,ORIGIN);
  const restored=await restoreCodeCommand(client,first.frozen,native,ORIGIN);
  assert.equal(restored.recovery_mode,'QUERY_ONLY');
  await assert.rejects(restored.submit(),TypeError);
 }
 const baseline=registeredCommand('POST','/api/v1/code-repositories/2/snapshots',KEY);
 assert.equal(commandRecoveryMode(baseline,{}),'REPLAY_SAME_KEY');
 assert.equal(commandRecoveryMode(registeredCommand('POST','/api/v1/testing-tasks/7/resume',KEY),{}),'REPLAY_SAME_KEY');
});
test('close uses only original identity/key, ignores damaged body and creates no new key',async()=>{
 const first=await prepared();const calls=[];
 const client=new ApiClient(async(path,options)=>{calls.push({path,...options});
  return response({close_status:'CLOSED',original_receipt:closed()});},
  ()=>assert.fail('close cannot create another key'));
 const api=new WalleApi(client,{});
 const control=await api.prepareCloseOriginalCommand({...first.frozen,
  body_json:null,body_sha256:'damaged'},ORIGIN,first.result_policy);
 assert.equal(calls.length,0);
 const result=await control.submit();
 assert.equal(result.status,200);assert.equal(result.data.original_receipt.original_http_status,409);
 assert.equal(result.data.original_receipt.record_status,'CLOSED');
 assert.equal(calls[0].path,'/api/v1/command-intents/close');
 assert.equal(calls[0].headers['Idempotency-Key'],KEY);
 assert.deepEqual(JSON.parse(calls[0].body),{method:'POST',path:PATH});
 assert.equal(Object.keys(JSON.parse(calls[0].body)).length,2);
});
test('already received does not imply cancellation and strict pairings reject missing records',async()=>{
 const first=await prepared();
 for(const receipt of [{...missing(),lookup_status:'IN_PROGRESS',record_status:'PROCESSING'},
  {...missing(),lookup_status:'UNKNOWN',record_status:'PROCESSING'}]) {
  const client=new ApiClient(async()=>response({close_status:'ALREADY_RECEIVED',original_receipt:receipt}));
  const control=await prepareCloseOriginalCommand(client,first.frozen,ORIGIN,first.result_policy);
  assert.equal((await control.submit()).data.close_status,'ALREADY_RECEIVED');
 }
 for(const [status,receipt] of [['CLOSED',missing()],['ALREADY_RECEIVED',closed()],
  ['ALREADY_RECEIVED',missing()],['ALREADY_RECEIVED',{...missing(),lookup_status:'UNKNOWN'}]]) {
  const client=new ApiClient(async()=>response({close_status:status,original_receipt:receipt}));
  const control=await prepareCloseOriginalCommand(client,first.frozen,ORIGIN,first.result_policy);
  await assert.rejects(control.submit(),ApiUnknown);
 }
});
test('invalid original identity cannot close; close unknown never replays or rekeys',async()=>{
 const first=await prepared();let sent=0;
 const client=new ApiClient(async()=>{sent++;throw new TypeError('offline');},()=>assert.fail('no key'));
 for(const broken of [{...first.frozen,path:'/api/v1/test-plans'},
  {...first.frozen,identity_sha256:'0'.repeat(64)},
  {...first.frozen,owner_module:'TESTING'}])
  await assert.rejects(prepareCloseOriginalCommand(client,broken,ORIGIN,first.result_policy),TypeError);
 assert.equal(sent,0);
 const action=await prepareCloseOriginalCommand(client,first.frozen,ORIGIN,first.result_policy);
 await assert.rejects(action.submit(),ApiUnknown);assert.equal(sent,1);
});

test('original mutation recognizes only its own COMMAND_CLOSED response',async()=>{
 const first=await prepared();
 for(const wrong of [false,true]){
  const client=new ApiClient(async()=>new Response(JSON.stringify({success:false,data:null,
   error:{code:'COMMAND_CLOSED',message:ERROR_MESSAGES.COMMAND_CLOSED,
    details:{method:'POST',path:wrong?'/api/v1/test-plans':PATH,closed_at:'2026-11-05T01:02:03.000Z'}},
   meta:{request_id:REQUEST}}),{status:409,headers:{'Content-Type':'application/json'}}),
   ()=>assert.fail('no new key'));
  const original=await restoreCodeCommand(client,first.frozen,binding,ORIGIN);
  await assert.rejects(original.submit(),wrong?ApiUnknown:ApiRejected);
 }
});
