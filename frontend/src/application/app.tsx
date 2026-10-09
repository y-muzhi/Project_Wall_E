import {useEffect,useState,useSyncExternalStore} from 'react';
import type {CSSProperties} from 'react';
import {ApplicationRouter} from './router.ts';
import {WorkbenchView} from '../requirements/workbench-view.tsx';
import {RequirementDetail} from '../requirements/detail.tsx';
import {ApplicationNavigation} from './navigation.tsx';
import {ApplicationHeaderHost} from './header.tsx';

export function Application({router}:Readonly<{router:ApplicationRouter}>){
 const state=useSyncExternalStore(router.subscribe,router.getSnapshot);
 const [headerHost,setHeaderHost]=useState<HTMLDivElement|null>(null),[headerHeight,setHeaderHeight]=useState(68);
 useEffect(()=>{const capture=()=>{const current=router.getSnapshot();if(current.entry&&current.workbench)router.saveEntry(current.workbench.state.requested,window.scrollY);};window.addEventListener('scroll',capture,{passive:true});return()=>window.removeEventListener('scroll',capture);},[router]);
 return <div className="application" style={{'--application-header-height':`${headerHeight}px`} as CSSProperties}>
  <ApplicationNavigation headerHost={setHeaderHost} headerHeight={setHeaderHeight} current={state.route.kind==='WORKBENCH'?'page':state.route.kind==='DETAIL'?'location':undefined} navigate={router.mainNavigation}/>
  <ApplicationHeaderHost.Provider value={headerHost}>
  <div className="application-main" data-page={state.route.kind}>
  {state.warning&&<p className="application-warning" role="status"><strong>提示：</strong>{state.warning}</p>}
  {state.route.kind==='WORKBENCH'&&state.workbench&&state.creation&&state.entry&&<WorkbenchView key={state.epoch} workbench={state.workbench} creation={state.creation} restoreScroll={state.restoreScroll} openRequirement={router.openRequirement} saveEntry={router.saveEntry} navigationGuard={router.navigationGuard} discardCreation={router.discardCreation}/>}
  {state.route.kind==='DETAIL'&&<RequirementDetail key={state.epoch} identity={state.route.id} api={router.applicationApi} back={router.backToWorkbench} ready={owner=>router.attachDeparture(owner.departure)}/>}
  {state.route.kind==='NOT_FOUND'&&<main className="application-missing"><h1>页面不存在</h1><p>请从需求工作台打开需求。</p><button className="ui-button" type="button" onClick={router.mainNavigation}>返回需求工作台</button></main>}
  </div>
  </ApplicationHeaderHost.Provider>
 </div>;
}
