import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiClient,ApiRejected} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';

const key='00000000-0000-4000-8000-000000000001';
const pair={markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]}};
test('manual save, cancel and complete transport the formal draft_id and preserve the original keyed request',async()=>{
 for(const method of ['save','cancel','complete']){
  const wires=[],api=new WalleApi(new ApiClient(async(path,init)=>{
   wires.push({path,init});return new Response(JSON.stringify({success:false,data:null,error:{code:'WORK_STATE_CONFLICT',message:'会话已变化',details:null},meta:{request_id:key}}),{status:409,headers:{'Content-Type':'application/json'}});
  },()=>key),null);
  const expected={document_id:2,draft_id:9,expected_version:4};
  const action=method==='save'?api.prepareSaveManualDraft(1,{...expected,...pair}):
   method==='cancel'?api.prepareCancelManualDraft(1,2,9,4):api.prepareCompleteManualDraft(1,2,9,4);
  await assert.rejects(action.submit(),ApiRejected);await assert.rejects(action.submit(),ApiRejected);
  assert.deepEqual(wires[0],wires[1]);
  assert.deepEqual(JSON.parse(wires[0].init.body),method==='save'?{...expected,...pair}:expected);
  assert.equal(new Headers(wires[0].init.headers).get('Idempotency-Key'),key);
  assert.equal(wires[0].init.method,{save:'PUT',cancel:'DELETE',complete:'POST'}[method]);
  assert.equal(wires[0].path,'/api/v1/requirements/1/manual-draft'+(method==='complete'?'/complete':''));
 }
});
