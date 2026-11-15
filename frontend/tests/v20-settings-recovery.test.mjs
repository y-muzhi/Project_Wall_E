import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RecoveryListReader} from '../src/code-tasks/settings/recovery-reader.ts';
import {codeSettingsSection} from '../src/code-tasks/settings/section.ts';
import {CommandStorageError} from '../src/code-tasks/command-recovery-store.ts';

const record=(key='original')=>Object.freeze({key,status:'UNKNOWN',operation_id:null});
const deferred=()=>{let resolve;const promise=new Promise(value=>resolve=value);return {promise,resolve};};
test('settings reader only queries original summaries and preserves NOT_FOUND',async()=>{
 const row=record(),calls=[];const port={store:{list:async()=>[row]},
 lookup:async(key,signal)=>{calls.push(key);assert.equal(signal.aborted,false);return {local:row,original_receipt:{lookup_status:'NOT_FOUND'}};},
 reconcileOperation:async()=>assert.fail('No accepted operation')};
 const reader=new RecoveryListReader(port);await reader.refresh();
 assert.deepEqual(calls,['original']);assert.deepEqual(reader.getSnapshot().records,[row]);
 assert.equal(reader.getSnapshot().loading,false);reader.dispose();
});
test('accepted operation is checked by its original key and terminal summary leaves pending',async()=>{
 const row={...record(),status:'ACCEPTED',operation_id:17};let records=[row],operations=0;
 const reader=new RecoveryListReader({store:{list:async()=>records},lookup:async()=>({local:row}),
 reconcileOperation:async(key)=>{assert.equal(key,row.key);operations++;records=[];return {final_state:'CONFIRMED'};}});
 await reader.refresh();assert.equal(operations,1);assert.deepEqual(reader.getSnapshot().records,[]);reader.dispose();
});
test('row read error keeps original record and successful metadata is not an empty state',async()=>{
 const row=record();const reader=new RecoveryListReader({store:{list:async()=>[row]},
 lookup:async()=>{throw Error('bad wire');},reconcileOperation:async()=>assert.fail()});
 await reader.refresh();assert.equal(reader.getSnapshot().records[0],row);
 assert.match(reader.getSnapshot().rowErrors[row.key],/保留记录/);assert.equal(reader.getSnapshot().error,null);reader.dispose();
});
test('storage failure preserves last successful records and retry recovers',async()=>{
 const row=record();let failed=false;
 const reader=new RecoveryListReader({store:{list:async()=>{if(failed)throw new CommandStorageError('UNAVAILABLE');return [row];}},
 lookup:async()=>({local:row}),reconcileOperation:async()=>assert.fail()});
 await reader.refresh();failed=true;await reader.refresh();
 assert.deepEqual(reader.getSnapshot().records,[row]);assert.match(reader.getSnapshot().error,/暂存不可用/);
 failed=false;await reader.refresh();assert.equal(reader.getSnapshot().error,null);reader.dispose();
});
test('overlapping focus requests coalesce and hidden late reads cannot replace resumed owner',async()=>{
 const gate=deferred(),old=record('old'),fresh=record('fresh');let lists=0,signals=[];
 const reader=new RecoveryListReader({store:{list:async()=>++lists===1?gate.promise:[fresh]},
 lookup:async(_key,signal)=>{signals.push(signal);return {local:fresh};},reconcileOperation:async()=>assert.fail()});
 const first=reader.refresh();await reader.refresh();assert.equal(lists,1);
 reader.pause();await reader.refresh();assert.deepEqual(reader.getSnapshot().records,[fresh]);
 gate.resolve([old]);await first;assert.deepEqual(reader.getSnapshot().records,[fresh]);reader.dispose();
});
test('disposal aborts original read and prevents stale updates',async()=>{
 const gate=deferred(),row=record();let signal;
 const reader=new RecoveryListReader({store:{list:async()=>[row]},lookup:async(_key,value)=>{signal=value;return gate.promise;},
 reconcileOperation:async()=>assert.fail()});
 const loading=reader.refresh();await Promise.resolve();assert.ok(signal);reader.dispose();
 assert.equal(signal.aborted,true);const snapshot=reader.getSnapshot();gate.resolve({local:row});await loading;
 assert.equal(reader.getSnapshot(),snapshot);
});
test('settings sections reject duplicates, unknown parameters and invalid values',()=>{
 assert.equal(codeSettingsSection(''),'repositories');
 for(const section of ['repositories','execution','checks','authorizations'])
  assert.equal(codeSettingsSection('?section='+section),section);
 for(const query of ['?section=','?section=execution&section=checks','?section=unknown','?return_to=/private'])
  assert.equal(codeSettingsSection(query),null);
});
