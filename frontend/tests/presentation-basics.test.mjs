import {test} from 'node:test';
import assert from 'node:assert/strict';
import {captureMessageAnchor,restoreMessageAnchor} from '../src/messages/scroll-position.ts';
import {REQUIREMENT_STATUS_LABELS,SAVE_STATUS_LABELS,saveStatusLabel} from '../src/shared/status-labels.ts';

test('status labels cover actual states and invalid local input cannot claim saved',()=>{
  assert.deepEqual(REQUIREMENT_STATUS_LABELS,{INITIALIZING:'初始化中',ACTIVE:'进行中',COMPLETED:'已完成'});
  assert.equal(Object.keys(SAVE_STATUS_LABELS).length,8);
  assert.match(saveStatusLabel('SAVED',false),/未保存/);
  assert.equal(saveStatusLabel('UNKNOWN',true),'保存结果待核实');
});

function fixture(){
  let shift=0;
  const part={dataset:{cardKey:'q1'},getBoundingClientRect:()=>({top:118+shift,bottom:190+shift})};
  const message={dataset:{messageId:'41',messageSequence:'9'},getBoundingClientRect:()=>({top:80+shift,bottom:200+shift}),querySelectorAll:()=>[part]};
  const root={scrollTop:240,scrollHeight:1000,clientHeight:400,getBoundingClientRect:()=>({top:100,bottom:500}),
    querySelectorAll:()=>[message],querySelector:()=>message};
  return {root,shift(value){shift=value;}};
}

test('shared conversation port preserves the visible card when older content is prepended',()=>{
  const {root,shift}=fixture(),saved=captureMessageAnchor(root);
  assert.equal(saved.id,'41');assert.equal(saved.part,'q1');assert.equal(saved.offset,18);
  assert.equal(saved.near,false);assert.equal(saved.last,9);
  root.scrollHeight+=150;shift(150);restoreMessageAnchor(root,saved);
  assert.equal(root.scrollTop,390);
});

test('near-bottom detection uses the outer port and retains the 80px boundary',()=>{
  const {root}=fixture();root.scrollTop=520;
  assert.equal(captureMessageAnchor(root).near,true);
  root.scrollTop=519;assert.equal(captureMessageAnchor(root).near,false);
});

test('removed visible message falls back to the real port height delta',()=>{
  const {root}=fixture(),saved=captureMessageAnchor(root);
  root.querySelector=()=>null;root.scrollHeight+=90;
  restoreMessageAnchor(root,saved);assert.equal(root.scrollTop,330);
});
