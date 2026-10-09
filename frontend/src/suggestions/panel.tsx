import {useId,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {Suggestion} from '../api/models.ts';
import {Confirmation} from '../shared/confirmation.tsx';
import type {RequirementSuggestionBatch} from './batch-owner.ts';
import {tableRowCells,replaceRowCell} from './row-edit.ts';
import {visibleSuggestions,nextPendingSuggestion} from './display.ts';
const statuses={PENDING:'待处理',ACCEPTED:'已接受',REJECTED:'已拒绝',EDITED:'已编辑并接受'} as const;
type Render=(markdown:string,rowColumns?:number)=>DocumentFragment;
function Preview({markdown,columns,render}:Readonly<{markdown:string;columns?:number;render:Render}>){
 const root=useRef<HTMLDivElement>(null),[error,setError]=useState(false);
 useLayoutEffect(()=>{try{root.current!.replaceChildren(render(markdown,columns));setError(false);}catch{root.current!.replaceChildren();setError(true);}return()=>root.current?.replaceChildren();},[markdown,columns,render]);
 return <><div ref={root} className="suggestion-preview milkdown"/>{error&&<><p role="alert">内容渲染失败，保留完整原文。</p><pre>{markdown}</pre></>}</>;
}
function Cells({cells}:Readonly<{cells:readonly string[]}>){return <div className="suggestion-preview"><table><tbody><tr>{cells.map((cell,index)=><td key={index}>{cell}</td>)}</tr></tbody></table></div>;}
function proposed(item:Suggestion):string{return item.user_edited_content??item.proposed_markdown??JSON.stringify(item.proposed_data);}
function RowProposal({item}:Readonly<{item:Suggestion}>){try{const cells=item.status==='EDITED'?JSON.parse(item.user_edited_content!).cells:item.proposed_data!.cells;if(!Array.isArray(cells)||cells.some(cell=>typeof cell!=='string'))throw Error('Invalid cells');return <Cells cells={cells}/>;}catch{return <><p role="alert">已保存的行内容无法渲染，保留原文。</p><pre>{item.user_edited_content}</pre></>;}}
function RowEdit({item,content,disabled,change,composition}:Readonly<{item:Suggestion;content:string;disabled:boolean;change(value:string):void;composition(active:boolean):void}>){
 const columns=item.proposed_data!.cells.length,cells=tableRowCells(content,columns);
 if(!cells)return <div><p role="alert" className="inline-error">表格行暂时无法编辑，原输入已保留。重新编辑将用建议行替换这份输入。</p><details><summary>查看保留的原输入</summary><pre>{content}</pre></details><button className="ui-button" type="button" disabled={disabled} onClick={()=>change(JSON.stringify(item.proposed_data))}>从建议行重新编辑</button></div>;
 return <fieldset className="suggestion-row-editor" disabled={disabled}><legend>编辑表格行</legend>{cells.map((cell,index)=><label key={index}>第 {index+1} 列<textarea className="ui-input" rows={2} value={cell} onChange={event=>change(replaceRowCell(content,columns,index,event.target.value))} onCompositionStart={()=>composition(true)} onCompositionEnd={event=>{change(replaceRowCell(content,columns,index,event.currentTarget.value));composition(false);}}/></label>)}<p className="field-help">保持原来的 {columns} 列，按单元格填写文字；不改变目标行。</p>{[...content].length>100000&&<p role="alert" className="inline-error">编辑内容超过容量，请缩短后保存。</p>}</fieldset>;
}

/** The owner keeps original drafts/requests; modal and edit-region visibility
 * are local UI. A successful individual decision never alters CURRENT. */
export function SuggestionPanel({owner,render,locate,notify}:Readonly<{owner:RequirementSuggestionBatch;render:Render;locate:(identity:number)=>boolean;notify:(message:string)=>void}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),[editing,setEditing]=useState<ReadonlySet<number>>(new Set()),[composing,setComposing]=useState<ReadonlySet<number>>(new Set()),[modal,setModal]=useState<'COMPLETE'|'DISCARD'|null>(null),[locationError,setLocationError]=useState<string|null>(null),prefix=useId(),batch=state.batch;
 const busy=state.loading||['SUBMITTING','READING'].includes(state.phase),protectedIntent=['UNKNOWN','CONFIRMED'].includes(state.phase);
 const [pendingOnly,setPendingOnly]=useState(false),listRoot=useRef<HTMLDivElement>(null),cursor=useRef<number|null>(null);
 const totals=state.receipt?.counts??batch?.counts,metadata=state.receipt&&'batch' in state.receipt?state.receipt.batch:batch,confirmedItem=state.receipt&&'suggestion' in state.receipt?state.receipt.suggestion:null;
 const items=batch?.suggestions.map(item=>confirmedItem?.id===item.id?confirmedItem:item)??[],visible=visibleSuggestions(items,pendingOnly,editing,state.intent?.suggestion?.id??null);
 const indicate=(identity:number)=>{cursor.current=identity;setLocationError(locate(identity)?null:'当前正文或目标无法定位，请重新读取；建议尚未应用。');};
 const next=()=>{const id=nextPendingSuggestion(items,cursor.current);if(id===null||composing.size>0)return;setPendingOnly(true);indicate(id);requestAnimationFrame(()=>{const element=listRoot.current?.querySelector<HTMLElement>(`[data-suggestion-id="${id}"]`);if(!element)return;listRoot.current!.scrollTop+=element.getBoundingClientRect().top-listRoot.current!.getBoundingClientRect().top;element.focus({preventScroll:true});});};
 const decide=async(identity:number,decision:'ACCEPTED'|'REJECTED'|'EDITED')=>{if(await owner.decide(identity,decision)){setEditing(previous=>new Set([...previous].filter(id=>id!==identity)));notify('建议决定已保存，正文保持不变');}};
 const recover=async()=>{const final=state.intent?.operation,identity=state.intent?.suggestion?.id;if(await (state.phase==='CONFIRMED'?owner.finish():owner.recover())){if(identity)setEditing(previous=>new Set([...previous].filter(id=>id!==identity)));if(final==='COMPLETE'){setModal(null);notify(owner.getSnapshot().batch?.completion_result==='NO_CHANGE'?'本批已完成，正文无变化':'本批修改已应用');}else if(final==='DISCARD'){setModal(null);notify('本批建议已放弃，正文保持不变');}else notify('建议决定已保存，正文保持不变');}};
 const confirm=async()=>{if(protectedIntent){await recover();return;}if(await (modal==='COMPLETE'?owner.complete():owner.discard())){notify(modal==='DISCARD'?'本批建议已放弃，正文保持不变':owner.getSnapshot().batch?.completion_result==='NO_CHANGE'?'本批已完成，正文无变化':'本批修改已应用');setModal(null);}};
 return <section className="suggestion-panel" aria-label="建议处理" aria-busy={busy}>
  <header><div className="read-section-heading"><strong>{batch?.title??'建议批次'}</strong><span className="read-status" role="status">{busy?(state.phase==='SUBMITTING'?'正在保存本次建议操作…':'正在读取实际建议和正文…'):''}</span></div>{metadata&&totals&&<><p>{metadata.summary}</p><p>共 {totals.total} 项 · 待处理 {totals.pending} · 已接受 {totals.accepted} · 已拒绝 {totals.rejected} · 已编辑 {totals.edited}</p><p>{metadata.status==='PENDING'?'本批尚未应用':metadata.status==='DISCARDED'?'本批已放弃':metadata.completion_result==='NO_CHANGE'?'本批已完成，正文无变化':'本批修改已应用'}</p>{state.receipt&&<p>已显示确认回执，完整批次正在重读。</p>}</>}</header>
  {state.phase==='CONFIRMED'&&<p role="status">操作已确认，正在读取实际批次和正文。</p>}
  {state.error&&!modal&&<p role="alert" className="inline-error">{state.error}</p>}{locationError&&<p role="alert">{locationError}</p>}
  {(state.error||state.needs_refresh||locationError)&&!modal&&!protectedIntent&&<button className="ui-button" type="button" disabled={busy||!state.available} onClick={()=>void owner.refresh().then(ok=>{if(ok)setLocationError(null);})}>重新核对建议状态</button>}
  {(state.stale||batch?.status==='PENDING'&&batch.base_content_version!==state.detail.current.content_version)&&<p role="alert">正文版本或目标已变化，不能直接完成；请放弃本批后重新发起修改。</p>}
  {protectedIntent&&!modal&&<button className="ui-button" type="button" disabled={busy||!state.available} onClick={()=>void recover()}>{state.phase==='UNKNOWN'?'重新确认建议操作结果':'重读已确认建议操作'}</button>}
  {batch&&<div className="suggestion-view-tools" role="group" aria-label="建议显示筛选"><button className="ui-button" type="button" aria-pressed={!pendingOnly} disabled={composing.size>0} onClick={()=>setPendingOnly(false)}>全部</button><button className="ui-button" type="button" aria-pressed={pendingOnly} disabled={composing.size>0} onClick={()=>setPendingOnly(true)}>待处理</button><button className="ui-button" type="button" disabled={busy||!state.available||composing.size>0||nextPendingSuggestion(items,cursor.current)===null} onClick={next}>下一条待处理</button></div>}
  <div className="suggestion-list" ref={listRoot} role="region" aria-label="建议列表">
  {pendingOnly&&visible.length===0&&<p className="panel-empty">{metadata?.status==='PENDING'?'没有待处理建议；已有决定尚须完成本批修改后才会应用。':'没有待处理建议；本批已结束，可切换全部查看已保存的决定。'}</p>}
  {items.map(item=>{const content=state.drafts[item.id]??proposed(item),rowInvalid=item.patch_operation==='REPLACE_TABLE_ROW'&&(!tableRowCells(content,item.proposed_data!.cells.length)||[...content].length>100000);return <article key={item.id} tabIndex={-1} hidden={!visible.includes(item.id)} data-suggestion-id={item.id} className="suggestion-card" onClick={event=>{if(!(event.target instanceof Element)||event.target.closest('button,a,input,textarea,label,select,fieldset,details')||window.getSelection()?.isCollapsed===false)return;indicate(item.id);}}>
   <h3>{item.order_no}. {item.title}</h3><p>{statuses[item.status]}</p><p>{item.explanation}</p>{item.impact&&<p>影响：{item.impact}</p>}
   {item.patch_operation==='INSERT_BEFORE'||item.patch_operation==='INSERT_AFTER'?<p>在目标区块{item.patch_operation==='INSERT_BEFORE'?'之前':'之后'}插入</p>:null}
   <h4>{item.patch_operation==='DELETE_BLOCK'?'待删除内容':item.patch_operation==='REPLACE_TABLE_ROW'?'原表格行':'原内容'}</h4>
   <Preview markdown={item.original_content} {...(item.patch_operation==='REPLACE_TABLE_ROW'?{columns:item.proposed_data!.cells.length}:{})} render={render}/>
   {item.patch_operation!=='DELETE_BLOCK'&&<><h4>{item.patch_operation.startsWith('INSERT_')?'新增内容':item.patch_operation==='REPLACE_TABLE_ROW'?'建议表格行':'建议内容'}</h4>
    {editing.has(item.id)?item.patch_operation==='REPLACE_TABLE_ROW'?<RowEdit item={item} content={content} disabled={!owner.editable} change={value=>owner.draft(item.id,value)} composition={active=>setComposing(previous=>active?new Set([...previous,item.id]):new Set([...previous].filter(id=>id!==item.id)))}/>:<label htmlFor={prefix+item.id}>编辑建议内容<textarea className="ui-input" id={prefix+item.id} value={content} disabled={!owner.editable} onChange={event=>owner.draft(item.id,event.target.value)} onCompositionStart={()=>setComposing(previous=>new Set([...previous,item.id]))} onCompositionEnd={event=>{owner.draft(item.id,event.currentTarget.value);setComposing(previous=>new Set([...previous].filter(id=>id!==item.id)));}}/><span>只编辑建议正文，目标和操作保持不变。</span></label>:item.patch_operation==='REPLACE_TABLE_ROW'?<RowProposal item={item}/>:<Preview markdown={item.status==='EDITED'?item.user_edited_content!:item.proposed_markdown!} render={render}/>}</>}
   {item.validation_status==='INVALID'&&<p role="alert">{item.validation_error}</p>}{state.item_errors[item.id]&&<p role="alert">{state.item_errors[item.id]}</p>}
   {state.intent?.suggestion?.id===item.id&&busy&&<p role="status">正在保存此项决定…</p>}
   <div className="suggestion-actions"><button className="ui-button" type="button" disabled={busy||!state.available} onClick={()=>indicate(item.id)}>定位目标</button>
    {batch?.status==='PENDING'&&<div className="suggestion-decisions" aria-label="建议决定">
     {editing.has(item.id)?<><button className="ui-button" type="button" disabled={!owner.editable||composing.has(item.id)||rowInvalid} onClick={()=>void decide(item.id,'EDITED')}>保存编辑并接受</button><button className="ui-button" type="button" disabled={busy||protectedIntent||composing.has(item.id)} onClick={()=>setEditing(previous=>new Set([...previous].filter(id=>id!==item.id)))}>取消编辑</button></>:
      <><button className="ui-button" type="button" disabled={!owner.editable||composing.has(item.id)} onClick={()=>void decide(item.id,'ACCEPTED')}>接受</button><button className="ui-button" type="button" disabled={!owner.editable||composing.has(item.id)} onClick={()=>void decide(item.id,'REJECTED')}>拒绝</button>
       {item.patch_operation!=='DELETE_BLOCK'&&<button className="ui-button" type="button" disabled={!owner.editable} onClick={()=>{owner.draft(item.id,state.drafts[item.id]??proposed(item));setEditing(previous=>new Set([...previous,item.id]));}}>编辑后接受</button>}</>}
    </div>}
   </div>
  </article>;})}
  </div>
  {batch&&<footer><p className="suggestion-completion-help">{metadata?.status==='PENDING'?`已处理 ${totals?totals.total-totals.pending:0} / ${totals?.total??0} 项 · 决定尚未应用；完成本批后才更新正文。`:metadata?.status==='DISCARDED'?'本批已放弃，正文保持不变。':'本批已结束，以实际结果为准。'}</p><button className="ui-button primary" type="button" disabled={!owner.canComplete||composing.size>0} onClick={()=>setModal('COMPLETE')}>完成本批修改</button><button type="button" className="ui-button destructive-text" disabled={!owner.canDiscard||composing.size>0} onClick={()=>setModal('DISCARD')}>放弃本批建议</button></footer>}
  <Confirmation open={modal!==null} title={modal==='DISCARD'?'放弃本批建议':'完成本批修改'} description={modal==='DISCARD'?'放弃本批后保留已有决定，正文不会改变。':'仅最终确认后才校验并应用本批建议；单项决定本身不会改变正文。'} busy={busy} error={state.error} dangerous={modal==='DISCARD'} confirmDisabled={!state.available||!protectedIntent&&(modal==='COMPLETE'?!owner.canComplete:!owner.canDiscard)} confirmLabel={protectedIntent?state.phase==='UNKNOWN'?'重新确认结果':'仅读恢复':modal==='DISCARD'?'确认放弃':'确认应用'} confirm={()=>void confirm()} cancel={()=>setModal(null)}/>
 </section>;
}
