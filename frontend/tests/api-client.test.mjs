import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown, ApiRejected, positiveInteger, exact } from '../src/api/client.ts';

const KEY = '00000000-0000-4000-8000-00000000000a';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const json = (value, status=200) => new Response(JSON.stringify(value), {status, headers:{'Content-Type':'application/json; charset=utf-8'}});
const success = (data, meta={request_id:REQUEST}) => ({success:true,data,error:null,meta});
const failure = (code, details=null) => ({success:false,data:null,error:{code,message:'安全错误提示',details},meta:{request_id:REQUEST}});
const decode = value => { const row=exact(value,['id']);return {id:positiveInteger(row.id)}; };
const unknown = promise => assert.rejects(promise, error => error instanceof ApiUnknown && error.mutation);

test('same user action resends exact immutable JSON and key after lost response, new action gets new key', async () => {
  const calls=[];let replies=0;let keys=0;
  const client=new ApiClient(async (url,options) => {
    calls.push({url,...options});if(replies++===0)throw new TypeError('lost response');return json(success({id:1}),201);
  },()=>keys++===0?KEY:REQUEST);
  const body={title:'原始😀',expected_version:7};const command=client.prepare('POST','/api/v1/requirements',body,{idempotent:true,success_status:201});
  body.title='后来编辑';body.expected_version=8;
  await unknown(client.commit(command,decode));assert.deepEqual((await client.commit(command,decode)).data,{id:1});
  assert.equal(calls.length,2);assert.equal(calls[0].body,calls[1].body);assert.deepEqual(JSON.parse(calls[0].body),{title:'原始😀',expected_version:7});
  assert.equal(calls[0].headers['Idempotency-Key'],KEY);assert.equal(calls[1].headers['Idempotency-Key'],KEY);
  const changed=client.prepare('POST','/api/v1/requirements',body,{idempotent:true,success_status:201});await client.commit(changed,decode);
  assert.equal(calls[2].headers['Idempotency-Key'],REQUEST);assert.equal(JSON.parse(calls[2].body).expected_version,8);
});

test('nonidempotent property edit sends no key and missing PATCH fields remain absent', async () => {
  let sent;const client=new ApiClient(async (url,options)=>{sent=options;return json(success({id:1}));},()=>{throw new Error('must not allocate a key');});
  await client.commit(client.prepare('PATCH','/api/v1/requirements/1',{title:'新标题'},{idempotent:false,success_status:200}),decode);
  assert.deepEqual(JSON.parse(sent.body),{title:'新标题'});assert.equal(sent.headers['Idempotency-Key'],undefined);
});

test('empty-body command omits both body and Content-Type while preserving action header', async () => {
  let sent;const client=new ApiClient(async (url,options)=>{sent=options;return json(success({id:1}));},()=>KEY);
  await client.commit(client.prepare('POST','/api/v1/guide-runs/1/cancel',null,{idempotent:true,success_status:200}),decode);
  assert.equal(sent.body,undefined);assert.equal(sent.headers['Content-Type'],undefined);assert.equal(sent.headers['Idempotency-Key'],KEY);
});

test('wrong envelope/status/content/body/unsafe integers/success decoder cannot confirm mutation success', async () => {
  const replies=[json(success({id:1}),202),json(success({id:9007199254740992})),json({...success({id:1}),extra:true}),
    json(success({id:1},{request_id:'invalid'})),new Response('<html>proxy</html>',{status:502}),
    new Response('{bad',{headers:{'Content-Type':'application/json'}}),json(success({id:1.5})),json({...failure('STATE_CONFLICT'),success:true},409)];
  const client=new ApiClient(async()=>replies.shift(),()=>KEY);
  const command=client.prepare('POST','/api/v1/guide-runs/1/cancel',null,{idempotent:true,success_status:200});
  for(let i=0;i<8;i++)await unknown(client.commit(command,decode));
});

test('native explicit business rejection retains safe details and request ID, no failure pagination', async () => {
  const client=new ApiClient(async()=>json(failure('CARD_ALREADY_ANSWERED',{response_message_id:21}),409),()=>KEY);
  const command=client.prepare('POST','/api/v1/conversation-messages/3/responses',{schema_version:1,responses:[]},{idempotent:true,success_status:202});
  await assert.rejects(client.commit(command,decode),error=>error instanceof ApiRejected&&error.code==='CARD_ALREADY_ANSWERED'&&error.request_id===REQUEST&&error.details.response_message_id===21);
  const bad=new ApiClient(async()=>json({...failure('STATE_CONFLICT'),meta:{request_id:REQUEST,pagination:{page:1,page_size:20,total:0,total_pages:0}}},409),()=>KEY);
  await unknown(bad.commit(bad.prepare('POST','/api/v1/guide-runs/1/cancel',null,{idempotent:true,success_status:200}),decode));
});

