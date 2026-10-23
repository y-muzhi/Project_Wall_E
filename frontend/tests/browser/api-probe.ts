import {configureProbeDocument,observeProbeData} from './v15-probe-targets.ts';
import { Crepe } from '@milkdown/crepe';
import { ApiClient } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import { editorHostProbe } from './editor-host-probe.ts';
import { readLimitsProbe } from './read-limits-probe.ts';
import { mountCreateProbe } from './create-probe.tsx';
import { mountWorkbenchProbe } from './workbench-probe.tsx';
import { mountDetailFrameProbe } from './detail-frame-probe.tsx';
import { detailReadProbe } from './detail-read-probe.ts';
import { manualEndProbe } from './manual-end-probe.ts';
import { manualStartProbe } from './manual-start-probe.ts';
import {prepareRecoveryAdoption,resumeRecoveryAdoption} from './recovery-adoption-probe.ts';
import {mountManualControlsProbe} from './manual-controls-probe.tsx';
import {manualSessionProbe} from './manual-session-probe.ts';
import {GuideRunPolling} from '../../src/guide/polling.ts';
import {mountLifecycleProbe} from './lifecycle-probe.tsx';
import {mountPropertyProbe} from './property-probe.tsx';
import {mountHeaderProbe} from './header-probe.tsx';
import {mountRevisionsProbe} from './revisions-probe.tsx';
import {mountNavigationProbe} from './navigation-probe.tsx';
import {mountDocumentOwnerProbe} from './document-owner-probe.tsx';
import {mountCommentsProbe} from './comments-probe.tsx';
import {mountCommentCommandsProbe} from './comment-commands-probe.tsx';
import {mountCommentPanelProbe} from './comment-panel-probe.tsx';
import {mountAiReadProbe} from './ai-read-probe.tsx';
import {mountRunActionsProbe} from './run-actions-probe.tsx';
import {mountGuideComposerProbe} from './guide-composer-probe.tsx';
import {mountCardsProbe} from './cards-probe.tsx';
import {suggestionProbe} from './suggestion-probe.ts';
import {mountSuggestionPanelProbe} from './suggestion-panel-probe.tsx';
import {mountConversationProbe} from './conversation-probe.tsx';
import {mountDetailProductProbe} from './detail-product-probe.tsx';

const editor = new Crepe({ root: document.querySelector<HTMLElement>('#editor')!, defaultValue: '', features: {
  [Crepe.Feature.CodeMirror]: false, [Crepe.Feature.ListItem]: false, [Crepe.Feature.LinkTooltip]: false, [Crepe.Feature.Cursor]: false,
  [Crepe.Feature.ImageBlock]: false, [Crepe.Feature.BlockEdit]: false, [Crepe.Feature.Toolbar]: false, [Crepe.Feature.Placeholder]: false,
  [Crepe.Feature.Table]: false, [Crepe.Feature.Latex]: false, [Crepe.Feature.TopBar]: false, [Crepe.Feature.AI]: false,
} });
await installSourceNodes(editor); await editor.create(); editor.setReadonly(true);
const wires: { path: string; method: string; status: number; body?: string; key?: string; content_type?:string|null; error_response?: string }[] = [];
const responses: { path: string; status: number; response: string }[] = [];
const transport: typeof fetch = async (input, options) => {
  let response: Response;
  try { response = await fetch(input, options); } catch (error) { wires.push({path:String(input),method:options?.method ?? 'GET',status:0,error_response:String(error)}); throw error; }
  const received = await response.clone().text();if(response.ok)observeProbeData(JSON.parse(received).data); responses.push({path:String(input),status:response.status,response:received}); if (responses.length > 5) responses.shift();
  wires.push({ path: String(input), method: options?.method ?? 'GET', status: response.status,
    ...((options?.method === 'POST' && String(input) === '/api/v1/requirements') ||
      (options?.method!==undefined&&options.method!=='GET'&&(/^\/api\/v1\/requirements\/\d+\/comments$/.test(String(input))||/^\/api\/v1\/comments\/\d+(?:\/resolve|\/reopen|\/guide-runs)?$/.test(String(input))))||
      (options?.method==='POST'&&(/^\/api\/v1\/guide-runs\/\d+\/(?:cancel|retry|continue)$/.test(String(input))||/^\/api\/v1\/requirements\/\d+\/guide-runs$/.test(String(input))||/^\/api\/v1\/conversation-messages\/\d+\/responses$/.test(String(input))))||
      (/^\/api\/v1\/(?:suggestions\/\d+\/decision|suggestion-batches\/\d+\/(?:complete|discard))$/.test(String(input))&&options?.method!=='GET')||
      (String(input).startsWith('/api/v1/requirements/') &&
        ((options?.method === 'POST' && (String(input).endsWith('/manual-draft/complete') || String(input).endsWith('/manual-draft')||String(input).endsWith('/complete-initialization')||String(input).endsWith('/complete')||String(input).endsWith('/reactivate')||String(input).endsWith('/revisions'))) ||
          (options?.method === 'DELETE' && String(input).endsWith('/manual-draft')) || (options?.method==='PATCH'&&/^\/api\/v1\/requirements\/\d+$/.test(String(input)))))
      ? { ...(options?.body!==undefined?{body:String(options.body)}:{}), key: new Headers(options?.headers).get('Idempotency-Key')!,content_type:new Headers(options?.headers).get('Content-Type') } : {}),
    ...(response.status >= 400 ? { error_response: received } : {}) }); return response;
};
const api = editor.editor.action(ctx => new WalleApi(new ApiClient(transport), ctx));
const status = document.querySelector<HTMLElement>('#status')!;
let lastRequirement = 0;
const hostProbe = editorHostProbe(api, () => lastRequirement);

