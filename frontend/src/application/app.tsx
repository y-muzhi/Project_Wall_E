import {useEffect,useSyncExternalStore} from 'react';
import {ApplicationRouter} from './router.ts';
import {WorkbenchView} from '../requirements/workbench-view.tsx';
import {RequirementDetail} from '../requirements/detail.tsx';

export function Application({router}:Readonly<{router:ApplicationRouter}>){
 const state=useSyncExternalStore(router.subscribe,router.getSnapshot);
 useEffect(()=>{const capture=()=>{const current=router.getSnapshot();if(current.entry&&current.workbench)router.saveEntry(current.workbench.state.requested,window.scrollY);};window.addEventListener('scroll',capture,{passive:true});return()=>window.removeEventListener('scroll',capture);},[router]);
 return <div className="application"><nav className="application-navigation" aria-label="主导航"><span className="application-brand">WALL-E</span><button type="button" onClick={router.mainNavigation}>需求工作台</button></nav>
  {state.warning&&<p className="application-warning" role="status">{state.warning}</p>}
  {state.route.kind==='WORKBENCH'&&state.workbench&&state.creation&&state.entry&&<WorkbenchView key={state.epoch} workbench={state.workbench} creation={state.creation} restoreScroll={state.restoreScroll} openRequirement={router.openRequirement} saveEntry={router.saveEntry} navigationGuard={router.navigationGuard} discardCreation={router.discardCreation}/>}
  {state.route.kind==='DETAIL'&&<RequirementDetail key={state.epoch} identity={state.route.id} api={router.applicationApi} back={router.backToWorkbench} ready={owner=>router.attachDeparture(owner.departure)}/>}
  {state.route.kind==='NOT_FOUND'&&<main className="application-missing"><h1>页面不存在</h1><p>请从需求工作台打开需求。</p><button type="button" onClick={router.mainNavigation}>返回需求工作台</button></main>}
 </div>;
}
