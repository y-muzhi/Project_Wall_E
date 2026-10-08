import {editorViewCtx} from '@milkdown/kit/core';
import type {Ctx} from '@milkdown/kit/ctx';
import {validateBlockState} from './contracts.ts';
import type {BlockMetadata} from './contracts.ts';
import type {EditedSnapshot} from './edited-snapshot.ts';
import {bindIdentityDocument} from './identity.ts';
import type {RequirementEditor} from './editor.ts';
import type {RevisionViewer} from '../revisions/viewer.ts';

export type OutlineEntry=Readonly<{block_id:number;level:number;depth:number;text:string}>;
export type NavigationContent=Readonly<{kind:'CURRENT'|'MANUAL_DRAFT'|'REVISION';blocks:readonly BlockMetadata[];outline:readonly OutlineEntry[]}>;
export type NavigationState=Readonly<{content:NavigationContent|null;active_heading:number|null;selected_block:number|null;source_block:number|null;
  toolbar:Readonly<{left:number;top:number}>|null;error:string|null}>;
interface NavigationPort{read():NavigationContent;element(blockId:number):HTMLElement|null;}

/** Heading depth follows the real preceding hierarchy, including skipped levels
 * and duplicate text. Section names never become identities. */
export function headingOutline(headings:readonly Readonly<{block_id:number;level:number;text:string}>[]):readonly OutlineEntry[]{
  const stack:number[]=[],ids=new Set<number>();
  return Object.freeze(headings.map(heading=>{
    if(!Number.isSafeInteger(heading.block_id)||heading.block_id<1||ids.has(heading.block_id)||!Number.isInteger(heading.level)||heading.level<1||heading.level>6)throw TypeError('Invalid heading identity/level');
    ids.add(heading.block_id);while(stack.length&&stack.at(-1)!>=heading.level)stack.pop();const depth=stack.length;stack.push(heading.level);
    return Object.freeze({...heading,depth});
  }));
}
function readNavigation(ctx:Ctx,pair:EditedSnapshot,kind:NavigationContent['kind']):NavigationContent{
  const {source,state}=validateBlockState(ctx,pair.markdown_content,pair.block_state_json),view=ctx.get(editorViewCtx);
  if(!view.state.doc.eq(bindIdentityDocument(source.document,state.blocks.map(block=>block.block_id),state.next_block_id)))throw Error('Displayed nodes differ from the complete source snapshot');
  const headings=source.blocks.flatMap((block,index)=>block.heading_level===null?[]:[{block_id:state.blocks[index]!.block_id,level:block.heading_level,text:block.plain_text}]);
  return Object.freeze({kind,blocks:state.blocks,outline:headingOutline(headings)});
}
function blockElement(ctx:Ctx,id:number):HTMLElement|null{
  const view=ctx.get(editorViewCtx);let result:HTMLElement|null=null;
  view.state.doc.forEach((node,position)=>{if(node.attrs.walle_block_id!==id)return;const dom=view.nodeDOM(position);if(dom instanceof HTMLElement)result=dom;});return result;
}

/** Snapshot/DOM navigation only: no HTTP, comment index, saved receipt or write
 * capability. Parent must refresh after adopting a server metadata receipt. */
