import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementComments} from '../src/comments/read.ts';
import {locateComment} from '../src/comments/locate.ts';
const at='2026-10-06T04:00:00.000Z';
const current={id:2,requirement_id:1,document_type:'CURRENT',content_version:3,markdown_content:'实际正文',block_state_json:{blocks:[{block_id:7}]}};
const location={status:'ATTACHED',block_id:7,start_offset:null,end_offset:null};
const item=id=>({id,requirement_id:1,content:'评论'+id,anchor_type:'BLOCK',block_id:7,anchor_ref:{block_markdown_snapshot:'原引用'},anchor_status:'ATTACHED',status:'OPEN',resolved_at:null,deleted_at:null,created_at:at,updated_at:at,location});
const index=(items,document=current)=>({requirement_id:1,document_id:document.id,content_version:document.content_version,total_count:items.length,open_count:items.filter(row=>row.status==='OPEN').length,blocks:[{block_id:7,open_count:items.filter(row=>row.status==='OPEN'&&row.location.status==='ATTACHED').length,comment_ids:items.filter(row=>row.status==='OPEN'&&row.location.status==='ATTACHED').map(row=>row.id)}].filter(row=>row.open_count),comments:items.map(({id,status,anchor_status,location})=>({id,status,anchor_status,location}))});
const page=(items,number)=>({data:{items:items.slice((number-1)*20,number*20)},meta:{pagination:{page:number,page_size:20,total:items.length,total_pages:Math.ceil(items.length/20)}}});
const port=rows=>({getCommentIndex:async()=>({data:index(rows)}),listComments:async(_id,number)=>page(rows,number),getComment:async id=>({data:rows.find(row=>row.id===id)})});
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const deferred=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};

