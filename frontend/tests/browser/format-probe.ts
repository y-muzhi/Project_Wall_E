import {Crepe} from '@milkdown/crepe';
import {editorViewCtx} from '@milkdown/kit/core';
import {TextSelection} from '@milkdown/kit/prose/state';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {installSourceNodes} from '../../src/documents/source-nodes.ts';
import {fixtureDraft} from './edited-snapshot.ts';
import type {DocumentReadModel} from '../../src/documents/contracts.ts';
import type {InitializationTemplate} from '../../src/documents/template-lock.ts';
import newTemplate from '../../../backend/resources/v2/templates/new-requirement.v1.md?raw';
import '../../src/shared/styles.css';

/** In-memory editor smoke fixture. No API, storage or model calls. */
export async function mountFormatProbe(markdown='# 测试标题\n\n正文测试\n',initializing:InitializationTemplate|null=null){
  const parserRoot=document.createElement('div'),root=document.createElement('main');root.className='detail-document-content';document.body.replaceChildren(root);
  const parser=new Crepe({root:parserRoot,defaultValue:markdown,features:Object.fromEntries(Object.values(Crepe.Feature).map(feature=>[feature,false]))});
  await installSourceNodes(parser);await parser.create();
  const draft=parser.editor.action(ctx=>{const state=ctx.get(editorViewCtx).state;return fixtureDraft(ctx,markdown,Array.from({length:state.doc.childCount},(_,i)=>i+1),state.doc.childCount+1) as DocumentReadModel;});
  await parser.destroy();let latest=draft.markdown_content,error:string|null=null,blurs=0;
  const editor=await RequirementEditor.create(root,draft,false,{change:pair=>{latest=pair.markdown_content;},error:value=>{error=value;},blur:()=>{blurs++;}},initializing);
  return {select(text:string){editor.action(ctx=>{const view=ctx.get(editorViewCtx);let from:number|undefined;view.state.doc.descendants((node,pos)=>{if(node.isText&&from===undefined){const index=node.text?.indexOf(text)??-1;if(index>=0)from=pos+index;}});if(from===undefined)throw Error('Fixture text not found');view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,from,from+text.length)));view.focus();});},
    state:()=>({markdown:latest,valid:editor.valid,readonly:editor.readonly,error,blurs}),readonly:(value:boolean)=>editor.setReadonly(value),destroy:()=>editor.destroy()};
}
export const mountInitializationFormatProbe=()=>mountFormatProbe(newTemplate,{requirement_type:'NEW',template_key:'new-requirement',template_version:'v1'});
