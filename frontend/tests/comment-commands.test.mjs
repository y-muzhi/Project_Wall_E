import {test} from 'node:test';
import assert from 'node:assert/strict';
import {CommentCommand} from '../src/comments/commands.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-06T04:00:00.000Z',detail={requirement:{id:1,status:'ACTIVE',document_work_state:'IDLE'},current:{id:2,requirement_id:1,document_type:'CURRENT',content_version:3,block_state_json:{blocks:[{block_id:7}]}},activity:{kind:'IDLE'},comment_index:{}};
const item={id:5,requirement_id:1,content:'原评论',anchor_type:'BLOCK',block_id:7,anchor_ref:{block_markdown_snapshot:'原引用'},anchor_status:'ATTACHED',status:'OPEN',resolved_at:null,deleted_at:null,created_at:at,updated_at:at,location:{status:'ATTACHED',block_id:7,start_offset:null,end_offset:null}};
const target={document_id:2,content_version:3,block_id:7,anchor_type:'BLOCK',selection:null,quote:'原引用'};
test('create/edit exact existing request fields, Unicode 2000 boundary, raw input retained and one submit owner',async()=>{
 let prepared,send=0;const api={prepareCreateComment:(id,body)=>{prepared={id,body};return {submit:async()=>{send++;return {data:{...item,id:6,content:body.content}};}};}};
 const flow=new CommentCommand(detail,{kind:'CREATE',target},api);flow.change('😀'.repeat(2001));assert(!await flow.submit());assert.equal(send,0);flow.change(' \r\n'+'😀'.repeat(2000)+'\u0085');const pending=flow.submit();assert.equal(pending,flow.submit());assert(await pending);assert.equal([...prepared.body.content].length,2000);assert.deepEqual(Object.keys(prepared.body).sort(),['anchor_type','block_id','content','expected_content_version']);assert.equal(prepared.body.expected_content_version,3);assert.equal(flow.getSnapshot().content,prepared.body.content);assert(!await flow.submit());flow.dispose();
 let patch;const edit=new CommentCommand(detail,{kind:'EDIT',comment:item},{prepareEditComment:(id,content)=>{patch={id,content};return {submit:async()=>({data:{...item,content}})};}});edit.change(' 修改\r\n纯文本 ');assert(await edit.submit());assert.deepEqual(patch,{id:5,content:'修改\n纯文本'});edit.dispose();
});
test('unknown edit first observes matching GET without declaring success, original opaque action replay, read failure does not send',async()=>{
 let prepares=0,sends=0,reads=0,fail=true;const api={prepareEditComment:()=>{prepares++;return {submit:async()=>{sends++;if(sends===1)throw new ApiUnknown(true);return {data:{...item,content:'新评论'}};}};},getComment:async()=>{reads++;return {data:{...item,content:'新评论'}};}};
 const flow=new CommentCommand(detail,{kind:'EDIT',comment:item},api);flow.change('新评论');assert(!await flow.submit());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert(!flow.rebase({...detail,requirement:{...detail.requirement,status:'COMPLETED'}}));flow.change('丢失原文');assert.equal(flow.getSnapshot().content,'新评论');
 const observe=async()=>{if(fail)throw Error('GET failed');return {...detail,requirement:{...detail.requirement,status:'COMPLETED'}};};assert(!await flow.retryUnknown(observe));assert.equal(sends,1);fail=false;assert(await flow.retryUnknown(observe));assert.equal(flow.getSnapshot().observed.comment.content,'新评论');assert.equal(prepares,1);assert.equal(sends,2);assert.equal(reads,1);flow.dispose();
});
test('resolve/reopen/delete independent anchor status; soft-delete GET cannot prove own success, known failures keep actual input',async()=>{
 for(const [kind,status,resolved,deleted] of [['RESOLVE','RESOLVED',at,null],['REOPEN','OPEN',null,null],['DELETE','OPEN',null,at]]){
   const comment={...item,status:kind==='REOPEN'?'RESOLVED':'OPEN',resolved_at:kind==='REOPEN'?at:null,anchor_status:'ORPHANED',location:{status:'ORPHANED',block_id:null,start_offset:null,end_offset:null}},method={RESOLVE:'prepareResolveComment',REOPEN:'prepareReopenComment',DELETE:'prepareDeleteComment'}[kind];let sends=0;
   const flow=new CommentCommand(detail,{kind,comment},{[method]:()=>({submit:async()=>{sends++;if(sends===1)throw new ApiUnknown(true);return {data:{...comment,status,resolved_at:resolved,deleted_at:deleted}};}}),getComment:async()=>({data:{...comment,status,resolved_at:resolved,deleted_at:deleted}})});
   assert(!await flow.submit());assert(await flow.retryUnknown(async()=>detail));assert.equal(sends,2);assert.equal(flow.getSnapshot().outcome.comment.anchor_status,'ORPHANED');flow.dispose();
 }
 const flow=new CommentCommand(detail,{kind:'EDIT',comment:item},{prepareEditComment:()=>({submit:async()=>{throw new ApiRejected('STATE_CONFLICT','已删除',null,'request',409);}})});flow.change('保留输入');assert(!await flow.submit());assert.equal(flow.getSnapshot().phase,'ERROR');assert.equal(flow.getSnapshot().content,'保留输入');flow.dispose();
});
test('create selection carries original exact strings only; stale CURRENT after actual rebase disables creation',async()=>{
 const selection={document_id:2,content_version:3,block_id:7,start_offset:1,end_offset:4,selected_text:' 😀 ',prefix_text:'前',suffix_text:'后'};let body;
 const flow=new CommentCommand(detail,{kind:'CREATE',target:{...target,anchor_type:'SELECTION',selection,quote:' 😀 '}},{prepareCreateComment:(_id,input)=>{body=input;return {submit:async()=>({data:{...item,content:input.content,anchor_type:'SELECTION',anchor_ref:{selected_text:' 😀 ',prefix_text:'前',suffix_text:'后'}}})};}});flow.change('选区评论');assert(await flow.submit());assert.deepEqual(body.selection,{selected_text:' 😀 ',prefix_text:'前',suffix_text:'后'});assert.equal(body.selection.start_offset,undefined);flow.dispose();
 const stale=new CommentCommand(detail,{kind:'CREATE',target},{});assert(stale.rebase({...detail,current:{...detail.current,content_version:4}}));assert(!stale.allowed);assert(!await stale.submit());stale.dispose();assert.throws(()=>new CommentCommand(detail,{kind:'CREATE',target:{...target,document_id:99}},{}));
});
test('MODIFY sends only original comment ID/current version, validates real source/scope, never resolves comment',async()=>{
 let input;const run={id:9,requirement_id:1,source_type:'COMMENT',source_id:5,function_type:'MODIFY_FROM_COMMENT',action_type:'MODIFY',status:'RUNNING',current_step:'PREPARING',scope:{scope_type:'BLOCK',scope_ref:{block_id:7}}};
 const flow=new CommentCommand(detail,{kind:'MODIFY',comment:item},{prepareModifyFromComment:(id,version)=>{input={id,version};return {submit:async()=>({data:run})};}});assert(await flow.submit());assert.deepEqual(input,{id:5,version:3});assert.equal(flow.getSnapshot().outcome.kind,'GUIDE');assert.equal(item.status,'OPEN');flow.dispose();
 assert.throws(()=>new CommentCommand(detail,{kind:'MODIFY',comment:{...item,anchor_status:'ORPHANED'}},{}));assert.throws(()=>new CommentCommand(detail,{kind:'MODIFY',comment:{...item,location:{status:'ORPHANED',block_id:null,start_offset:null,end_offset:null}}},{}));assert.throws(()=>new CommentCommand({...detail,requirement:{...detail.requirement,status:'COMPLETED'}},{kind:'EDIT',comment:item},{}));
});
test('retired queued action does not send; unexpected positive projection stays UNKNOWN for original recovery',async()=>{
 let sends=0;const api={prepareEditComment:()=>({submit:async()=>{sends++;return {data:{...item,content:'different'}};}})};
 const retired=new CommentCommand(detail,{kind:'EDIT',comment:item},api),queued=retired.submit();retired.dispose();assert(!await queued);assert.equal(sends,0);
 const flow=new CommentCommand(detail,{kind:'EDIT',comment:item},api);flow.change('期待');assert(!await flow.submit());assert.equal(flow.getSnapshot().phase,'UNKNOWN');assert.equal(flow.getSnapshot().outcome,null);flow.dispose();
});
test('creation requires actual original quote, and editing cannot accept a soft-deleted positive row',async()=>{
 const create=new CommentCommand(detail,{kind:'CREATE',target},{prepareCreateComment:()=>({submit:async()=>({data:{...item,content:'评论',anchor_ref:{block_markdown_snapshot:'另一份原文'}}})})});create.change('评论');assert(!await create.submit());assert.equal(create.getSnapshot().phase,'UNKNOWN');create.dispose();
 const edit=new CommentCommand(detail,{kind:'EDIT',comment:item},{prepareEditComment:()=>({submit:async()=>({data:{...item,content:'评论',deleted_at:at}})})});edit.change('评论');assert(!await edit.submit());assert.equal(edit.getSnapshot().phase,'UNKNOWN');edit.dispose();
});
test('known failure rebase needs actual same comment and respects its latest status without dropping edit input',async()=>{
 const flow=new CommentCommand(detail,{kind:'EDIT',comment:item},{});flow.change('保留编辑');assert(!flow.rebase(detail));assert(flow.rebase(detail,{...item,status:'RESOLVED',resolved_at:at}));assert(!flow.allowed);assert(!await flow.submit());assert.equal(flow.getSnapshot().content,'保留编辑');assert.throws(()=>flow.rebase(detail,{...item,id:99}));flow.dispose();
});
