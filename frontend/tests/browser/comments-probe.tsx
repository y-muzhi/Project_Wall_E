import {createRoot} from 'react-dom/client';
import {editorViewCtx} from '@milkdown/kit/core';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import type {Comment} from '../../src/api/models.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {DocumentNavigation} from '../../src/documents/navigation.ts';
import {RequirementComments} from '../../src/comments/read.ts';
import {CommentList,CommentMarkerLayer} from '../../src/comments/components.tsx';
import {locateComment} from '../../src/comments/locate.ts';
import {selectionFromProjectedText} from '../../src/documents/selection.ts';
import '../../src/shared/styles.css';

/** All rows, IDs, quotes, locations and concurrent mutations come from actual
 * API/SQLite. Only specific read responses are locally dropped for recovery. */
export async function mountCommentsProbe(api:WalleApi){
  const main=document.createElement('main');main.id='native-comments';main.style.cssText='display:grid;grid-template-columns:minmax(640px,1fr) 420px;gap:24px;margin:24px;';
  const scroll=document.createElement('section'),relative=document.createElement('div'),host=document.createElement('div'),markerHost=document.createElement('div'),panel=document.createElement('aside');
  scroll.style.cssText='height:520px;overflow:auto;background:white;padding:20px;';relative.style.position='relative';host.className='detail-document-content';relative.append(host,markerHost);scroll.append(relative);panel.style.cssText='height:520px;overflow:auto;padding:4px;';main.append(scroll,panel);document.body.append(main);
  const initial=(await api.getCurrentDocument(2)).data,draft=(await api.prepareStartManualDraft(2,initial.content_version).submit()).data.manual_draft;
  let editor=await RequirementEditor.create(host,draft,false);
  editor.action(ctx=>{const view=ctx.get(editorViewCtx),p=view.state.schema.nodes.paragraph!;view.dispatch(view.state.tr.insert(view.state.doc.content.size,[p.create(null,view.state.schema.text('评论定位😀目标原文')),p.create(null,view.state.schema.text('会失效的选区😀'))]));});
  require(editor.valid&&editor.ledger!==null);const allocated=editor.ledger.currentSnapshot.block_state_json.blocks.slice(-2).map(block=>block.block_id),submission=editor.ledger.beginSave();
  const saved=(await api.prepareSaveManualDraft(2,{expected_version:submission.expected_version,markdown_content:submission.markdown_content,block_state_json:submission.block_state_json}).submit()).data;editor.ledger.acknowledgeSave(submission,saved);
  const withSelection=(await api.prepareCompleteManualDraft(2,saved.content_version).submit()).data;await editor.destroy();
  const rows:Comment[]=[];for(let number=1;number<=24;number++)rows.push((await api.prepareCreateComment(2,{expected_content_version:withSelection.content_version,content:'实际评论 '+number+'\n纯文本 **保持字面值** 😀',anchor_type:'BLOCK',block_id:allocated[0]!}).submit()).data);
  const liveSelection=selectionFromProjectedText({document_id:withSelection.id,content_version:withSelection.content_version,block_id:allocated[0]!},'评论定位😀目标原文',4,6);
  const attached=(await api.prepareCreateComment(2,{expected_content_version:withSelection.content_version,content:'定位真实码点选区😀',anchor_type:'SELECTION',block_id:allocated[0]!,selection:{selected_text:liveSelection.selected_text,prefix_text:liveSelection.prefix_text,suffix_text:liveSelection.suffix_text}}).submit()).data;
  const selected=selectionFromProjectedText({document_id:withSelection.id,content_version:withSelection.content_version,block_id:allocated[1]!},'会失效的选区😀',0,'会失效的选区😀'.length);
  const orphan=(await api.prepareCreateComment(2,{expected_content_version:withSelection.content_version,content:'位置失效但保持未解决',anchor_type:'SELECTION',block_id:allocated[1]!,selection:{selected_text:selected.selected_text,prefix_text:selected.prefix_text,suffix_text:selected.suffix_text}}).submit()).data;
  const second=(await api.prepareStartManualDraft(2,withSelection.content_version).submit()).data.manual_draft;editor=await RequirementEditor.create(host,second,false);
  editor.action(ctx=>{const view=ctx.get(editorViewCtx);let from=-1,to=-1;view.state.doc.forEach((node,offset)=>{if(node.attrs.walle_block_id===allocated[1]){from=offset;to=offset+node.nodeSize;}});require(from>=0);view.dispatch(view.state.tr.delete(from,to));});
  require(editor.valid&&editor.ledger!==null);const deleting=editor.ledger.beginSave(),deleted=(await api.prepareSaveManualDraft(2,{expected_version:deleting.expected_version,markdown_content:deleting.markdown_content,block_state_json:deleting.block_state_json}).submit()).data;editor.ledger.acknowledgeSave(deleting,deleted);
  const current=(await api.prepareCompleteManualDraft(2,deleted.content_version).submit()).data;await editor.destroy();editor=await RequirementEditor.create(host,current,true);
  const navigation=DocumentNavigation.forEditor(host,editor,scroll);let drop=false,race=false,reads=0,locates=0;
  const comments=new RequirementComments(current,{getCommentIndex:api.getCommentIndex.bind(api),getComment:api.getComment.bind(api),listComments:async(id,page,signal)=>{
    reads++;if(race){race=false;await api.prepareDeleteComment(rows[0]!.id).submit();}const actual=await api.listComments(id,page,signal);if(drop){drop=false;throw Error('Explicit dropped actual I27 response');}return actual;
  }});
  const panelRoot=createRoot(panel),markerRoot=createRoot(markerHost);panelRoot.render(<CommentList comments={comments} locate={id=>{const result=locateComment(comments,editor,navigation,id);if(result)locates++;return result;}}/>);markerRoot.render(<CommentMarkerLayer comments={comments} editor={editor} documentRoot={host}/>);
  require(await comments.refresh());
  return {state:()=>({comments:comments.getSnapshot(),ready:comments.ready,reads,locates,scroll:scroll.scrollTop,ids:rows.map(row=>row.id),orphan:orphan.id,attached:attached.id,current_id:current.id,current_version:current.content_version,block:allocated[0],editor_selection:editor.action(ctx=>{const view=ctx.get(editorViewCtx);return {range:view.state.selection.toJSON(),text:view.state.doc.textBetween(view.state.selection.from,view.state.selection.to)};})}),
    async concurrent(){race=true;require(await comments.select(rows[20]!.id));const confirmed=comments.getSnapshot().confirmed;require(confirmed!==null&&confirmed.pagination.page===1&&confirmed.items.at(-1)?.id===rows[20]!.id);return true;},
    async fail(){drop=true;require(!await comments.refresh(2));require(comments.getSnapshot().confirmed?.pagination.page===1&&!comments.ready);return true;},
    async orphan(){require(await comments.select(orphan.id));require(comments.getSnapshot().confirmed?.pagination.page===2&&comments.located(orphan.id)===null);return true;},
    async deleted(){require(!await comments.select(rows[0]!.id));require(comments.getSnapshot().error?.includes('已删除')===true);return true;},
    async selection(){require(await comments.select(attached.id));return true;},
    async statuses(){await api.prepareResolveComment(rows[1]!.id).submit();require(await comments.refresh(1));require(comments.getSnapshot().confirmed?.index.blocks[0]?.open_count===23);await api.prepareReopenComment(rows[1]!.id).submit();require(await comments.refresh(1));require(comments.getSnapshot().confirmed?.index.blocks[0]?.open_count===24);return true;},
    async inspect(){const actual=(await api.getCurrentDocument(2)).data,index=(await api.getCommentIndex(2)).data;
      require(actual.id===current.id&&actual.content_version===current.content_version&&actual.markdown_content===current.markdown_content&&JSON.stringify(actual.block_state_json)===JSON.stringify(current.block_state_json));require(index.total_count===25&&index.open_count===25&&index.blocks[0]?.open_count===24&&index.comments.find(row=>row.id===orphan.id)?.location.status==='ORPHANED');
      return {passed:true,reads,locates,current_id:current.id,current_version:current.content_version,block:allocated[0],original_count:26,total:index.total_count,open:index.open_count,attached_marker:index.blocks[0]!.open_count,deleted:(await api.getComment(rows[0]!.id)).data.deleted_at!==null,orphan:index.comments.find(row=>row.id===orphan.id),scope:'Actual I27/I28/I37, native 26 comments, current block IDs/quotes and real delete/resolve/reopen concurrency; production mutation controls not yet implemented, no Provider/full page acceptance'};},
    async destroy(){comments.dispose();navigation.dispose();panelRoot.unmount();markerRoot.unmount();await editor.destroy();main.remove();}};
}
