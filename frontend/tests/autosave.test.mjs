import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ManualDraftAutosave } from '../src/documents/autosave.ts';
import { ApiClient, ApiUnknown, ApiRejected, API_REQUEST_TIMEOUT_MS } from '../src/api/client.ts';
import { ManualDraftEnd } from '../src/documents/manual-end.ts';

// Controller-only diagnostic ports. Real Milkdown/SQLite receipt adoption is
// covered independently in the browser; these do not model provenance.
const at = '2026-10-05T10:40:00.000Z';

// Preserve the production port's ticket -> immutable action binding, while
// keeping document decoding/storage isolated from Milkdown and user data.
function timeoutPort(transport) {
 const actions=new WeakMap();let keys=0;
 const client=new ApiClient(transport,()=>`00000000-0000-4000-8000-${String(++keys).padStart(12,'0')}`);
 return {async save(ticket){let action=actions.get(ticket);if(!action){action=client.prepare('PUT','/api/v1/manual-drafts/2',ticket,{idempotent:true,success_status:200});actions.set(ticket,action);}return (await client.commit(action,x=>x)).data;},async read(){return (await client.read('/api/v1/manual-drafts/2',x=>x)).data;}};
}
const receiptH04=data=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:'00000000-0000-4000-8000-00000000000b'}}),{headers:{'Content-Type':'application/json'}});

test('H04 save timeout reconciles original key before saving newer locally retained edits',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const sent=[],held=deferred();
 const rig=setup(timeoutPort(async(_url,options)=>{if(options.method==='GET')return receiptH04(draft());sent.push(options);if(sent.length===1)return held.promise;const ticket=JSON.parse(options.body);return receiptH04(draft(ticket.markdown_content,ticket.expected_version+1));}));
 try{
  rig.edit('first');const pending=rig.controller.flush();await settle();rig.edit('newest');await settle();assert.equal(rig.writes.at(-1)[2].markdown_content,'newest');
  t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);await pending;assert.equal(sent.length,3);assert.equal(sent[0].headers['Idempotency-Key'],sent[1].headers['Idempotency-Key']);assert.equal(sent[0].body,sent[1].body);
  assert.notEqual(sent[1].headers['Idempotency-Key'],sent[2].headers['Idempotency-Key']);assert.equal(JSON.parse(sent[2].body).expected_version,2);assert.equal(rig.controller.state.status,'SAVED');assert.equal(rig.controller.state.confirmed_version,3);assert.equal(rig.controller.localSnapshot.markdown_content,'newest');
  held.resolve(receiptH04(draft('first',2)));await settle();assert.equal(rig.controller.state.confirmed_version,3);
 }finally{rig.controller.dispose();}
});

