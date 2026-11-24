import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FormationPathEditor } from '../src/formation/path-editor.ts';
import { FormationDrafts } from '../src/formation/drafts.ts';
const original = {
  type:'RENAME_STEP',step_ref:'s2',title:'邀请有效期',
};
function recovery(change=original) {
  let version=1, listener=()=>{}, stored=null;
  const preview=[],writes=[];
  const owner={requirementId:1,documentId:2,discussionVersion:2,contentVersion:1,writeReason:null,
    read:{getSnapshot:()=>({summary:{data:{formation_version:version}}})},
    getSnapshot:()=>({phase:'IDLE',pending:[]}), subscribe(fn){listener=fn;return ()=>{}},
    api:{previewFormationPath:async(_r,_d,body,_query,signal)=>new Promise(resolve=>preview.push({body,signal,resolve}))},
    execute:async(command)=>{writes.push(command);return true}
  };
  const drafts=new FormationDrafts(1,2,'http://localhost:5173',()=>({getItem:()=>stored,setItem:(_k,v)=>stored=v}));
  drafts.load();
  drafts.savePath({schema_version:1,owner_key:drafts.ownerKey,base_D:2,base_F:1,base_V:1,based_on_proposal:null,
    changes:[change],result_routes:[],reason:'之前暂存的调整',updated_at:'2026-11-22T10:00:00.000Z'});
  const editor=new FormationPathEditor(owner,drafts);
  return {drafts,editor,writes,preview,changeVersion(){version++;listener()}};
}
test('stored valid route draft can only save its exact payload after a matching preview',async()=>{
  const f=recovery();
  try{
    assert.equal(f.editor.canSave,false);
    const request=f.editor.preview();
    assert.deepEqual(f.preview[0].body.discussion_command.changes,[original]);
    f.preview[0].resolve({data:{}});
    assert.equal(await request,true);
    assert.equal(await f.editor.save(),true);
    assert.deepEqual(f.writes[0].changes,[original]);
    assert.equal(f.drafts.readPath(),null);
  }finally{f.editor.dispose()}
});
test('late preview or stale version cannot authorize a stored draft',async()=>{
  const f=recovery();
  try{
    const request=f.editor.preview();
    f.changeVersion();
    assert.equal(f.preview[0].signal.aborted,true);
    f.preview[0].resolve({data:{}});
    assert.equal(await request,false);
    assert.equal(await f.editor.save(),false);
    assert.equal(f.writes.length,0);
    assert.deepEqual(f.drafts.readPath().changes,[original]);
  }finally{f.editor.dispose()}
});
test('incomplete historic draft remains readable without a preview or write', async()=>{
  const f=recovery({type:'RENAME_STEP',step_ref:'s2',title:''});
  try{
    assert.ok(f.editor.validation);
    assert.equal(await f.editor.preview(),false);
    assert.equal(f.editor.getSnapshot().changes[0].value.title,'');
    assert.equal(f.preview.length,0);
  }finally{f.editor.dispose()}
});
