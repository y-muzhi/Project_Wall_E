import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiRejected,ApiUnknown} from '../src/api/client.ts';
import {batch as decodeBatch} from '../src/api/models.ts';
import {RequirementSuggestionBatch} from '../src/suggestions/batch-owner.ts';
const at='2026-10-06T06:00:00.000Z';
const copy=value=>structuredClone(value);
function suggestion(id,operation='REPLACE_BLOCK'){
 return {id,batch_id:8,order_no:id-9,title:'调整规则',explanation:'明确规则',impact:null,patch_operation:operation,target_ref:{block_id:id},selector:operation==='REPLACE_TABLE_ROW'?{key_column_index:0,key_value:'key'}:null,original_content:operation==='REPLACE_TABLE_ROW'?'| key | 原值 |\n':'原值\n',proposed_markdown:['DELETE_BLOCK','REPLACE_TABLE_ROW'].includes(operation)?null:'新值\n',proposed_data:operation==='REPLACE_TABLE_ROW'?{cells:['key','新值']}:null,user_edited_content:null,status:'PENDING',validation_status:'VALID',validation_error:null,created_at:at,decided_at:null,updated_at:at};
}
function counts(items){return {total:items.length,...Object.fromEntries(['PENDING','ACCEPTED','REJECTED','EDITED'].map(status=>[status.toLowerCase(),items.filter(item=>item.status===status).length]))};}
function batch(items=[suggestion(10),suggestion(11,'DELETE_BLOCK'),suggestion(12,'REPLACE_TABLE_ROW')]){
 return decodeBatch({id:8,requirement_id:1,guide_run_id:6,source_type:'USER_INSTRUCTION',source_id:null,title:'批次',summary:'明确隔离端口夹具',status:'PENDING',completion_result:null,error_message:null,base_content_version:2,applied_content_version:null,created_at:at,completed_at:null,updated_at:at,suggestions:items,counts:counts(items)});
}
function detail(value,currentVersion=2){return {requirement:{id:1,status:'ACTIVE',document_work_state:value.status==='PENDING'?'SUGGESTION_REVIEWING':'IDLE',active_operation_type:value.status==='PENDING'?'SUGGESTION_BATCH':null,active_operation_id:value.status==='PENDING'?value.id:null},current:{id:2,requirement_id:1,document_type:'CURRENT',content_version:currentVersion,markdown_content:'原正文\n',block_state_json:{schema_version:1,next_block_id:13,blocks:[]}},activity:value.status==='PENDING'?{kind:'BATCH',batch:value}:{kind:'IDLE'},comment_index:{}};}
async function fixture(){
 const f={batch:batch(),version:2,prepares:[],sends:0,reads:0,queries:0,adopts:0,sequence:[],drop:false,failRead:false,failAdopt:false,rejection:null,hold:null,receiptChange:null};
 const actual=()=>detail(f.batch,f.version);
 const prepare=(kind,id,body=null)=>{f.prepares.push({kind,id,body:copy(body)});let receipt;return {submit:async()=>{f.sends++;f.sequence.push('send');if(f.hold)await f.hold;if(f.rejection)throw f.rejection;if(!receipt){
  const next=copy(f.batch);if(kind==='DECIDE'){const item=next.suggestions.find(item=>item.id===id);item.status=body.decision;item.user_edited_content=body.edited_content;item.decided_at=at;next.counts=counts(next.suggestions);receipt={suggestion:copy(item),counts:next.counts};}
  else{next.status=kind==='COMPLETE'?'COMPLETED':'DISCARDED';next.completed_at=at;next.completion_result=kind==='COMPLETE'?(f.change?'CHANGES_APPLIED':'NO_CHANGE'):null;next.applied_content_version=f.change&&kind==='COMPLETE'?3:null;if(next.applied_content_version)f.version=3;const {suggestions,counts,...metadata}=next;receipt={batch:metadata,counts,...(kind==='COMPLETE'?{current_document:actual().current}: {})};if(kind==='COMPLETE')receipt.current_document={...actual().current,content_version:f.version};}
  f.batch=decodeBatch(next);if(f.receiptChange)receipt=f.receiptChange(receipt);
 }if(f.drop){f.drop=false;throw new ApiUnknown(true);}return {data:copy(receipt)};}};};
 const api={getBatch:async()=>{f.queries++;f.sequence.push('batch');return {data:f.batch};},prepareDecideSuggestion:(id,body)=>prepare('DECIDE',id,body),prepareCompleteBatch:(id,version)=>prepare('COMPLETE',id,{expected_content_version:version}),prepareDiscardBatch:id=>prepare('DISCARD',id)};
 const owner=new RequirementSuggestionBatch(8,actual(),api,async()=>{f.reads++;f.sequence.push('detail');if(f.failRead)throw Error('Unavailable');return actual();},async()=>{f.adopts++;if(f.failAdopt)throw Error('Adoption unavailable');});owner.setAvailable(true);assert(await owner.refresh());return {f,owner,actual,api};
}
test('actual I20 full read, immutable ordering/counts, owner occupancy and hidden/terminal permissions',async()=>{
 const {f,owner,actual}=await fixture();assert.deepEqual(owner.getSnapshot().batch.suggestions.map(item=>item.id),[10,11,12]);assert(!owner.canComplete);assert(owner.canDiscard);owner.setAvailable(false);assert(!owner.editable);assert(!await owner.refresh());owner.setAvailable(true);owner.adopt({...actual(),requirement:{...actual().requirement,active_operation_id:9}});assert(!owner.editable);owner.adopt(actual());assert(owner.editable);f.batch={...f.batch,status:'DISCARDED',completed_at:at};assert(await owner.refresh());assert(!owner.editable);assert(!owner.canDiscard);owner.dispose();
});
test('explicit decisions can be changed before completion; only successful receipt/read clears its own editor',async()=>{
 const {f,owner}=await fixture();owner.draft(10,'  保留Markdown 😀\n');owner.draft(12,'{"cells":["key","另一个草稿"]}');assert(await owner.decide(10,'EDITED'));assert.equal(f.prepares[0].body.edited_content,'  保留Markdown 😀\n');assert.equal(owner.getSnapshot().batch.suggestions[0].user_edited_content,'  保留Markdown 😀\n');assert(!Object.hasOwn(owner.getSnapshot().drafts,10));assert(Object.hasOwn(owner.getSnapshot().drafts,12));assert(await owner.decide(10,'REJECTED'));assert.equal(owner.getSnapshot().batch.suggestions[0].user_edited_content,null);assert.equal(owner.getSnapshot().batch.counts.rejected,1);assert.equal(owner.getSnapshot().detail.current.content_version,2);owner.dispose();
});
test('DELETE cannot be EDITED; invalid Unicode/raw text and wrong row cells remain local, without preparing a write',async()=>{
 const {f,owner}=await fixture();assert(!await owner.decide(11,'EDITED'));owner.draft(10,'\ud800');assert(!await owner.decide(10,'EDITED'));assert.equal(owner.getSnapshot().drafts[10],'\ud800');owner.draft(12,'{"cells":["only one"]}');assert(!await owner.decide(12,'EDITED'));owner.draft(12,'{"cells":["key","value"],"target_ref":10}');assert(!await owner.decide(12,'EDITED'));assert.equal(f.prepares.length,0);owner.draft(12,'{"cells":["key","😀"]}');assert(await owner.decide(12,'EDITED'));assert.equal(f.prepares.length,1);owner.dispose();
});
test('known PATCH_INVALID retains original decision/draft and safe item error; no optimistic CURRENT mutation',async()=>{
 const {f,owner}=await fixture();owner.draft(10,'错误块');f.rejection=new ApiRejected('PATCH_INVALID','修改建议结构不合法或不能组合应用',{suggestion_errors:[{suggestion_id:10,code:'PATCH_INVALID',message:'修改建议结构不合法或不能组合应用'}]},'r',422);assert(!await owner.decide(10,'EDITED'));assert.equal(owner.getSnapshot().batch.suggestions[0].status,'PENDING');assert.equal(owner.getSnapshot().drafts[10],'错误块');assert(owner.getSnapshot().item_errors[10]);assert(owner.editable);f.rejection=null;assert(await owner.decide(10,'REJECTED'));owner.dispose();
});
test('lost decision receipt observes changed server status but needs original request; read failure cannot replay',async()=>{
 const {f,owner}=await fixture();owner.draft(10,'原稿');f.drop=true;assert(!await owner.decide(10,'EDITED'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(owner.getSnapshot().batch.suggestions[0].status,'PENDING');owner.setAvailable(false);assert(!await owner.recover());owner.setAvailable(true);f.failRead=true;assert(!await owner.recover());assert.equal(f.sends,1);f.failRead=false;f.sequence=[];assert(await owner.recover());assert.deepEqual(f.sequence.slice(0,3),['detail','batch','send']);assert.equal(f.prepares.length,1);assert.equal(f.sends,2);assert.equal(owner.getSnapshot().batch.suggestions[0].status,'EDITED');owner.dispose();
});
test('confirmed decision plus failed adoption keeps receipt/draft and supports pure read recovery',async()=>{
 const {f,owner}=await fixture();owner.draft(10,'保留');f.failAdopt=true;assert(!await owner.decide(10,'EDITED'));assert.equal(owner.getSnapshot().phase,'CONFIRMED');assert.equal(owner.getSnapshot().receipt.suggestion.status,'EDITED');assert.equal(owner.getSnapshot().drafts[10],'保留');assert(!await owner.decide(11,'ACCEPTED'));owner.setAvailable(false);assert(!await owner.finish());owner.setAvailable(true);f.failAdopt=false;assert(await owner.finish());assert.equal(f.sends,1);assert.equal(f.prepares.length,1);assert(!Object.hasOwn(owner.getSnapshot().drafts,10));owner.dispose();
});
test('serial in-flight decision blocks duplicate/new writes, draft changes and premature final commands',async()=>{
 const {f,owner}=await fixture();let release;f.hold=new Promise(resolve=>release=resolve);owner.draft(10,'原稿');const job=owner.decide(10,'EDITED');assert(!await owner.decide(10,'REJECTED'));assert(!await owner.complete());assert(!await owner.discard());owner.draft(10,'不该覆盖');assert.equal(owner.getSnapshot().drafts[10],'原稿');release();assert(await job);assert.equal(f.sends,1);owner.dispose();
});
test('all-rejected completion uses batch base content version, unknown terminal receipt recovery and no-change document',async()=>{
 const {f,owner}=await fixture();for(const id of [10,11,12])assert(await owner.decide(id,'REJECTED'));assert(owner.canComplete);f.drop=true;assert(!await owner.complete());assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(owner.getSnapshot().batch.status,'PENDING');assert(await owner.recover());assert.equal(f.prepares.at(-1).body.expected_content_version,2);assert.equal(f.sends,5);assert.equal(f.prepares.length,4);assert.equal(owner.getSnapshot().batch.completion_result,'NO_CHANGE');assert.equal(owner.getSnapshot().detail.current.content_version,2);assert(!owner.canComplete);owner.dispose();
});
test('discard preserves all recorded decisions; TARGET_STALE disables completion/edit while permitting discard',async()=>{
 const {f,owner}=await fixture();assert(await owner.decide(10,'ACCEPTED'));for(const id of [11,12])assert(await owner.decide(id,'REJECTED'));f.rejection=new ApiRejected('TARGET_STALE','目标已变化',null,'r',409);assert(!await owner.complete());assert(owner.getSnapshot().stale);assert(!owner.editable);assert(!owner.canComplete);assert(owner.canDiscard);f.rejection=null;assert(await owner.discard());assert.equal(owner.getSnapshot().batch.status,'DISCARDED');assert.equal(owner.getSnapshot().batch.suggestions[0].status,'ACCEPTED');assert.equal(owner.getSnapshot().detail.current.content_version,2);owner.dispose();
});
test('temporary known storage/in-progress failures retain request, immutable foreign reads/receipts cannot authorize success',async()=>{
 for(const code of ['STORAGE_UNAVAILABLE','REQUEST_IN_PROGRESS']){const {f,owner}=await fixture();f.rejection=new ApiRejected(code,'暂时失败',null,'r',code==='STORAGE_UNAVAILABLE'?503:409);assert(!await owner.decide(10,'ACCEPTED'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');f.rejection=null;assert(await owner.recover());assert.equal(f.prepares.length,1);owner.dispose();}
 const {f,owner}=await fixture();f.receiptChange=receipt=>({...receipt,suggestion:{...receipt.suggestion,target_ref:{block_id:999}}});assert(!await owner.decide(10,'ACCEPTED'));assert.equal(owner.getSnapshot().phase,'UNKNOWN');assert.equal(owner.getSnapshot().receipt,null);f.batch={...f.batch,suggestions:f.batch.suggestions.map(item=>item.id===10?{...item,target_ref:{block_id:999}}:item)};assert(!await owner.recover());assert.equal(f.sends,1);owner.dispose();
});
test('failed I20 refresh keeps whole original read, and retirement before dispatch sends nothing',async()=>{
 const {f,owner,api}=await fixture();const original=owner.getSnapshot().batch;api.getBatch=async()=>({data:{...f.batch,counts:{...f.batch.counts,pending:0}}});assert(!await owner.refresh());assert.equal(owner.getSnapshot().batch,original);assert(owner.getSnapshot().error);owner.dispose();
 const other=await fixture();const job=other.owner.decide(10,'ACCEPTED');other.owner.dispose();assert(!await job);assert.equal(other.f.prepares.length,0);assert.equal(other.f.sends,0);
});
test('hiding from the observation notification prevents replay and retains the original UNKNOWN action',async()=>{
 const {f,owner}=await fixture();f.drop=true;assert(!await owner.decide(10,'ACCEPTED'));const release=owner.subscribe(()=>{if(owner.getSnapshot().observed)owner.setAvailable(false);});assert(!await owner.recover());assert.equal(f.sends,1);assert.equal(owner.getSnapshot().phase,'UNKNOWN');release();owner.setAvailable(true);assert(await owner.recover());assert.equal(f.prepares.length,1);owner.dispose();
});
