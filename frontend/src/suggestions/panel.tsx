import './panel.css';
import {SourceReference} from '../requirements/source-reference.tsx';
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
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),[editing,setEditing]=useState<ReadonlySet<number>>(new Set()),[composing,setComposing]=useState<ReadonlySet<number>>(new Set()),[modal,setModal]=useState<'BULK'|'COMPLETE'|'DISCARD'|null>(null),[bulkIds,setBulkIds]=useState<readonly number[]>([]),[locationError,setLocationError]=useState<string|null>(null),prefix=useId(),batch=state.batch;
 const busy=state.loading||['SUBMITTING','READING'].includes(state.phase),protectedIntent=['UNKNOWN','READING','SUBMITTING','CONFIRMED'].includes(state.phase),[pendingOnly,setPendingOnly]=useState(false),listRoot=useRef<HTMLDivElement>(null),cursor=useRef<number|null>(null);
 const projected=state.receipt&&'batch' in state.receipt&&'suggestions' in state.receipt.batch?state.receipt.batch:batch;
 const totals=state.receipt?('counts' in state.receipt?state.receipt.counts:state.receipt.batch.counts):batch?.counts,metadata=state.receipt&&'batch' in state.receipt?state.receipt.batch:batch;
 const confirmedItem=state.receipt&&'suggestion' in state.receipt?state.receipt.suggestion:null;
 const items=projected?.suggestions.map(item=>confirmedItem?.id===item.id?confirmedItem:item)??[],visible=visibleSuggestions(items,pendingOnly,editing,state.intent?.suggestion?.id??null);
 const indicate=(identity:number)=>{cursor.current=identity;setLocationError(locate(identity)?null:'当前正文或目标无法定位，请重新读取；建议尚未应用。');};
 const next=()=>{const id=nextPendingSuggestion(items,cursor.current);if(id===null||composing.size>0)return;setPendingOnly(true);indicate(id);requestAnimationFrame(()=>{const element=listRoot.current?.querySelector<HTMLElement>(`[data-suggestion-id="${id}"]`);if(!element)return;listRoot.current!.scrollTop+=element.getBoundingClientRect().top-listRoot.current!.getBoundingClientRect().top;element.focus({preventScroll:true});});};
 const decidedNotice=(operation:string|undefined)=>operation==='ACCEPT_PENDING'?'全部待处理建议已接受，确认应用后更新正文':'建议决定已保存，正文保持不变';
 const decide=async(identity:number,decision:'ACCEPTED'|'REJECTED'|'EDITED')=>{if(await owner.decide(identity,decision)){setEditing(previous=>new Set([...previous].filter(id=>id!==identity)));notify(decidedNotice('DECIDE'));}};
 const recover=async()=>{const final=state.intent?.operation,identity=state.intent?.suggestion?.id;if(await (state.phase==='CONFIRMED'?owner.finish():owner.recover())){if(identity)setEditing(previous=>new Set([...previous].filter(id=>id!==identity)));setModal(null);if(final==='COMPLETE')notify(owner.getSnapshot().batch?.completion_result==='NO_CHANGE'?'本批已完成，正文无变化':'本批修改已应用');else if(final==='DISCARD')notify('本批建议已放弃，正文保持不变');else notify(decidedNotice(final));}};
 const confirm=async()=>{if(protectedIntent){await recover();return;}const success=modal==='BULK'?await owner.acceptPending(bulkIds):modal==='COMPLETE'?await owner.complete():await owner.discard();if(success){notify(modal==='BULK'?decidedNotice('ACCEPT_PENDING'):modal==='DISCARD'?'本批建议已放弃，正文保持不变':owner.getSnapshot().batch?.completion_result==='NO_CHANGE'?'本批已完成，正文无变化':'本批修改已应用');setModal(null);}};
 const pending=totals?.pending??0,processed=totals?totals.total-pending:0;
 return <section className="suggestion-panel suggestion-review" aria-label="建议处理" aria-busy={busy}>
  <header className="review-header">
   <div className="review-heading"><h2>{batch?.title??'修改建议'}</h2><span className="review-batch-status" data-state={metadata?.status}>{metadata?.status==='PENDING'?'尚未应用':metadata?.status==='DISCARDED'?'已放弃':metadata?.completion_result==='NO_CHANGE'?'无正文变化':'已应用'}</span></div>
   {metadata&&totals&&<>
    <p className="review-target">目标文档 <strong>{state.target?.name??'文档 '+metadata.target_document_id}</strong><span>基于 V{metadata.base_content_version}</span><span>共 {totals.total} 项</span></p>
    <dl className="review-counts">{([['pending','待处理'],['accepted','已接受'],['rejected','已拒绝'],['edited','已编辑']] as const).map(([key,label])=><div key={key} data-state={key}><dt>{label}</dt><dd>{totals[key]}</dd></div>)}</dl>
    <details className="review-context"><summary>修改说明与来源{metadata.source_refs.length>0?` · ${metadata.source_refs.length} 项`:''}</summary><p>{metadata.summary}</p>{metadata.source_refs.length>0&&<ul>{metadata.source_refs.map(source=><li key={JSON.stringify(source)}><SourceReference read={signal=>owner.readReference(source,signal)} label={source.kind==='REVISION'?`文档 #${source.document_id} · 版本记录 #${source.revision_id}`:source.kind==='MESSAGE'||source.kind==='CARD_ANSWER'?`消息 #${source.message_id}`:`运行 #${source.guide_run_id}`}/></li>)}</ul>}</details>
    {state.detail.current?.id!==metadata.target_document_id&&<p className="review-note">当前正在阅读其他文档，本批仍应用到上述目标。</p>}
   </>}
   <span className="read-status" role="status">{busy?(state.phase==='SUBMITTING'?'正在保存本次建议操作…':'正在读取实际建议和正文…'):''}</span>
  </header>
  {state.phase==='CONFIRMED'&&<p className="review-notice" role="status">操作已确认，正在读取实际批次和正文。</p>}
  {state.error&&!modal&&<p role="alert" className="inline-error review-notice">{state.error}</p>}{locationError&&<p className="review-notice" role="alert">{locationError}</p>}
  {(state.error||state.needs_refresh||locationError)&&!modal&&!protectedIntent&&<button className="ui-button" type="button" disabled={busy||!state.available} onClick={()=>void owner.refresh().then(ok=>{if(ok)setLocationError(null);})}>重新核对建议状态</button>}
  {(state.stale||batch?.status==='PENDING'&&batch.base_content_version!==state.detail.current?.content_version)&&<p className="review-notice" role="alert">正文版本或目标已变化，不能直接完成；请放弃本批后重新发起修改。</p>}
  {protectedIntent&&!modal&&<button className="ui-button" type="button" disabled={busy||!state.available} onClick={()=>void recover()}>{state.phase==='UNKNOWN'?'重新确认建议操作结果':'重读已确认建议操作'}</button>}
  {batch&&<div className="review-toolbar">
   <div className="suggestion-view-tools" role="group" aria-label="建议显示筛选"><button className="ui-button" type="button" aria-pressed={!pendingOnly} disabled={composing.size>0} onClick={()=>setPendingOnly(false)}>全部</button><button className="ui-button" type="button" aria-pressed={pendingOnly} disabled={composing.size>0} onClick={()=>setPendingOnly(true)}>待处理</button></div>
   <div className="review-toolbar-actions"><button className="ui-button" type="button" disabled={busy||!state.available||composing.size>0||nextPendingSuggestion(items,cursor.current)===null} onClick={next}>下一条待处理</button>{metadata?.status==='PENDING'&&<button className="ui-button review-bulk-button" type="button" disabled={!owner.canAcceptPending||composing.size>0} onClick={()=>{setBulkIds(items.filter(item=>item.status==='PENDING').map(item=>item.id));setModal('BULK');}}>接受全部待处理{pending>0?`（${pending}）`:''}</button>}</div>
   {owner.hasPendingDrafts&&<p className="review-draft-help">有未保存的编辑，请先保存或取消编辑，再批量接受。</p>}
  </div>}
  <div className="suggestion-list" ref={listRoot} role="region" aria-label="建议列表">
   {pendingOnly&&visible.length===0&&<p className="panel-empty">{metadata?.status==='PENDING'?'没有待处理建议；已有决定尚须完成本批修改后才会应用。':'没有待处理建议；本批已结束，可切换全部查看已保存的决定。'}</p>}
   {items.map(item=>{const content=state.drafts[item.id]??proposed(item),rowInvalid=item.patch_operation==='REPLACE_TABLE_ROW'&&(!tableRowCells(content,item.proposed_data!.cells.length)||[...content].length>100000);return <article key={item.id} tabIndex={-1} hidden={!visible.includes(item.id)} data-suggestion-id={item.id} className="suggestion-card" data-state={item.status} onClick={event=>{if(!(event.target instanceof Element)||event.target.closest('button,a,input,textarea,label,select,fieldset,details')||window.getSelection()?.isCollapsed===false)return;indicate(item.id);}}>
    <header className="review-card-heading"><span className="review-order">{String(item.order_no).padStart(2,'0')}</span><h3>{item.title}</h3><span className="review-decision-status" data-state={item.status}>{statuses[item.status]}</span></header>
    <div className="review-card-body"><p className="review-explanation">{item.explanation}</p>{item.impact&&<p className="review-impact"><span>影响</span>{item.impact}</p>}
     {item.patch_operation==='INSERT_BEFORE'||item.patch_operation==='INSERT_AFTER'?<p className="review-impact">在目标区块{item.patch_operation==='INSERT_BEFORE'?'之前':'之后'}插入</p>:null}
     <div className={'review-diff'+(item.patch_operation==='DELETE_BLOCK'?' review-diff-delete':'')}>
      <section className="review-diff-pane review-before" aria-label={item.patch_operation==='DELETE_BLOCK'?'待删除内容':'原内容'}><h4>{item.patch_operation==='DELETE_BLOCK'?'待删除内容':item.patch_operation==='REPLACE_TABLE_ROW'?'原表格行':'原内容'}</h4><Preview markdown={item.original_content} {...(item.patch_operation==='REPLACE_TABLE_ROW'?{columns:item.proposed_data!.cells.length}:{})} render={render}/></section>
      {item.patch_operation!=='DELETE_BLOCK'&&<section className="review-diff-pane review-after" aria-label="建议内容"><h4>{item.patch_operation.startsWith('INSERT_')?'新增内容':item.patch_operation==='REPLACE_TABLE_ROW'?'建议表格行':'建议内容'}</h4>
       {editing.has(item.id)?item.patch_operation==='REPLACE_TABLE_ROW'?<RowEdit item={item} content={content} disabled={!owner.editable} change={value=>owner.draft(item.id,value)} composition={active=>setComposing(previous=>active?new Set([...previous,item.id]):new Set([...previous].filter(id=>id!==item.id)))}/>:<label htmlFor={prefix+item.id}>编辑建议内容<textarea className="ui-input" aria-label="编辑建议内容" id={prefix+item.id} value={content} disabled={!owner.editable} onChange={event=>owner.draft(item.id,event.target.value)} onCompositionStart={()=>setComposing(previous=>new Set([...previous,item.id]))} onCompositionEnd={event=>{owner.draft(item.id,event.currentTarget.value);setComposing(previous=>new Set([...previous].filter(id=>id!==item.id)));}}/><span>只编辑建议正文，目标和操作保持不变。</span></label>:item.patch_operation==='REPLACE_TABLE_ROW'?<RowProposal item={item}/>:<Preview markdown={item.status==='EDITED'?item.user_edited_content!:item.proposed_markdown!} render={render}/>}</section>}
     </div>
     {item.validation_status==='INVALID'&&<p role="alert" className="inline-error">{item.validation_error}</p>}{state.item_errors[item.id]&&<p role="alert" className="inline-error">{state.item_errors[item.id]}</p>}
     {state.intent?.suggestion?.id===item.id&&busy&&<p role="status">正在保存此项决定…</p>}
    </div>
    <footer className="suggestion-actions"><button className="ui-button review-locate" type="button" disabled={busy||!state.available} onClick={()=>indicate(item.id)}>定位正文</button>
     {batch?.status==='PENDING'&&<div className="suggestion-decisions" aria-label="建议决定">
      {editing.has(item.id)?<><button className="ui-button primary" type="button" disabled={!owner.editable||composing.has(item.id)||rowInvalid} onClick={()=>void decide(item.id,'EDITED')}>保存编辑并接受</button><button className="ui-button" type="button" disabled={!owner.editable||composing.has(item.id)} onClick={()=>{owner.cancelDraft(item.id);setEditing(previous=>new Set([...previous].filter(id=>id!==item.id)));}}>取消编辑</button></>:
       <><button className="ui-button review-accept" type="button" disabled={!owner.editable||composing.has(item.id)||item.status==='ACCEPTED'} onClick={()=>void decide(item.id,'ACCEPTED')}>{item.status==='ACCEPTED'?'已接受':'接受'}</button><button className="ui-button" type="button" disabled={!owner.editable||composing.has(item.id)||item.status==='REJECTED'} onClick={()=>void decide(item.id,'REJECTED')}>{item.status==='REJECTED'?'已拒绝':'拒绝'}</button>{item.patch_operation!=='DELETE_BLOCK'&&<button className="ui-button" type="button" disabled={!owner.editable} onClick={()=>{owner.draft(item.id,state.drafts[item.id]??proposed(item));setEditing(previous=>new Set([...previous,item.id]));}}>编辑后接受</button>}</>}
     </div>}
    </footer>
   </article>;})}
  </div>
  {batch&&<footer className="review-batch-actions"><div className="review-completion-state"><strong>{metadata?.status==='PENDING'?`已处理 ${processed} / ${totals?.total??0} 项`:metadata?.status==='DISCARDED'?'本批已放弃':'本批已完成'}</strong><p className="suggestion-completion-help">{metadata?.status==='PENDING'?pending>0?'接受仅保存决定，全部处理后再确认应用。':'决定已保存，确认应用后更新正文。':metadata?.status==='DISCARDED'?'正文保持不变。':'以实际保存结果为准。'}</p></div>{metadata?.status==='PENDING'&&<div className="review-final-buttons"><button className="ui-button primary" type="button" disabled={!owner.canComplete||composing.size>0} onClick={()=>setModal('COMPLETE')}>完成本批修改</button><button type="button" className="ui-button destructive-text" disabled={!owner.canDiscard||composing.size>0} onClick={()=>setModal('DISCARD')}>放弃本批建议</button></div>}</footer>}
  <Confirmation open={modal!==null} title={modal==='BULK'?`接受全部 ${bulkIds.length} 项待处理建议？`:modal==='DISCARD'?'放弃本批建议':'完成本批修改'} description={modal==='BULK'?'仅接受本次待处理建议，保留已接受、已拒绝和已编辑的决定。正文暂不改变，仍需完成本批修改后确认应用。':modal==='DISCARD'?'放弃本批后保留已有决定，正文不会改变。':'仅最终确认后才校验并应用本批建议；单项决定本身不会改变正文。'} busy={busy} error={state.error} dangerous={modal==='DISCARD'} confirmDisabled={!state.available||!protectedIntent&&(modal==='BULK'?!owner.canAcceptPending:modal==='COMPLETE'?!owner.canComplete:!owner.canDiscard)} confirmLabel={protectedIntent?state.phase==='UNKNOWN'?'重新确认结果':'仅读恢复':modal==='BULK'?'确认批量接受':modal==='DISCARD'?'确认放弃':'确认应用'} confirm={()=>void confirm()} cancel={()=>setModal(null)}/>
 </section>;
}
