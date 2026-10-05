import {Crepe} from '@milkdown/crepe';
import {editorViewCtx} from '@milkdown/kit/core';
import type {Node} from '@milkdown/kit/prose/model';
import {revisionDecoder} from '../api/models.ts';
import {snapshotObject} from '../api/client.ts';
import {installSourceNodes} from '../documents/source-nodes.ts';
import {installIdentityAttributes,installIdentityState} from '../documents/identity.ts';
import type {Revision} from './read.ts';

/** Actual RevisionReadModel viewer. No fake document_type/content_version or
 * editing ledger is created to masquerade this snapshot as CURRENT/draft. */
export class RevisionViewer {
  readonly snapshot:Revision;private readonly crepe:Crepe;private readonly host:HTMLElement;private readonly initial:Node;private retiring:Promise<void>|undefined;
  private constructor(crepe:Crepe,host:HTMLElement,snapshot:Revision){this.crepe=crepe;this.host=host;this.snapshot=snapshot;
    this.initial=crepe.editor.action(ctx=>{const view=ctx.get(editorViewCtx);view.setProps({editable:()=>false,attributes:()=>({role:'textbox','aria-label':`历史版本 V${snapshot.version_no}，只读`,'aria-multiline':'true','aria-readonly':'true'}),
      dispatchTransaction:transaction=>{if(this.retiring||transaction.docChanged)return;view.updateState(view.state.applyTransaction(transaction).state);}});return view.state.doc;});
    crepe.setReadonly(true);
  }
  static async create(root:HTMLElement,input:Revision):Promise<RevisionViewer>{
    input=snapshotObject(input) as unknown as Revision;const host=document.createElement('div');host.className='revision-document-view';root.append(host);
    const crepe=new Crepe({root:host,defaultValue:input.markdown_content,features:{
      [Crepe.Feature.CodeMirror]:false,[Crepe.Feature.ListItem]:false,[Crepe.Feature.LinkTooltip]:false,[Crepe.Feature.Cursor]:false,[Crepe.Feature.ImageBlock]:false,
      [Crepe.Feature.BlockEdit]:false,[Crepe.Feature.Toolbar]:false,[Crepe.Feature.Placeholder]:false,[Crepe.Feature.Table]:false,[Crepe.Feature.Latex]:false,[Crepe.Feature.TopBar]:false,[Crepe.Feature.AI]:false}});
    try{await installSourceNodes(crepe);installIdentityAttributes(crepe);installIdentityState(crepe,input.block_state_json.blocks.map(block=>block.block_id),input.block_state_json.next_block_id);await crepe.create();
      const actual=crepe.editor.action(ctx=>revisionDecoder(ctx)(input));return new RevisionViewer(crepe,host,actual);
    }catch(error){await crepe.destroy();host.remove();throw error;}
  }
  get unchanged():boolean{return this.crepe.editor.action(ctx=>ctx.get(editorViewCtx).state.doc.eq(this.initial));}
  get blockIds():readonly number[]{return this.crepe.editor.action(ctx=>{const ids:number[]=[];ctx.get(editorViewCtx).state.doc.forEach(node=>ids.push(node.attrs.walle_block_id));return Object.freeze(ids);});}
  destroy():Promise<void>{if(this.retiring)return this.retiring;const promise=this.crepe.destroy().then(()=>{this.host.remove();});this.retiring=promise;return promise;}
}
