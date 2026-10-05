import {useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementLifecycle,LifecycleOutcome} from './lifecycle.ts';
import {Confirmation} from '../shared/confirmation.tsx';
const labels={INITIALIZATION:'完成初始化',COMPLETE:'完成需求',REACTIVATE:'重新激活'} as const;
const descriptions={INITIALIZATION:'将当前正文保存为初始化基线，解除初始化模板结构锁定并进入正式维护阶段。',COMPLETE:'完成后正文和评论将只读，仍可提问和查看历史版本。',REACTIVATE:'重新激活后可以继续维护需求；正文和已有版本记录保持不变。'} as const;

/** Parent keeps this flow through unknown results and supplies actual full
 * detail/revision refresh. blocked is a viewport/history/read guard, not an
 * inferred rollback or new status made from the historical receipt. */
export function RequirementLifecycleControl(props:Readonly<{flow:RequirementLifecycle;blocked:boolean;changed(outcome:LifecycleOutcome):void|Promise<void>}>){
  const state=useSyncExternalStore(props.flow.subscribe,props.flow.getSnapshot),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),pending=useRef(false);
  const active=busy||['SUBMITTING','READING'].includes(state.phase),label=labels[props.flow.operation];
  const refresh=async()=>{const outcome=props.flow.getSnapshot().outcome;if(outcome)await props.changed(outcome);};
  const execute=async(readOnly=false)=>{
    if(pending.current||props.blocked)return;pending.current=true;setBusy(true);setError(null);
    try{const confirmed=readOnly?true:state.phase==='UNKNOWN'?await props.flow.retryUnknown():await props.flow.submit();if(confirmed){setOpen(false);await refresh();}}
    catch{setError('变更已确认，实际详情暂时无法读取，请重试读取');}finally{pending.current=false;setBusy(false);}
  };
  return <div className="requirement-lifecycle-control">
    <button type="button" disabled={props.blocked||active||state.phase==='CONFIRMED'} onClick={()=>setOpen(true)}>{state.phase==='UNKNOWN'?'确认生命周期变更结果':label}</button>
    {state.phase==='CONFIRMED'&&<p role="status">{label}已确认，{error?'详情尚未重新读取。':'正在读取实际详情。'}</p>}
    {state.phase==='CONFIRMED'&&error&&<button type="button" disabled={props.blocked||active} onClick={()=>void execute(true)}>重新读取实际详情</button>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    {state.error&&!open&&<p role="alert" className="inline-error">{state.error}</p>}
    <Confirmation open={open} title={`${label}？`} description={descriptions[props.flow.operation]} busy={props.blocked||active}
      error={state.error} confirmLabel={state.phase==='UNKNOWN'?'重新确认结果':'确认'+label} cancelLabel={state.phase==='UNKNOWN'?'保留请求并关闭弹窗':'取消'}
      cancel={()=>setOpen(false)} confirm={()=>void execute()}/>
  </div>;
}
