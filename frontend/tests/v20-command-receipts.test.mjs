import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown, ApiRejected, exact, positiveInteger } from '../src/api/client.ts';
import { COMMAND_ROUTES, registeredCommand } from '../src/api/code-command-registry.ts';
import { codeErrorPolicy, ERROR_MESSAGES } from '../src/api/code-errors.ts';
import { commandReceipt, readCommandReceipt } from '../src/api/code-command-receipts.ts';
import { WalleApi } from '../src/api/walle.ts';

const KEY='00000000-0000-4000-8000-00000000000a';
const REQUEST='00000000-0000-4000-8000-00000000000b';
const original=registeredCommand('POST','/api/v1/code-tasks/7/start',KEY);
const policy={decoder_kind:original.decoder_kind,success_status:[202],errors:['INVALID_STATE'],
  decode(value, scope) {const row=exact(value,['task_id','operation_id']);assert.equal(row.task_id,scope.parameters.task_id);
    return {task_id:positiveInteger(row.task_id),operation_id:positiveInteger(row.operation_id)};}};
const missing=()=>({lookup_status:'NOT_FOUND',record_status:null,original_http_status:null,original_outcome:null,task_id:null,testing_task_id:null,operation_id:null});
const closed=()=>({...missing(),lookup_status:'FOUND',record_status:'CLOSED',original_http_status:409,
 original_outcome:{success:false,data:null,error:{code:'COMMAND_CLOSED',message:ERROR_MESSAGES.COMMAND_CLOSED,
 details:{method:'POST',path:original.path,closed_at:'2026-11-05T01:02:03.000Z'}}}});
const accepted=()=>({...missing(),lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
 original_outcome:{success:true,data:{task_id:7,operation_id:9},error:null},task_id:7,operation_id:9});
const response=(data,status=200)=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:REQUEST}}),
 {status,headers:{'Content-Type':'application/json'}});
const failure=(code,details,status,message=ERROR_MESSAGES[code])=>new Response(JSON.stringify({
 success:false,data:null,error:{code,message,details},meta:{request_id:REQUEST}}),
 {status,headers:{'Content-Type':'application/json'}});

test('all registered identities keep module and canonical safe IDs; no GET or recursive close',()=>{
 assert.equal(COMMAND_ROUTES.length,48);
 for(const [module,kind,template] of COMMAND_ROUTES) {
  const path=template.replace(/\{[a-z_]+\}/g,'9007199254740991');
  const command=registeredCommand('POST',path,KEY);
  assert.equal(command.owner_module,module);assert.equal(command.decoder_kind,kind);
  assert.ok(Object.isFrozen(command)&&Object.isFrozen(command.parameters));
 }
 assert.ok(COMMAND_ROUTES.every(Object.isFrozen));
 for (const path of ['/api/v1/code-tasks/01/start','/api/v1/code-tasks/9007199254740992/start',
 '/api/v1/code-tasks/1/start/','/api/v1/code-tasks/%31/start','/api/v1/command-intents/close',
 'https://example.test/api/v1/test-plans','/api/v1/testing-tasks/1/start']) {
  assert.throws(()=>registeredCommand('POST',path,KEY),TypeError,path);
 }
 assert.throws(()=>registeredCommand('GET',original.path,KEY),TypeError);
 assert.throws(()=>registeredCommand('POST',original.path,KEY.toUpperCase()),TypeError);
});

test('closed is the original 409 and never the success of the control exchange',()=>{
 const receipt=commandReceipt(closed(),original,policy);
 assert.equal(receipt.record_status,'CLOSED');assert.equal(receipt.original_http_status,409);
 assert.equal(receipt.original_outcome.success,false);
 for(const mutate of [
 row=>row.original_http_status=200,
 row=>row.record_status='REJECTED',
 row=>row.original_outcome.error.details.path='/api/v1/test-plans',
 row=>row.original_outcome.error.details.closed_at='2026-02-31T01:02:03.000Z',
 row=>row.original_outcome.error.message='unregistered copy',
 ]) {const row=closed();mutate(row);assert.throws(()=>commandReceipt(row,original,policy),TypeError);}
});

test('lookup states cannot invent outcome, terminal status or cross-module association',()=>{
 for(const status of ['IN_PROGRESS','UNKNOWN']) {
  assert.equal(commandReceipt({...missing(),lookup_status:status,record_status:'PROCESSING'},original,policy).lookup_status,status);
 }
 assert.equal(commandReceipt(missing(),original,policy).lookup_status,'NOT_FOUND');
 for(const row of [
 {...missing(),operation_id:1}, {...missing(),lookup_status:'IN_PROGRESS'}, {...missing(),record_status:'CLOSED'},
 {...missing(),lookup_status:'UNKNOWN',original_http_status:202},
 {...accepted(),task_id:8}, {...accepted(),testing_task_id:7},
 {...accepted(),operation_id:null}, {...accepted(),original_outcome:{success:true,data:{task_id:7,operation_id:10},error:null}}, {...accepted(),record_status:'PROCESSING'},
 ]) assert.throws(()=>commandReceipt(row,original,policy),TypeError);
 assert.throws(()=>commandReceipt(missing(),{...original,owner_module:'TESTING'},policy),TypeError);
});

