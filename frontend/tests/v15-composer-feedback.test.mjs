import {test} from 'node:test';
import assert from 'node:assert/strict';
import {composerFeedback,composerProgress} from '../src/guide/composer-feedback.ts';

const state=(changes={})=>({action:'DISCUSS',phase:'READY',needs_refresh:false,detail:{requirement:{status:'CLOSED',document_work_state:'IDLE'}},target:null,source_refs:[],...changes});
test('feedback distinguishes discussion from a revision whose result may require review',()=>{
 const input=state();assert.equal(composerFeedback(input,true,true).blocked,null);assert.match(composerFeedback(input,true,true).effect,/不修改文档/);
 assert.match(composerFeedback(state({action:'REVISE',target:{document_id:2}}),true,true).effect,/已保存或待审阅/);
 assert.equal(input.detail.requirement.status,'CLOSED');
});
test('missing configuration has an actionable reason while a stale owner denial remains denied',()=>{
 assert.match(composerFeedback(state({action:'REVISE'}),true,false).blocked,/选择写入范围/);
 assert.match(composerFeedback(state({target:{document_id:2}}),true,false).blocked,/已变化/);
});
test('unknown results and real work occupancy take precedence over new configuration suggestions',()=>{
 const unknown=composerFeedback(state({action:'REVISE',phase:'UNKNOWN'}),false,false);assert.match(unknown.blocked,/核实原请求/);
 const editing=state({detail:{requirement:{document_work_state:'MANUAL_EDITING'}}});assert.match(composerFeedback(editing,false,false).blocked,/完成或取消人工编辑/);
 const proposals=state({detail:{requirement:{document_work_state:'SUGGESTION_REVIEWING'}}});assert.match(composerFeedback(proposals,false,false).blocked,/完成或放弃当前修改建议/);
});

test('request progress uses the active stage and leaves idle forms clear', () => {
  assert.equal(composerProgress(state(), false), null);
  assert.equal(composerProgress(state({ phase: 'SUBMITTING' }), false), '正在发送');
  assert.equal(composerProgress(state({ phase: 'CONFIRMED' }), false), '读取结果');
  const running = state({ detail: { requirement: { document_work_state: 'GUIDE_ACTIVE' } } });
  assert.equal(composerProgress(running, false), '等待回复');
  assert.equal(composerProgress(state(), true), '保存讨论主题');
});
