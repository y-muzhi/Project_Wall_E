import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown} from '../src/api/client.ts';
import {DocumentDirectoryCommands} from '../src/requirements/document-directory.ts';
import {recoveryStorageKey,DraftRecoveryStore} from '../src/documents/recovery-store.ts';
import {editorReadModel} from '../src/documents/contracts.ts';

const at='2026-10-22T00:00:00.000Z';
const document=id=>({id,requirement_id:1,name:'文档'+id,document_kind:'DESIGN',document_type:'CURRENT',metadata_version:1,content_version:1,
 current_revision_id:id,confirmed_revision_id:null,archived_at:null,updated_at:at,source_status:'UNCHANGED'});
const detail=(changes={})=>({requirement:{id:1,status:'CLOSED',document_work_state:'IDLE'},documents:[document(1)],selected_document_id:1,current:null,...changes});

test('unknown creation preserves its original action and does not steal a newer reading selection',async()=>{
 let prepared=0,sent=0;const selected=[],bodies=[];
 const flow=new DocumentDirectoryCommands(detail(),{prepareCreateDocument(_req,body){prepared++;bodies.push(body);return {async submit(){sent++;if(sent===1)throw new ApiUnknown(true);return {data:{document:document(2),revision_id:2}};}};}},async()=>detail({selected_document_id:3,documents:[document(1),document(2),document(3)]}),async identity=>selected.push(identity));
 const body={name:' 新设计 ',document_kind:'DESIGN',template_ref:null};
 assert.equal(await flow.create(body),false);body.name='外部修改';assert.equal(flow.getSnapshot().phase,'UNKNOWN');
 assert.equal(await flow.create(body),false);assert.equal(await flow.retryUnknown(),true);
 assert.equal(prepared,1);assert.equal(sent,2);assert.equal(bodies[0].name,'新设计');assert.deepEqual(selected,[]);flow.dispose();
});

test('known creation followed by failed refresh reuses only reads and selects its actual new document once',async()=>{
 let writes=0,reads=0;const selected=[];
 const flow=new DocumentDirectoryCommands(detail(),{prepareCreateDocument(){return {async submit(){writes++;return {data:{document:document(2),revision_id:2}};}};}},async()=>{if(++reads===1)throw Error('lost GET');return detail({documents:[document(1),document(2)]});},async identity=>selected.push(identity));
 assert.equal(await flow.create({name:'设计',document_kind:'DESIGN',template_ref:null}),false);
 assert.equal(flow.getSnapshot().phase,'CONFIRMED');const first=flow.finish(),second=flow.finish();assert.equal(first,second);assert.equal(await first,true);
 assert.equal(writes,1);assert.equal(reads,2);assert.deepEqual(selected,[2]);flow.dispose();
});

test('metadata targets its captured document and version while another document is read',async()=>{
 const bodies=[];
 const flow=new DocumentDirectoryCommands(detail({documents:[document(1),document(2)],selected_document_id:2}),{prepareUpdateDocument(identity,body){bodies.push({identity,body});return {async submit(){return {data:{document:{...document(1),metadata_version:2,name:'新名称'},event_id:7}};}};}},async()=>detail(),async()=>{throw Error('Metadata must not change reading selection');});
 assert.equal(await flow.metadata(document(1),{type:'RENAME',name:' 新名称 '}),true);
 assert.deepEqual(bodies,[{identity:1,body:{expected_metadata_version:1,change:{type:'RENAME',name:'新名称'}}}]);
 flow.adopt(detail({documents:[{...document(1),metadata_version:2}]}));assert.throws(()=>flow.metadata(document(1),{type:'ARCHIVE'}));flow.dispose();
});

test('recovery keys include all actual identities and reject cross-session reads before opening storage',async()=>{
 const binding={requirement_id:1,target_document_id:2,manual_draft_id:3,base_content_version:7};
 assert.deepEqual(recoveryStorageKey(binding),[1,2,3,7]);
 assert.notDeepEqual(recoveryStorageKey({...binding,target_document_id:4}),recoveryStorageKey(binding));
 assert.notDeepEqual(recoveryStorageKey({...binding,base_content_version:8}),recoveryStorageKey(binding));
 let opened=0;const store=new DraftRecoveryStore(undefined,binding,{factory:()=>{opened++;throw Error('must not open');}});
 await assert.rejects(store.get(1,4),/another actual edit session/);await assert.rejects(store.clearClosedDraft(2,3),/another actual edit session/);assert.equal(opened,0);store.close();
 assert.throws(()=>new DraftRecoveryStore(undefined,{...binding,manual_draft_id:2}));
});

test('the editor projection preserves the original body/version without taking ownership of metadata',()=>{
 const value={...document(1),created_at:at,template_ref:null,markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
 const core=editorReadModel(value);assert.deepEqual(Object.keys(core).sort(),['block_state_json','content_version','created_at','document_type','id','markdown_content','requirement_id','updated_at']);
 assert.equal(core.block_state_json,value.block_state_json);assert.equal(value.name,'文档1');assert.equal(core.name,undefined);
});
