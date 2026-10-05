import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { normalizeOrdinary, ordinaryInput } from '../src/shared/text.ts';
import { RequirementWorkbench, defaultWorkbenchQuery, workbenchQuery } from '../src/requirements/workbench.ts';
import { CreateRequirementFlow, createPayload, emptyCreateDraft } from '../src/requirements/create.ts';
import { requirementCatalog } from '../src/requirements/catalog.ts';
import { ApiRejected, ApiUnknown } from '../src/api/client.ts';
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve, reject; const promise = new Promise((yes,no) => { resolve=yes;reject=no; }); return {promise,resolve,reject}; }
function page(page=1,total=1,items=[{id:1}]) { return {data:{items},meta:{pagination:{page,page_size:20,total,total_pages:Math.ceil(total/20)}}}; }
const query = (changes={}) => ({...defaultWorkbenchQuery,...changes});
function readPort() { const calls=[];return {calls,api:{listRequirements(input,signal) {const wait=deferred();calls.push({input,signal,...wait});return wait.promise;}}}; }
test('ordinary form normalization agrees with actual backend White_Space for every edge character and preserves BOM/C0/NFC', () => {
  const cases=[];for(let point=0;point<=0x3000;point++) cases.push(String.fromCodePoint(point)+'😀e\u0301Ａ'+String.fromCodePoint(point));
  cases.push(' \r\na\rb\r\nc\u0085','\ufeff 标题 \ufeff','\u001c 内容 \u001c');
  const script='import json,sys;from backend.app.shared.validation import normalize_text;print(json.dumps([normalize_text(x) for x in json.load(sys.stdin)],ensure_ascii=True))';
  const native=spawnSync(resolve(import.meta.dirname,'../../.venv/Scripts/python.exe'),['-X','utf8','-c',script],{cwd:resolve(import.meta.dirname,'../..'),input:JSON.stringify(cases),encoding:'utf8'});
  assert.equal(native.status,0,native.stderr);const expected=JSON.parse(native.stdout);assert.equal(expected.length,cases.length);
  for(let index=0;index<cases.length;index++) assert.equal(normalizeOrdinary(cases[index]),expected[index],'Native normalization case '+index);
  assert.equal(ordinaryInput(' 😀'.repeat(20).replaceAll(' ',''),'title',1,20,false),'😀'.repeat(20));
  assert.throws(()=>ordinaryInput('😀'.repeat(21),'title',1,20,false));assert.throws(()=>normalizeOrdinary('\ud800'));
  assert.throws(()=>ordinaryInput('a\rb','title',1,20,false));assert.equal(normalizeOrdinary('e\u0301Ａ'),'e\u0301Ａ');
});
test('workbench canonical all filters omit HTTP parameters, duplicate/current queries coalesce and explicit refresh reads', async () => {
  const port=readPort(),controller=new RequirementWorkbench(port.api);const first=controller.query(),duplicate=controller.query();assert.equal(first,duplicate);
  await tick();assert.deepEqual(port.calls[0].input,{page:1});port.calls[0].resolve(page());await first;
  assert.equal(controller.phase,'READY');assert(Object.isFrozen(controller.state.confirmed.status));await controller.query();assert.equal(port.calls.length,1);
  const refresh=controller.refresh();await tick();assert.equal(port.calls.length,2);assert.equal(controller.phase,'REFRESHING');port.calls[1].resolve(page());await refresh;
  assert.deepEqual(workbenchQuery(query({status:['COMPLETED','INITIALIZING'],keyword:'\u0085词\u0085'})).status,['INITIALIZING','COMPLETED']);
  assert.throws(()=>workbenchQuery(query({status:[]})));assert.throws(()=>workbenchQuery(query({status:['ACTIVE','ACTIVE']})));
  assert.throws(()=>workbenchQuery(query({page:0})));assert.throws(()=>workbenchQuery(query({keyword:'😀'.repeat(101)})));controller.dispose();
});
test('inverse old success/failure/finally cannot change new rows, error or loading and abort only owned read', async () => {
  const port=readPort(),controller=new RequirementWorkbench(port.api);const old=controller.query(query({keyword:'旧'}));await tick();
  const latest=controller.query(query({keyword:'新',page:2}));await tick();assert.equal(port.calls[0].signal.aborted,true);
  port.calls[0].resolve(page());await old;assert.equal(controller.state.loading,true);assert.equal(controller.state.result,null);
  assert.equal(controller.query(query({keyword:'新',page:2})),latest);port.calls[1].resolve(page(2,21,[{id:22}]));await latest;
  assert.deepEqual(controller.state.result.items,[{id:22}]);assert.equal(controller.state.confirmed.keyword,'新');
  const stale=controller.query(query({keyword:'晚错误'}));await tick();const next=controller.query(query({keyword:'最新'}));await tick();
  port.calls[3].resolve(page(1,1,[{id:44}]));await next;port.calls[2].reject(new Error('late'));await stale;
  assert.equal(controller.phase,'READY');assert.equal(controller.state.error,null);assert.deepEqual(controller.state.result.items,[{id:44}]);controller.dispose();
});
test('refresh failure retains last successful condition and rows, differentiates empty/no-match/out-of-range, dispose rejects late publication', async () => {
  const port=readPort(),controller=new RequirementWorkbench(port.api);let run=controller.query();await tick();port.calls[0].reject(new Error());await run;assert.equal(controller.phase,'ERROR');
  run=controller.refresh();await tick();port.calls[1].resolve(page(1,0,[]));await run;assert.equal(controller.phase,'EMPTY');
  run=controller.query(query({keyword:'条件'}));await tick();port.calls[2].reject(new ApiRejected('VALIDATION_FAILED','条件错误',null,'diagnostic',422));await run;
  assert.equal(controller.phase,'REFRESH_ERROR');assert.equal(controller.state.confirmed.keyword,'');assert.equal(controller.state.requested.keyword,'条件');assert.equal(controller.state.field_error,'条件错误');
  run=controller.refresh();await tick();port.calls[3].resolve(page(1,0,[]));await run;assert.equal(controller.phase,'NO_MATCH');
  run=controller.query(query({page:99}));await tick();port.calls[4].resolve(page(99,21,[]));await run;assert.equal(controller.phase,'OUT_OF_RANGE');
  run=controller.refresh();await tick();const before=controller.state;controller.dispose();assert.equal(port.calls[5].signal.aborted,true);port.calls[5].resolve(page(99,0,[]));await run;assert.equal(controller.state,before);
});
function validDraft() { const template=requirementCatalog.templates.find(value=>value.requirement_types.includes('NEW'));return {title:' 标题😀 ',type:'NEW',template:{template_key:template.template_key,template_version:template.template_version},idea:'\u0085初始\r\n想法\u0085',mode:'DESIGN'}; }
function createPort() { const prepared=[],calls=[];return {prepared,calls,api:{prepareCreateRequirement(payload) {const id=prepared.length+1;prepared.push(payload);return {submit() {const wait=deferred();calls.push({id,payload,...wait});return wait.promise;}};}}}; }
test('five fields validate in display order with native codepoint bounds and fixed catalog type/template mapping', async () => {
  assert.deepEqual(Object.keys(createPayload(emptyCreateDraft).fields),['title','type','template','idea','mode']);
  const port=createPort(),flow=new CreateRequirementFlow(port.api);assert.equal(flow.hasInput,false);await flow.submit();assert.equal(port.prepared.length,0);
  flow.edit({...emptyCreateDraft,type:'NEW'});assert.equal(flow.state.draft.template.template_key,'new-requirement');assert.equal(flow.state.draft.mode,null);
  flow.edit({...flow.state.draft,type:'CHANGE'});assert.equal(flow.state.draft.template.template_key,'change-requirement');
  flow.edit({...flow.state.draft,type:null});assert.equal(flow.state.draft.template,null);assert.equal(flow.hasInput,false);
  const valid=validDraft(),payload=createPayload(valid).payload;assert.equal(payload.title,'标题😀');assert.equal(payload.initial_idea,'初始\n想法');
  assert.deepEqual(createPayload({...valid,title:'😀'.repeat(20),idea:'😀'.repeat(10000)}).fields,{});
  assert.deepEqual(Object.keys(createPayload({...valid,title:'😀'.repeat(21),idea:'😀'.repeat(10001)}).fields),['title','idea']);
  assert.equal(createPayload({...valid,type:'CHANGE'}).payload,null);flow.dispose();
});
test('pending create coalesces, unknown preserves exact prepared action/input and retries same operation; known success locks edits', async () => {
  const port=createPort(),flow=new CreateRequirementFlow(port.api),draft=validDraft();flow.edit(draft);draft.title='外部修改';assert.equal(flow.state.draft.title,' 标题😀 ');
  const first=flow.submit();assert.equal(flow.submit(),first);assert.equal(flow.state.busy,true);assert.throws(()=>flow.edit(validDraft()));await tick();
  port.calls[0].reject(new ApiUnknown(true));await first;assert.equal(flow.state.unknown,true);assert.throws(()=>flow.edit(validDraft()));
  const retry=flow.submit();await tick();assert.equal(port.prepared.length,1);assert.equal(port.calls[1].id,port.calls[0].id);assert.equal(port.calls[1].payload,port.calls[0].payload);
  const result=Object.freeze({requirement:{id:3},guide_run_id:7});port.calls[1].resolve({data:result});await retry;
  assert.equal(flow.state.result,result);assert.equal(flow.state.unknown,false);assert.throws(()=>flow.edit(validDraft()));await flow.submit();assert.equal(port.calls.length,2);flow.dispose();
});
test('definite server field errors map to form, edits prepare new action; disposal ignores late success without abort or false rollback', async () => {
  const port=createPort(),flow=new CreateRequirementFlow(port.api);flow.edit(validDraft());let pending=flow.submit();await tick();
  port.calls[0].reject(new ApiRejected('VALIDATION_FAILED','不合法',{field_errors:[{field:'template_version',reason:'INVALID_FORMAT',message:'版本不合法'}]},'diagnostic',422));await pending;
  assert.equal(flow.state.unknown,false);assert.deepEqual(flow.state.fields,{template:'版本不合法'});assert.equal(flow.state.error,null);
  flow.edit({...flow.state.draft,title:'新标题'});pending=flow.submit();await tick();assert.equal(port.prepared.length,2);const before=flow.state;flow.dispose();
  port.calls[1].resolve({data:{requirement:{id:9},guide_run_id:10}});await pending;assert.equal(flow.state,before);
});
