import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode, CSSProperties } from 'react';
import { DetailLayout, DetailViewportGuard } from './detail-layout.ts';
import type { DetailTab } from './detail-layout.ts';

export interface DetailFrameProps {
  layout: DetailLayout; viewport: DetailViewportGuard; title: ReactNode; status: ReactNode; actions: ReactNode;
  outline: ReactNode; document: ReactNode; ai: ReactNode; comments: ReactNode; revisions: ReactNode;
  activity: string | null; saveStatus: ReactNode; back(): void;
  readPanel(tab: DetailTab, signal: AbortSignal): Promise<void>;
}
const tabs = [{value:'AI',label:'AI 对话'},{value:'COMMENTS',label:'评论'},{value:'REVISIONS',label:'版本记录'}] as const;

/** Actual regions are supplied by the detail owner; no synthetic documents or
 * command permissions are created by this layout component. Hidden regions
 * stay mounted so a viewport change cannot discard editor/local input. */
export function DetailFrame(props: DetailFrameProps) {
  const state = useSyncExternalStore(props.layout.subscribe, props.layout.getSnapshot);
  const guard = useSyncExternalStore(props.viewport.subscribe, props.viewport.getSnapshot);
  const columns = useRef<HTMLDivElement>(null), callbacks = useRef(props); callbacks.current = props;
  const drag = useRef<{id:number;x:number;width:number}|null>(null);
  const [panelError,setPanelError] = useState(false), [panelRetry,setPanelRetry] = useState(0);
  const supported = state.mode !== 'BLOCKED' && guard.phase === 'SUPPORTED';
  useLayoutEffect(() => {
    const owner = columns.current!.ownerDocument, browser = owner.defaultView!;
    const visibility = () => props.viewport.setForeground(!owner.hidden);
    const pagehide = () => props.viewport.setForeground(false);
    const focus = () => { visibility(); props.viewport.refreshAfterFocus(); };
    const measure = () => {
      const width = browser.innerWidth, padding = width < 1280 ? 16 : 32;
      // The hidden columns have zero rect width; viewport content width remains
      // the constraint while the guard waits for actual state re-read.
      const actual = columns.current?.getBoundingClientRect().width ?? 0;
      props.layout.viewport(width, actual > 0 ? actual : Math.max(0,width-padding)); props.viewport.viewport(width);
    };
    visibility(); measure(); props.viewport.activate(); browser.addEventListener('resize',measure);
    owner.addEventListener('visibilitychange',visibility); browser.addEventListener('pagehide',pagehide); browser.addEventListener('pageshow',visibility); browser.addEventListener('focus',focus);
    const observer = new ResizeObserver(measure); if(columns.current)observer.observe(columns.current);
    return () => {browser.removeEventListener('resize',measure);owner.removeEventListener('visibilitychange',visibility);browser.removeEventListener('pagehide',pagehide);browser.removeEventListener('pageshow',visibility);browser.removeEventListener('focus',focus);observer.disconnect();};
  },[props.layout,props.viewport]);
  useEffect(() => {
    if (!supported || !state.right_open) return;
    const controller = new AbortController(); setPanelError(false);
    void Promise.resolve().then(() => callbacks.current.readPanel(state.right_tab,controller.signal)).catch(() => { if(!controller.signal.aborted)setPanelError(true); });
    return () => controller.abort();
  },[supported,state.right_open,state.right_tab,panelRetry]);
  const sizes = `${state.left_open ? '200px 6px ' : ''}minmax(640px, 1fr)${state.right_open ? ` 6px ${state.right_width}px` : ''}`;
  const panels: Record<DetailTab,ReactNode> = {AI:props.ai,COMMENTS:props.comments,REVISIONS:props.revisions};
  return <main className="requirement-detail-frame" data-layout={state.mode} data-viewport-phase={guard.phase}>
    <header className="detail-header"><button type="button" onClick={props.back} data-focus-fallback>返回需求工作台</button>
      <div className="detail-heading"><h1>{props.title}</h1><div>{props.status}</div></div>
      <div className="detail-actions" hidden={!supported} inert={!supported}>{props.actions}</div></header>
    {state.warning && <p role="status" className="detail-layout-warning">{state.warning}</p>}
    {!supported && <section className="detail-window-block" role="status">
      {state.mode === 'BLOCKED' ? <><h2>当前窗口过窄，请将窗口调整至至少 1024px</h2><p>调整窗口后重新读取当前状态。</p></> :
        guard.phase === 'RESTORE_FAILED' ? <><h2>当前状态读取失败</h2><button type="button" onClick={() => props.viewport.retry()}>重新读取</button></> : <h2>正在重新读取当前状态…</h2>}
      {guard.saving && <p>正在尝试保存草稿…</p>}
      {guard.save_failed && <p className="inline-error">草稿保存失败，当前编辑内容仍保留在本页。</p>}
      <div>{props.saveStatus}</div>
    </section>}
    <div className="detail-document-toolbar" hidden={!supported} inert={!supported}>
      <button type="button" aria-expanded={state.left_open} onClick={() => props.layout.toggleLeft()}>大纲</button>
      <button type="button" aria-expanded={state.right_open} onClick={() => props.layout.toggleRight()}>辅助面板{!state.right_open && props.activity ? ` · ${props.activity}` : ''}</button>
      <div className="detail-save-status">{props.saveStatus}</div>
    </div>
    <div className="detail-columns" ref={columns} hidden={!supported} inert={!supported} style={{gridTemplateColumns:sizes} as CSSProperties}>
      <aside className="detail-outline" hidden={!state.left_open} aria-label="文档大纲">{props.outline}</aside>
      <div className="detail-left-divider" hidden={!state.left_open} />
      <section className="detail-document-region" aria-label="需求正文"><div className="detail-document-content">{props.document}</div></section>
      <div className="detail-resizer" hidden={!state.right_open} role="separator" aria-label="调整辅助面板宽度" aria-orientation="vertical"
        aria-valuemin={360} aria-valuemax={Math.floor(state.right_max)} aria-valuenow={Math.round(state.right_width)} tabIndex={state.right_open ? 0 : -1}
        onPointerDown={event => { if(event.button!==0)return;event.preventDefault();drag.current={id:event.pointerId,x:event.clientX,width:state.right_width};event.currentTarget.setPointerCapture(event.pointerId); }}
        onPointerMove={event => {const start=drag.current;if(start&&start.id===event.pointerId)props.layout.resizeRight(start.width+start.x-event.clientX);}}
        onPointerUp={() => {drag.current=null;}} onPointerCancel={() => {drag.current=null;}} onLostPointerCapture={() => {drag.current=null;}}
        onKeyDown={event => {
          const value = event.key==='ArrowLeft' ? state.right_width+20 : event.key==='ArrowRight' ? state.right_width-20 : event.key==='Home' ? 360 : event.key==='End' ? state.right_max : null;
          if(value!==null){event.preventDefault();props.layout.resizeRight(value);}
        }} />
      <aside className="detail-panel" hidden={!state.right_open} aria-label="辅助面板">
        <div className="detail-panel-tabs" role="tablist" aria-label="辅助功能">{tabs.map(item => <button key={item.value} type="button" role="tab"
          id={`detail-tab-${item.value}`} aria-controls={`detail-panel-${item.value}`} aria-selected={state.right_tab===item.value}
          onClick={() => props.layout.openTab(item.value)}>{item.label}</button>)}</div>
        {panelError && <div className="detail-panel-error" role="alert">读取失败，保留已确认内容。<button type="button" onClick={() => setPanelRetry(value=>value+1)}>重试</button></div>}
        {tabs.map(item => <section key={item.value} id={`detail-panel-${item.value}`} role="tabpanel" aria-labelledby={`detail-tab-${item.value}`}
          className="detail-panel-content" hidden={state.right_tab!==item.value} inert={state.right_tab!==item.value}>{panels[item.value]}</section>)}
      </aside>
    </div>
  </main>;
}
