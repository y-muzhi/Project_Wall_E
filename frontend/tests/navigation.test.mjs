import assert from 'node:assert/strict';
import test from 'node:test';
import {headingOutline,blockControlPositions} from '../src/documents/navigation.ts';

test('outline preserves identity/order and builds skipped heading levels and duplicate names',()=>{
  const entries=headingOutline([{block_id:40,level:2,text:'重复😀'},{block_id:7,level:5,text:'深层'},{block_id:90,level:3,text:'重复😀'},{block_id:8,level:1,text:''},{block_id:10,level:6,text:'末尾'}]);
  assert.deepEqual(entries.map(item=>[item.block_id,item.depth,item.text]),[[40,0,'重复😀'],[7,1,'深层'],[90,1,'重复😀'],[8,0,''],[10,1,'末尾']]);
  assert.ok(Object.isFrozen(entries)&&entries.every(Object.isFrozen));assert.deepEqual(headingOutline([]),[]);
});
test('outline refuses duplicate identities or non-heading levels without guessing',()=>{
  for(const level of [0,7,1.5,NaN])assert.throws(()=>headingOutline([{block_id:1,level,text:'甲'}]));
  assert.throws(()=>headingOutline([{block_id:1,level:1,text:'甲'},{block_id:1,level:2,text:'乙'}]));
});

test('gutter controls share the first-line center, leave a text gap and clamp together',()=>{
 const bounds={left:100,right:900,top:80,bottom:700};
 const large=blockControlPositions({left:184,top:120},bounds,38,true);
 assert.deepEqual(large,{actions:{left:108,top:125},fold:{left:140,top:125}});
 assert.equal(large.fold.left-(large.actions.left+24),8);
 assert.equal(184-(large.fold.left+24),20);
 assert.deepEqual(blockControlPositions({left:184,top:120},bounds,28,true,4),{actions:{left:108,top:124},fold:{left:140,top:124}});
 assert.equal(blockControlPositions({left:184,top:40},bounds,38,true).fold.top,84);
 assert.equal(blockControlPositions({left:184,top:690},bounds,38,true).actions.top,668);
 const plain=blockControlPositions({left:184,top:120},bounds,28,false);
 assert.deepEqual(plain,{actions:{left:140,top:120},fold:{left:140,top:120}});
 assert.equal(184-(plain.actions.left+24),20);
 assert.equal(plain.actions.left-large.actions.left,32);
 assert.deepEqual(blockControlPositions({left:184,top:120},bounds,28,false,4).actions,{left:140,top:124});
 assert.equal(blockControlPositions({left:104,top:40},bounds,28,false).actions.left,104);
 assert.equal(blockControlPositions({left:1000,top:690},bounds,28,false).actions.left,856);
});