test('H04 finish editing exits waiting after save and recovery-read timeouts, without completing or clearing the draft',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const methods=[];
 const rig=setup(timeoutPort(async(_url,options)=>{methods.push(options.method);return new Promise(()=>{});}));
 let locked=false,completes=0,clears=0;
 const end=new ManualDraftEnd({...draft(),id:1,document_type:'CURRENT'},draft(),{prepareCompleteManualDraft(){completes++;throw Error('must not complete');}},
  {flushLocal:()=>true,setReadonly:value=>{locked=value;}},rig.controller,{async clearClosedDraft(){clears++;}});
 try{
  rig.edit('retained');const ending=end.complete();await settle();assert(locked);
  t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);await settle();assert.equal(rig.controller.state.status,'UNKNOWN');assert.deepEqual(methods,['PUT','GET']);
  t.mock.timers.tick(API_REQUEST_TIMEOUT_MS);assert.equal(await ending,false);assert.equal(end.getSnapshot().phase,'ERROR');assert.equal(completes,0);assert.equal(clears,0);assert.equal(rig.controller.state.confirmed_version,1);assert.equal(rig.controller.localSnapshot.markdown_content,'retained');
  assert(end.continueEditing());assert(!locked);rig.edit('can continue');assert.equal(rig.controller.localSnapshot.markdown_content,'can continue');assert.deepEqual(rig.timing.live(),[2000]);
 }finally{end.dispose();rig.controller.dispose();}
});
const pair = text => ({ markdown_content: text, block_state_json: { schema_version: 1, next_block_id: 1, blocks: [] } });
const draft = (text = 'initial', version = 1) => ({ id: 2, requirement_id: 1, document_type: 'MANUAL_DRAFT', content_version: version, created_at: at, updated_at: at, ...pair(text) });
function ledger(document) {
  const port = { currentSnapshot: pair(document.markdown_content), savedVersion: document.content_version, active: null, proofs: new Set(),
    beginSave() { assert.equal(this.active, null); const ticket = Object.freeze({ requirement_id: 1, expected_version: this.savedVersion, ...this.currentSnapshot }); this.active = ticket; this.proofs.add(ticket); return ticket; },
    suspendSave(ticket) { assert.equal(this.active, ticket); this.active = null; },
    rejectSave(ticket) { assert(this.proofs.delete(ticket)); if (this.active === ticket) this.active = null; },
    acknowledgeSave(ticket, value) { assert(this.proofs.has(ticket)); assert.equal(value.content_version, ticket.expected_version + 1); assert.equal(value.markdown_content, ticket.markdown_content); this.savedVersion = value.content_version; this.active = null; this.proofs.clear(); return this.currentSnapshot; } };
  return port;
}
function clock() {
  const timers = [];
  return { timers, schedule(callback, delay) { const timer = { callback, delay, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; },
    fire(delay) { const timer = timers.find(item => !item.cancelled && item.delay === delay); assert(timer, `missing ${delay} timer`); timer.cancelled = true; timer.callback(); },
    live() { return timers.filter(timer => !timer.cancelled).map(timer => timer.delay); } };
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const settle = async () => { for (let count = 0; count < 25; count++) await Promise.resolve(); };
function setup(api) {
  const initial = draft(), session = ledger(initial), timing = clock(), writes = [], clears = [];
  const cache = { async put(...args) { writes.push(args); return true; }, async clearIfRevision(...args) { clears.push(args); return true; } };
  const controller = new ManualDraftAutosave(initial, session, api, cache, timing);
  const edit = text => { session.currentSnapshot = pair(text); controller.changed(); };
  return { controller, session, timing, writes, clears, edit };
}

test('explicit recovery continues stored local revision, preserves real confirmed version, and cannot run over an edited or mismatched session',async()=>{
 const rig=setup({save:async ticket=>draft(ticket.markdown_content,ticket.expected_version+1),read:async()=>draft()}),local={schema_version:1,base_confirmed_version:1,local_revision:20,updated_at:at,...pair('restored')};
 assert.throws(()=>rig.controller.restoreLocal({...local,base_confirmed_version:2},()=>local));
 rig.controller.restoreLocal(local,()=>{rig.session.currentSnapshot=pair('restored');return rig.session.currentSnapshot;});await settle();
 assert.equal(rig.controller.state.confirmed_version,1);assert.equal(rig.controller.state.local_revision,21);assert.equal(rig.writes.at(-1)[2].local_revision,21);assert.equal(rig.writes.at(-1)[2].base_confirmed_version,1);
 assert.throws(()=>rig.controller.restoreLocal(local,()=>local));await rig.controller.flush();assert.equal(rig.controller.state.confirmed_version,2);assert.equal(rig.controller.state.status,'SAVED');rig.controller.dispose();
});

test('superseded local put is a visible storage failure, not falsely reported as successful local protection',async()=>{
 const initial=draft(),session=ledger(initial),timing=clock(),controller=new ManualDraftAutosave(initial,session,{save:async()=>initial,read:async()=>initial},{put:async()=>false,clearIfRevision:async()=>false},timing);
 session.currentSnapshot=pair('unsaved');controller.changed();await settle();assert.equal(controller.state.local_storage_error,true);assert.equal(controller.state.status,'DIRTY');assert.equal(controller.localSnapshot.markdown_content,'unsaved');controller.dispose();
});

test('idle2sec and maximum10sec send a complete pair, continuous edits keep the original maximum deadline', async () => {
  const sent = [], rig = setup({ async save(ticket) { sent.push(ticket); return draft(ticket.markdown_content, ticket.expected_version + 1); }, async read() { return draft(); } });
  rig.edit('first'); rig.edit('second'); assert.deepEqual(rig.timing.live(), [10000, 2000]);
  rig.timing.fire(10000); await settle(); assert.equal(sent.length, 1); assert.equal(sent[0].markdown_content, 'second');
  assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 2); assert.deepEqual(rig.timing.live(), []);
  rig.edit('third'); rig.timing.fire(2000); await settle(); assert.equal(sent[1].expected_version, 2); rig.controller.dispose();
});
test('one in-flight write, many edits coalesce to newest and old success never overwrites current local content', async () => {
  const first = deferred(), sent = []; let active = 0, peak = 0;
  const rig = setup({ async save(ticket) { sent.push(ticket); active++; peak = Math.max(peak, active); const value = sent.length === 1 ? await first.promise : draft(ticket.markdown_content, ticket.expected_version + 1); active--; return value; }, async read() { return draft(); } });
  rig.edit('first'); const saving = rig.controller.flush(); await settle(); rig.edit('intermediate'); rig.edit('newest');
  assert.equal(sent.length, 1); first.resolve(draft('first', 2)); await saving;
  assert.equal(sent.length, 2); assert.equal(sent[1].markdown_content, 'newest'); assert.equal(sent[1].expected_version, 2); assert.equal(peak, 1);
  assert.equal(rig.controller.localSnapshot.markdown_content, 'newest'); assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 3);
  assert.equal(rig.clears.length, 1); assert.equal(rig.clears[0][2], 3); rig.controller.dispose();
});
test('lost receipt confirms the same original ticket instead of inferring command success from GET text', async () => {
  let persisted=draft(),calls=0,original;
  const rig=setup({async save(ticket){calls++;original??=ticket;assert.equal(ticket,original);persisted=draft(ticket.markdown_content,2);if(calls===1)throw new ApiUnknown(true);return persisted;},async read(){return persisted;}});
  rig.edit('committed');await rig.controller.flush();assert.equal(calls,2);assert.equal(rig.controller.state.status,'SAVED');assert.equal(rig.controller.state.confirmed_version,2);rig.controller.dispose();
});

