import {createRoot} from 'react-dom/client';
import {editorViewCtx} from '@milkdown/kit/core';
import {TextSelection} from '@milkdown/kit/prose/state';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {DocumentNavigation} from '../../src/documents/navigation.ts';
import {DocumentOutline,BlockAuxiliary} from '../../src/documents/navigation-view.tsx';
import {RevisionViewer} from '../../src/revisions/viewer.ts';

/** Native API/SQLite fixture with actual ledger allocation, not handcrafted IDs
 * or provenance. Read-only navigation receives the actual I08/I25 models. */
export async function mountNavigationProbe(api:WalleApi){
  const main=document.createElement('main');main.id='native-navigation';main.style.cssText='display:grid;grid-template-columns:200px minmax(640px,1fr);gap:48px;margin:24px;';
  const outline=document.createElement('aside'),scrollport=document.createElement('section'),host=document.createElement('div');
  scrollport.style.cssText='height:480px;overflow:auto;background:white;padding:24px;';host.className='detail-document-content';scrollport.append(host);main.append(outline,scrollport);document.body.append(main);
  const original=(await api.getCurrentDocument(2)).data,start=(await api.prepareStartManualDraft(2,original.content_version).submit()).data.manual_draft;
  let editor=await RequirementEditor.create(host,start,false),navigation=DocumentNavigation.forEditor(host,editor,scrollport);
  let root=createRoot(outline);root.render(<><DocumentOutline navigation={navigation}/><BlockAuxiliary navigation={navigation}/></>);
  editor.action(ctx=>{const view=ctx.get(editorViewCtx),schema=view.state.schema;
    const heading=(level:number,text:string)=>schema.nodes.heading!.create({level},schema.text(text));
    const body=(text:string)=>schema.nodes.paragraph!.create(null,schema.text(text));
    // Four long sections force native scrolling in a bounded document region.
    const content=[heading(1,'重复标题😀'),...Array.from({length:12},(_,i)=>body('第一节真实内容 '+i)),heading(4,'跳级章节'),...Array.from({length:12},(_,i)=>body('深层真实内容 '+i)),heading(2,'重复标题😀'),...Array.from({length:12},(_,i)=>body('第二节真实内容 '+i)),heading(1,'末尾章节'),body('末尾正文')];
    view.dispatch(view.state.tr.insert(view.state.doc.content.size,content));
  });require(editor.valid&&editor.ledger!==null);navigation.refresh();const draftNavigation=navigation.getSnapshot();require(draftNavigation.error===null&&draftNavigation.content?.kind==='MANUAL_DRAFT');
  const headings=draftNavigation.content.outline.slice(-4);require(headings.length===4&&JSON.stringify(headings.map(item=>item.depth))==='[0,1,1,0]'&&headings[0]!.block_id!==headings[2]!.block_id);
  const local=editor.ledger.currentSnapshot,submission=editor.ledger.beginSave(),saved=(await api.prepareSaveManualDraft(2,{expected_version:submission.expected_version,markdown_content:submission.markdown_content,block_state_json:submission.block_state_json}).submit()).data;editor.ledger.acknowledgeSave(submission,saved);
  const current=(await api.prepareCompleteManualDraft(2,saved.content_version).submit()).data;
  navigation.dispose();root.unmount();await editor.destroy();editor=await RequirementEditor.create(host,current,true);navigation=DocumentNavigation.forEditor(host,editor,scrollport);root=createRoot(outline);root.render(<><DocumentOutline navigation={navigation}/><BlockAuxiliary navigation={navigation}/></>);
  require(navigation.getSnapshot().error===null);const receipt=(await api.prepareCreateRevision(2,{expected_version:current.content_version,description:'大纲来源真实快照'}).submit()).data;
  let viewer:RevisionViewer|undefined,historyNav:DocumentNavigation|undefined;let active=navigation;
  return {state:()=>({navigation:active.getSnapshot(),scroll:scrollport.scrollTop,headings,current_id:current.id,current_version:current.content_version,draft_id:start.id,history:viewer!==undefined}),
    async history(){navigation.dispose();root.unmount();await editor.destroy();const revision=(await api.getRevision(receipt.id)).data;viewer=await RevisionViewer.create(host,revision);historyNav=DocumentNavigation.forRevision(host,viewer,scrollport);active=historyNav;root=createRoot(outline);root.render(<><DocumentOutline navigation={historyNav}/><BlockAuxiliary navigation={historyNav}/></>);require(active.getSnapshot().error===null);return true;},
    async editOutline(){// Separate live draft verifies invalid/composition lock and title changes without server overwrite.
      require(viewer===undefined);const fresh=(await api.prepareStartManualDraft(2,current.content_version).submit()).data.manual_draft;navigation.dispose();root.unmount();await editor.destroy();editor=await RequirementEditor.create(host,fresh,false);navigation=DocumentNavigation.forEditor(host,editor,scrollport);active=navigation;root=createRoot(outline);root.render(<><DocumentOutline navigation={navigation}/><BlockAuxiliary navigation={navigation}/></>);
      editor.action(ctx=>{const view=ctx.get(editorViewCtx);let position=0;view.state.doc.forEach((node,offset)=>{if(node.attrs.walle_block_id===headings[2]!.block_id)position=offset+1;});view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,position,position+'重复标题😀'.length)).insertText('已改标题😀'));});navigation.refresh();require(navigation.getSnapshot().content?.outline.find(item=>item.block_id===headings[2]!.block_id)?.text==='已改标题😀');
      host.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));require(navigation.getSnapshot().error!==null&&navigation.locate(headings[0]!.block_id)===false);
      host.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));require(navigation.getSnapshot().error===null);
      await api.prepareCancelManualDraft(2,fresh.content_version).submit();navigation.dispose();root.unmount();await editor.destroy();editor=await RequirementEditor.create(host,current,true);navigation=DocumentNavigation.forEditor(host,editor,scrollport);active=navigation;root=createRoot(outline);root.render(<><DocumentOutline navigation={navigation}/><BlockAuxiliary navigation={navigation}/></>);return true;
    },
    async inspect(){require(viewer!==undefined&&historyNav!==undefined&&viewer.unchanged&&historyNav.getSnapshot().content?.kind==='REVISION');const actual=(await api.getCurrentDocument(2)).data,revision=(await api.getRevision(receipt.id)).data;
      require(actual.id===current.id&&actual.content_version===current.content_version&&actual.markdown_content===current.markdown_content&&JSON.stringify(actual.block_state_json)===JSON.stringify(current.block_state_json));
      require(revision.markdown_content===current.markdown_content&&JSON.stringify(revision.block_state_json)===JSON.stringify(current.block_state_json));
      require(local.markdown_content===actual.markdown_content);return {passed:true,current_id:actual.id,current_version:actual.content_version,revision_id:revision.id,revision_fields:Object.keys(revision).length,draft_id:start.id,headings,server_sources:headings.map(heading=>actual.block_state_json.blocks.find(block=>block.block_id===heading.block_id)),revision_unchanged:viewer.unchanged,scope:'Actual ledger/manual save/complete/current and Revision navigation; native scroll/source/focus verified separately. Synthetic composition only, no true IME, full product route, comments or Provider'};},
    async destroy(){active.dispose();root.unmount();if(viewer)await viewer.destroy();else await editor.destroy();main.remove();}};
}
