import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode, CSSProperties } from 'react';
import { DetailLayout, DetailViewportGuard } from './detail-layout.ts';
import type { DetailTab } from './detail-layout.ts';
import {Icon} from '../shared/icon.tsx';
import {PageHeader} from '../application/header.tsx';
import {activeModal} from '../shared/modal.ts';
import {useLayoutMotion,useMotionPresence} from '../shared/motion-react.ts';
import {motionTiming} from '../shared/motion.ts';

export interface DetailFrameProps {
  properties?: ReactNode; layout: DetailLayout; viewport: DetailViewportGuard; title: ReactNode; status: ReactNode; actions: ReactNode;
  outline: ReactNode; outlineActions?: ReactNode; document(navigation:ReactNode):ReactNode; ai: ReactNode; progress: ReactNode; comments: ReactNode; revisions: ReactNode;
  activity: string | null; saveStatus: ReactNode; back(): void;
  readPanel(tab: DetailTab, signal: AbortSignal): Promise<void>;
}
const tabs = [{value:'AI',label:'AI 对话'},{value:'PROGRESS',label:'进展'},{value:'COMMENTS',label:'评论'},{value:'REVISIONS',label:'文档记录'}] as const;

/** Actual regions are supplied by the detail owner; no synthetic documents or
 * command permissions are created by this layout component. Hidden regions
 * stay mounted so a viewport change cannot discard editor/local input. */