test('pending original save keeps its ticket while newer edits wait, then drains the newest body at the confirmed next version', async () => {
  let persisted=draft(),calls=0;const sent=[];
  const rig=setup({async save(ticket){sent.push(ticket);calls++;if(calls===1)throw new ApiUnknown(true);if(calls===2)throw new ApiRejected('REQUEST_IN_PROGRESS','pending',null,'diagnostic',409);persisted=draft(ticket.markdown_content,ticket.expected_version+1);return persisted;},async read(){return persisted;}});
  rig.edit('first');await rig.controller.flush();assert.equal(rig.controller.state.status,'UNKNOWN');assert.equal(rig.controller.state.confirmed_version,1);
  rig.edit('newest');await rig.controller.flush();
  assert.equal(sent[0],sent[1]);assert.equal(sent[1],sent[2]);assert.equal(sent[3].markdown_content,'newest');assert.equal(sent[3].expected_version,2);
  assert.equal(rig.controller.state.status,'SAVED');assert.equal(rig.controller.state.confirmed_version,3);rig.controller.dispose();
});

test('matching content from another action cannot acknowledge our failed original save', async () => {
  let persisted=draft(),calls=0;
  const rig=setup({async save(ticket){if(++calls===1){persisted=draft(ticket.markdown_content,2);throw new ApiUnknown(true);}throw new ApiRejected('CONTENT_VERSION_CONFLICT','conflict',null,'diagnostic',409);},async read(){return persisted;}});
  rig.edit('same text');await rig.controller.flush();assert.equal(calls,2);assert.equal(rig.controller.state.status,'CONFLICT');assert.equal(rig.controller.state.confirmed_version,1);assert.equal(rig.controller.localSnapshot.markdown_content,'same text');rig.controller.dispose();
});