test('original outcomes use the original endpoint decoder and error whitelist',()=>{
 assert.deepEqual(commandReceipt(accepted(),original,policy).original_outcome.data,{task_id:7,operation_id:9});
 assert.throws(()=>commandReceipt(accepted(),original,{...policy,success_status:[201]}),TypeError);
 assert.throws(()=>commandReceipt(accepted(),original,{...policy,decoder_kind:'APP-TEST-CMD-C01'}),TypeError);
 const row=closed();row.record_status='REJECTED';row.original_outcome.error={
  code:'INVALID_STATE',message:ERROR_MESSAGES.INVALID_STATE,details:{task_id:7,current_state_version:2,
   related_operation_id:null,related_entity_kind:null,related_entity_id:null}};
 assert.equal(commandReceipt(row,original,policy).record_status,'REJECTED');
 assert.throws(()=>commandReceipt(row,original,{...policy,errors:[]}),TypeError);
 row.original_outcome.error.details.private_path='never accepted';
 assert.throws(()=>commandReceipt(row,original,policy),TypeError);
});

test('existing transport keeps document errors strict and new details have two-field input errors',async()=>{
 const details={field_errors:[{field:'body.authorization_id',reason:'TYPE'}]};
 const code=codeErrorPolicy(['INVALID_INPUT','AUTHORIZATION_NOT_APPLICABLE']);
 const client=new ApiClient(async()=>failure('INVALID_INPUT',details,422));
 await assert.rejects(client.read('/api/v1/requirements',value=>value),ApiUnknown);
 await assert.rejects(client.read('/api/v1/testing-command-receipts',value=>value,[],undefined,code),
  error=>error instanceof ApiRejected && error.code==='INVALID_INPUT' && error.details.field_errors[0].reason==='TYPE');
 const authorization=new ApiClient(async()=>failure('AUTHORIZATION_NOT_APPLICABLE',{task_id:null,authorization_id:2},403));
 await assert.rejects(authorization.read('/api/v1/testing-command-receipts',value=>value,[],undefined,code),
  error=>error instanceof ApiRejected && error.status===403);
});

test('5xx write results stay unknown and native error methods are frozen with prepared body',async()=>{
 const native=codeErrorPolicy(['CONFIG_NOT_READY']);
 const mutable={...native};
 const client=new ApiClient(async()=>failure('CONFIG_NOT_READY',{capability_codes:['Q20-DB']},503),()=>KEY);
 const action=client.prepare('POST','/api/v1/code-tasks/7/start',{}, {idempotent:true,success_status:202,error_policy:mutable});
 mutable.decode=()=>null;mutable.mutationUnknown=()=>false;
 await assert.rejects(client.commit(action,value=>value),error=>error instanceof ApiUnknown && error.mutation);
});

test('actual WalleApi read uses only original registered GET and never sends body or action key',async()=>{
 const calls=[];
 const client=new ApiClient(async(url,options)=>{calls.push({url,options});return response(closed());},()=>{throw Error('GET never allocates UUID');});
 const api=new WalleApi(client,{});
 const result=await api.commandReceipt(original,policy);
 assert.equal(result.status,200);assert.equal(result.data.original_http_status,409);
 const url=new URL(calls[0].url,'http://localhost');
 assert.equal(url.pathname,'/api/v1/code-command-receipts');assert.equal(url.searchParams.get('path'),original.path);
 assert.equal(url.searchParams.get('request_key'),KEY);assert.equal(calls[0].options.method,'GET');
 assert.equal(calls[0].options.body,undefined);assert.equal(calls[0].options.headers['Idempotency-Key'],undefined);
 const testOriginal=registeredCommand('POST','/api/v1/test-plans',KEY);
 const read=new ApiClient(async(url)=>{assert.ok(url.startsWith('/api/v1/testing-command-receipts?'));return response(missing());});
 await readCommandReceipt(read,testOriginal,{...policy,decoder_kind:testOriginal.decoder_kind});
});

test('invalid receipts and non-endpoint errors are unknown; query-only read is never a replay',async()=>{
 const client=new ApiClient(async()=>failure('CONTENT_NOT_READY',{
  task_id:null,current_state_version:null,related_operation_id:null,related_entity_kind:null,related_entity_id:null},409));
 const identity=registeredCommand('POST','/api/v1/test-plans',KEY);
 await assert.rejects(readCommandReceipt(client,identity,{...policy,decoder_kind:identity.decoder_kind}),ApiUnknown);
 const invalid=new ApiClient(async()=>response({...closed(),original_http_status:200}));
 await assert.rejects(readCommandReceipt(invalid,original,policy),ApiUnknown);
});