export function DetailFrame(props: DetailFrameProps) {
  const state = useSyncExternalStore(props.layout.subscribe, props.layout.getSnapshot);
  const guard = useSyncExternalStore(props.viewport.subscribe, props.viewport.getSnapshot);
  const columns = useRef<HTMLDivElement>(null), callbacks = useRef(props); callbacks.current = props;
  const motion=useLayoutMotion(),leftPresent=useMotionPresence(state.left_open,motionTiming.layout),rightPresent=useMotionPresence(state.right_open,motionTiming.layout),documentPresent=useMotionPresence(state.document_open,motionTiming.layout);
  const transition=(change:()=>void)=>motion.run([{element:columns.current,properties:['grid-template-columns']}],change,supported);
  const rightToggle=useRef<HTMLButtonElement>(null);
  const documentView=useRef<HTMLButtonElement>(null);
  const outlineOpen=useRef<HTMLButtonElement>(null),outlineClose=useRef<HTMLButtonElement>(null),outlineFocus=useRef(false);
  const drag = useRef<{id:number;x:number;width:number}|null>(null);
  const [resizing,setResizing]=useState(false);
  const [panelError,setPanelError] = useState(false), [panelRetry,setPanelRetry] = useState(0);
  const supported = state.mode !== 'BLOCKED' && guard.phase === 'SUPPORTED';
  // Revalidation gates interaction, not the last confirmed picture. Hiding
  // columns on every focus return collapses their geometry and flashes the page.
  const visible = state.mode !== 'BLOCKED';
  useLayoutEffect(()=>{if(outlineFocus.current){outlineFocus.current=false;const target=state.left_open&&state.left_drawer?outlineClose.current:state.document_open?outlineOpen.current:documentView.current??rightToggle.current;target?.focus({preventScroll:true});}},[state.left_open,state.left_drawer,state.document_open]);
  const toggleOutline=()=>{outlineFocus.current=true;transition(()=>props.layout.toggleLeft());};
  useLayoutEffect(() => {
    const owner = columns.current!.ownerDocument, browser = owner.defaultView!;
    const pagehide = () => props.viewport.suspendPage();
    const measure = () => {
      const width = browser.innerWidth, padding = width < 1280 ? 16 : 32;
      // The hidden columns have zero rect width; viewport content width remains
      // the constraint while the guard waits for actual state re-read.
      const actual = columns.current?.getBoundingClientRect().width ?? 0;
      props.layout.viewport(width, actual > 0 ? actual : Math.max(0,width-padding)); props.viewport.viewport(width);
    };
    const pageshow = () => { measure(); props.viewport.resumePage(); };
    measure(); props.viewport.activate(); browser.addEventListener('resize',measure);
    browser.addEventListener('pagehide',pagehide); browser.addEventListener('pageshow',pageshow);
    const observer = new ResizeObserver(measure); if(columns.current)observer.observe(columns.current);
    return () => {browser.removeEventListener('resize',measure);browser.removeEventListener('pagehide',pagehide);browser.removeEventListener('pageshow',pageshow);observer.disconnect();};
  },[props.layout,props.viewport]);
  useEffect(() => {
    if (!supported || !state.right_open) return;
    const controller = new AbortController(); setPanelError(false);
    void Promise.resolve().then(() => callbacks.current.readPanel(state.right_tab,controller.signal)).catch(() => { if(!controller.signal.aborted)setPanelError(true); });
    return () => controller.abort();
  },[supported,state.right_open,state.right_tab,panelRetry]);
  // Stable tracks interpolate; hidden regions no longer add/remove grid tracks.
  const sizes = `${state.left_open&&!state.left_drawer?200:0}px ${state.left_open&&!state.left_drawer?6:0}px ${Math.max(0,state.document_width)}px ${state.right_open&&state.split_view?6:0}px ${state.right_open?state.right_width:0}px`;
  const panels: Record<DetailTab,ReactNode> = {AI:props.ai,PROGRESS:props.progress,COMMENTS:props.comments,REVISIONS:props.revisions};
  const navigation=<button ref={outlineOpen} className="ui-button icon-button document-navigation-toggle" disabled={!supported} type="button" aria-label={state.left_open?'收起文档导航':'展开文档导航'} title={state.left_open?'收起文档导航':'展开文档导航'} aria-expanded={state.left_open} aria-controls="detail-outline" onClick={toggleOutline}><Icon name={state.left_open?'collapseLeft':'outline'}/></button>;
  return <main className="requirement-detail-frame" data-layout={state.mode} data-viewport-phase={guard.phase}>
    <PageHeader><header className="detail-header" role="group" aria-label="需求工作栏"><div className="detail-title-row"><div className="detail-return"><button className="ui-button" type="button" aria-label="返回需求工作台" title="返回需求工作台" onClick={props.back} data-focus-fallback><Icon name="left"/>工作台</button>
      <div className="detail-header-view-controls" hidden={!visible||state.split_view} inert={!supported}>
        {!state.split_view&&<div role="group" aria-label="阅读视图"><button ref={documentView} className="ui-button" type="button" disabled={!supported} aria-pressed={state.document_open} onClick={()=>transition(()=>props.layout.showDocument())}>文档</button><button className="ui-button" type="button" disabled={!supported} aria-pressed={state.right_open} onClick={()=>transition(()=>props.layout.openTab('AI'))}>AI 对话</button></div>}
      </div></div>
      <div className="detail-heading"><h1 title={typeof props.title==='string'?props.title:undefined}>{props.title}</h1><div className="detail-subtitle"><div className="detail-context">{props.status}</div><div className="detail-identity">{props.saveStatus}</div></div></div>
      <div className="detail-header-controls" hidden={!visible} inert={!supported}><div className="detail-header-operation-row"><button ref={rightToggle} className="ui-button detail-ai-launcher" type="button" disabled={!supported} aria-label="AI 助手" title="打开 AI 对话" aria-expanded={state.right_open&&state.right_tab==='AI'} aria-controls="detail-panel-AI" onClick={()=>transition(()=>props.layout.openTab('AI'))}><Icon name="panel"/>AI 助手</button><div className="detail-header-business-actions">{props.properties}{props.actions&&<div className="detail-actions">{props.actions}</div>}</div></div>
        {!state.right_open&&props.activity&&<span className="detail-hidden-activity" role="status">{props.activity}</span>}</div></div></header></PageHeader>
    {state.warning && <p role="status" className="detail-layout-warning">{state.warning}</p>}
    {!visible && <section className="detail-window-block" role="status">
      <h2>当前窗口过窄，请将窗口调整至至少 1024px</h2><p>调整窗口后重新读取当前状态。</p>
      {guard.saving && <p>正在尝试保存草稿…</p>}
      {guard.save_failed && <p className="inline-error">草稿保存失败，当前编辑内容仍保留在本页。</p>}
      <div>{props.saveStatus}</div>
    </section>}
    <div className="detail-document-toolbar" hidden={!visible||supported}>
      <div className="detail-refresh-status" role="status" aria-live="polite">
        {!supported && <div className="detail-refresh-notice">
          {guard.phase === 'RESTORE_FAILED' ? <>状态读取失败，内容保留，操作暂停。<button className="ui-button" type="button" onClick={() => props.viewport.retry()}>重新读取</button></> : <span>正在同步状态，操作暂时暂停…</span>}
          {guard.save_failed && <span className="inline-error">草稿保存失败，编辑内容仍保留。</span>}
        </div>}
      </div>
    </div>
    <div className="detail-columns" ref={columns} data-navigation-drawer={state.left_drawer} hidden={!visible} inert={!supported} aria-busy={!supported} style={{gridTemplateColumns:sizes} as CSSProperties}>
      {state.left_drawer&&state.left_open&&<button type="button" className="detail-navigation-backdrop" aria-label="关闭文档导航" onClick={toggleOutline}/>}
      <aside id="detail-outline" className="detail-outline" hidden={!leftPresent} inert={!state.left_open} aria-hidden={!state.left_open} data-motion-open={state.left_open} aria-label="文档导航" onKeyDown={event=>{if(state.left_drawer&&event.key==='Escape'&&!event.defaultPrevented&&!event.nativeEvent.isComposing&&!activeModal()){event.preventDefault();toggleOutline();}}}><header className="outline-heading detail-outline-heading"><button ref={outlineClose} className="ui-button icon-button" hidden={!state.left_drawer} type="button" aria-label="收起文档导航" title="收起文档导航" aria-expanded={state.left_open} aria-controls="detail-outline" onClick={toggleOutline}><Icon name="collapseLeft"/></button><strong>文档导航</strong><div className="detail-outline-actions">{props.outlineActions}</div></header>{props.outline}</aside>
      <div className="detail-left-divider" hidden={!leftPresent||state.left_drawer} />
      <section className="detail-document-region" hidden={!documentPresent} inert={!state.document_open} aria-hidden={!state.document_open} data-motion-open={state.document_open} aria-label="需求正文"><div className="detail-document-content">{props.document(navigation)}</div></section>
      <div className="detail-resizer" data-resizing={resizing} hidden={!state.right_open||!state.split_view} role="separator" aria-label="调整辅助面板宽度" title="拖动调整辅助面板宽度；方向键每次调整20px" aria-orientation="vertical"
        aria-valuemin={360} aria-valuemax={Math.floor(state.right_max)} aria-valuenow={Math.round(state.right_width)} tabIndex={state.right_open ? 0 : -1}
        onPointerDown={event => { if(event.button!==0)return;event.preventDefault();motion.cancel();drag.current={id:event.pointerId,x:event.clientX,width:state.right_width};setResizing(true);event.currentTarget.setPointerCapture(event.pointerId); }}
        onPointerMove={event => {const start=drag.current;if(start&&start.id===event.pointerId)props.layout.resizeRight(start.width+start.x-event.clientX);}}
        onPointerUp={() => {drag.current=null;setResizing(false);}} onPointerCancel={() => {drag.current=null;setResizing(false);}} onLostPointerCapture={() => {drag.current=null;setResizing(false);}}
        onKeyDown={event => {
          const value = event.key==='ArrowLeft' ? state.right_width+20 : event.key==='ArrowRight' ? state.right_width-20 : event.key==='Home' ? 360 : event.key==='End' ? state.right_max : null;
          if(value!==null){event.preventDefault();transition(()=>props.layout.resizeRight(value));}
        }} />
      <aside className="detail-panel" hidden={!rightPresent} inert={!state.right_open} aria-hidden={!state.right_open} data-motion-open={state.right_open} aria-label="辅助面板">
        <div className="detail-panel-heading"><button className="ui-button icon-button detail-panel-width" type="button" disabled={!supported||!state.split_view||state.right_max<380} aria-label={state.right_width<state.right_max-1?'展开辅助面板宽度':'收窄辅助面板宽度'} title={state.right_max<380?'当前窗口没有足够的调宽空间':state.right_width<state.right_max-1?'展开至当前可用最大宽度':'收窄至360px'} onClick={()=>transition(()=>props.layout.resizeRight(state.right_width<state.right_max-1?state.right_max:360))}><Icon name="panel"/></button><div className="detail-panel-tabs" role="tablist" aria-label="辅助功能">{tabs.map(item => <button className="ui-button" key={item.value} type="button" role="tab"
          id={`detail-tab-${item.value}`} title={item.value==='PROGRESS'?'大纲与进展':item.label} aria-controls={`detail-panel-${item.value}`} aria-selected={state.right_tab===item.value}
          tabIndex={state.right_tab===item.value?0:-1} onKeyDown={event=>{
            const index=tabs.findIndex(tab=>tab.value===item.value),next=event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
            if(next===null)return;event.preventDefault();const target=tabs[next]!;transition(()=>props.layout.openTab(target.value));
            event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`#detail-tab-${target.value}`)?.focus({preventScroll:true});
          }}
          onClick={() => transition(()=>props.layout.openTab(item.value))}>{item.label}</button>)}</div><button className="ui-button icon-button detail-panel-close" type="button" disabled={!supported} aria-label="关闭辅助面板" title="关闭辅助面板" onClick={()=>{transition(()=>props.layout.toggleRight());rightToggle.current?.focus({preventScroll:true});}}><Icon name="close"/></button></div>
        {panelError && <div className="detail-panel-error" role="alert">读取失败，保留已确认内容。<button className="ui-button" type="button" onClick={() => setPanelRetry(value=>value+1)}>重试</button></div>}
        {tabs.map(item => <section key={item.value} id={`detail-panel-${item.value}`} role="tabpanel" aria-labelledby={`detail-tab-${item.value}`}
          className="detail-panel-content" hidden={state.right_tab!==item.value} inert={state.right_tab!==item.value}>{panels[item.value]}</section>)}
      </aside>
    </div>
  </main>;
}
