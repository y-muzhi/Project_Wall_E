import assert from 'node:assert/strict';
import test from 'node:test';
import {Schema} from '@milkdown/kit/prose/model';
import {EditorState,TextSelection} from '@milkdown/kit/prose/state';
import {slashMatch,replaceSlash,linkCommand,validLink} from '../src/documents/format-commands.ts';
const schema=new Schema({nodes:{doc:{content:'block+'},paragraph:{group:'block',content:'text*',attrs:{id:{default:1}}},code_block:{group:'block',content:'text*',code:true},text:{}},marks:{link:{attrs:{href:{}}}}});
const state=(text,type='paragraph')=>{const block=schema.nodes[type].create(type==='paragraph'?{id:7}:null,text?schema.text(text):null),doc=schema.nodes.doc.create(null,[block,schema.nodes.paragraph.create({id:9},schema.text('保留邻段'))]);return EditorState.create({doc,selection:TextSelection.create(doc,1+text.length)});};
test('slash is contextual: code, URLs, whitespace and selected content stay ordinary text',()=>{
  assert.deepEqual(slashMatch(state('/table')),{from:1,to:7,query:'table'});
  for(const text of ['https://a.test/','正文/','/有 空格','//','/'+ 'a'.repeat(33)])assert.equal(slashMatch(state(text)),null);
  assert.equal(slashMatch(state('/','code_block')),null);
  const selected=state('/');assert.equal(slashMatch(selected.apply(selected.tr.setSelection(TextSelection.create(selected.doc,1,2)))),null);
});
test('slash insertion is atomic and keeps neighboring blocks and identities',()=>{
  const before=state('/table'),match=slashMatch(before);let sent=[];
  assert.equal(replaceSlash(match,(candidate,dispatch)=>{dispatch?.(candidate.tr.insertText('插入内容'));return true;})(before,tr=>sent.push(tr)),true);
  assert.equal(sent.length,1);const after=before.apply(sent[0]);assert.equal(after.doc.textContent,'插入内容保留邻段');assert.equal(after.doc.child(0).attrs.id,7);assert.equal(after.doc.child(1).attrs.id,9);
});
test('unsupported or stale slash command never deletes the query',()=>{
  const before=state('/table'),match=slashMatch(before);let dispatched=0;
  assert.equal(replaceSlash(match,()=>false)(before,()=>dispatched++),false);
  const edited=before.apply(before.tr.insertText('x'));assert.equal(replaceSlash(match,()=>true)(edited,()=>dispatched++),false);assert.equal(dispatched,0);assert.equal(before.doc.firstChild.textContent,'/table');
});
test('links preserve selected text, slash link inserts a visible label, unsafe schemes are rejected',()=>{
  assert.equal(validLink('javascript:alert(1)'),false);assert.equal(validLink('/relative'),false);assert.equal(validLink('https://example.com'),true);assert.equal(validLink('mailto:a@example.com'),true);
  const before=state('/link');let result;assert.equal(replaceSlash(slashMatch(before),linkCommand('https://example.com',true))(before,tr=>{result=before.apply(tr);}),true);
  assert.equal(result.doc.firstChild.textContent,'https://example.com');assert.equal(result.doc.firstChild.firstChild.marks[0].attrs.href,'https://example.com');
  const text=state('原文字'),selected=text.apply(text.tr.setSelection(TextSelection.create(text.doc,1,4)));linkCommand('https://example.com',true)(selected,tr=>{result=selected.apply(tr);});assert.equal(result.doc.firstChild.textContent,'原文字');
});
