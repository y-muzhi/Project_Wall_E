import {test} from 'node:test';
import assert from 'node:assert/strict';
import {WorkbenchHistory,decodeWorkbenchEntry,pageRoute} from '../src/requirements/workbench-history.ts';
import {defaultWorkbenchQuery} from '../src/requirements/workbench.ts';
import {localTime} from '../src/shared/time.ts';
function browser() {let count=0;const values=new Map();return {history:{state:null,scrollRestoration:'auto',replaceState(value){this.state=value;}},storage:{getItem(key){return values.get(key)??null;},setItem(key,value){values.set(key,value);}},values,identify:()=>`00000000-0000-4000-8000-${String(++count).padStart(12,'0')}`};}
test('each navigation entry owns frozen committed query/page/scroll; explicit main entry resets, return restores original position',()=>{
  const port=browser(),owner=new WorkbenchHistory(port.history,port.storage,port.identify);const initial=owner.enter('DEFAULT');
  assert.equal(port.history.scrollRestoration,'manual');
  const draft={...defaultWorkbenchQuery,keyword:'\u0085已提交\u0085',status:['ACTIVE'],page:3};const saved=owner.save(initial,draft,444.5);draft.keyword='未提交外部变化';
  assert.equal(saved.query.keyword,'已提交');assert.equal(saved.scroll,444.5);assert(Object.isFrozen(saved.query.status));assert.equal(owner.enter('RESTORE').entry_id,initial.entry_id);
  const other=owner.enter('DEFAULT');assert.notEqual(other.entry_id,saved.entry_id);assert.deepEqual(other.query,defaultWorkbenchQuery);assert.equal(other.scroll,0);
  port.history.state=saved;const afterReload=new WorkbenchHistory(port.history,port.storage,port.identify).enter('RESTORE');assert.deepEqual(afterReload,saved);
});
test('session supplement uses only actual history entry ID, never most recent other query',()=>{
  const port=browser(),owner=new WorkbenchHistory(port.history,port.storage,port.identify),first=owner.enter('DEFAULT');const saved=owner.save(first,{...defaultWorkbenchQuery,keyword:'原条目'},200);
  owner.save(owner.enter('DEFAULT'),{...defaultWorkbenchQuery,keyword:'另一个条目'},500);
  port.history.state={schema_version:1,kind:'WALLE_WORKBENCH',entry_id:first.entry_id};
  const fresh=new WorkbenchHistory(port.history,port.storage,port.identify);assert.deepEqual(fresh.enter('RESTORE'),saved);
  port.history.state={schema_version:1,kind:'WALLE_WORKBENCH',entry_id:'00000000-0000-4000-8000-999999999999'};assert.equal(fresh.enter('RESTORE').query.keyword,'');
});
test('corrupt/noncanonical recovery safely uses defaults; storage/history failures remain visible and do not lose current in-memory snapshot',()=>{
  const port=browser(),owner=new WorkbenchHistory(port.history,port.storage,port.identify),entry=owner.enter('DEFAULT');
  for(const altered of [{scroll:-1},{scroll:Infinity},{extra:true},{query:{...entry.query,keyword:' 带空白 '}},{query:{...entry.query,status:['ACTIVE','INITIALIZING','COMPLETED']}}])assert.throws(()=>decodeWorkbenchEntry({...entry,...altered}));
  port.values.set('walle:v1:workbench:'+entry.entry_id,'broken');port.history.state={schema_version:1,kind:'WALLE_WORKBENCH',entry_id:entry.entry_id};
  const fresh=new WorkbenchHistory(port.history,port.storage,port.identify);assert.equal(fresh.enter('RESTORE').query.keyword,'');assert.match(fresh.storageWarning,/暂存不可用/);
  const denied={getItem(){throw new Error('denied');},setItem(){throw new Error('denied');}},fail=new WorkbenchHistory(port.history,denied,port.identify);
  const fallback=fail.enter('DEFAULT');assert.match(fail.storageWarning,/暂存不可用/);assert.deepEqual(fail.enter('RESTORE'),fallback);
  const failedHistory={state:null,replaceState(){throw new Error('denied');}},failure=new WorkbenchHistory(failedHistory,null,port.identify);
  assert.equal(failure.enter('DEFAULT').query.keyword,'');assert.match(failure.storageWarning,/无法保存/);
});
test('page route uses canonical safe internal IDs, and local display rejects malformed UTC without changing ordering',()=>{
  assert.deepEqual(pageRoute('/requirements/1'),{kind:'DETAIL',id:1});assert.deepEqual(pageRoute('/'),{kind:'WORKBENCH'});
  for(const path of ['/requirements/01','/requirements/0','/requirements/+1','/requirements/1/','/requirements/9007199254740992','/requirements/REQ000001'])assert.equal(pageRoute(path).kind,'NOT_FOUND');
  for(const time of ['invalid','2026-02-30T00:00:00.000Z','2026-10-05T00:00:00Z','0000-01-01T00:00:00.000Z'])assert.equal(localTime(time),'--');
  assert.match(localTime('2026-10-05T00:00:00.000Z'),/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});
