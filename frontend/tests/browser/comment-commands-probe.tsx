import {createRoot} from 'react-dom/client';
import {require} from '../../src/api/decoding.ts';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi,ApiAction} from '../../src/api/walle.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {CommentCommand} from '../../src/comments/commands.ts';
import type {CommentOutcome} from '../../src/comments/commands.ts';
import {commentTarget} from '../../src/comments/target.ts';
import {CommentCommandControl} from '../../src/comments/command-control.tsx';

/** Native production control fixture; one owner per row held outside React
 * renders. Success is real, but first response is deliberately dropped. */
export async function mountCommentCommandsProbe(api:WalleApi){
  const main=document.createElement('main');main.id='native-comment-commands';main.style.cssText='margin:24px;display:grid;grid-template-columns:1fr 1fr;gap:16px;';
  const host=document.createElement('div');main.append(host);document.body.append(main);
  const current=(await api.getCurrentDocument(2)).data,editor=await RequirementEditor.create(host,current,true),detailReader=new RequirementDetailRead(2,api);require(await detailReader.refresh());const detail=detailReader.getSnapshot().confirmed!;
  await api.prepareResolveComment(4).submit();const list=(await api.listComments(2,1)).data.items;
  const counts:Record<string,{prepared:number;sends:number}>=Object.fromEntries(['CREATE','EDIT','RESOLVE','REOPEN','DELETE','MODIFY'].map(kind=>[kind,{prepared:0,sends:0}]));
  const wrap=<T,>(kind:string,action:ApiAction<T>):ApiAction<T>=>{counts[kind]!.prepared++;return {submit:async()=>{counts[kind]!.sends++;const real=await action.submit();if(counts[kind]!.sends===1)throw new ApiUnknown(true);return real;}};};
  const commandApi={getComment:api.getComment.bind(api),prepareCreateComment:(...args:Parameters<WalleApi['prepareCreateComment']>)=>wrap('CREATE',api.prepareCreateComment(...args)),prepareEditComment:(...args:Parameters<WalleApi['prepareEditComment']>)=>wrap('EDIT',api.prepareEditComment(...args)),prepareResolveComment:(...args:Parameters<WalleApi['prepareResolveComment']>)=>wrap('RESOLVE',api.prepareResolveComment(...args)),prepareReopenComment:(...args:Parameters<WalleApi['prepareReopenComment']>)=>wrap('REOPEN',api.prepareReopenComment(...args)),prepareDeleteComment:(...args:Parameters<WalleApi['prepareDeleteComment']>)=>wrap('DELETE',api.prepareDeleteComment(...args)),prepareModifyFromComment:(...args:Parameters<WalleApi['prepareModifyFromComment']>)=>wrap('MODIFY',api.prepareModifyFromComment(...args))};
  const target=commentTarget(editor,26),flows={CREATE:new CommentCommand(detail,{kind:'CREATE',target},commandApi),EDIT:new CommentCommand(detail,{kind:'EDIT',comment:list.find(row=>row.id===2)!},commandApi),RESOLVE:new CommentCommand(detail,{kind:'RESOLVE',comment:list.find(row=>row.id===3)!},commandApi),REOPEN:new CommentCommand(detail,{kind:'REOPEN',comment:list.find(row=>row.id===4)!},commandApi),DELETE:new CommentCommand(detail,{kind:'DELETE',comment:list.find(row=>row.id===5)!},commandApi),MODIFY:new CommentCommand(detail,{kind:'MODIFY',comment:list.find(row=>row.id===6)!},commandApi)};
  const mounts=new Map<string,{root:ReturnType<typeof createRoot>;element:HTMLElement}>(),delivered:Record<string,number>={},outcomes:Record<string,CommentOutcome>={};let reads=0,failObservation=false,failCreateRefresh=true;
  const readActual=async()=>{reads++;require(await detailReader.refresh(true));if(failObservation){failObservation=false;throw Error('Explicit dropped actual full detail');}const actual=detailReader.getSnapshot().confirmed!;return actual;};
  const mount=(kind:string,flow:CommentCommand,element:HTMLElement)=>{const root=createRoot(element);mounts.set(kind,{root,element});
    root.render(<CommentCommandControl flow={flow} blocked={false} writeReady={true} readActual={readActual} changed={async outcome=>{outcomes[kind]=outcome;await readActual();if(kind==='CREATE'&&failCreateRefresh){failCreateRefresh=false;throw Error('Explicit parent adoption failure after actual complete read');}delivered[kind]=(delivered[kind]??0)+1;}}/>);
  };
  for(const [kind,flow] of Object.entries(flows)){const element=document.createElement('section');element.setAttribute('aria-label','实际评论'+kind);element.style.cssText='border:1px solid #cbd5e1;padding:16px;';main.append(element);mount(kind,flow,element);}
  return {state:()=>({flows:Object.fromEntries(Object.entries(flows).map(([kind,flow])=>[kind,flow.getSnapshot()])),counts,reads,delivered}),failObservation(){failObservation=true;},
    remount(kind:keyof typeof flows){const owned=mounts.get(kind)!;owned.root.unmount();mount(kind,flows[kind],owned.element);return true;},
    async inspect(){require(Object.values(flows).every(flow=>flow.getSnapshot().phase==='CONFIRMED'));require(Object.values(counts).every(value=>value.prepared===1&&value.sends===2));require(Object.keys(delivered).length===6&&Object.values(delivered).every(value=>value===1));
      const creation=outcomes.CREATE!,modify=outcomes.MODIFY!;require(creation.kind==='COMMENT'&&modify.kind==='GUIDE');const run=(await api.getGuideRun(modify.run.id)).data;require(run.function_type==='MODIFY_FROM_COMMENT'&&run.source_id===6&&run.status==='FAILED'&&run.error_code==='CONFIG_INVALID');
      const actual=(await api.getCurrentDocument(2)).data;require(actual.id===current.id&&actual.content_version===current.content_version&&actual.markdown_content===current.markdown_content&&JSON.stringify(actual.block_state_json)===JSON.stringify(current.block_state_json));
      const edited=(await api.getComment(2)).data,resolved=(await api.getComment(3)).data,reopened=(await api.getComment(4)).data,deleted=(await api.getComment(5)).data,source=(await api.getComment(6)).data;
      require(edited.content==='真实修改评论😀\n第二行'&&resolved.status==='RESOLVED'&&reopened.status==='OPEN'&&reopened.resolved_at===null&&deleted.deleted_at!==null&&source.status==='OPEN');
      require((await api.getComment(creation.comment.id)).data.content==='真实新建评论😀\n第二行');
      return {passed:true,counts,reads,delivered,current_id:current.id,current_version:current.content_version,new_comment:creation.comment.id,guide_run:run.id,guide_status:run.status,guide_error:run.error_code,source_comment_open:source.status==='OPEN',scope:'Actual six production comment controls, each first native success locally lost and original action replayed once; native missing-model config fails without paid call; no whole product parent/page lifetime or Provider effects acceptance'};
    },async destroy(){Object.values(flows).forEach(flow=>flow.dispose());mounts.forEach(({root})=>root.unmount());detailReader.dispose();await editor.destroy();main.remove();}};
}
