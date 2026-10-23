import {useId, useLayoutEffect, useRef, useState} from 'react';
import {Icon} from '../shared/icon.tsx';
import {activeModal, registerModal, trapModalTab} from '../shared/modal.ts';

const desktopNavigation = '(min-width: 1480px)';
const collapsedKey='walle:v1.5:navigation-collapsed';
function restoredCollapsed():boolean{try{return window.localStorage.getItem(collapsedKey)==='1';}catch{return false;}}

/** Global navigation is separate from the detail's document outline. Its drawer
 * keeps its preference separate from the measured detail layout. */
export function ApplicationNavigation({current, navigate,headerHost,headerHeight}: Readonly<{
  current: 'page'|'location'|undefined; navigate(): void;
  headerHost?(element:HTMLDivElement|null):void;headerHeight?(height:number):void;
}>) {
  const [wide, setWide] = useState(() => window.matchMedia(desktopNavigation).matches);
  const [collapsed,setCollapsed]=useState(restoredCollapsed);
  const [open, setOpen] = useState(false), [hint,setHint]=useState(false), id = useId();
  const shortcut=navigator.userAgent.includes('Mac')?'⌘+Shift+S':'Ctrl+Shift+S';
  const toggle = useRef<HTMLButtonElement>(null), destination = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDialogElement>(null), release = useRef<(() => void) | null>(null);
  const header=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{
    const element=header.current;if(!element||!headerHeight)return;
    const measure=()=>headerHeight(Math.ceil(element.getBoundingClientRect().height));
    measure();const observer=new ResizeObserver(measure);observer.observe(element);return()=>observer.disconnect();
  },[headerHeight]);
  useLayoutEffect(() => {
    const media = window.matchMedia(desktopNavigation);
    const changed = () => { setWide(media.matches); setOpen(false); };
    changed(); media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  useLayoutEffect(() => {
    if (!open || wide) return;
    const element = drawer.current!;
    element.showModal(); const unregister = registerModal(element); release.current = unregister;
    destination.current?.focus();
    return () => {
      element.close(); unregister(); if (release.current === unregister) release.current = null;
      if (!activeModal()) {
        const target = toggle.current ?? destination.current;
        if (target?.isConnected) target.focus({preventScroll: true});
      }
    };
  }, [open, wide]);
  const close = () => {
    drawer.current?.close(); release.current?.(); release.current = null; setOpen(false);
  };
  const visit = () => {
    // Release the navigation modal before a route guard opens its own dialog.
    if (open) close();
    navigate();
  };
  const fold=()=>{const next=!collapsed;setCollapsed(next);try{window.localStorage.setItem(collapsedKey,next?'1':'0');}catch{/* The current tab still retains this preference. */}};
  const toggleNavigation=()=>{setHint(false);if(wide)fold();else if(open)close();else setOpen(true);};
  useLayoutEffect(()=>{
    const keydown=(event:KeyboardEvent)=>{
      if(event.isComposing||event.altKey||!event.shiftKey||!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=='s')return;
      const modal=activeModal();if(modal&&modal!==drawer.current)return;
      event.preventDefault();event.stopPropagation();if(!event.repeat)toggleNavigation();
    };
    window.addEventListener('keydown',keydown,true);return()=>window.removeEventListener('keydown',keydown,true);
  },[wide,collapsed,open]);
  const navigation = <nav className={'application-navigation'+(wide&&collapsed?' is-collapsed':'')} aria-label="主导航" id={wide ? id : undefined}>
    <button ref={destination} type="button" className="ui-button application-navigation-item" aria-label="需求工作台" title="需求工作台" aria-current={current} onClick={visit}>
      <Icon name="workbench"/><span className="application-navigation-label">需求工作台</span>
    </button>
  </nav>;
  return <>
    <div className="application-header" role="banner" ref={header}>
      <div className={'application-brand-zone'+(wide&&collapsed?' is-collapsed':'')}>
      <span className="application-brand-lockup" hidden={!wide||collapsed}><span className="application-brand">WALL-E</span></span>
      <span className="application-navigation-toggle-wrap" onMouseEnter={()=>setHint(true)} onMouseLeave={()=>setHint(false)}>
        <button ref={toggle} type="button" className={'ui-button application-navigation-toggle'+(wide&&collapsed?' is-compact':'')}
          aria-label={wide?(collapsed?'展开导航栏':'收起导航栏'):'展开主导航'} aria-keyshortcuts={shortcut.startsWith('⌘')?'Meta+Shift+S':'Control+Shift+S'} aria-describedby={hint?`${id}-hint`:undefined}
          aria-haspopup={wide?undefined:'dialog'} aria-expanded={wide?!collapsed:open} aria-controls={id} onClick={toggleNavigation}
          onFocus={()=>setHint(true)} onBlur={()=>setHint(false)} onKeyDown={event=>{if(event.key==='Escape')setHint(false);}}>
          {wide&&collapsed&&<span className="application-toggle-brand application-brand-mark" aria-hidden="true">W</span>}<Icon name="sidebar"/>
        </button>
        <span id={`${id}-hint`} role="tooltip" className="application-navigation-tooltip" hidden={!hint}>显示/隐藏侧边栏<kbd>{shortcut}</kbd></span>
      </span>
      </div><div className="application-page-header" ref={headerHost}/>
    </div>
    {wide ? navigation : <dialog ref={drawer} id={id} className="application-navigation-drawer" aria-label="主导航菜单" tabIndex={-1}
      onKeyDown={trapModalTab} onCancel={event => { event.preventDefault(); close(); }}
      onClick={event => { if (event.target === event.currentTarget) {
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
      } }}>
      <div className="application-navigation-drawer-heading"><span>导航</span><button type="button" className="ui-button icon-button" aria-label="关闭主导航" onClick={close}><Icon name="close"/></button></div>
      {navigation}
    </dialog>}
  </>;
}
