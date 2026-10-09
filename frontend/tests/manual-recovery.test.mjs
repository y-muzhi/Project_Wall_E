import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ManualDraftRecovery} from '../src/documents/manual-recovery.ts';
const at='2026-10-05T14:20:00.000Z',pair={markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const root={id:1,status:'ACTIVE',document_work_state:'MANUAL_EDITING',active_operation_type:'MANUAL_DRAFT',active_operation_id:3};
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:7,created_at:at,updated_at:at,...pair};
const draft={...current,id:3,document_type:'MANUAL_DRAFT',content_version:2};
const record={schema_version:1,base_confirmed_version:2,local_revision:20,updated_at:at,...pair};
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
const flush=async()=>{for(let i=0;i<14;i++)await Promise.resolve();};
function fixture(){const f={local:record,server:draft,root,clears:[],restores:0,readonly:[],cacheError:false,readError:false,clearResult:true};
 const api={getRequirement:async()=>{if(f.readError)throw Error('network');return {data:f.root};},getCurrentDocument:async()=>({data:current}),getManualDraft:async()=>({data:f.server})};
 const editor={setReadonly:v=>f.readonly.push(v),restoreLocal:local=>{f.restores++;return local;}};
 const autosave={state:{confirmed_version:2,local_revision:0},localSnapshot:pair,restoreLocal:(local,apply)=>{apply();}};
 const cache={get:async(id,draftId)=>{assert.equal(id,1);assert.equal(draftId,3);if(f.cacheError)throw Error('storage');return f.local;},clearIfRevision:async(...args)=>{f.clears.push(args);return f.clearResult;}};
 const recovery=new ManualDraftRecovery(root,current,draft,api,editor,autosave,cache);return {f,api,editor,autosave,cache,recovery};}

test('fresh actual manual session stays frozen until explicit same-base restore; duplicate restore shares pending and opposite discard is refused',async()=>{
 const p=fixture();assert.deepEqual(p.f.readonly,[true]);assert(await p.recovery.inspect());assert.equal(p.f.restores,0);assert.equal(p.recovery.getSnapshot().phase,'AVAILABLE');
 const held=deferred();p.api.getManualDraft=()=>held.promise;const restoring=p.recovery.restore();assert.equal(p.recovery.restore(),restoring);assert(!await p.recovery.discardLocalConfirmed());await flush();assert.equal(p.f.restores,0);
 held.resolve({data:draft});assert(await restoring);assert.equal(p.f.restores,1);assert.deepEqual(p.f.clears,[]);assert.deepEqual(p.f.readonly,[true,false]);assert.equal(p.recovery.getSnapshot().phase,'RESTORED');p.recovery.dispose();
});
test('verified unchanged draft without local content resumes automatically and does not restore or clear anything',async()=>{
 const p=fixture();p.f.local=null;const notifications=[];
 const release=p.recovery.subscribe(()=>notifications.push({phase:p.recovery.getSnapshot().phase,ready:p.recovery.canContinueServer}));
 assert(await p.recovery.inspect());assert.equal(notifications.at(-1).phase,'SERVER_SELECTED');assert.equal(notifications.at(-1).ready,false);
 assert.deepEqual(p.f.readonly,[true,false]);assert.equal(p.f.restores,0);assert.deepEqual(p.f.clears,[]);
 assert.equal(p.recovery.getSnapshot().server.content_version,2);assert.equal(p.autosave.state.confirmed_version,2);
 assert(!p.recovery.continueServerWithoutLocal());release();p.recovery.dispose();
});

test('no-local inspection stays locked until all reads settle, and duplicate inspection unlocks only once',async()=>{
 const p=fixture();p.f.local=null;const held=deferred();p.api.getManualDraft=()=>held.promise;
 const pending=p.recovery.inspect();assert.equal(p.recovery.inspect(),pending);await flush();assert.deepEqual(p.f.readonly,[true]);
 held.resolve({data:draft});assert(await pending);assert.deepEqual(p.f.readonly,[true,false]);
 assert(!await p.recovery.inspect());assert.deepEqual(p.f.readonly,[true,false]);p.recovery.dispose();
});

test('no-local content cannot bypass a changed server baseline or mismatching session',async()=>{
 const p=fixture();p.f.local=null;p.f.server={...draft,content_version:3};assert(await p.recovery.inspect());
 assert.equal(p.recovery.getSnapshot().phase,'COMPARE');assert.deepEqual(p.f.readonly,[true]);assert(!p.recovery.canContinueServer);p.recovery.dispose();
 const q=fixture();q.f.local=null;q.f.root={...root,active_operation_id:9};assert(!await q.recovery.inspect());
 assert.equal(q.recovery.getSnapshot().phase,'ERROR');assert.deepEqual(q.f.readonly,[true]);assert.deepEqual(q.f.clears,[]);q.recovery.dispose();
});

