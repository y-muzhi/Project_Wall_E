import {test} from 'node:test';
import assert from 'node:assert/strict';
import {composerFeedback} from '../src/guide/composer-feedback.ts';

const state=(changes={})=>({action:'DISCUSS',phase:'READY',needs_refresh:false,detail:{requirement:{status:'CLOSED',document_work_state:'IDLE'}},new_target:{name:''},target:null,source_refs:[],...changes});
test('feedback distinguishes discussion, saved revisions and reviewable suggestions without granting send authority',()=>{
 const input=state();assert.equal(composerFeedback(input,true,true).blocked,null);assert.match(composerFeedback(input,true,true).effect,/不修改文档/);
 assert.match(composerFeedback(state({action:'REVISE',target:{document_id:2}}),true,true).effect,/新版本.*原版本保留/);
 assert.match(composerFeedback(state({action:'PROPOSE_CHANGES',target:{document_id:2}}),true,true).effect,/完成后才写入/);
 assert.equal(input.detail.requirement.status,'CLOSED');
});
test('missing configuration has an actionable reason while a stale owner denial remains denied',()=>{
 assert.equal(composerFeedback(state({action:'GENERATE'}),true,false).configure,true);
 assert.match(composerFeedback(state({action:'REVISE'}),true,false).blocked,/目标文档/);
 assert.match(composerFeedback(state({action:'REVIEW'}),true,false).blocked,/工作目标或参考文档/);
 assert.match(composerFeedback(state({target:{document_id:2}}),true,false).blocked,/已变化/);
});
test('unknown results and real work occupancy take precedence over new configuration suggestions',()=>{
 const unknown=composerFeedback(state({action:'GENERATE',phase:'UNKNOWN'}),false,false);assert.equal(unknown.configure,false);assert.match(unknown.blocked,/核实原请求/);
 const editing=state({detail:{requirement:{document_work_state:'MANUAL_EDITING'}}});assert.match(composerFeedback(editing,false,false).blocked,/完成或取消人工编辑/);
 const proposals=state({detail:{requirement:{document_work_state:'SUGGESTION_REVIEWING'}}});assert.match(composerFeedback(proposals,false,false).blocked,/完成或放弃当前修改建议/);
});
