import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ComposerDrafts} from '../src/guide/composer-drafts.ts';
import {ReadingPositions,readingKey} from '../src/documents/reading-position.ts';
const storage=()=>{const values=new Map();return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
test('composer restores only owned text in the new namespace and clears only the accepted requirement',()=>{
 const port=storage(),drafts=new ComposerDrafts(()=>port,11);port.setItem('walle:v1:composer:1','old');
 assert.equal(drafts.load(1).instruction,'');drafts.save(1,'原文\n😀');drafts.save(2,'另一需求');
 assert.equal(drafts.load(1).instruction,'原文\n😀');drafts.clear(1);assert.equal(drafts.load(1).instruction,'');assert.equal(drafts.load(2).instruction,'另一需求');
 port.setItem('walle:v1.5:document-composer:1:11',JSON.stringify({schema_version:1,requirement_id:2,document_id:11,instruction:'错误归属'}));assert(drafts.load(1).warning);
});
test('invalid and unavailable local storage cannot replace an in-memory message or restore commands',()=>{
 const port=storage(),drafts=new ComposerDrafts(()=>port,11);port.setItem('walle:v1.5:document-composer:1:11',JSON.stringify({schema_version:1,requirement_id:1,document_id:11,instruction:'x',operation:'GENERATE'}));
 assert.equal(drafts.load(1).instruction,'');assert(drafts.load(1).warning);
 const denied=new ComposerDrafts(()=>{throw Error('denied');},11);assert(denied.load(1).warning);assert(denied.save(1,'保留文字'));assert(denied.clear(1));
});
test('scroll positions remain separate for requirement, document, current version and immutable revision',()=>{
 const port={scrollTop:0},positions=new ReadingPositions(port),a={requirement_id:1,document_id:11,kind:'CURRENT',version:2};
 positions.select(a);port.scrollTop=240;positions.capture();positions.select({...a,document_id:12});assert.equal(port.scrollTop,0);
 port.scrollTop=70;positions.capture();positions.select({...a,kind:'REVISION',version:2});assert.equal(port.scrollTop,0);
 port.scrollTop=90;positions.capture();positions.select(a);assert.equal(port.scrollTop,240);
 positions.select({...a,version:3});assert.equal(port.scrollTop,0);assert.throws(()=>readingKey({...a,document_id:0}));
});

test('same requirement documents keep separate drafts and cleanup never touches the sibling',()=>{
 const port=storage(),a=new ComposerDrafts(()=>port,11),b=new ComposerDrafts(()=>port,12);
 a.save(1,'A');b.save(1,'B');assert.equal(a.load(1).instruction,'A');assert.equal(b.load(1).instruction,'B');
 a.clear(1);assert.equal(b.load(1).instruction,'B');
 port.setItem('walle:v1.5:document-composer:1:11',JSON.stringify({schema_version:1,requirement_id:1,document_id:12,instruction:'foreign'}));
 assert.equal(a.load(1).instruction,'');assert(a.load(1).warning);
});
