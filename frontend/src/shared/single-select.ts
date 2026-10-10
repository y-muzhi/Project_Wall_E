export type SelectOption = Readonly<{value:string;label:string;disabled?:boolean}>;
export type SingleSelectConfig = Readonly<{
  value:string;options:readonly SelectOption[];change(value:string):void;
  label:string;placeholder?:string;disabled?:boolean;compact?:boolean;
  id?:string;describedBy?:string|undefined;invalid?:boolean;required?:boolean;field?:string;
}>;
let identity=0;

/** One DOM owner for React fields and imperative editor tools. The manual
 * popover remains a DOM descendant while escaping clipping and modal stacking. */
export function createSingleSelect(document:Document,initial:SingleSelectConfig){
  const browser=document.defaultView!,element=document.createElement('span'),trigger=document.createElement('button');
  const text=document.createElement('span'),arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');
  const panel=document.createElement('div'),key=`single-select-${++identity}`;
  element.className='single-select';trigger.type='button';trigger.className='single-select-trigger';
  trigger.setAttribute('role','combobox');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-controls',key);
  text.className='single-select-text';arrow.setAttribute('viewBox','0 0 16 16');arrow.setAttribute('aria-hidden','true');
  path.setAttribute('d','m4 6 4 4 4-4');arrow.append(path);trigger.append(text,arrow);
  panel.className='single-select-panel';panel.id=key;panel.setAttribute('role','listbox');panel.setAttribute('popover','manual');panel.hidden=true;
  element.append(trigger,panel);
  let config=initial,opened=false,active=-1,rows:HTMLDivElement[]=[],signature='';
  const enabled=()=>config.options.map((option,index)=>option.disabled?-1:index).filter(index=>index>=0);
  function highlight(){
    rows.forEach((row,index)=>row.classList.toggle('is-active',index===active));
    const row=rows[active];if(row){trigger.setAttribute('aria-activedescendant',row.id);row.scrollIntoView({block:'nearest'});}
    else trigger.removeAttribute('aria-activedescendant');
  }
  function position(){
    if(!opened)return;
    const rect=trigger.getBoundingClientRect();
    if(!rect.width||!rect.height||element.closest('[hidden],[inert]')){close();return;}
    const margin=8,gap=6,below=browser.innerHeight-rect.bottom-margin-gap,above=rect.top-margin-gap;
    const up=below<Math.min(panel.scrollHeight,180)&&above>below;
    panel.style.width=`${Math.min(Math.max(rect.width,160),browser.innerWidth-margin*2)}px`;
    panel.style.maxHeight=`${Math.max(0,Math.min(280,up?above:below))}px`;
    panel.style.left=`${Math.max(margin,Math.min(rect.left,browser.innerWidth-margin-panel.offsetWidth))}px`;
    panel.style.top=`${Math.max(margin,up?rect.top-gap-panel.offsetHeight:rect.bottom+gap)}px`;
  }
  function outside(event:PointerEvent){if(event.target instanceof browser.Node&&!element.contains(event.target))close();}
  function focusOutside(event:FocusEvent){if(event.target instanceof browser.Node&&!element.contains(event.target))close();}
  function scroll(event:Event){if(event.target instanceof browser.Node&&panel.contains(event.target))return;position();}
  function close(){
    if(!opened)return;opened=false;trigger.setAttribute('aria-expanded','false');trigger.removeAttribute('aria-activedescendant');
    if(panel.matches(':popover-open'))panel.hidePopover();panel.hidden=true;
    document.removeEventListener('pointerdown',outside,true);document.removeEventListener('focusin',focusOutside);
    document.removeEventListener('scroll',scroll,true);browser.removeEventListener('resize',position);
  }
  function open(){
    if(config.disabled||!enabled().length||opened)return;
    opened=true;panel.hidden=false;trigger.setAttribute('aria-expanded','true');
    active=config.options.findIndex(option=>option.value===config.value&&!option.disabled);if(active<0)active=enabled()[0]??-1;
    panel.showPopover();position();highlight();trigger.focus({preventScroll:true});
    document.addEventListener('pointerdown',outside,true);document.addEventListener('focusin',focusOutside);
    document.addEventListener('scroll',scroll,true);browser.addEventListener('resize',position);
  }
  function choose(index:number){
    const option=config.options[index];if(config.disabled||!option||option.disabled)return;
    close();if(option.value!==config.value)config.change(option.value);
  }
  // Editor selection must survive mouse use. Keyboard users keep focus on the
  // combobox, with aria-activedescendant representing the active option.
  trigger.addEventListener('mousedown',event=>event.preventDefault());
  trigger.addEventListener('click',()=>opened?close():open());
  trigger.addEventListener('keydown',event=>{
    if(event.isComposing||config.disabled)return;
    if(event.key==='Escape'&&opened){event.preventDefault();event.stopPropagation();close();return;}
    if(event.key==='Tab'){close();return;}
    if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();if(opened)choose(active);else open();return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
      event.preventDefault();event.stopPropagation();const wasOpen=opened;open();const indices=enabled();if(!indices.length)return;
      if(event.key==='Home')active=indices[0]!;else if(event.key==='End')active=indices.at(-1)!;
      else if(wasOpen)active=indices[(indices.indexOf(active)+(event.key==='ArrowDown'?1:-1)+indices.length)%indices.length]!;
      highlight();
    }
  });
  function update(next:SingleSelectConfig){
    if(new Set(next.options.map(option=>option.value)).size!==next.options.length)throw new TypeError('Unique single-select option values required');
    const nextSignature=JSON.stringify(next.options);
    if(opened&&(next.disabled||next.value!==config.value||nextSignature!==signature))close();
    config=next;element.classList.toggle('is-compact',!!next.compact);trigger.disabled=!!next.disabled||!enabled().length;trigger.dataset.value=next.value;
    trigger.id=next.id??`${key}-trigger`;trigger.setAttribute('aria-label',next.label);panel.setAttribute('aria-label',next.label);
    trigger.setAttribute('aria-expanded',String(opened));trigger.setAttribute('aria-invalid',String(!!next.invalid));trigger.setAttribute('aria-required',String(!!next.required));
    if(next.describedBy)trigger.setAttribute('aria-describedby',next.describedBy);else trigger.removeAttribute('aria-describedby');
    if(next.field)trigger.dataset.field=next.field;else delete trigger.dataset.field;
    const selected=next.options.find(option=>option.value===next.value);
    text.textContent=selected?.label??next.placeholder??'请选择';trigger.title=text.textContent;
    trigger.classList.toggle('is-placeholder',!selected);
    if(signature!==nextSignature){
      signature=nextSignature;
      rows=next.options.map((option,index)=>{
        const row=document.createElement('div');row.className='single-select-option';row.id=`${key}-${index}`;
        row.setAttribute('role','option');row.setAttribute('aria-disabled',String(!!option.disabled));row.title=option.label;
        const caption=document.createElement('span');caption.textContent=option.label;
        const check=document.createElement('span');check.className='single-select-check';check.textContent='✓';check.setAttribute('aria-hidden','true');row.append(caption,check);
        row.addEventListener('mousedown',event=>event.preventDefault());row.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(index);});
        row.addEventListener('pointermove',()=>{if(!option.disabled&&active!==index){active=index;highlight();}});return row;
      });panel.replaceChildren(...rows);
    }
    rows.forEach((row,index)=>row.setAttribute('aria-selected',String(next.options[index]?.value===next.value)));
  }
  update(initial);
  return {element,trigger,update,close,get open(){return opened;},contains:(node:Node|null)=>!!node&&element.contains(node),destroy(){close();element.remove();}};
}