async function bootstrapProperties(){
  const identities:number[]=[];
  for(const title of ['实际状态验证','实际标题验证']){
    const created=(await api.prepareCreateRequirement({title,requirement_type:'NEW',initial_idea:'明确的属性专项验证输入'}).submit()).data;
    require(created.documents.length===0&&created.requirement.document_work_state==='IDLE');identities.push(created.requirement.id);
  }
  return {passed:true,identities,scope:'Two explicit isolated creations, zero documents and no automatic model request'};
}
async function run(){
 const created=(await api.prepareCreateRequirement({title:'API联调😀',requirement_type:'NEW',initial_idea:'明确的隔离测试输入'}).submit()).data;
 lastRequirement=created.requirement.id;
 require(created.documents.length===0&&created.requirement.status==='PLANNING');
 const listed=await api.listRequirements({keyword:'API联调😀',status:['PLANNING'],requirement_type:['NEW']});
 require(listed.data.items.some(item=>item.id===lastRequirement));
 const updated=await api.prepareUpdateRequirement(lastRequirement,{expected_metadata_version:created.requirement.metadata_version,changes:{title:'更新联调😀',status:'CLOSED'}}).submit();
 require(updated.data.title==='更新联调😀'&&updated.data.status==='CLOSED'&&updated.data.document_work_state==='IDLE');
 return {passed:true,identity:lastRequirement,initial_message_id:created.initial_message_id,scope:'V1.5 creation/list/metadata only; other probes require their specific isolated setup'};
}

