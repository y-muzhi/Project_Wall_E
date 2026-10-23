import {probeDocumentDetail} from './v15-probe-targets.ts';
import {createRoot} from 'react-dom/client';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementLifecycle} from '../../src/requirements/lifecycle.ts';
import {RequirementLifecycleControl} from '../../src/requirements/lifecycle-control.tsx';

/** Explicit isolated-browser action only; never invoked by startup or focus. */
export async function mountLifecycleProbe(api:WalleApi){
 const list=await api.listRequirements(),identity=list.data.items[0]?.id;require(identity!==undefined);
 const reader=new RequirementDetailRead(identity,api);require(await reader.refresh());
 const initial=probeDocumentDetail(reader.getSnapshot().confirmed!),flow=new RequirementLifecycle(initial.requirement.status,initial,api);
 const element=document.createElement('main');document.body.append(element);const react=createRoot(element);
 let adoptions=0;
 react.render(<RequirementLifecycleControl flow={flow} blocked={false} changed={async()=>{require(await reader.refresh());adoptions++;}}/>);
 return {state:()=>({identity,state:flow.getSnapshot(),adoptions}),
  inspect(){const state=flow.getSnapshot();require(state.phase==='CONFIRMED'&&adoptions>0);return {passed:true,identity,status:state.actual.status,metadata_version:state.actual.metadata_version,scope:'Manual status PATCH only; no content snapshot or model invocation'};},
  destroy(){flow.dispose();reader.dispose();react.unmount();element.remove();}};
}