test('server storage or internal error on a mutation may follow a real commit and stays unknown', async () => {
  for(const [code,status] of [['INTERNAL_ERROR',500],['STORAGE_UNAVAILABLE',503]]) {
    const client=new ApiClient(async()=>json(failure(code),status),()=>KEY);
    await unknown(client.commit(client.prepare('POST','/api/v1/requirements',{}, {idempotent:true,success_status:201}),decode));
  }
});

test('read failure cannot change an already-confirmed business state; repeated filters use repeated query keys', async () => {
  let url;const client=new ApiClient(async target=>{url=target;return json(failure('STORAGE_UNAVAILABLE'),503);});
  const confirmed={status:'RUNNING'};
  await assert.rejects(client.read('/api/v1/requirements',decode,[['status','ACTIVE'],['status','COMPLETED'],['keyword','甲 😀']]),ApiRejected);
  assert.deepEqual(confirmed,{status:'RUNNING'});assert.equal(url,'/api/v1/requirements?status=ACTIVE&status=COMPLETED&keyword=%E7%94%B2+%F0%9F%98%80');
});

test('page and cursor metadata preserve empty/out-of-range and next cursor definitions', async () => {
  const responses=[json(success({id:1},{request_id:REQUEST,pagination:{page:8,page_size:20,total:0,total_pages:0}})),
    json(success({id:1},{request_id:REQUEST,pagination:{page_size:20,next_cursor:9,has_more:true}})),
    json(success({id:1},{request_id:REQUEST,pagination:{page_size:20,next_cursor:null,has_more:false}}))];
  const client=new ApiClient(async()=>responses.shift());
  assert.equal((await client.read('/api/v1/requirements',decode)).meta.pagination.page,8);
  assert.equal((await client.read('/api/v1/requirements/1/messages',decode)).meta.pagination.next_cursor,9);
  assert.equal((await client.read('/api/v1/requirements/1/messages',decode)).meta.pagination.next_cursor,null);
});

test('preparation rejects malformed Unicode, undefined, nonplain/cyclic/nonfinite/unsafe values before any send', () => {
  const client=new ApiClient(async()=>{throw new Error('must not send');},()=>KEY);const cyclic={};cyclic.self=cyclic;
  for(const body of [{title:'\ud800'}, {title:undefined},{value:NaN},{value:Infinity},{value:9007199254740992},{value:new Date()},cyclic]) {
    assert.throws(()=>client.prepare('POST','/api/v1/requirements',body,{idempotent:true,success_status:201}),TypeError);
  }
  for(const target of ['https://other/api/v1/requirements','//other/api/v1/requirements','/api/v1/requirements/','/api/v1/requirements?x=1']) {
    assert.throws(()=>client.prepare('POST',target,{}, {idempotent:true,success_status:201}),TypeError);
  }
});

test('forged or another-client command is rejected before sending; actual abort remains unknown', async () => {
  const first=new ApiClient(async()=>{throw new DOMException('aborted','AbortError');},()=>KEY);
  const action=first.prepare('POST','/api/v1/requirements',{}, {idempotent:true,success_status:201});
  const other=new ApiClient(async()=>{throw new Error('must not send');});
  await assert.rejects(other.commit(action,decode),TypeError);await assert.rejects(first.commit({kind:'WALLE_COMMAND'},decode),TypeError);
  await unknown(first.commit(action,decode,new AbortController().signal));
});

test('body accessors are captured once and repeated shared objects preserve actual JSON without alias mutation', async () => {
  let reads=0;let sent;const body={get title(){reads++;return reads===1?'捕获一次':NaN;},nested:{id:1}};
  const client=new ApiClient(async(url,options)=>{sent=options;return json(success({id:1}));},()=>KEY);
  const action=client.prepare('PATCH','/api/v1/requirements/1',body,{idempotent:false,success_status:200});body.nested.id=2;
  await client.commit(action,decode);assert.equal(reads,1);assert.deepEqual(JSON.parse(sent.body),{title:'捕获一次',nested:{id:1}});
});

test('unknown error code or contradictory mapped HTTP status remains unconfirmed', async () => {
  const responses=[json(failure('UNREGISTERED_FAILURE'),409),json(failure('STATE_CONFLICT'),422)];
  const client=new ApiClient(async()=>responses.shift(),()=>KEY);
  const action=client.prepare('POST','/api/v1/guide-runs/1/cancel',null,{idempotent:true,success_status:200});
  await unknown(client.commit(action,decode));await unknown(client.commit(action,decode));
});
