import {test} from 'node:test';
import assert from 'node:assert/strict';
import {instructionFeedback} from '../src/guide/input-feedback.ts';
import {ordinaryInput} from '../src/shared/text.ts';
import {tableRowCells,replaceRowCell} from '../src/suggestions/row-edit.ts';

test('send feedback rejects empty and Unicode whitespace without preparing a request',()=>{
  for(const value of ['', '\r\n\u3000\u0085 '])assert.deepEqual(instructionFeedback(value),{length:0,valid:false,error:'请输入消息后发送。'});
});
test('send count follows normalized codepoints, including astral characters and CRLF',()=>{
  const raw=' \u3000😀\r\n边界\r\n ';
  assert.equal(instructionFeedback(raw).length,[...ordinaryInput(raw,'AI 指令',1,10000)].length);
  assert.equal(instructionFeedback(raw).length,4);
  assert.equal(instructionFeedback(raw).valid,true);
});
test('send feedback matches the real validator at the Unicode length boundary',()=>{
  assert.equal(instructionFeedback('😀'.repeat(10000)).valid,true);
  assert.equal(instructionFeedback('😀'.repeat(10001)).valid,false);
  assert.throws(()=>ordinaryInput('😀'.repeat(10001),'AI 指令',1,10000));
  assert.equal(instructionFeedback('\ud800').valid,false);
  assert.match(instructionFeedback('\ud800').error,/Unicode/);
});
test('table cell edits retain exact neighboring text and encode only the fixed cells contract',()=>{
  const before=JSON.stringify({cells:[' 前后空格 ', 'a|b\n第二行', '😀"\\']});
  const result=replaceRowCell(before,3,1,'新\r\n值 | "😀"');
  assert.deepEqual(JSON.parse(result),{cells:[' 前后空格 ','新\r\n值 | "😀"','😀"\\']});
  assert.deepEqual(Object.keys(JSON.parse(result)),['cells']);
  assert.equal(tableRowCells(result,3).length,3);
});
test('invalid retained rows cannot silently lose text, columns or extra fields',()=>{
  for(const raw of ['broken','null','[]','{"cells":["a"]}','{"cells":["a",3]}','{"cells":["a","b"],"extra":1}']){
    assert.equal(tableRowCells(raw,2),null);
    assert.throws(()=>replaceRowCell(raw,2,0,'replacement'));
  }
});
test('table editing preserves empty cells and refuses invalid column indices',()=>{
  const raw='{"cells":["","a"]}';
  assert.deepEqual(tableRowCells(replaceRowCell(raw,2,1,''),2),['','']);
  for(const index of [-1,2,0.5])assert.throws(()=>replaceRowCell(raw,2,index,'b'));
});