test('failed no-local inspection retries into automatic editing, but a disposed session never unlocks',async()=>{
 const p=fixture();p.f.local=null;p.f.readError=true;assert(!await p.recovery.inspect());assert.deepEqual(p.f.readonly,[true]);
 p.f.readError=false;assert(await p.recovery.inspect());assert.equal(p.recovery.getSnapshot().phase,'SERVER_SELECTED');assert.deepEqual(p.f.readonly,[true,false]);p.recovery.dispose();
 const q=fixture();q.f.local=null;const held=deferred();q.api.getManualDraft=()=>held.promise;const pending=q.recovery.inspect();await flush();
 q.recovery.dispose();held.resolve({data:draft});assert(!await pending);assert.deepEqual(q.f.readonly,[true]);
});

test('a previously discovered local snapshot disappearing during restore cannot be treated as automatic no-local recovery',async()=>{
 const p=fixture();assert(await p.recovery.inspect());const known=p.recovery.getSnapshot().local;p.f.local=null;
 assert(!await p.recovery.restore());assert.equal(p.recovery.getSnapshot().phase,'ERROR');assert.deepEqual(p.recovery.getSnapshot().local,known);
 assert(!p.recovery.canContinueServer);assert.deepEqual(p.f.readonly,[true]);assert.deepEqual(p.f.clears,[]);assert.equal(p.f.restores,0);p.recovery.dispose();
});
test('version divergence keeps both snapshots for comparison without overwrite, deletion or local server-version adoption',async()=>{
 const p=fixture();p.f.server={...draft,content_version:3};assert(await p.recovery.inspect());assert.equal(p.recovery.getSnapshot().phase,'COMPARE');assert.equal(p.recovery.getSnapshot().local.base_confirmed_version,2);assert.equal(p.recovery.getSnapshot().server.content_version,3);
 assert(!await p.recovery.restore());assert.equal(p.f.restores,0);assert.deepEqual(p.f.clears,[]);assert(!p.recovery.continueServerWithoutLocal());
 assert(await p.recovery.discardLocalConfirmed());assert.deepEqual(p.f.clears,[[1,3,20]]);assert.equal(p.recovery.getSnapshot().phase,'SERVER_SELECTED');assert.deepEqual(p.f.readonly,[true]);p.recovery.dispose();
});
test('changed local selection and revision CAS losing preserve newer cache; only explicit exact revision discard permits current host input',async()=>{
 const p=fixture();await p.recovery.inspect();p.f.local={...record,local_revision:21};assert(!await p.recovery.restore());assert.equal(p.f.restores,0);assert.equal(p.recovery.getSnapshot().local.local_revision,21);
 p.f.clearResult=false;assert(!await p.recovery.discardLocalConfirmed());assert.equal(p.recovery.getSnapshot().local.local_revision,21);assert.deepEqual(p.f.readonly,[true]);
 p.f.clearResult=true;assert(await p.recovery.discardLocalConfirmed());assert.deepEqual(p.f.clears,[[1,3,21],[1,3,21]]);assert.deepEqual(p.f.readonly,[true,false]);p.recovery.dispose();
});
test('read or occupancy failure locks input; unavailable local store permits explicit server continuation only after actual server read, and dispose retires late facts',async()=>{
 const p=fixture();p.f.readError=true;assert(!await p.recovery.inspect());assert(!p.recovery.continueServerWithoutLocal());p.f.readError=false;p.f.root={...root,active_operation_id:9};assert(!await p.recovery.inspect());assert.equal(p.f.restores,0);p.recovery.dispose();
 const q=fixture();q.f.cacheError=true;assert(await q.recovery.inspect());assert.equal(q.recovery.getSnapshot().phase,'ERROR');assert(q.recovery.getSnapshot().storage_error);
 q.f.readError=true;assert(!await q.recovery.inspect());assert(!q.recovery.canContinueServer);assert(!q.recovery.continueServerWithoutLocal());assert.deepEqual(q.f.readonly,[true]);
 q.f.readError=false;assert(await q.recovery.inspect());assert(q.recovery.canContinueServer);assert(q.recovery.continueServerWithoutLocal());assert(q.recovery.getSnapshot().storage_error);q.recovery.dispose();
 const z=fixture(),held=deferred();z.api.getManualDraft=()=>held.promise;const pending=z.recovery.inspect();await flush();z.recovery.dispose();held.resolve({data:draft});assert(!await pending);assert.equal(z.recovery.getSnapshot().server,null);assert.deepEqual(z.f.clears,[]);
});
