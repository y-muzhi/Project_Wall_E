import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementPropertyEdit} from '../src/requirements/property-edit.ts';
import {ApiUnknown,ApiRejected} from '../src/api/client.ts';
const root={id:1,title:'实际标题',status:'PLANNING',metadata_version:1,document_work_state:'IDLE'};
const detail=(requirement=root)=>({requirement,current:null,activity:{kind:'IDLE'}});
function fixture(){const f={prepares:[],sends:0,error:null};const api={prepareUpdateRequirement(id,body){f.prepares.push({id,body});return {async submit(signal){assert.equal(signal,undefined);f.sends++;if(f.error)throw f.error;return {data:{...root,...body.changes,metadata_version:body.expected_metadata_version+1}};}};}};return {f,api,flow:new RequirementPropertyEdit('title',detail(),api)};}

test('title normalizes the 20 code point limit and sends exact metadata changes even with no document',async()=>{
 const {f,flow}=fixture();assert(flow.begin());for(const value of ['', 'x\ny','😀'.repeat(21),'\ud800']){flow.change(value);assert(!await flow.save());assert.equal(flow.getSnapshot().draft,value);assert.equal(f.prepares.length,0);}
 flow.change('  '+'😀'.repeat(20)+'  ');assert(await flow.save());assert.deepEqual(f.prepares,[{id:1,body:{expected_metadata_version:1,changes:{title:'😀'.repeat(20)}}}]);flow.dispose();
});
test('unknown title recovery uses the same original request without a matching GET claiming success',async()=>{
 const {f,api,flow}=fixture();api.getRequirement=()=>{throw Error('No GET confirms a title command');};flow.begin();flow.change(' 原标题意图 ');f.error=new ApiUnknown(true);assert(!await flow.save());
 flow.adoptDetail(detail({...root,metadata_version:9,title:'别的页面'}));assert(!flow.cancel());flow.change('不能替换未知请求');assert.equal(flow.getSnapshot().draft,' 原标题意图 ');
 f.error=null;assert(await flow.inspectUnknown());assert.equal(f.prepares.length,1);assert.equal(f.sends,2);assert.equal(flow.getSnapshot().receipt.title,'原标题意图');flow.dispose();
});
test('definite metadata conflict keeps raw text; a fresh actual baseline allows the next explicit intention in CLOSED too',async()=>{
 const {f,flow}=fixture();flow.begin();flow.change(' 新标题 ');f.error=new ApiRejected('METADATA_VERSION_CONFLICT','已变化',null,'r',409);assert(!await flow.save());assert.equal(flow.getSnapshot().phase,'EDITING');assert.equal(flow.getSnapshot().draft,' 新标题 ');
 flow.adoptDetail(detail({...root,status:'CLOSED',metadata_version:6}));assert(flow.allowed);f.error=null;assert(await flow.save());assert.equal(f.prepares[1].body.expected_metadata_version,6);flow.dispose();
});
test('retired queued saves send nothing; already sent recovery has no read-abort signal and late receipt cannot revive the owner',async()=>{
 const q=fixture();q.flow.begin();q.flow.change('排队');const queued=q.flow.save();q.flow.dispose();assert(!await queued);assert.equal(q.f.sends,0);
 let sends=0,resolve;const flow=new RequirementPropertyEdit('title',detail(),{prepareUpdateRequirement:()=>({submit:async signal=>{assert.equal(signal,undefined);if(++sends===1)throw new ApiUnknown(true);return new Promise(yes=>resolve=yes);}})});
 flow.begin();flow.change('未知原意图');assert(!await flow.save());const pending=flow.inspectUnknown();await Promise.resolve();flow.dispose();resolve({data:{...root,title:'未知原意图'}});assert(!await pending);assert.equal(flow.getSnapshot().receipt,null);
});
