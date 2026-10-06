import {useRef,useState,useSyncExternalStore} from 'react';
import type {CommentCommand,CommentOutcome} from './commands.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {Confirmation} from '../shared/confirmation.tsx';
const labels={CREATE:'添加评论',EDIT:'保存评论',RESOLVE:'解决评论',REOPEN:'重新打开评论',DELETE:'删除评论',MODIFY:'让 AI 修改'} as const;

/** The parent owns one flow per comment across page/historical/actual refresh.
 * Positive refresh failure is a GET retry, not a second user operation. */
export function CommentCommandControl(props:Readonly<{flow:CommentCommand;blocked:boolean;writeReady:boolean;readActual():Promise<DetailSnapshot>;changed(outcome:CommentOutcome):void|Promise<void>;cancel?():void}>){
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),pending=useRef(false);
  const intent=props.flow.intent,text=intent.kind==='CREATE'||intent.kind==='EDIT',active=busy||['SUBMITTING','READING'].includes(state.phase),unknown=state.phase==='UNKNOWN';
  const execute=async(readOnly=false)=>{
    if(pending.current||props.blocked||!readOnly&&!unknown&&(!props.writeReady||!props.flow.allowed))return;pending.current=true;setBusy(true);setError(null);
    try{const confirmed=readOnly?true:unknown?await props.flow.retryUnknown(props.readActual):await props.flow.submit();if(confirmed){setOpen(false);const outcome=props.flow.getSnapshot().outcome;if(outcome)await props.changed(outcome);}}
    catch{setError('评论操作已确认，实际详情暂时无法重新读取，请重试读取');}finally{pending.current=false;setBusy(false);}
  };
  const quote=intent.kind==='CREATE'?intent.target.quote:'selected_text' in intent.comment.anchor_ref?intent.comment.anchor_ref.selected_text:intent.comment.anchor_ref.block_markdown_snapshot;
  return <div className="comment-command" aria-busy={active}>
    {text&&<><blockquote className="comment-quote">{quote}</blockquote><label>评论正文<textarea aria-label="评论正文" value={state.content} disabled={props.blocked||active||unknown||state.phase==='CONFIRMED'||!props.writeReady||!props.flow.allowed} onChange={event=>props.flow.change(event.target.value)}/></label></>}
    {state.error&&<p role="alert" className="inline-error">{state.error}</p>}{error&&<p role="alert" className="inline-error">{error}</p>}
    {active&&<p role="status">{state.phase==='READING'?'正在核实评论结果…':state.phase==='CONFIRMED'?'正在重新读取实际详情…':'正在提交评论操作…'}</p>}
    {state.observed&&unknown&&<p role="status">已读取实际状态，仍需确认原请求结果。</p>}
    {state.phase==='CONFIRMED'?<><p role="status">{intent.kind==='MODIFY'?'修改任务已接受，评论保持未解决。':'评论操作已确认。'}</p><button type="button" disabled={props.blocked||active} onClick={()=>void execute(true)}>重新读取评论与详情</button></>:
      <button type="button" disabled={props.blocked||active||!unknown&&(!props.writeReady||!props.flow.allowed)} onClick={()=>intent.kind==='DELETE'?setOpen(true):void execute()}>{unknown?'重新确认评论操作结果':labels[intent.kind]}</button>}
    {props.cancel&&state.phase!=='CONFIRMED'&&<button type="button" disabled={active} onClick={props.cancel}>{unknown?'保留请求并关闭编辑区':'取消编辑'}</button>}
    <Confirmation open={open} dangerous title="删除评论？" description="确认后评论将从默认列表移除，历史来源会保留。" busy={props.blocked||active||!unknown&&!props.writeReady} error={state.error}
      confirmLabel={unknown?'重新确认删除结果':'确认删除'} cancelLabel={unknown?'保留请求并关闭弹窗':'保留评论'} cancel={()=>setOpen(false)} confirm={()=>void execute()}/>
  </div>;
}
