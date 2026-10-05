import {createRoot} from 'react-dom/client';
import {useSyncExternalStore} from 'react';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementHeaderCommands} from '../../src/requirements/header-commands.ts';
import {RequirementHeader} from '../../src/requirements/header.tsx';

export async function mountHeaderProbe(api:WalleApi){
  const element=document.createElement('main');element.id='native-requirement-header';element.style.padding='24px';document.body.append(element);const react=createRoot(element);
  const prepares:Record<string,number>={},submits:Record<string,number>={};let loseStart=true,loseComplete=true,loseRead=false;
  const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
    if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const actual=await target.getCommentIndex(...args);if(loseRead){loseRead=false;throw new ApiUnknown(false);}return actual;};
    const action=key==='prepareStartManualDraft'?'START':key==='prepareCompleteRequirement'?'COMPLETE':key==='prepareReactivateRequirement'?'REACTIVATE':key==='prepareUpdateRequirement'?'PROPERTY':null;
    if(action)return (...args:unknown[])=>{prepares[action]=(prepares[action]??0)+1;const original=value.apply(target,args);return {submit:async()=>{submits[action]=(submits[action]??0)+1;const actual=await original.submit();
      if(action==='START'&&loseStart){loseStart=false;throw new ApiUnknown(true);}if(action==='COMPLETE'&&loseComplete){loseComplete=false;throw new ApiUnknown(true);}return actual;}};};return value.bind(target);}});
  const reader=new RequirementDetailRead(2,wrapped);require(await reader.refresh());const initial=reader.getSnapshot().confirmed!;require(initial.requirement.status==='ACTIVE'&&initial.activity.kind==='IDLE');
  const commands=new RequirementHeaderCommands(initial,wrapped),originalStart=commands.getSnapshot().manual,originalLife=commands.getSnapshot().lifecycle;
  const actualRead=async()=>{require(await reader.refresh());const actual=reader.getSnapshot().confirmed!;
    require(actual.current.id===initial.current.id&&actual.current.content_version===initial.current.content_version&&actual.current.markdown_content===initial.current.markdown_content&&JSON.stringify(actual.current.block_state_json)===JSON.stringify(initial.current.block_state_json));return actual;};
  let historical=false;
  function View(props:Readonly<{history:boolean}>){useSyncExternalStore(reader.subscribe,reader.getSnapshot);return <RequirementHeader commands={commands} ready={reader.writeReady} blocked={false} history={props.history} refresh={actualRead} refreshRevisions={async()=>{await api.listRevisions(2);}}/>;}
  react.render(<View history={historical}/>);
  return {state:()=>{const state=commands.getSnapshot();return {root:state.detail.requirement,title:commands.title.getSnapshot(),manual:state.manual?.getSnapshot(),life:state.lifecycle?.getSnapshot(),operation:state.lifecycle?.operation,
    manual_generation:state.manual_generation,lifecycle_generation:state.lifecycle_generation,prepares,submits,ready:reader.writeReady,same_start:state.manual===originalStart,same_life:state.lifecycle===originalLife};},
    async refresh(){commands.adopt(await actualRead());},async failedRead(){loseRead=true;require(!await reader.refresh());require(!reader.writeReady);},failNextFullRead(){loseRead=true;},
    history(value:boolean){historical=value;react.render(<View history={historical}/>);},
    async cancelDraft(){const draft=(await api.getManualDraft(2)).data;await api.prepareCancelManualDraft(2,draft.content_version).submit();commands.adopt(await actualRead());},
    inspect(){const state=commands.getSnapshot();require(state.detail.requirement.status==='ACTIVE'&&state.detail.activity.kind==='IDLE'&&state.lifecycle?.operation==='COMPLETE'&&state.manual?.getSnapshot().phase==='READY');
      require(commands.title.getSnapshot().phase==='VIEW'&&state.detail.requirement.title==='工具栏保留标题😀');require(prepares.START===1&&submits.START===2&&prepares.COMPLETE===1&&submits.COMPLETE===2&&prepares.REACTIVATE===1&&submits.REACTIVATE===1&&prepares.PROPERTY===1&&submits.PROPERTY===1);
      return {passed:true,prepares,submits,current_id:initial.current.id,current_version:initial.current.content_version,title:state.detail.requirement.title,lifecycle_generation:state.lifecycle_generation,manual_generation:state.manual_generation,
        scope:'Actual header parent/native unknown start survives MANUAL read and failed full read, raw title retained, native title in manual occupancy, explicit native cancel, unknown completion survives COMPLETED read/original replay then actual next controls/reactivation; no complete product editor/page or Provider'};},
    destroy(){commands.dispose();reader.dispose();react.unmount();element.remove();}};
}
