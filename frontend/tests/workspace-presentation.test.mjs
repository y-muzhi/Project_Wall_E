import test from 'node:test';
import assert from 'node:assert/strict';
import {cards as decodeCards} from '../src/api/models.ts';
import {blankAnswers} from '../src/guide/card-answers.ts';
import {cardProgress} from '../src/guide/card-progress.ts';
import {visibleSuggestions,nextPendingSuggestion} from '../src/suggestions/display.ts';
import {headingOutline} from '../src/documents/navigation.ts';
import {visibleOutline} from '../src/documents/outline-display.ts';

const card=(key,required=true)=>({card_key:key,card_type:'MULTI_SELECT',question:'问题'+key,context:'上下文',required,options:[{option_key:'a',label:'选项A',description:'说明',impact:'影响',risks:'风险'},{option_key:'b',label:'选项B',description:'说明',impact:'影响',risks:'风险'}],selection_rule:{min:1,max:2},custom_answer:{enabled:true,max_length:200},recommendation:{option_keys:['a'],reason:'仅推荐'},related_spec_context:[]});
const definition=()=>decodeCards({schema_version:1,intro:'请选择',cards:[card('required'),card('optional',false)]});
test('local readiness never counts recommendations or silently skipped optional questions',()=>{
 const cards=definition(),answers=structuredClone(blankAnswers(cards)),before=structuredClone(answers),progress=cardProgress(cards,answers);
 assert.deepEqual(progress,{ready:[],required:['required'],remaining:['required','optional'],total:2});assert.deepEqual(answers,before);
});
test('local readiness uses formal Unicode and choice limits while retaining raw inputs',()=>{
 const cards=definition(),answers=structuredClone(blankAnswers(cards));answers.responses[0].custom_answer='  😀\r\n需求  ';answers.responses[1].skipped=true;
 assert.deepEqual(cardProgress(cards,answers).ready,['required','optional']);assert.equal(answers.responses[0].custom_answer,'  😀\r\n需求  ');
 for(const value of ['  ','\ud800','字'.repeat(201)]){answers.responses[0].custom_answer=value;assert.deepEqual(cardProgress(cards,answers).required,['required']);}
 answers.responses[0].custom_answer='valid';answers.responses[0].selected_option_keys=['a','a'];assert.deepEqual(cardProgress(cards,answers).required,['required']);
});
test('required skip and outside choices stay incomplete even when local fields are nonempty',()=>{
 const cards=definition(),answers=structuredClone(blankAnswers(cards));answers.responses[0].skipped=true;answers.responses[1].selected_option_keys=['outside'];
 assert.deepEqual(cardProgress(cards,answers).remaining,['required','optional']);
});
test('pending filter preserves order, edited fields and protected intentions without mutating decisions',()=>{
 const items=[{id:9,status:'ACCEPTED'},{id:3,status:'PENDING'},{id:7,status:'EDITED'},{id:2,status:'REJECTED'}],before=structuredClone(items);
 assert.deepEqual(visibleSuggestions(items,true,new Set([7]),9),[9,3,7]);assert.deepEqual(visibleSuggestions(items,false,new Set(),null),[9,3,7,2]);assert.deepEqual(items,before);
});
test('next pending follows original order and wraps, never guessing accepted items',()=>{
 const items=[{id:9,status:'ACCEPTED'},{id:3,status:'PENDING'},{id:1,status:'PENDING'}];
 assert.equal(nextPendingSuggestion(items,null),3);assert.equal(nextPendingSuggestion(items,3),1);assert.equal(nextPendingSuggestion(items,1),3);assert.equal(nextPendingSuggestion(items,9),3);assert.equal(nextPendingSuggestion([{id:9,status:'EDITED'}],null),null);
});
test('outline folding respects actual hierarchy and identities across duplicate headings',()=>{
 const outline=headingOutline([{block_id:1,level:1,text:'重复'},{block_id:2,level:3,text:'重复'},{block_id:3,level:5,text:'深层'},{block_id:4,level:2,text:'其他'},{block_id:5,level:1,text:'重复'}]),before=structuredClone(outline);
 assert.deepEqual(visibleOutline(outline,new Set([2])),[true,true,false,true,true]);assert.deepEqual(visibleOutline(outline,new Set([1])),[true,false,false,false,true]);assert.deepEqual(visibleOutline(outline,new Set([999])),[true,true,true,true,true]);assert.deepEqual(outline,before);
});
