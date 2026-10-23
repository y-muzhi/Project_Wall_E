import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiUnknown,ApiClient} from '../src/api/client.ts';
import {WalleApi} from '../src/api/walle.ts';
import {CommentCommand} from '../src/comments/commands.ts';
const at='2026-10-22T00:00:00.000Z';
const detail=(document=2,version=7)=>({requirement:{id:1,status:'CLOSED',discussion_version:4,document_work_state:'IDLE'},current:{id:document,requirement_id:1,document_type:'CURRENT',content_version:version,archived_at:null,block_state_json:{blocks:[{block_id:1}]}},activity:{kind:'IDLE'}});
const comment={id:1,requirement_id:1,document_id:2,content:'按此评论提出建议',anchor_type:'BLOCK',block_id:1,anchor_ref:{block_markdown_snapshot:'原文'},anchor_status:'ATTACHED',status:'OPEN',resolved_at:null,deleted_at:null,created_at:at,updated_at:at,location:{status:'ATTACHED',block_id:1,start_offset:null,end_offset:null}};
const receipt={processing:'MODEL',guide_run_id:9,user_message_id:22};
test('comment proposal keeps the actual document/discussion versions and original request while another document is observed',async()=>{
 const prepared=[];let sends=0;const api={prepareModifyFromComment(...args){prepared.push(args);return {async submit(){sends++;if(sends===1)throw new ApiUnknown(true);return {data:receipt};}};},async getComment(){return {data:comment};}};
 const owner=new CommentCommand(detail(),{kind:'MODIFY',comment},api);
 assert.equal(await owner.submit(),false);assert.equal(owner.getSnapshot().phase,'UNKNOWN');
 assert.equal(await owner.retryUnknown(async()=>detail(3,99)),true);assert.equal(owner.getSnapshot().phase,'CONFIRMED');
 assert.deepEqual(prepared,[[1,7,4]]);assert.equal(sends,2);assert.equal(owner.getSnapshot().outcome.document_id,2);assert.deepEqual(owner.getSnapshot().outcome.receipt,receipt);owner.dispose();
});
test('a comment cannot use another reading document as its owner or silently rebase onto it',()=>{
 const api={};assert.throws(()=>new CommentCommand(detail(3),{kind:'MODIFY',comment},api));
 const owner=new CommentCommand(detail(),{kind:'MODIFY',comment},api);assert.equal(owner.rebase(detail(3),comment),false);assert.equal(owner.allowed,true);owner.dispose();
});
test('the comment API transports two versions and a MODEL receipt rather than manufacturing a full run',async()=>{
 const requests=[],key='00000000-0000-4000-8000-000000000001';
 const api=new WalleApi(new ApiClient(async(path,init)=>{requests.push({path,init});return new Response(JSON.stringify({success:true,data:receipt,error:null,meta:{request_id:key}}),{status:202,headers:{'Content-Type':'application/json'}});},()=>key),null);
 assert.deepEqual((await api.prepareModifyFromComment(1,7,4).submit()).data,receipt);
 assert.equal(requests[0].path,'/api/v1/comments/1/guide-runs');assert.deepEqual(JSON.parse(requests[0].init.body),{expected_content_version:7,expected_discussion_version:4});
});
