import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ComposerDrafts} from '../src/guide/composer-drafts.ts';
import {ReadingPositions,readingKey} from '../src/documents/reading-position.ts';
const storage=()=>{const values=new Map();return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
test('composer restores only owned text in the new namespace and clears only the accepted requirement',()=>{
 const port=storage(),drafts=new ComposerDrafts(()=>port);port.setItem('walle:v1:composer:1','old');
 assert.equal(drafts.load(1).instruction,'');drafts.save(1,'原文\n😀');drafts.save(2,'另一需求');
 assert.equal(drafts.load(1).instruction,'原文\n😀');drafts.clear(1);assert.equal(drafts.load(1).instruction,'');assert.equal(drafts.load(2).instruction,'另一需求');
 port.setItem('walle:v1.5:composer:1',JSON.stringify({schema_version:1,requirement_id:2,instruction:'错误归属'}));assert(drafts.load(1).warning);
});
test('invalid and unavailable local storage cannot replace an in-memory message or restore commands',()=>{
 const port=storage(),drafts=new ComposerDrafts(()=>port);port.setItem('walle:v1.5:composer:1',JSON.stringify({schema_version:1,requirement_id:1,instruction:'x',operation:'GENERATE'}));
 assert.equal(drafts.load(1).instruction,'');assert(drafts.load(1).warning);
 const denied=new ComposerDrafts(()=>{throw Error('denied');});assert(denied.load(1).warning);assert(denied.save(1,'保留文字'));assert(denied.clear(1));
});
test('scroll positions remain separate for requirement, document, current version and immutable revision',()=>{
 const port={scrollTop:0},positions=new ReadingPositions(port),a={requirement_id:1,document_id:11,kind:'CURRENT',version:2};
 positions.select(a);port.scrollTop=240;positions.capture();positions.select({...a,document_id:12});assert.equal(port.scrollTop,0);
 port.scrollTop=70;positions.capture();positions.select({...a,kind:'REVISION',version:2});assert.equal(port.scrollTop,0);
 port.scrollTop=90;positions.capture();positions.select(a);assert.equal(port.scrollTop,240);
 positions.select({...a,version:3});assert.equal(port.scrollTop,0);assert.throws(()=>readingKey({...a,document_id:0}));
});
