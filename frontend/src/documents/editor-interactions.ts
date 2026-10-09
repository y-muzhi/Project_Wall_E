import {commandsCtx,editorViewCtx} from '@milkdown/kit/core';
import type {Ctx} from '@milkdown/kit/ctx';
import {TextSelection} from '@milkdown/kit/prose/state';
import type {Command} from '@milkdown/kit/prose/state';
import {wrapInHeadingCommand,turnIntoTextCommand} from '@milkdown/kit/preset/commonmark';
import {formatCommand,linkCommand,replaceSlash,slashMatch,validLink} from './format-commands.ts';
import type {FormatAction,SlashMatch} from './format-commands.ts';
import {selectionToolbarPosition} from './selection-toolbar-position.ts';

type Owner=Readonly<{action<T>(callback:(ctx:Ctx)=>T):T;formattingReady:boolean}>;
type Run=(command:(ctx:Ctx)=>Command)=>boolean;
type InsertItem=Readonly<{label:string;search:string;action:FormatAction|'link'}>;
const insertItems:readonly InsertItem[]=[
  {label:'正文',search:'正文 段落 paragraph text',action:'text'},
  {label:'标题 1',search:'标题 1 heading h1',action:'h1'},
  {label:'标题 2',search:'标题 2 heading h2',action:'h2'},
  {label:'标题 3',search:'标题 3 heading h3',action:'h3'},
  {label:'表格',search:'表格 table',action:'table'},
  {label:'链接',search:'链接 link url',action:'link'},
  {label:'无序列表',search:'无序列表 bullet list ul',action:'bullet'},
  {label:'有序列表',search:'有序列表 ordered list ol',action:'ordered'},
  {label:'引用',search:'引用 quote blockquote',action:'quote'},
  {label:'代码块',search:'代码块 code',action:'code'},
  {label:'分隔线',search:'分隔线 divider hr',action:'hr'},
];
let interactionIdentity=0;

/** In-place editing UI only. Every mutation uses the same owned dispatch as
 * the fixed toolbar; hidden/readonly/IME editors never acquire a second owner. */
