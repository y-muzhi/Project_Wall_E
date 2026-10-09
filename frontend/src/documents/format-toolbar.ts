import {commandsCtx,editorViewCtx} from '@milkdown/kit/core';
import type {Ctx} from '@milkdown/kit/ctx';
import type {Command} from '@milkdown/kit/prose/state';
import type {Node} from '@milkdown/kit/prose/model';
import {listCommand} from './format-commands.ts';
import {installEditorInteractions} from './editor-interactions.ts';
import {lift} from '@milkdown/kit/prose/commands';
import {undo,redo} from '@milkdown/kit/prose/history';
import {deleteRow,deleteColumn,deleteTable} from '@milkdown/kit/prose/tables';
import {toggleStrongCommand,toggleEmphasisCommand,toggleInlineCodeCommand,turnIntoTextCommand,wrapInHeadingCommand,
  wrapInBlockquoteCommand,createCodeBlockCommand,insertHrCommand} from '@milkdown/kit/preset/commonmark';
import {toggleStrikethroughCommand,insertTableCommand,addRowAfterCommand,addColAfterCommand} from '@milkdown/kit/preset/gfm';

type Owner=Readonly<{action<T>(callback:(ctx:Ctx)=>T):T;formattingReady:boolean}>;
let toolbarIdentity=0;

/** Formatting uses the owned view's dispatchTransaction. It never edits DOM,
 * reparses the whole document or bypasses identity/template/autosave guards. */
