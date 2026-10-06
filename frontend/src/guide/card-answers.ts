import {cards as decodeCards,responses as decodeResponses} from '../api/models.ts';
import type {Cards,Responses} from '../api/models.ts';
import {exact,snapshotObject} from '../api/client.ts';
import {ordinaryInput} from '../shared/text.ts';
export type Card=Cards['cards'][number];
export type Answer=Responses['responses'][number];
export class CardAnswerError extends Error{readonly card_key:string;constructor(key:string,message:string){super(message);this.card_key=key;}}
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
export function blankAnswers(cards:Cards):Responses{return capture({schema_version:1,responses:cards.cards.map(card=>({card_key:card.card_key,selected_option_keys:[],custom_answer:null,skipped:false}))});}

/** Checks the whole original group, with no recommendation defaults or partial
 * submission. Draft blanks are legal locally; formal answers are normalized
 * and require an explicit skip for an unanswered optional question. */
export function checkAnswers(definition:Cards,input:Responses,formal=true):Responses{
 const cards=decodeCards(definition),root=exact(input,['schema_version','responses']);
 if(!Array.isArray(root.responses))throw new CardAnswerError('','回答必须是完整卡片数组');
 const prepared=formal?{...root,responses:root.responses.map(value=>{const row=exact(value,['card_key','selected_option_keys','custom_answer','skipped']),card=cards.cards.find(card=>card.card_key===row.card_key);if(row.custom_answer!==null&&card){try{return {...row,custom_answer:ordinaryInput(row.custom_answer as string,'自定义回答',1,card.custom_answer.max_length)};}catch(error){throw new CardAnswerError(card.card_key,error instanceof Error?error.message:'自定义回答不合法');}}return row;})}:input;
 const answers=decodeResponses(prepared),keys=cards.cards.map(card=>card.card_key);
 if(answers.responses.length!==keys.length||answers.responses.some(answer=>!keys.includes(answer.card_key)))throw new CardAnswerError('','回答必须准确覆盖整组问题');
 const responses=cards.cards.map(card=>{
  const answer=answers.responses.find(row=>row.card_key===card.card_key)!;const fail=(message:string):never=>{throw new CardAnswerError(card.card_key,message);};
  if(answer.selected_option_keys.some(key=>!card.options.some(option=>option.option_key===key)))fail('所选选项不属于原问题');
  if(answer.skipped){if(card.required)fail('必答问题不能跳过');return {...answer,selected_option_keys:[],custom_answer:null};}
  let custom=answer.custom_answer;
  if(custom!==null){if(!card.custom_answer.enabled)fail('此问题不允许自定义回答');if(formal)try{custom=ordinaryInput(custom,'自定义回答',1,card.custom_answer.max_length);}catch(error){fail(error instanceof Error?error.message:'自定义回答不合法');}}
  const count=answer.selected_option_keys.length+Number(custom!==null);
  if(card.card_type!=='MULTI_SELECT'&&count>1)fail('预设选项与自定义回答只能选择一个');
  if(formal&&(count===0||count<card.selection_rule.min||count>card.selection_rule.max))fail(card.required?'请完成此必答问题，并符合选择数量限制':'请回答此问题或明确选择跳过');
  return {...answer,custom_answer:custom};
 });
 return capture({schema_version:1,responses});
}
export function formalAnswerText(cards:Cards,answers:Responses):string{
 const formal=checkAnswers(cards,answers);return cards.cards.flatMap(card=>{const answer=formal.responses.find(row=>row.card_key===card.card_key)!;return [card.question,...(answer.skipped?['已跳过']:[...answer.selected_option_keys.map(key=>card.options.find(option=>option.option_key===key)!.label),...(answer.custom_answer===null?[]:[answer.custom_answer])])];}).join('\n');
}
