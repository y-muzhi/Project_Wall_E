import {useSyncExternalStore} from 'react';
import type {RequirementRunActions} from './run-actions.ts';
export function RunControls({owner}:Readonly<{owner:RequirementRunActions}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),busy=state.refreshing||['SUBMITTING','READING'].includes(state.phase),protectedIntent=['UNKNOWN','CONFIRMED'].includes(state.phase);
 return <section aria-label="AI 运行操作" className="run-controls" aria-busy={busy}>
  {state.run?.status==='FAILED'&&<button type="button" disabled={busy||protectedIntent||!owner.allowed('RETRY')} onClick={()=>void owner.start('RETRY')}>重新运行</button>}
  {state.run&&['RUNNING','WAITING_USER'].includes(state.run.status)&&<><button type="button" disabled={busy||protectedIntent||!owner.allowed('CANCEL')} onClick={()=>void owner.start('CANCEL')}>取消运行</button>{state.run.current_step==='PERSISTING'&&<p>当前结果正在提交，不能取消，请等待最终结果。</p>}</>}
  {state.origin&&<p>本次{state.operation==='CANCEL'?'取消':'重新运行'}操作针对原运行，原记录保持独立。</p>}
  {state.phase==='SUBMITTING'&&<p role="status">{state.operation==='CANCEL'?'正在取消运行…':'正在接受新的运行…'}</p>}
  {state.phase==='READING'&&<p role="status">正在核实实际资源，原请求已保留…</p>}
  {state.phase==='CONFIRMED'&&<p role="status">{state.operation==='CANCEL'?'取消已确认':'新运行已接受'}，正在读取实际运行与需求；接受不表示模型完成。</p>}
  {state.error&&<p role="alert" className="inline-error">{state.error}</p>}
  {state.phase==='UNKNOWN'&&<button type="button" disabled={busy||!state.available} onClick={()=>void owner.recover()}>重新确认运行操作结果</button>}
  {state.phase==='CONFIRMED'&&<button type="button" disabled={busy||!state.available} onClick={()=>void owner.finish()}>重读已确认运行操作</button>}
  {state.phase==='ERROR'&&<button type="button" disabled={busy||!state.available} onClick={()=>void owner.refresh()}>重读运行与需求</button>}
 </section>;
}
