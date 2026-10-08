import {useLayoutEffect,useRef,useState} from 'react';

export type MessageMarkdownRenderer=(markdown:string)=>DocumentFragment;

/** Display only. The installed document parser keeps authored HTML as text in a
 * read-only fragment; neither this component nor a rendering failure changes a message.
 * Card fallbacks and formal responses remain on the original text path. */
export function MessageContent({content,render}:Readonly<{content:string;render?:MessageMarkdownRenderer}>){
 const root=useRef<HTMLDivElement>(null),[failed,setFailed]=useState(false);
 useLayoutEffect(()=>{
  const element=root.current;if(!element||!render)return;
  try{element.replaceChildren(render(content));setFailed(false);}
  catch{element.replaceChildren();setFailed(true);}
  return()=>element.replaceChildren();
 },[content,render]);
 return <>
  {render&&<div ref={root} className="message-markdown milkdown" hidden={failed}/>}
  {(!render||failed)&&<p className="message-content">{content}</p>}
  {render&&failed&&<p role="status">消息排版暂时不可用，已保留完整原文。</p>}
 </>;
}
