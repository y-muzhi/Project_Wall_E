import type {Cards,Responses} from '../api/models.ts';
import {checkAnswers} from './card-answers.ts';

/** Read-only local readiness, using the same formal answer rules as submit. */
export function cardProgress(cards:Cards,answers:Responses){
  const ready:string[]=[],required:string[]=[],remaining:string[]=[];
  for(const card of cards.cards){
    const answer=answers.responses.find(item=>item.card_key===card.card_key);
    try{if(!answer)throw Error('Missing answer');checkAnswers({...cards,cards:[card]},{schema_version:1,responses:[answer]});ready.push(card.card_key);}
    catch{remaining.push(card.card_key);if(card.required)required.push(card.card_key);}
  }
  return {ready,required,remaining,total:cards.cards.length};
}
