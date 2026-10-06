import {createRoot} from 'react-dom/client';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementAiRead} from '../../src/guide/read-owner.ts';
import {AiReadPanel} from '../../src/guide/read-view.tsx';
import {RequirementRunActions} from '../../src/guide/run-actions.ts';
import {RunControls} from '../../src/guide/run-controls.tsx';
import '../../src/shared/styles.css';

/** Real production routes/SQLite/Run polling. REVIEW's native worker is held
 * by an explicit private server dispatch barrier; this is not model evidence. */
export async function mountRunActionsProbe(api:WalleApi){
 const main=document.createElement('main');main.id='native-run-actions';main.style.cssText='padding:24px;max-width:640px;margin:auto';document.body.append(main);
 const current=(await api.getCurrentDocument(2)).data,created=(await api.prepareCreateGuide(2,{expected_version:current.content_version,action_type:'ASK',instruction:'真实失败后重新运行😀',scope_type:'DOCUMENT',source_type:'USER_INSTRUCTION'}).submit()).data;
 const failed=async(identity:number)=>{const due=Date.now()+10000;while(Date.now()<due){const actual=(await api.getGuideRun(identity)).data;if(actual.status==='FAILED'){require(actual.error_code==='CONFIG_INVALID');return actual;}await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Actual config failure required');};
 const original=await failed(created.guide_run.id),counts={cancelPrepares:0,retryPrepares:0,cancelSends:0,retrySends:0,receives:0,reads:0,adopts:0},reader=new RequirementDetailRead(2,api);let dropRead=false,dropAdopt=false,shown=true;
 const read=async()=>{counts.reads++;if(dropRead){dropRead=false;throw new ApiUnknown(false);}require(await reader.refresh());return reader.getSnapshot().confirmed!;};
 const actual=await read();let actions:RequirementRunActions,ai:RequirementAiRead;
 let cancelledWritten:Awaited<ReturnType<WalleApi['getGuideRun']>>['data']|null=null;
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(key==='prepareCancelGuide'||key==='prepareRetryGuide')return (identity:number)=>{const cancel=key==='prepareCancelGuide',action=cancel?target.prepareCancelGuide(identity):target.prepareRetryGuide(identity);if(cancel)counts.cancelPrepares++;else counts.retryPrepares++;let sends=0,receipt:string|null=null;return {submit:async()=>{sends++;if(cancel)counts.cancelSends++;else counts.retrySends++;const result=await action.submit();if(sends===1){receipt=JSON.stringify(result.data);if(cancel)cancelledWritten=(await target.getGuideRun(identity)).data;throw new ApiUnknown(true);}require(JSON.stringify(result.data)===receipt);return result;}};};return typeof value==='function'?value.bind(target):value;}});
 const adopt=async(detail:typeof actual)=>{counts.adopts++;if(dropAdopt){dropAdopt=false;throw Error('实际父级采用暂时失败，已确认回执仍保留');}ai.adopt(detail);actions.adopt(detail,ai.getSnapshot().run);};
 ai=new RequirementAiRead(actual,api,read,async snapshot=>{ai.adopt(snapshot);actions.adopt(snapshot,ai.getSnapshot().run);},()=>{shown=true;actions.setAvailable(true);});
 actions=new RequirementRunActions(actual,wrapped,read,adopt,async run=>{counts.receives++;await ai.receive(run);ai.readRun();});
 const release=ai.subscribe(()=>{const state=ai.getSnapshot();actions.adopt(state.detail,state.run);});
 actions.setAvailable(true);ai.setVisible(true);await ai.receive(original);await ai.refresh();
 const root=createRoot(main);function View(){return <><button type="button" onClick={()=>{shown=!shown;actions.setAvailable(shown);ai.setVisible(shown);main.querySelector<HTMLElement>('[data-ai-body]')!.hidden=!shown;}}>切换面板显示</button><div data-ai-body><AiReadPanel owner={ai}/><RunControls owner={actions}/></div></>;}
 root.render(<View/>);
 return {state(){return {actions:actions.getSnapshot(),ai:ai.getSnapshot(),counts,shown};},failRead(){dropRead=true;},failAdopt(){dropAdopt=true;},selectOriginal(){ai.open(original);},async selectInitialization(){ai.open((await api.getGuideRun(2)).data);},
  async prepareCancel(){const actual=(await api.prepareCreateGuide(2,{expected_version:current.content_version,action_type:'REVIEW',instruction:'真实取消调度屏障',scope_type:'DOCUMENT',source_type:'USER_INSTRUCTION'}).submit()).data;const detail=await read();ai.adopt(detail);actions.adopt(detail,detail.activity.kind==='GUIDE'?detail.activity.run:null);await ai.receive(actual.guide_run);await ai.refresh();return actual.guide_run.id;},
  async inspect(){const latest=(await api.getCurrentDocument(2)).data,runs=(await api.listGuideRuns(2)).data.items,messages=(await api.listMessages(2)).data.items;require(JSON.stringify(latest)===JSON.stringify(current));const old=(await api.getGuideRun(original.id)).data;require(JSON.stringify(old)===JSON.stringify(original));require(counts.retryPrepares===1&&counts.retrySends===2&&counts.cancelPrepares===1&&counts.cancelSends===2&&counts.receives===2);require(runs.length===4&&messages.length===3);require(runs.find(run=>run.retry_of_guide_run_id===original.id)?.status==='FAILED');require(runs[0]!.status==='CANCELLED');require(cancelledWritten!==null&&JSON.stringify((await api.getGuideRun(cancelledWritten.id)).data)===JSON.stringify(cancelledWritten));return {passed:true,counts,original,actual_runs:runs,cancelled_written:cancelledWritten,original_receipts_equal:true,messages:messages.map(row=>({id:row.id,sequence:row.sequence_no,run:row.guide_run_id})),current_unchanged:true,scope:'Actual native retry and pre-orchestration RUNNING cancellation; no successful model output, WAITING/PERSISTING positive race or root-page acceptance'};},
  async destroy(){root.unmount();release();actions.dispose();ai.dispose();reader.dispose();main.remove();return {passed:true};}};
}
