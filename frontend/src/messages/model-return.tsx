import {MessageContent} from './content.tsx';
import type {MessageMarkdownRenderer} from './content.tsx';
const object=(value:unknown):Record<string,unknown>|null=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:null;
/** Optional presentation only: unfamiliar fields remain in the full original.
 * These read-only cards never issue commands or manufacture formal choices. */
export function ModelReturnContent({content,render}:Readonly<{content:string;render?:MessageMarkdownRenderer}>){
 let value:Record<string,unknown>|null=null;try{value=object(JSON.parse(content));}catch{/* Plain and partial content stays readable. */}
 if(!value||typeof value.message!=='string')return <MessageContent content={content} {...(render?{render}:{})}/>;
 const group=object(value.cards),cards=Array.isArray(group?.cards)?group.cards:[];
 if(!value.message.trim()&&cards.length===0)return <MessageContent content={content} {...(render?{render}:{})}/>;
 return <div className="model-return-content">
  <MessageContent content={value.message} {...(render?{render}:{})}/>
  {typeof group?.intro==='string'&&group.intro!==value.message&&<MessageContent content={group.intro} {...(render?{render}:{})}/>}
  {cards.map((item,index)=>{const card=object(item);if(!card)return null;return <section key={index} className="returned-card">
   {typeof card.question==='string'&&<p><strong>{index+1}. {card.question}</strong></p>}
   {typeof card.context==='string'&&card.context&&<MessageContent content={card.context} {...(render?{render}:{})}/>}
   {Array.isArray(card.options)&&<ul>{card.options.map((item,optionIndex)=>{const option=object(item);return option&&<li key={optionIndex}>{['label','description','impact','risks'].map(key=>typeof option[key]==='string'&&option[key]&&<p key={key}>{key==='impact'?'影响：':key==='risks'?'风险：':''}{String(option[key])}</p>)}</li>;})}</ul>}
   {card.recommendation!=null&&<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>模型建议：{JSON.stringify(card.recommendation,null,2)}</pre>}
  </section>;})}
  <details><summary>查看完整返回原文</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{content}</pre></details>
 </div>;
}
