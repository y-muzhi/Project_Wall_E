import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {discussionState} from '../src/api/models.ts';
import {progressPresentation,topicRecords} from '../src/requirements/discussion-presentation.ts';
const manifest=JSON.parse(readFileSync(new URL('../../backend/resources/v9/manifest.json',import.meta.url),'utf8'));
const guide=manifest.files.find(file=>file.resource_ref.key==='collaboration.discovery').resource_ref;
const mainlines=[{ref:'value',title:'目标与价值',purpose:'明确目标'},{ref:'scope',title:'范围与约束',purpose:'明确范围'}];
const topic=(ref,phase='p1',changes={})=>({topic_ref:ref,phase_ref:phase,mainline_ref:'value',title:ref,purpose:'目的',expected_outcomes:[{outcome_ref:ref+':o1',text:'成果',criterion:'判断依据'}],assessment:'DISCUSSING',evidence_refs:['e1','e2','e3'],dependencies:[],unresolved_impacts:[],updated_by_message_id:1,...changes});
const record=(ref,state,origin='USER_STATEMENT')=>({evidence_ref:ref,assertion:ref,origin,nature:'FACT',applies_to:['t1'],source_refs:[{kind:'MESSAGE',message_id:1}],state,supersedes:[],topic_refs:['t1']});
const state=(changes={})=>discussionState({schema_version:1,phase:{phase_ref:'p1',kind:'DISCOVERY',guide_ref:guide,closure:null},focus_topic_ref:'t1',topics:[topic('t1'),topic('t2','p0')],evidence:[record('e1','ACTIVE'),record('e2','DISPUTED','AI_PROPOSAL'),record('e3','SUPERSEDED','USER_DECISION')],pending_user_message_ids:[],binding:{target_document_id:null,source_refs:[],scope:null,document_kind:null},dispositions:[],last_step:null,counters:{phase:2,topic:3,evidence:4},...changes});

test('progress shows only this phase while retaining resource order and all unknown-mainline topics',()=>{
 const input=state({topics:[topic('t1'),topic('t2','p0'),topic('t3','p1',{mainline_ref:'new-mainline'})]});
 const view=progressPresentation(input,mainlines);
 assert.deepEqual(view.topics.map(t=>t.topic_ref),['t1','t3']);assert.deepEqual(view.groups.map(g=>g.ref),['value','scope','other']);
 assert.equal(view.groups[1].topics.length,0);assert.equal(view.groups[2].topics[0].topic_ref,'t3');assert.equal(view.focus.topic_ref,'t1');
 assert.equal(progressPresentation(state({focus_topic_ref:'t2'}),mainlines).focus,null);
});
test('disputed assertions stay visible, superseded assertions remain separately readable, and origins are never upgraded',()=>{
 const input=state(),records=topicRecords(input,input.topics[0]);
 assert.deepEqual(records.current.map(e=>e.evidence_ref),['e1','e2']);assert.deepEqual(records.history.map(e=>e.evidence_ref),['e3']);
 assert.equal(records.current[1].origin,'AI_PROPOSAL');assert.equal(records.history[0].origin,'USER_DECISION');assert.equal(input.evidence.length,3);
});
test('a saved recommendation retains its reason and actual topic without becoming an automatic operation',()=>{
 const input=state({last_step:{message_id:2,value:{action:'RECOMMEND_DRAFT',topic_ref:'t1',reason:'已有主线；仍有待定内容。',unresolved_impacts:['范围待定']}}});
 const view=progressPresentation(input,mainlines);assert.equal(view.next.label,'建议形成文档');assert.equal(view.next.reason,'已有主线；仍有待定内容。');
 assert.equal(view.next.topic.topic_ref,'t1');assert.deepEqual(view.next.impacts,['范围待定']);assert.equal(progressPresentation(state(),mainlines).next,null);
 assert.equal(progressPresentation({...input,last_step:{message_id:2,value:{action:'UNSUPPORTED',reason:'不能猜'}}},mainlines).next,null);
});
test('phase and topic dispositions stay scoped independently of assessment and no historical decision leaks into this phase',()=>{
 const decision=(scope)=>({kind:'DEFER',scope_refs:[scope],message_id:1,summary:'保留用户原话'});
 const input=state({topics:[topic('t1','p1',{assessment:'SUPPORTED'}),topic('t3','p1',{assessment:'REVIEW_REQUIRED'})],dispositions:[decision('p1'),decision('p0'),decision('t1')]});
 const view=progressPresentation(input,mainlines);assert.equal(view.phaseDispositions.length,1);assert.equal(view.reviewCount,1);
 assert.equal(topicRecords(input,input.topics[0]).dispositions.length,1);assert.equal(view.topics[0].assessment,'SUPPORTED');
});
test('presentation does not mutate frozen source data, topic ordering, evidence or guide definitions',()=>{
 const input=state(),before=JSON.stringify(input),guides=Object.freeze(mainlines.map(item=>Object.freeze({...item})));
 progressPresentation(input,guides);topicRecords(input,input.topics[0]);assert.equal(JSON.stringify(input),before);assert.equal(guides.length,2);
});