export class DocumentNavigation{
  private readonly root:HTMLElement;private readonly port:NavigationPort;private readonly scrollport:HTMLElement|null;
  private readonly listeners=new Set<()=>void>();private readonly removers:(()=>void)[]=[];private observer:MutationObserver;private resize:ResizeObserver;
  private frame:number|null=null;private needsRead=false;private closed=false;private visible=true;
  private highlighted:HTMLElement|null=null;private highlightTimer:ReturnType<typeof setTimeout>|undefined;
  private value:NavigationState=Object.freeze({content:null,active_heading:null,selected_block:null,source_block:null,toolbar:null,error:null});
  private constructor(root:HTMLElement,port:NavigationPort,scrollport:HTMLElement|null){
    this.root=root;this.port=port;this.scrollport=scrollport;
    const listen=(target:EventTarget,name:string,callback:EventListener,capture=false)=>{target.addEventListener(name,callback,capture);this.removers.push(()=>target.removeEventListener(name,callback,capture));};
    listen(window,'scroll',()=>this.schedule(false),true);listen(window,'resize',()=>this.schedule(false));
    listen(root,'pointerover',event=>this.selectTarget(event.target));listen(root,'focusin',event=>this.selectTarget(event.target));
    listen(root,'compositionstart',()=>this.schedule(true));listen(root,'compositionend',()=>this.schedule(true));
    listen(root,'keyup',()=>{const selection=window.getSelection();if(selection?.anchorNode)this.selectTarget(selection.anchorNode);});
    this.observer=new MutationObserver(()=>this.schedule(true));this.observer.observe(root,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['data-block-id']});
    this.resize=new ResizeObserver(()=>this.schedule(false));this.resize.observe(root);if(scrollport)this.resize.observe(scrollport);this.refresh();
  }
  static forEditor(root:HTMLElement,editor:RequirementEditor,scrollport:HTMLElement|null=null):DocumentNavigation{
    return new DocumentNavigation(root,{read:()=>{if(!editor.valid)throw Error('Draft has incomplete input');const input=editor.loadedDocument;return editor.action(ctx=>readNavigation(ctx,editor.ledger?.currentSnapshot??input,input.document_type));},
      element:id=>editor.action(ctx=>blockElement(ctx,id))},scrollport);
  }
  static forRevision(root:HTMLElement,viewer:RevisionViewer,scrollport:HTMLElement|null=null):DocumentNavigation{
    return new DocumentNavigation(root,{read:()=>viewer.action(ctx=>readNavigation(ctx,viewer.snapshot,'REVISION')),element:id=>viewer.action(ctx=>blockElement(ctx,id))},scrollport);
  }
  getSnapshot=():NavigationState=>this.value;
  subscribe=(callback:()=>void):(()=>void)=>{this.listeners.add(callback);return()=>this.listeners.delete(callback);};
  private publish(changes:Partial<NavigationState>):void{
    if(this.closed)return;const next=Object.freeze({...this.value,...changes});if(next.content===this.value.content&&next.active_heading===this.value.active_heading&&next.selected_block===this.value.selected_block&&next.source_block===this.value.source_block&&next.error===this.value.error&&next.toolbar?.left===this.value.toolbar?.left&&next.toolbar?.top===this.value.toolbar?.top)return;this.value=next;
    for(const callback of this.listeners)try{callback();}catch(error){console.error('WALL-E document navigation observer failed',error);}
  }
  private schedule(read:boolean):void{if(this.closed)return;this.needsRead||=read;if(this.frame!==null)return;this.frame=requestAnimationFrame(()=>{this.frame=null;const read=this.needsRead;this.needsRead=false;if(read)this.refresh();else this.measure();});}
  refresh():void{
    if(this.closed)return;this.clearHighlight();try{const content=this.port.read(),ids=new Set(content.blocks.map(block=>block.block_id));
      this.publish({content,error:null,selected_block:this.value.selected_block!==null&&ids.has(this.value.selected_block)?this.value.selected_block:null,
        source_block:this.value.source_block!==null&&ids.has(this.value.source_block)?this.value.source_block:null});this.measure();
    }catch{this.publish({error:'当前输入尚未形成完整文档，大纲和区块来源暂不可操作。',toolbar:null,source_block:null});}
  }
  private bounds():{left:number;right:number;top:number;bottom:number}{const box=this.scrollport?.getBoundingClientRect();return {left:Math.max(0,box?.left??0),right:Math.min(window.innerWidth,box?.right??window.innerWidth),top:Math.max(0,box?.top??0),bottom:Math.min(window.innerHeight,box?.bottom??window.innerHeight)};}
  private measure():void{
    if(this.closed||!this.visible||this.value.error||!this.value.content)return;const bounds=this.bounds();let heading:number|null=null,first:number|null=null;
    const scrolling=this.scrollport??document.scrollingElement,atEnd=scrolling!==null&&scrolling.scrollHeight-scrolling.clientHeight-scrolling.scrollTop<=1;
    if(this.root.getClientRects().length){for(const entry of this.value.content.outline){const element=this.port.element(entry.block_id);if(!element?.getClientRects().length)continue;const top=element.getBoundingClientRect().top;first??=entry.block_id;if(top<=(atEnd?bounds.bottom-1:bounds.top+24))heading=entry.block_id;else break;}}
    heading??=first;const element=this.value.selected_block===null?null:this.port.element(this.value.selected_block),box=element?.getBoundingClientRect();
    const visible=element?.getClientRects().length&&box&&box.bottom>bounds.top&&box.top<bounds.bottom;
    // CSS aligns the toolbar's right edge with this anchor, within the actual
    // document viewport instead of placing it over the left outline/panel.
    this.publish({active_heading:heading,toolbar:visible?Object.freeze({left:Math.max(bounds.left+8,Math.min(bounds.right-8,box.right)),top:Math.max(bounds.top+4,Math.min(bounds.bottom-40,box.top))}):null});
  }
  private selectTarget(target:EventTarget|null):void{
    if(!this.visible||this.value.error||!this.value.content||!(target instanceof Node))return;
    for(const block of this.value.content.blocks){const element=this.port.element(block.block_id);if(element&&(element===target||element.contains(target))){this.publish({selected_block:block.block_id});this.measure();return;}}
  }
  private clearHighlight():void{if(this.highlightTimer!==undefined)clearTimeout(this.highlightTimer);this.highlightTimer=undefined;this.highlighted?.classList.remove('comment-target-highlight');this.highlighted=null;}
  locate(blockId:number,highlight=false):boolean{
    if(this.closed||!this.visible||this.value.error||!this.value.content?.blocks.some(block=>block.block_id===blockId))return false;
    const element=this.port.element(blockId);if(!element?.getClientRects().length)return false;
    if(this.scrollport){const top=element.getBoundingClientRect().top-this.scrollport.getBoundingClientRect().top-this.scrollport.clientTop;this.scrollport.scrollTop+=top;}
    else element.scrollIntoView({block:'start',inline:'nearest',behavior:'instant'});this.publish({selected_block:blockId});this.measure();if(highlight){this.clearHighlight();this.highlighted=element;element.classList.add('comment-target-highlight');this.highlightTimer=setTimeout(()=>this.clearHighlight(),2000);}return true;
  }
  source(blockId:number|null):void{if(this.closed)return;if(blockId!==null&&(!this.visible||this.value.error||!this.value.content?.blocks.some(block=>block.block_id===blockId)))return;this.publish({source_block:blockId});}
  setVisible(visible:boolean):void{if(this.closed||this.visible===visible)return;this.visible=visible;if(visible)this.refresh();else{this.clearHighlight();this.publish({toolbar:null,source_block:null,active_heading:null});}}
  dispose():void{if(this.closed)return;this.closed=true;this.clearHighlight();for(const remove of this.removers)remove();this.observer.disconnect();this.resize.disconnect();if(this.frame!==null)cancelAnimationFrame(this.frame);this.listeners.clear();}
}