test('repeated unknown writes/read failure back off2/5/10/30 capped, keep confirmed version and latest local pair', async () => {
  let reads = 0; const rig = setup({ async save() { throw new ApiUnknown(true); }, async read() { reads++; if (reads > 1) throw new ApiUnknown(false); return draft(); } });
  rig.edit('unsynced'); await rig.controller.flush();
  for (const delay of [2000, 5000, 10000, 30000]) { assert.deepEqual(rig.timing.live(), [delay]); rig.timing.fire(delay); await settle(); }
  assert.deepEqual(rig.timing.live(), [30000]); assert.equal(rig.controller.state.status, 'UNKNOWN'); assert.equal(rig.controller.state.confirmed_version, 1); assert.equal(rig.controller.localSnapshot.markdown_content, 'unsynced'); rig.controller.dispose();
});
test('validation refusal stops retries until corrected; unrelated external version stops overwrite and retains local content', async () => {
  let calls = 0; const rig = setup({ async save(ticket) { if (++calls === 1) throw new ApiRejected('DOCUMENT_INVALID', 'invalid', null, 'diagnostic', 422); return draft(ticket.markdown_content, 2); }, async read() { return draft('external', 3); } });
  rig.edit('bad'); await rig.controller.flush(); assert.equal(rig.controller.state.status, 'VALIDATION_ERROR'); assert.deepEqual(rig.timing.live(), []);
  await rig.controller.flush(); assert.equal(calls, 1); rig.edit('corrected'); rig.timing.fire(2000); await settle(); assert.equal(rig.controller.state.status, 'SAVED'); rig.controller.dispose();
  const conflict = setup({ async save() { throw new ApiUnknown(true); }, async read() { return draft('external', 3); } });
  conflict.edit('local'); await conflict.controller.flush(); assert.equal(conflict.controller.state.status, 'CONFLICT'); assert.equal(conflict.controller.state.server_conflict.markdown_content, 'external');
  conflict.edit('newer local'); await conflict.controller.flush(); assert.equal(conflict.controller.localSnapshot.markdown_content, 'newer local'); assert.equal(conflict.controller.state.confirmed_version, 1); assert.deepEqual(conflict.timing.live(), []); conflict.controller.dispose();
});
test('freeze drains newest before completion, discard pauses and waits, disposal ignores late receipt without deleting cache', async () => {
  const first = deferred(), sent = []; const rig = setup({ async save(ticket) { sent.push(ticket); return sent.length === 1 ? first.promise : draft(ticket.markdown_content, 3); }, async read() { return draft(); } });
  rig.edit('one'); void rig.controller.flush(); await settle(); rig.edit('two'); const drain = rig.controller.freezeAndFlush();
  assert.throws(() => rig.edit('three'), /frozen/); first.resolve(draft('one', 2)); assert.equal(await drain, true); assert.equal(sent.length, 2); rig.controller.dispose();
  const held = deferred(); let calls = 0;
  const paused = setup({ async save() { calls++; return held.promise; }, async read() { return draft(); } });
  paused.edit('one'); void paused.controller.flush(); await settle(); paused.edit('two'); const wait = paused.controller.pauseAndWait(); held.resolve(draft('one', 2)); await wait;
  await paused.controller.flush(); assert.equal(calls, 1); assert.equal(paused.controller.state.accepting_input, false); paused.controller.dispose();
  const late = deferred(), disposed = setup({ async save() { return late.promise; }, async read() { return draft(); } });
  disposed.edit('retain'); const pending = disposed.controller.flush(); await settle(); disposed.controller.dispose(); late.resolve(draft('retain', 2)); await pending;
  assert.equal(disposed.controller.state.status, 'CLOSED'); assert.equal(disposed.controller.state.confirmed_version, 1); assert.equal(disposed.clears.length, 0);
});
