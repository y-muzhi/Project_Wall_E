import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ManualDraftEnd} from '../src/documents/manual-end.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-05T13:00:00.000Z',pair={markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:7,created_at:at,updated_at:at,...pair};
const draft={...current,id:3,document_type:'MANUAL_DRAFT',content_version:2};
const deferred=()=>{let resolve;const promise=new Promise(accept=>{resolve=accept;});return {promise,resolve};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){const calls=[],f={fail:null,clears:0,cleanupFail:false,version:2,submits:0};
 const editor={flushLocal:()=>true,setReadonly:value=>calls.push(['readonly',value])};
 const autosave={state:{confirmed_version:2},localSnapshot:pair,freezeAndFlush:async()=>{calls.push(['freeze']);return true;},pauseAndWait:async()=>{calls.push(['pause']);},resumeEditing:()=>calls.push(['resume']),dispose:()=>calls.push(['dispose'])};
 const prepare=kind=>(id,version)=>{calls.push(['prepare',kind,id,version]);const action={submit:async()=>{f.submits++;calls.push(['submit',action]);if(f.fail){const error=f.fail;f.fail=null;throw error;}return {data:kind==='COMPLETE'?{...current,content_version:8}:{requirement_id:1,manual_draft_id:3,cancelled:true}};}};return action;};
 const api={prepareCompleteManualDraft:prepare('COMPLETE'),prepareCancelManualDraft:prepare('CANCEL'),getRequirement:async()=>({data:{id:1,document_work_state:'MANUAL_EDITING',active_operation_id:3}}),getCurrentDocument:async()=>({data:current}),getManualDraft:async()=>({data:{...draft,content_version:f.version}})};
 const cache={clearClosedDraft:async()=>{f.clears++;if(f.cleanupFail)throw Error('storage');}};return {...f,calls,editor,autosave,api,cache,f};}

test('complete waits confirmed last save then uses draft version, coalesces only same operation and never exposes success or cleans before receipt',async()=>{
 const p=fixture(),wait=deferred();p.autosave.freezeAndFlush=async()=>wait.promise;const end=new ManualDraftEnd(current,draft,p.api,p.editor,p.autosave,p.cache);
 const first=end.complete();assert.equal(end.complete(),first);assert(!await end.cancelConfirmed());await settle();assert(!p.calls.some(c=>c[0]==='prepare'));assert.equal(end.getSnapshot().outcome,null);
 p.autosave.state.confirmed_version=5;wait.resolve(true);assert(await first);assert.deepEqual(p.calls.find(c=>c[0]==='prepare'),['prepare','COMPLETE',1,5]);assert.equal(end.getSnapshot().phase,'CLOSED');assert.equal(end.getSnapshot().outcome.current.id,2);assert.equal(p.f.clears,1);end.dispose();
});
test('confirmed cancel stops new saves, waits owned save, reads native latest version and checks cancelled session identity before cleanup',async()=>{
 const p=fixture(),wait=deferred();p.f.version=9;p.autosave.pauseAndWait=async()=>{p.calls.push(['pause']);await wait.promise;};const end=new ManualDraftEnd(current,draft,p.api,p.editor,p.autosave,p.cache);
 const pending=end.cancelConfirmed();await settle();assert(!p.calls.some(c=>c[0]==='prepare'));wait.resolve();assert(await pending);assert.deepEqual(p.calls.find(c=>c[0]==='prepare'),['prepare','CANCEL',1,9]);assert(!p.calls.some(c=>c[0]==='freeze'));assert.equal(end.getSnapshot().outcome.manual_draft_id,3);end.dispose();
});
test('unknown keeps original immutable action, freezes opposite operation and clears only after joint reads and exact replay confirms receipt',async()=>{
 const p=fixture();p.f.fail=new ApiUnknown(true);const end=new ManualDraftEnd(current,draft,p.api,p.editor,p.autosave,p.cache);assert(!await end.complete());assert.equal(end.getSnapshot().phase,'UNKNOWN');assert.equal(p.f.clears,0);assert(!end.continueEditing());assert(!await end.cancelConfirmed());
 const original=p.calls.find(c=>c[0]==='submit')[1];p.api.getRequirement=async()=>({data:{id:1,document_work_state:'IDLE',active_operation_id:null}});p.api.getManualDraft=async()=>{throw new ApiRejected('MANUAL_DRAFT_NOT_FOUND','missing',null,'request',404);};
 assert(await end.retryUnknown());assert.equal(p.calls.filter(c=>c[0]==='prepare').length,1);assert(p.calls.filter(c=>c[0]==='submit').every(c=>c[1]===original));assert.equal(end.getSnapshot().observed.manual_draft,null);assert.equal(p.f.clears,1);end.dispose();
});
test('known refusal preserves editable session; cache failure cannot turn a confirmed commit into unknown or cause another command',async()=>{
 const p=fixture();p.f.fail=new ApiRejected('DOCUMENT_INVALID','invalid',null,'request',422);const end=new ManualDraftEnd(current,draft,p.api,p.editor,p.autosave,p.cache);
 assert(!await end.complete());assert.equal(end.getSnapshot().phase,'ERROR');assert.equal(p.f.clears,0);assert(end.continueEditing());assert.equal(end.getSnapshot().phase,'EDITING');
 p.f.cleanupFail=true;assert(await end.complete());assert.equal(end.getSnapshot().phase,'CLOSED');assert(end.getSnapshot().local_cleanup_error);const submits=p.f.submits;
 p.f.cleanupFail=false;assert(await end.clearLocal());assert.equal(p.f.submits,submits);assert(!end.getSnapshot().local_cleanup_error);end.dispose();
});
test('unconfirmed save and partial composition prevent complete command, while invalid ending receipt remains unknown with local draft intact',async()=>{
 const p=fixture(),end=new ManualDraftEnd(current,draft,p.api,p.editor,p.autosave,p.cache);p.editor.flushLocal=()=>false;assert(!await end.complete());assert(!p.calls.some(c=>c[0]==='prepare'));assert(end.continueEditing());p.editor.flushLocal=()=>true;p.autosave.freezeAndFlush=async()=>false;assert(!await end.complete());assert(!p.calls.some(c=>c[0]==='prepare'));end.dispose();
 const q=fixture();q.api.prepareCancelManualDraft=()=>({submit:async()=>({data:{requirement_id:1,manual_draft_id:88,cancelled:true}})});const wrong=new ManualDraftEnd(current,draft,q.api,q.editor,q.autosave,q.cache);
 assert(!await wrong.cancelConfirmed());assert.equal(wrong.getSnapshot().phase,'UNKNOWN');assert.equal(q.f.clears,0);wrong.dispose();
});
