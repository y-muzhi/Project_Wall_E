import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readVisiblePanel} from '../src/requirements/panel-read.ts';

test('visible comment-to-AI handoff repeats a retired GET once without another command',async()=>{
 const controller=new AbortController();let reads=0;
 await readVisiblePanel(async()=>{if(++reads===1)throw new DOMException('Read retired','AbortError');},controller.signal);
 assert.equal(reads,2);
});
test('actual panel failure and repeated cancellation remain visible failures with bounded reads',async()=>{
 for(const error of [new Error('actual read failure'),new DOMException('Read retired','AbortError')]){
  let reads=0;await assert.rejects(readVisiblePanel(async()=>{reads++;throw error;},new AbortController().signal),actual=>actual===error);
  assert.equal(reads,error.name==='AbortError'?2:1);
 }
});
test('panel retirement before or during a cancelled read starts no further GET',async()=>{
 const controller=new AbortController();controller.abort();let reads=0;
 await readVisiblePanel(async()=>{reads++;},controller.signal);assert.equal(reads,0);
 const active=new AbortController();await readVisiblePanel(async()=>{reads++;active.abort();throw new DOMException('Read retired','AbortError');},active.signal);
 assert.equal(reads,1);
});
