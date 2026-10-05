import {createRoot} from 'react-dom/client';
import type {WalleApi,RequirementFilters} from '../../src/api/walle.ts';
import {ApiUnknown} from '../../src/api/client.ts';
import {RequirementWorkbench} from '../../src/requirements/workbench.ts';
import {WorkbenchHistory,pageRoute} from '../../src/requirements/workbench-history.ts';
import type {WorkbenchEntry} from '../../src/requirements/workbench-history.ts';
import {CreateRequirementFlow} from '../../src/requirements/create.ts';
import {WorkbenchView} from '../../src/requirements/workbench-view.tsx';
import {require} from '../../src/api/decoding.ts';

/** Actual production page view/API with an explicitly limited diagnostic route owner. */
export async function mountWorkbenchProbe(api:WalleApi,seed=false) {
  if(seed)for(let index=1;index<=21;index++) {
    const type=index%2?'NEW':'CHANGE';await api.prepareCreateRequirement({title:'工作台条目'+String(index).padStart(2,'0'),requirement_type:type,
      template_key:type==='NEW'?'new-requirement':'change-requirement',template_version:'v1',initial_idea:'隔离原生列表/分页/返回诊断',initialization_mode:'DESIGN'}).submit();
  }
  const element=document.createElement('section');element.id='native-workbench-probe';document.body.prepend(element);
  const root=createRoot(element),original={url:location.href,state:history.state,restoration:history.scrollRestoration};
  const owner=new WorkbenchHistory(history,sessionStorage),cache=new Map<string,RequirementWorkbench>();
  let entry:WorkbenchEntry=owner.enter('DEFAULT'),workbench:RequirementWorkbench,creation=new CreateRequirementFlow(api);
  let blocked=false,showing=true,generation=0,viewEpoch=0,restoreScroll:number|null=null,detailAbort:AbortController|undefined,hold=false,drop=false,release:(()=>void)|undefined;
  const reads:RequirementFilters[]=[],opened:number[]=[];
  const port:Pick<WalleApi,'listRequirements'>={async listRequirements(input,signal) {
    reads.push(input??{});const actual=await api.listRequirements(input,signal);
    if(hold){hold=false;await new Promise<void>(resolve=>{release=resolve;});release=undefined;}
    if(drop){drop=false;throw new ApiUnknown(false);}return actual;
  }};
  const saveEntry=(query:Parameters<WorkbenchHistory['save']>[1],position:number)=>{if(showing)entry=owner.save(entry,query,position);};
  const guard=(value:boolean)=>{blocked=value;};
  function renderView(){root.render(<WorkbenchView key={entry.entry_id+':'+viewEpoch} workbench={workbench} creation={creation} restoreScroll={restoreScroll}
    openRequirement={open} saveEntry={saveEntry} navigationGuard={guard} discardCreation={discard}/>);}
  function renderWorkbench(restoring:boolean) {
    showing=true;detailAbort?.abort();generation++;workbench=cache.get(entry.entry_id)??new RequirementWorkbench(port,entry.query);cache.set(entry.entry_id,workbench);
    viewEpoch=generation;restoreScroll=restoring?entry.scroll:null;renderView();
  }
  function discard(){creation.dispose();creation=new CreateRequirementFlow(api);renderView();}
  async function detail(id:number) {
    showing=false;workbench.pause();const token=++generation;detailAbort?.abort();detailAbort=new AbortController();window.scrollTo(0,0);
    root.render(<main style={{padding:32}}><p>正在读取详情返回诊断…</p></main>);
    try {const [requirement,current]=await Promise.all([api.getRequirement(id,detailAbort.signal),api.getCurrentDocument(id,detailAbort.signal)]);
      if(token!==generation)return;
      root.render(<main style={{padding:32}} data-native-detail={id}><h1>详情返回诊断</h1><p>{requirement.data.requirement_no} · {requirement.data.title}</p>
        <p>实际 CURRENT 版本：{current.data.content_version}；此诊断宿主不代替完整详情产品页。</p><button type="button" onClick={()=>history.back()}>返回需求工作台</button></main>);
    }catch(error){if(token===generation)root.render(<main role="alert">详情读取失败：{String(error)}</main>);}
  }
  function open(id:number){if(blocked&&!creation.state.result)return;opened.push(id);history.pushState({kind:'WALLE_DETAIL_DIAGNOSTIC',id},'','/requirements/'+id);void detail(id);}
  function pop(){const route=pageRoute(location.pathname);if(route.kind==='DETAIL'){void detail(route.id);return;}
    entry=owner.enter('RESTORE');creation.dispose();creation=new CreateRequirementFlow(api);renderWorkbench(true);}
  window.addEventListener('popstate',pop);history.replaceState(history.state,'','/requirements');renderWorkbench(false);
  return {
    state:()=>({state:workbench.state,phase:workbench.phase,entry,reads,opened,blocked,showing,scroll:window.scrollY,held:!!release}),
    holdNext:()=>{hold=true;},release:()=>{require(!!release);release();},dropNextRead:()=>{drop=true;},
    outOfRange:()=>workbench.query({...workbench.state.requested,page:99}),
    mainNavigation:()=>{if(blocked)return;workbench.pause();history.pushState(null,'','/requirements');entry=owner.enter('DEFAULT');creation.dispose();creation=new CreateRequirementFlow(api);renderWorkbench(false);},
    sessionSnapshot:()=>JSON.parse(sessionStorage.getItem('walle:v1:workbench:'+entry.entry_id)!),
    async updateOpened(){const id=opened.at(-1);require(id!==undefined);return (await api.prepareUpdateRequirement(id,{title:'工作台条目更新'}).submit()).data;},
    destroy(){generation++;detailAbort?.abort();release?.();for(const controller of cache.values())controller.dispose();creation.dispose();window.removeEventListener('popstate',pop);root.unmount();element.remove();history.replaceState(original.state,'',original.url);history.scrollRestoration=original.restoration;window.scrollTo(0,0);},
  };
}