export function installEditorInteractions(root:HTMLElement,owner:Owner,run:Run,report:(message:string|null)=>void){
  const document=root.ownerDocument,browser=document.defaultView!,identity=++interactionIdentity;
  const editorDOM=owner.action(ctx=>ctx.get(editorViewCtx).dom);
  const popup=(className:string,label:string)=>{const element=document.createElement('div');element.className=className;element.hidden=true;element.setAttribute('aria-label',label);document.body.append(element);return element;};
  const slash=popup('editor-slash-menu','插入类型'),bubble=popup('editor-selection-toolbar','选中文字格式');
  slash.id=`editor-slash-${identity}`;slash.setAttribute('role','listbox');bubble.setAttribute('role','group');
  const link=popup('editor-context-link','插入或修改链接');link.setAttribute('role','dialog');
  const form=document.createElement('form'),label=document.createElement('label'),href=document.createElement('input');
  label.textContent='链接地址';href.type='url';href.required=true;href.className='ui-input';href.placeholder='https://example.com';label.append(href);form.append(label);
  const error=document.createElement('p');error.setAttribute('role','status');error.className='inline-error';form.append(error);
  const submit=document.createElement('button');submit.type='submit';submit.className='ui-button primary';submit.textContent='应用链接';form.append(submit);
  const cancel=document.createElement('button');cancel.type='button';cancel.className='ui-button';cancel.textContent='取消链接';form.append(cancel);link.append(form);
  let query:SlashMatch|null=null,dismissed='',active=0,options:{item:InsertItem;enabled:boolean;element:HTMLButtonElement}[]=[];
  let pendingLink:{match:SlashMatch|null;doc:unknown}|null=null;
  let dismissedSelection:{from:number;to:number;doc:unknown}|null=null;
  let bubblePointerFocus=false;
  const buttons:{element:HTMLButtonElement;action:FormatAction;mark?:string}[]=[];
  const view=()=>owner.action(ctx=>ctx.get(editorViewCtx));
  const signature=(match:SlashMatch|null)=>match?`${match.from}:${match.to}:${match.query}`:'';
  function hideSlash(){slash.hidden=true;if(editorDOM.getAttribute('aria-controls')===slash.id){editorDOM.removeAttribute('aria-controls');editorDOM.removeAttribute('aria-activedescendant');editorDOM.removeAttribute('aria-haspopup');}}
  function dismissSlash(){dismissed=signature(query);hideSlash();}
  function closeLink(focus=false){pendingLink=null;link.hidden=true;error.textContent='';if(focus&&owner.formattingReady)view().focus();}
  function openLink(match:SlashMatch|null=null){dismissSlash();bubble.hidden=true;pendingLink={match,doc:view().state.doc};href.value='';error.textContent='';link.hidden=false;position(link);href.focus();}
  cancel.addEventListener('click',()=>{closeLink(true);update();});
  form.addEventListener('submit',event=>{event.preventDefault();if(!pendingLink||!owner.formattingReady)return;
    if(!validLink(href.value)){error.textContent='请输入完整的 http、https 或 mailto 链接。';return;}
    if(view().state.doc!==pendingLink.doc){closeLink();report('正文已变化，请重新选择链接位置。');return;}
    const match=pendingLink.match,value=href.value;
    if(run(()=>match?replaceSlash(match,linkCommand(value,true)):linkCommand(value,true))){closeLink(true);update();}
  });
  link.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeLink(true);update();}});
  const preserve=(element:HTMLElement)=>element.addEventListener('mousedown',event=>event.preventDefault());
  const style=document.createElement('select');style.className='ui-input';style.setAttribute('aria-label','选区正文或标题级别');
  // focusout fires before the native select receives focus. Keep this owned
  // control mounted through that transition so its dropdown can actually open.
  bubble.addEventListener('pointerdown',()=>{bubblePointerFocus=true;});
  for(let level=0;level<=6;level++){const option=document.createElement('option');option.value=String(level);option.textContent=level?`标题 ${level}`:'正文';style.append(option);}
  style.addEventListener('change',()=>{const level=Number(style.value);run(ctx=>level?ctx.get(commandsCtx).get(wrapInHeadingCommand.key)(level):ctx.get(commandsCtx).get(turnIntoTextCommand.key)());});bubble.append(style);
  for(const [label,action,mark] of [['加粗','bold','strong'],['斜体','italic','emphasis'],['删除线','strike','strike_through'],['行内代码','inlineCode','inlineCode']] as const){
    const button=document.createElement('button');button.type='button';button.className='ui-button';button.textContent=label;button.setAttribute('aria-label',`选区${label}`);preserve(button);
    button.addEventListener('click',()=>run(ctx=>formatCommand(ctx,action)));bubble.append(button);buttons.push({element:button,action,mark});
  }
  const linkButton=document.createElement('button');linkButton.type='button';linkButton.className='ui-button';linkButton.textContent='链接';linkButton.setAttribute('aria-label','选区链接');preserve(linkButton);linkButton.addEventListener('click',()=>openLink());bubble.append(linkButton);
  bubble.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();const {selection,doc}=view().state;dismissedSelection={from:selection.from,to:selection.to,doc};bubble.hidden=true;view().focus();}});
  function position(element:HTMLElement){
    if(element.hidden)return;
    try{const editor=view(),coords=editor.coordsAtPos(element===slash?editor.state.selection.from:editor.state.selection.to),port=root.closest('.requirement-owned-document')??root,rect=port.getBoundingClientRect();
      const top=Math.max(8,rect.top),bottom=Math.min(browser.innerHeight-8,rect.bottom);
      if(rect.width===0||element!==bubble&&(coords.bottom<top||coords.top>bottom)){element.hidden=true;return;}
      const width=element.offsetWidth,height=element.offsetHeight;
      if(element===bubble){
        const {selection}=editor.state,from=editor.domAtPos(selection.from),to=editor.domAtPos(selection.to),range=document.createRange();
        range.setStart(from.node,from.offset);range.setEnd(to.node,to.offset);
        const bounds=range.getBoundingClientRect(),bodyTop=Math.max(top,root.querySelector('.editor-format-toolbar')?.getBoundingClientRect().bottom??top),position=selectionToolbarPosition(bounds,{left:Math.max(8,rect.left),right:Math.min(browser.innerWidth-8,rect.right),top:bodyTop,bottom},width,height);
        if(!position){element.hidden=true;return;}
        element.style.left=`${position.left}px`;element.style.top=`${position.top}px`;return;
      }
      element.style.left=`${Math.max(8,Math.min(coords.left,Math.min(browser.innerWidth-8,rect.right)-width))}px`;
      element.style.top=`${Math.max(top,Math.min(coords.bottom+8,bottom-height))}px`;
    }catch{element.hidden=true;}
  }
  function highlight(){for(let i=0;i<options.length;i++){const option=options[i]!;option.element.setAttribute('aria-selected',String(i===active));}const selected=options[active];if(selected){view().dom.setAttribute('aria-activedescendant',selected.element.id);selected.element.scrollIntoView({block:'nearest'});}}
  function choose(index:number){const option=options[index],match=query;if(!option?.enabled||!match||!owner.formattingReady)return;
    if(option.item.action==='link'){openLink(match);return;}
    const action=option.item.action;dismissSlash();run(ctx=>replaceSlash(match,formatCommand(ctx,action)));
  }
  function update(){
    if(!owner.formattingReady||root.closest('[hidden],[inert]')){hideSlash();bubble.hidden=true;closeLink();return;}
    const editor=view(),state=editor.state,focused=document.activeElement;
    if(pendingLink){if(state.doc!==pendingLink.doc)closeLink();else{hideSlash();bubble.hidden=true;position(link);return;}}
    const next=slashMatch(state),changed=signature(next)!==signature(query);if(changed){active=0;dismissed='';}query=next;
    const focusInEditor=editor.hasFocus(),focusInBubble=bubblePointerFocus||!!focused&&bubble.contains(focused);
    if(next&&signature(next)!==dismissed&&focusInEditor){
      const items=insertItems.filter(item=>item.search.toLowerCase().includes(next.query.toLowerCase()));
      options=items.map((item,index)=>{const enabled=item.action==='link'||owner.action(ctx=>replaceSlash(next,formatCommand(ctx,item.action as FormatAction))(state,undefined,editor));
        const element=document.createElement('button');element.type='button';element.className='ui-button';element.id=`${slash.id}-${index}`;element.setAttribute('role','option');element.setAttribute('aria-disabled',String(!enabled));element.disabled=!enabled;element.tabIndex=-1;element.textContent=item.label;preserve(element);element.addEventListener('click',()=>choose(index));return {item,enabled,element};});
      slash.replaceChildren(...options.map(item=>item.element));
      if(!options.length){const message=document.createElement('p');message.textContent='未找到匹配的插入类型';slash.append(message);}
      if(!options[active]?.enabled)active=Math.max(0,options.findIndex(item=>item.enabled));
      slash.hidden=false;editor.dom.setAttribute('aria-haspopup','listbox');editor.dom.setAttribute('aria-controls',slash.id);position(slash);if(!slash.hidden)highlight();else hideSlash();bubble.hidden=true;
    }else{
      hideSlash();const selection=state.selection;
      if(dismissedSelection&&(dismissedSelection.doc!==state.doc||dismissedSelection.from!==selection.from||dismissedSelection.to!==selection.to))dismissedSelection=null;
      bubble.hidden=!!dismissedSelection||!(selection instanceof TextSelection&&!selection.empty&&(focusInEditor||focusInBubble)&&state.doc.textBetween(selection.from,selection.to).trim());
      if(!bubble.hidden){if(focused!==style)style.value=selection.$from.parent.type.name==='heading'?String(selection.$from.parent.attrs.level):'0';
        for(const item of buttons){item.element.disabled=!owner.action(ctx=>formatCommand(ctx,item.action)(state,undefined,editor));const mark=item.mark&&state.schema.marks[item.mark];item.element.setAttribute('aria-pressed',String(!!mark&&state.doc.rangeHasMark(selection.from,selection.to,mark)));}
        position(bubble);
      }
    }
  }
  const keydown=(event:KeyboardEvent)=>{
    const target=event.target;if(!(target instanceof browser.Node)||!view().dom.contains(target)||!owner.formattingReady||event.isComposing||event.keyCode===229)return;
    if(!slash.hidden){
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismissSlash();return;}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();event.stopPropagation();const enabled=options.map((option,index)=>option.enabled?index:-1).filter(index=>index>=0);const current=enabled.indexOf(active);if(enabled.length)active=enabled[(current+(event.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length]!;highlight();return;}
      if(event.key==='Enter'&&options[active]?.enabled){event.preventDefault();event.stopPropagation();choose(active);return;}
    }
    if(event.key==='Escape'&&!bubble.hidden){event.preventDefault();event.stopPropagation();const {selection,doc}=view().state;dismissedSelection={from:selection.from,to:selection.to,doc};bubble.hidden=true;return;}
    if(!(event.ctrlKey||event.metaKey)||event.altKey)return;
    const key=event.key.toLowerCase();let action:FormatAction|null=null;
    if(key==='b'&&!event.shiftKey)action='bold';else if(key==='i'&&!event.shiftKey)action='italic';
    else if(key==='z')action=event.shiftKey?'redo':'undo';else if(key==='y'&&!event.shiftKey)action='redo';
    else if(event.shiftKey&&(event.code==='Digit7'||event.code==='Digit8'))action=event.code==='Digit7'?'ordered':'bullet';
    if(key==='k'&&!event.shiftKey){event.preventDefault();event.stopPropagation();openLink();return;}
    if(action){event.preventDefault();event.stopPropagation();run(ctx=>formatCommand(ctx,action!));}
  };
  const outside=(event:PointerEvent)=>{const target=event.target;if(!(target instanceof browser.Node))return;
    if(!bubble.contains(target))bubblePointerFocus=false;
    if(!slash.contains(target))dismissSlash();if(!link.contains(target)&&!bubble.contains(target))closeLink();
    if(!bubble.contains(target)&&!root.contains(target))bubble.hidden=true;
  };
  const focus=()=>{bubblePointerFocus=false;update();},reposition=()=>{
    position(slash);
    if(!pendingLink&&!dismissedSelection&&owner.formattingReady&&!root.closest('[hidden],[inert]')){
      const editor=view(),selection=editor.state.selection;
      bubble.hidden=!(selection instanceof TextSelection&&!selection.empty&&(editor.hasFocus()||bubblePointerFocus||!!document.activeElement&&bubble.contains(document.activeElement))&&editor.state.doc.textBetween(selection.from,selection.to).trim());
      position(bubble);
    }else bubble.hidden=true;
    position(link);
  };
  root.addEventListener('keydown',keydown,true);document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focus);document.addEventListener('scroll',reposition,true);browser.addEventListener('resize',reposition);
  return {update,contains:(target:Node|null)=>!!target&&(bubble.contains(target)||slash.contains(target)||link.contains(target)),destroy:()=>{hideSlash();root.removeEventListener('keydown',keydown,true);document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focus);document.removeEventListener('scroll',reposition,true);browser.removeEventListener('resize',reposition);slash.remove();bubble.remove();link.remove();}};
}