test('whole I37 markers differ from actual page; off-page I28 locates actual page without inserting or reordering',async()=>{
 const rows=Array.from({length:25},(_,i)=>item(i+1)),reader=new RequirementComments(current,port(rows));
 assert(await reader.refresh());assert.equal(reader.getSnapshot().confirmed.items.length,20);assert.equal(reader.getSnapshot().confirmed.index.blocks[0].open_count,25);
 assert(await reader.select(25));const state=reader.getSnapshot();assert.equal(state.confirmed.pagination.page,2);assert.deepEqual(state.confirmed.items.map(row=>row.id),[21,22,23,24,25]);assert.equal(state.selected,25);
 assert.equal(reader.located(25).comment.id,25);assert.equal(reader.located(1),null);reader.dispose();
});
test('concurrent deletion crossing page boundary rereads actual index/page; bounded changes retain last page and disable navigation',async()=>{
 let rows=Array.from({length:25},(_,i)=>item(i+1)),calls=0,race=false;const api={...port(rows),getCommentIndex:async()=>({data:index(rows)}),listComments:async(_id,number)=>{calls++;if(race){race=false;rows=rows.slice(1);}return page(rows,number);}};
 const reader=new RequirementComments(current,api);assert(await reader.refresh());race=true;assert(await reader.select(21));assert.equal(reader.getSnapshot().confirmed.pagination.page,1);assert.equal(reader.getSnapshot().confirmed.items.at(-1).id,21);assert.equal(calls,3);
 const saved=reader.getSnapshot().confirmed;api.getCommentIndex=async()=>({data:index(rows)});api.listComments=async(_id,number)=>{rows=rows.slice(1);return page(rows,number);};assert(!await reader.refresh());assert.equal(reader.getSnapshot().confirmed,saved);assert(!reader.ready);assert.equal(reader.located(21),null);reader.dispose();
});
test('stored anchor status differs from current location; orphan still readable but cannot navigate; soft-delete I28 is not a list row',async()=>{
 const rows=[{...item(1),anchor_status:'ORPHANED'}, {...item(2),location:{status:'ORPHANED',block_id:null,start_offset:null,end_offset:null}}];
 const api=port(rows),reader=new RequirementComments(current,api);assert(await reader.refresh());assert.equal(reader.located(1).comment.id,1);assert.equal(reader.located(2),null);
 api.getComment=async id=>({data:{...item(id),deleted_at:at}});assert(!await reader.select(2));assert.match(reader.getSnapshot().error,/已删除/);assert.equal(reader.getSnapshot().confirmed.items.length,2);reader.dispose();
});
test('old page survives failed GET; wrong document/version/block projection is rejected; actual new CURRENT needs new read',async()=>{
 const rows=[item(1)],api=port(rows),reader=new RequirementComments(current,api);assert(await reader.refresh());const saved=reader.getSnapshot().confirmed;
 api.listComments=async()=>{throw Error('read');};assert(!await reader.refresh(2));assert.equal(reader.getSnapshot().page,2);assert.equal(reader.getSnapshot().confirmed.pagination.page,1);assert.equal(reader.getSnapshot().confirmed,saved);
 api.listComments=async(_id,number)=>page(rows,number);api.getCommentIndex=async()=>({data:{...index(rows),document_id:99}});assert(!await reader.refresh(1));assert.equal(reader.getSnapshot().confirmed,saved);
 const next={...current,content_version:4};reader.setCurrent(next);assert(!reader.ready);api.getCommentIndex=async()=>({data:index(rows,next)});assert(await reader.refresh());assert(reader.ready);assert.equal(reader.getSnapshot().confirmed.current.content_version,4);
 api.getCommentIndex=async()=>({data:{...index(rows,next),blocks:[{block_id:99,open_count:1,comment_ids:[1]}]}});assert(!await reader.refresh());reader.dispose();assert.throws(()=>new RequirementComments({...current,document_type:'MANUAL_DRAFT'},api));
});
test('owned abort/generations suppress late pages and retirement before first HTTP; inactive page retains actual data',async()=>{
 const hold=deferred(),rows=[item(1)];let calls=0,signal;const api={...port(rows),getCommentIndex:async(_id,owned)=>{calls++;signal=owned;return hold.promise;}};
 const reader=new RequirementComments(current,api),pending=reader.refresh();await flush();reader.pause();assert(signal.aborted);hold.resolve({data:index(rows)});assert(!await pending);assert.equal(reader.getSnapshot().confirmed,null);assert(!reader.getSnapshot().active);
 api.getCommentIndex=async()=>({data:index(rows)});assert(await reader.refresh());reader.pause();assert.equal(reader.getSnapshot().confirmed.items.length,1);assert(!reader.ready);reader.dispose();const retired=new RequirementComments(current,api),queued=retired.refresh();retired.dispose();assert(!await queued);assert.equal(calls,1);
});
test('navigation rejects manual/history/cross-version; original selection offsets/context are passed without trim or truncation',async()=>{
 const selection={...item(1),anchor_type:'SELECTION',anchor_ref:{selected_text:' 😀 ',prefix_text:'前',suffix_text:'后'},location:{...location,start_offset:1,end_offset:4}};
 const reader=new RequirementComments(current,port([selection]));assert(await reader.refresh());let located=null,block=null;
 const editor={valid:true,loadedDocument:current,locate:event=>located=event},nav={getSnapshot:()=>({content:{kind:'CURRENT'}}),locate:id=>{block=id;return true;}};
 assert(locateComment(reader,editor,nav,1));assert.equal(located.selected_text,' 😀 ');assert.equal(located.start_offset,1);assert.equal(block,7);
 editor.loadedDocument={...current,document_type:'MANUAL_DRAFT'};assert(!locateComment(reader,editor,nav,1));editor.loadedDocument={...current,content_version:4};assert(!locateComment(reader,editor,nav,1));editor.loadedDocument=current;nav.getSnapshot=()=>({content:{kind:'REVISION'}});assert(!locateComment(reader,editor,nav,1));reader.dispose();
});
