import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementCommentPanel} from '../src/comments/panel-owner.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const at='2026-10-06T04:00:00.000Z',location={status:'ATTACHED',block_id:7,start_offset:null,end_offset:null};
const item=id=>({id,requirement_id:1,content:'评论'+id,anchor_type:'BLOCK',block_id:7,anchor_ref:{block_markdown_snapshot:'原引用'},anchor_status:'ATTACHED',status:'OPEN',resolved_at:null,deleted_at:null,created_at:at,updated_at:at,location});
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:3,markdown_content:'实际正文',block_state_json:{blocks:[{block_id:7},{block_id:8}]}};
const detail={requirement:{id:1,status:'ACTIVE',document_work_state:'IDLE'},current,activity:{kind:'IDLE'},comment_index:{}};
const target={document_id:2,content_version:3,block_id:7,anchor_type:'BLOCK',selection:null,quote:'原引用'};
const defer=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
function fixture(count=25){
 const facts={rows:Array.from({length:count},(_,i)=>item(i+1)),detail,reads:0,adopts:0,lists:0,drop:false};
 const api={getCommentIndex:async()=>{const rows=facts.rows,open=rows.filter(row=>row.status==='OPEN');return {data:{requirement_id:1,document_id:2,content_version:facts.detail.current.content_version,total_count:rows.length,open_count:open.length,blocks:open.length?[{block_id:7,open_count:open.length,comment_ids:open.map(row=>row.id)}]:[],comments:rows.map(({id,status,anchor_status,location})=>({id,status,anchor_status,location}))}};},
 listComments:async(_id,page)=>{facts.lists++;if(facts.drop){facts.drop=false;throw Error('Dropped list');}return {data:{items:facts.rows.slice((page-1)*20,page*20)},meta:{pagination:{page,page_size:20,total:facts.rows.length,total_pages:Math.ceil(facts.rows.length/20)}}};},
 getComment:async id=>({data:facts.rows.find(row=>row.id===id)})};
 const read=async()=>{facts.reads++;return facts.detail;},adopt=async()=>{facts.adopts++;};
 return {facts,api,read,adopt};
}
test('one retained edit per comment survives page changes; only actual visible row can rebase and permit another write',async()=>{
 const f=fixture(),panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async()=>{});await panel.refresh();
 const flow=panel.begin(1,'EDIT');flow.change('保留原输入');assert.equal(panel.begin(1,'DELETE'),flow);assert(panel.writable(flow));
 assert(await panel.page(2));assert.equal(panel.slot(1).flow,flow);assert.equal(flow.getSnapshot().content,'保留原输入');assert(!panel.writable(flow));
 f.facts.rows[0]={...item(1),status:'RESOLVED',resolved_at:at};assert(await panel.select(1));assert(!flow.allowed);assert(!panel.writable(flow));assert.equal(flow.getSnapshot().content,'保留原输入');
 assert.equal(panel.comments.getSnapshot().selection_revision,1);await panel.refresh();assert.equal(panel.comments.getSnapshot().selection_revision,1);await panel.select(1);assert.equal(panel.comments.getSnapshot().selection_revision,2);panel.dispose();
});
test('explicit rescope preserves raw composer input, but UNKNOWN original intent cannot be replaced or inferred by matching GET',async()=>{
 const f=fixture(1);let sends=0,prepares=0;f.api.prepareCreateComment=(_id,body)=>{prepares++;return {submit:async()=>{sends++;if(sends===1)throw new ApiUnknown(true);return {data:{...item(2),content:body.content}};}};};
 const panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async()=>{});await panel.refresh();const first=panel.create(target);first.change(' 原始\r\n内容😀 ');
 const scoped=panel.create({...target,block_id:8,quote:'另一引用'});assert.notEqual(scoped,first);assert.equal(scoped.getSnapshot().content,' 原始\r\n内容😀 ');assert.equal(panel.create({...target,block_id:8,quote:'另一引用'}),scoped);
 // Re-select the actual original block before sending; the raw input survives.
 const flow=panel.create(target);assert(!await flow.submit());assert(panel.close(flow));assert(!panel.slot(null).open);assert.equal(panel.create({...target,block_id:8,quote:'另一引用'}),flow);assert.equal(panel.slot(null).flow.intent.target.block_id,7);
 const before=f.facts.adopts;assert(await flow.retryUnknown(panel.observe));assert.equal(f.facts.adopts,before);assert.equal(panel.slot(null).flow,flow);assert.equal(prepares,1);assert.equal(sends,2);panel.dispose();
});
test('positive list adoption failure keeps confirmed owner; exact receipt retry is GET only and never repeats write',async()=>{
 const f=fixture(1);let sends=0;f.api.prepareEditComment=(_id,content)=>({submit:async()=>{sends++;f.facts.rows[0]={...item(1),content};return {data:f.facts.rows[0]};}});
 const panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async()=>{});await panel.refresh();const flow=panel.begin(1,'EDIT');flow.change('新正文');assert(await flow.submit());const outcome=flow.getSnapshot().outcome;
 await assert.rejects(panel.finish(flow,{...outcome}),/Original confirmed/);f.facts.drop=true;await assert.rejects(panel.finish(flow,outcome),/列表/);assert.equal(panel.slot(1).flow,flow);assert.equal(flow.getSnapshot().phase,'CONFIRMED');assert.equal(sends,1);
 await panel.finish(flow,outcome);assert.equal(panel.slot(1),null);assert.equal(sends,1);assert.equal(panel.comments.getSnapshot().confirmed.items[0].content,'新正文');panel.dispose();
});
test('GUIDE delivery acknowledges once, even when subsequent actual parent/page adoption fails',async()=>{
 const f=fixture(1),run={id:9,requirement_id:1,source_type:'COMMENT',source_id:1,function_type:'MODIFY_FROM_COMMENT',action_type:'MODIFY',status:'RUNNING',current_step:'PREPARING',scope:{scope_type:'BLOCK',scope_ref:{block_id:7}}};let deliveries=0,sends=0;
 f.api.prepareModifyFromComment=()=>({submit:async()=>{sends++;return {data:run};}});const panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async actual=>{assert.equal(actual.id,9);deliveries++;});await panel.refresh();
 const flow=panel.begin(1,'MODIFY');assert(await flow.submit());f.facts.drop=true;await assert.rejects(panel.finish(flow,flow.getSnapshot().outcome));assert.equal(deliveries,1);await panel.finish(flow,flow.getSnapshot().outcome);assert.equal(deliveries,1);assert.equal(sends,1);assert.equal(f.facts.rows[0].status,'OPEN');panel.dispose();
});
test('unacknowledged Guide receiver failure retains original receipt and can retry the same Run before any parent adoption',async()=>{
 const f=fixture(1),run={id:9,requirement_id:1,source_type:'COMMENT',source_id:1,function_type:'MODIFY_FROM_COMMENT',action_type:'MODIFY',status:'RUNNING',current_step:'PREPARING',scope:{scope_type:'BLOCK',scope_ref:{block_id:7}}};let calls=0,accepted=null;
 f.api.prepareModifyFromComment=()=>({submit:async()=>({data:run})});const panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async actual=>{calls++;accepted??=actual.id;assert.equal(actual.id,accepted);if(calls===1)throw Error('Receiver adoption incomplete');});await panel.refresh();
 const flow=panel.begin(1,'MODIFY');assert(await flow.submit());await assert.rejects(panel.finish(flow,flow.getSnapshot().outcome),/incomplete/);assert.equal(f.facts.adopts,1);assert.equal(panel.slot(1).flow,flow);await panel.finish(flow,flow.getSnapshot().outcome);assert.equal(calls,2);assert.equal(accepted,9);assert.equal(panel.slot(1),null);panel.dispose();
});
test('history while parent read is pending suppresses adoption and retains confirmed receipt for fresh restoration',async()=>{
 const f=fixture(1),hold=defer();let waiting=false;f.api.prepareResolveComment=()=>({submit:async()=>{f.facts.rows[0]={...item(1),status:'RESOLVED',resolved_at:at};return {data:f.facts.rows[0]};}});
 const panel=new RequirementCommentPanel(detail,f.api,()=>waiting?hold.promise:f.read(),f.adopt,async()=>{});await panel.refresh();const flow=panel.begin(1,'RESOLVE');assert(await flow.submit());waiting=true;
 const pending=panel.finish(flow,flow.getSnapshot().outcome),rejected=assert.rejects(pending,/Retired comment observation/);await flush();panel.setView('HISTORY');hold.resolve(detail);await rejected;assert.equal(f.facts.adopts,1);assert.equal(panel.slot(1).flow,flow);assert(!panel.comments.ready);
 waiting=false;panel.setView('CURRENT');assert(!panel.writeReady);await panel.finish(flow,flow.getSnapshot().outcome);assert.equal(panel.slot(1),null);assert.equal(f.facts.adopts,2);panel.dispose();
});
test('known concurrency error requires fresh complete detail/page, retains input and observes actual resolved permission',async()=>{
 const f=fixture(1);f.api.prepareEditComment=()=>({submit:async()=>{throw new ApiRejected('STATE_CONFLICT','已解决',null,'request',409);}});
 const panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async()=>{});await panel.refresh();const flow=panel.begin(1,'EDIT');flow.change('保留编辑');assert(!await flow.submit());assert(panel.getSnapshot().needs_refresh);assert(!panel.writeReady);
 f.facts.rows[0]={...item(1),status:'RESOLVED',resolved_at:at};await panel.refresh();assert(!panel.getSnapshot().needs_refresh);assert(!panel.writable(flow));assert.equal(flow.getSnapshot().content,'保留编辑');assert(panel.close(flow));assert(panel.begin(1,'REOPEN'));panel.dispose();
});
test('retirement cancels queued parent reads and never substitutes an actual observation from another requirement',async()=>{
 const f=fixture(1),panel=new RequirementCommentPanel(detail,f.api,f.read,f.adopt,async()=>{});const queued=panel.refresh(),rejected=assert.rejects(queued);panel.dispose();await rejected;assert.equal(f.facts.reads,0);
 const wrong=new RequirementCommentPanel(detail,f.api,async()=>({...detail,requirement:{...detail.requirement,id:99}}),f.adopt,async()=>{});await assert.rejects(wrong.observe(),/Owned/);assert.equal(f.facts.adopts,0);wrong.dispose();
});
