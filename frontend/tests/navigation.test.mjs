import assert from 'node:assert/strict';
import test from 'node:test';
import {headingOutline} from '../src/documents/navigation.ts';

test('outline preserves identity/order and builds skipped heading levels and duplicate names',()=>{
  const entries=headingOutline([{block_id:40,level:2,text:'重复😀'},{block_id:7,level:5,text:'深层'},{block_id:90,level:3,text:'重复😀'},{block_id:8,level:1,text:''},{block_id:10,level:6,text:'末尾'}]);
  assert.deepEqual(entries.map(item=>[item.block_id,item.depth,item.text]),[[40,0,'重复😀'],[7,1,'深层'],[90,1,'重复😀'],[8,0,''],[10,1,'末尾']]);
  assert.ok(Object.isFrozen(entries)&&entries.every(Object.isFrozen));assert.deepEqual(headingOutline([]),[]);
});
test('outline refuses duplicate identities or non-heading levels without guessing',()=>{
  for(const level of [0,7,1.5,NaN])assert.throws(()=>headingOutline([{block_id:1,level,text:'甲'}]));
  assert.throws(()=>headingOutline([{block_id:1,level:1,text:'甲'},{block_id:1,level:2,text:'乙'}]));
});