export function installFormatToolbar(root:HTMLElement,owner:Owner,report:(message:string|null)=>void){
  const document=root.ownerDocument,toolbar=document.createElement('div');
  toolbar.className='editor-format-toolbar';toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','正文格式工具');
  const group=(label:string)=>{const element=document.createElement('div');element.className='editor-format-group';element.setAttribute('role','group');element.setAttribute('aria-label',label);toolbar.append(element);return element;};
  const common=group('常用格式'),table=group('表格操作');
  const more=document.createElement('button');more.type='button';more.className='ui-button';more.textContent='更多格式';more.setAttribute('aria-expanded','false');
  const extra=document.createElement('div');extra.className='editor-format-more';extra.id=`editor-format-more-${++toolbarIdentity}`;extra.hidden=true;extra.setAttribute('role','group');extra.setAttribute('aria-label','更多格式工具');more.setAttribute('aria-controls',extra.id);toolbar.append(more,extra);
  const tableLabels=new Set(['表格加行','表格加列','删除当前行','删除当前列','删除表格']);
  const shortcuts:Record<string,string>={'加粗':'Ctrl/⌘+B','斜体':'Ctrl/⌘+I','无序列表':'Ctrl/⌘+Shift+8','有序列表':'Ctrl/⌘+Shift+7','撤销':'Ctrl/⌘+Z','重做':'Ctrl+Y / ⌘+Shift+Z'};
  const commonLabels=new Set(['加粗','斜体','无序列表','有序列表','撤销','重做']);
  const icons:Record<string,string>={'无序列表':'M6 4h8M6 8h8M6 12h8M2 4h1M2 8h1M2 12h1','有序列表':'M7 4h7M7 8h7M7 12h7M2 2h1v4M2 9q2-2 2 0l-2 3h2','撤销':'M6 3 2 7l4 4M2 7h7a4 4 0 0 1 4 4','重做':'m10 3 4 4-4 4M14 7H7a4 4 0 0 0-4 4'};
  const expand=(open:boolean)=>{extra.hidden=!open;more.setAttribute('aria-expanded',String(open));};
  more.addEventListener('mousedown',event=>event.preventDefault());more.addEventListener('click',()=>expand(extra.hidden!==false));
  toolbar.addEventListener('keydown',event=>{if(event.key==='Escape'&&!extra.hidden&&!event.defaultPrevented){event.preventDefault();expand(false);more.focus({preventScroll:true});}});
  const outside=(event:PointerEvent)=>{if(event.target instanceof document.defaultView!.Node&&!toolbar.contains(event.target))expand(false);};document.addEventListener('pointerdown',outside);
  const buttons:{element:HTMLButtonElement;command:(ctx:Ctx)=>Command;mark?:string}[]=[];
  const run=(command:(ctx:Ctx)=>Command)=>{
    if(!owner.formattingReady)return false;
    const applied=owner.action(ctx=>{const view=ctx.get(editorViewCtx);view.focus();
      const applied=command(ctx)(view.state,view.dispatch,view);if(!applied)report('当前选区不支持此格式，请选择可编辑的正文内容。');return applied;
    });update();return applied;
  };
  const button=(label:string,command:(ctx:Ctx)=>Command,mark?:string)=>{
    const element=document.createElement('button');element.type='button';element.className='ui-button';element.textContent=label;element.title=label;
    element.setAttribute('aria-label',label);
    if(commonLabels.has(label)){
      element.classList.add('format-icon-button');element.replaceChildren();
      if(label==='加粗'||label==='斜体'){const icon=document.createElement('span');icon.textContent=label==='加粗'?'B':'I';icon.className=label==='加粗'?'format-bold':'format-italic';icon.setAttribute('aria-hidden','true');element.append(icon);}
      else{const icon=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');icon.setAttribute('viewBox','0 0 16 16');icon.setAttribute('aria-hidden','true');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','1.5');icon.setAttribute('stroke-linecap','round');icon.setAttribute('stroke-linejoin','round');path.setAttribute('d',icons[label]!);icon.append(path);element.append(icon);}
    }
    element.addEventListener('mousedown',event=>event.preventDefault());element.addEventListener('click',()=>run(command));
    (tableLabels.has(label)?table:commonLabels.has(label)?common:extra).append(element);buttons.push({element,command,...(mark?{mark}:{})});
  };
  // Explicit callbacks retain each command's payload type.
  const formatLabel=document.createElement('label');formatLabel.textContent='样式';
  const style=document.createElement('select');style.className='ui-input';style.setAttribute('aria-label','正文或标题级别');
  for(let level=0;level<=6;level++){const option=document.createElement('option');option.value=String(level);option.textContent=level?`标题 ${level}`:'正文';style.append(option);}
  style.addEventListener('change',()=>{const level=Number(style.value);run(ctx=>level?ctx.get(commandsCtx).get(wrapInHeadingCommand.key)(level):ctx.get(commandsCtx).get(turnIntoTextCommand.key)());});
  formatLabel.append(style);common.append(formatLabel);
  button('加粗',ctx=>ctx.get(commandsCtx).get(toggleStrongCommand.key)(),'strong');
  button('斜体',ctx=>ctx.get(commandsCtx).get(toggleEmphasisCommand.key)(),'emphasis');
  button('删除线',ctx=>ctx.get(commandsCtx).get(toggleStrikethroughCommand.key)(),'strike_through');
  button('行内代码',ctx=>ctx.get(commandsCtx).get(toggleInlineCodeCommand.key)(),'inlineCode');
  button('无序列表',ctx=>listCommand(ctx,false));
  button('有序列表',ctx=>listCommand(ctx,true));
  button('引用',ctx=>ctx.get(commandsCtx).get(wrapInBlockquoteCommand.key)());
  button('退出引用/列表',()=>lift);
  button('代码块',ctx=>ctx.get(commandsCtx).get(createCodeBlockCommand.key)());
  button('分隔线',ctx=>ctx.get(commandsCtx).get(insertHrCommand.key)());
  button('插入表格',ctx=>ctx.get(commandsCtx).get(insertTableCommand.key)({row:3,col:3}));
  button('表格加行',ctx=>ctx.get(commandsCtx).get(addRowAfterCommand.key)());
  button('表格加列',ctx=>ctx.get(commandsCtx).get(addColAfterCommand.key)());
  button('删除当前行',()=>deleteRow);button('删除当前列',()=>deleteColumn);button('删除表格',()=>deleteTable);
  button('撤销',()=>undo);button('重做',()=>redo);
  const linkButton=document.createElement('button');linkButton.type='button';linkButton.className='ui-button';linkButton.textContent='链接';
  linkButton.title='链接（Ctrl/⌘+K）';linkButton.setAttribute('aria-expanded','false');linkButton.addEventListener('mousedown',event=>event.preventDefault());common.append(linkButton);
  const form=document.createElement('form');form.className='editor-link-form';form.hidden=true;
  const linkLabel=document.createElement('label');linkLabel.textContent='链接地址';
  const href=document.createElement('input');href.type='url';href.className='ui-input';href.placeholder='https://example.com';href.required=true;linkLabel.append(href);form.append(linkLabel);
  const apply=document.createElement('button');apply.type='submit';apply.className='ui-button';apply.textContent='应用链接';form.append(apply);
  const cancel=document.createElement('button');cancel.type='button';cancel.className='ui-button';cancel.textContent='取消';form.append(cancel);
  const closeLink=()=>{form.hidden=true;linkButton.setAttribute('aria-expanded','false');owner.action(ctx=>ctx.get(editorViewCtx).focus());};
  cancel.addEventListener('click',closeLink);
  linkButton.addEventListener('click',()=>{form.hidden=!form.hidden;linkButton.setAttribute('aria-expanded',String(!form.hidden));if(!form.hidden)href.focus();});
  form.addEventListener('submit',event=>{event.preventDefault();if(!owner.formattingReady)return;let value:URL;try{value=new URL(href.value);}catch{report('请输入完整的 http、https 或 mailto 链接。');return;}
    if(!['http:','https:','mailto:'].includes(value.protocol)){report('链接仅支持 http、https 或 mailto。');return;}
    run(()=> (state,dispatch)=>{const type=state.schema.marks.link;if(!type)return false;const mark=type.create({href:href.value});
      dispatch?.(state.selection.empty?state.tr.addStoredMark(mark):state.tr.addMark(state.selection.from,state.selection.to,mark));return true;
    });closeLink();
  });
  form.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeLink();}});
  button('移除链接',()=> (state,dispatch)=>{const type=state.schema.marks.link,selection=state.selection;
    if(!type||selection.empty||!state.doc.rangeHasMark(selection.from,selection.to,type))return false;
    dispatch?.(state.tr.removeMark(selection.from,selection.to,type));return true;
  });
  toolbar.append(form);root.prepend(toolbar);
  let interactions:ReturnType<typeof installEditorInteractions>|null=null;
  function update(){
    const disabled=!owner.formattingReady;toolbar.setAttribute('aria-disabled',String(disabled));
    style.disabled=disabled;linkButton.disabled=disabled;href.disabled=disabled;apply.disabled=disabled;more.disabled=disabled;
    more.title=disabled?'请先恢复编辑或等待状态同步':'展开低频格式工具';
    owner.action(ctx=>{const view=ctx.get(editorViewCtx),state=view.state,selection=state.selection;
      let inTable=selection instanceof Object&&'node' in selection&&(selection.node as Node).type.name==='table';
      for(let depth=selection.$from.depth;depth>0;depth--)if(selection.$from.node(depth).type.name==='table')inTable=true;
      table.hidden=!inTable;
      style.value=selection.$from.parent.type.name==='heading'?String(selection.$from.parent.attrs.level):'0';
      for(const item of buttons){item.element.disabled=disabled||!item.command(ctx)(state,undefined,view);
        item.element.title=item.element.disabled?(disabled?'当前正文尚不可编辑，请先处理恢复提示或等待状态同步。':'当前选区不支持此操作，请选择合适的正文位置。'):(item.element.getAttribute('aria-label')??item.element.textContent??'')+(shortcuts[item.element.getAttribute('aria-label')??'']?`（${shortcuts[item.element.getAttribute('aria-label')??'']}）`:'');
        if(item.mark){const type=state.schema.marks[item.mark];const active=!!type&&(selection.empty?!!type.isInSet(state.storedMarks??selection.$from.marks()):state.doc.rangeHasMark(selection.from,selection.to,type));item.element.setAttribute('aria-pressed',String(active));}
      }
    });interactions?.update();
  }
  interactions=installEditorInteractions(root,owner,run,report);
  update();return {update,contains:(target:globalThis.Node|null)=>!!target&&(toolbar.contains(target)||!!interactions?.contains(target)),destroy:()=>{document.removeEventListener('pointerdown',outside);interactions?.destroy();toolbar.remove();}};
}