Object.assign(window, { apiProbe: { configureTarget:configureProbeDocument,run, hostProbe, readLimits: () => readLimitsProbe(api), mountCreate: () => {
  const probe = mountCreateProbe(api); Object.assign(window,{createProbe:probe});
}, mountWorkbench:async(seed:boolean)=>{Object.assign(window,{workbenchProbe:await mountWorkbenchProbe(api,seed)});},
 mountDetailFrame:async()=>{Object.assign(window,{detailFrameProbe:await mountDetailFrameProbe(api,2)});},
 detailRead:()=>detailReadProbe(api,2),
 manualEnd:()=>manualEndProbe(api,2),
 manualStart:()=>manualStartProbe(api,2),
 recoveryAdoptionPrepare:()=>prepareRecoveryAdoption(api,2),recoveryAdoptionResume:()=>resumeRecoveryAdoption(api),
 mountManualControls:async(operation:'COMPLETE'|'CANCEL',localMode:'AVAILABLE'|'COMPARE'|'NONE')=>{Object.assign(window,{manualControlsProbe:await mountManualControlsProbe(api,2,operation,localMode)});},
 manualSession:()=>manualSessionProbe(api,2),
 mountLifecycle:async()=>{Object.assign(window,{lifecycleProbe:await mountLifecycleProbe(api)});},
 mountProperties:async()=>{Object.assign(window,{propertyProbe:await mountPropertyProbe(api)});},
 bootstrapProperties,
 mountDetailProduct:async()=>{Object.assign(window,{detailProductProbe:await mountDetailProductProbe(api)});return true;},
 prepareSuggestions:async()=>{Object.assign(window,{suggestionProbe:await suggestionProbe(api)});return true;},
 mountConversation:async(identity:number,kind:'INITIALIZE'|'EXPIRE'|'WAITING')=>{Object.assign(window,{conversationProbe:await mountConversationProbe(api,identity,kind)});return true;},
 prepareSuggestionPanel:async(unified=false)=>{Object.assign(window,{suggestionPanelProbe:await mountSuggestionPanelProbe(api,unified)});return true;},
 mountHeader:async()=>{Object.assign(window,{headerProbe:await mountHeaderProbe(api)});},
 mountRevisions:async()=>{Object.assign(window,{revisionsProbe:await mountRevisionsProbe(api)});},
 mountNavigation:async()=>{Object.assign(window,{navigationProbe:await mountNavigationProbe(api)});},
 mountDocumentOwner:async()=>{Object.assign(window,{documentOwnerProbe:await mountDocumentOwnerProbe(api)});},
 mountComments:async()=>{Object.assign(window,{commentsProbe:await mountCommentsProbe(api)});},
 mountCommentCommands:async()=>{Object.assign(window,{commentCommandsProbe:await mountCommentCommandsProbe(api)});},
 mountCommentPanel:async()=>{Object.assign(window,{commentPanelProbe:await mountCommentPanelProbe(api)});},
 mountAiRead:async()=>{Object.assign(window,{aiReadProbe:await mountAiReadProbe(api)});},
 mountRunActions:async()=>{Object.assign(window,{runActionsProbe:await mountRunActionsProbe(api)});},
 mountGuideComposer:async(identity=2)=>{Object.assign(window,{guideComposerProbe:await mountGuideComposerProbe(api,identity)});},
 mountCards:async(identity:number,kind:'INITIALIZE'|'WAITING'|'EXPIRE',original?:number,deferSources=false)=>{Object.assign(window,{cardsProbe:await mountCardsProbe(api,identity,kind,original,deferSources)});},
 pollingObserver:async()=>{
  const runs=await api.listGuideRuns(2,{status:['FAILED']}),native=runs.data.items[0]!;require(native!==undefined);let reads=0,healthy=0;
  const fault=new Error('Explicit private observer diagnostic');
  const poll=new GuideRunPolling(native.id,async(id,signal)=>{reads++;return (await api.getGuideRun(id,signal)).data;});
  const original=console.error;let faults=0;console.error=(...args)=>{if(args[0]==='WALL-E run observer failed'&&args[1]===fault)faults++;else original(...args);};
  try{poll.subscribe(()=>{throw fault;});poll.subscribe(state=>{if(state.confirmed)healthy++;});poll.setVisible(true);
   const due=Date.now()+10000;while(!poll.state.confirmed&&Date.now()<due)await new Promise(resolve=>setTimeout(resolve,20));
   require(reads===1&&healthy===1&&faults===3&&poll.state.confirmed?.id===native.id&&poll.state.confirmed.status==='FAILED'&&!poll.state.connection_error&&!poll.state.polling);
   return {passed:true,native_run_id:native.id,actual_reads:reads,isolated_observer_faults:faults,healthy_delivery:healthy,native_status:poll.state.confirmed.status,scope:'Actual I19/I16/native failed-config run and controlled view observer faults; no Provider or whole acceptance'};
  }finally{poll.dispose();console.error=original;}
 },
 wireFacts: () => wires, transportFacts: () => responses, creationWires: () => wires.filter(wire => wire.body?.includes('真实抽屉😀')), destroy: () => editor.destroy() } }); status.textContent = 'READY';
