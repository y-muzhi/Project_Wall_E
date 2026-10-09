import {Icon} from './icon.tsx';
import { useLayoutEffect, useId, useRef, useState } from 'react';
import { normalizeOrdinary } from './text.ts';

export type FilterValue = string | number;
export type FilterOption<T extends FilterValue> = Readonly<{ value: T; label: string }>;
export function MultiFilter<T extends FilterValue>({ name, options, value, disabled = false, change }: Readonly<{
  name: string; options: readonly FilterOption<T>[]; value: readonly T[]; disabled?: boolean;
  change(selectedValues: readonly T[], isAllSelected: boolean): void;
}>) {
  type Draft = Readonly<{selected:readonly T[];baseline:readonly T[];choices:readonly T[]}>;
  const [draft, setDraft] = useState<Draft|null>(null), [upwards, setUpwards] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null), id = useId();
  if (options.length < 2 || new Set(options.map(option => option.value)).size !== options.length || new Set(value).size !== value.length || value.some(item => !options.some(option => Object.is(item, option.value)))) throw new TypeError('Valid controlled filter required');
  const choices=options.map(option=>option.value), canonical=value.length?choices.filter(item=>value.some(selected=>Object.is(item,selected))):choices;
  const equal=(left:readonly T[],right:readonly T[])=>left.length===right.length&&left.every((item,index)=>Object.is(item,right[index]));
  const all = canonical.length === options.length;
  const label = `${name}：${all ? '全部' : value.length === 1 ? options.find(option => Object.is(option.value, value[0]))!.label : '已选 ' + value.length + ' 项'}`;
  const compatible=!!draft&&equal(draft.baseline,canonical)&&equal(draft.choices,choices),open=compatible&&!disabled;
  const pending=useRef(draft),current=useRef({canonical,choices,disabled,change});pending.current=draft;current.current={canonical,choices,disabled,change};
  const updateDraft=(next:Draft|null)=>{pending.current=next;setDraft(next);};
  const finish=(apply:boolean)=>{
    const captured=pending.current,latest=current.current;if(!captured)return;updateDraft(null);
    if(!apply||latest.disabled||!equal(captured.baseline,latest.canonical)||!equal(captured.choices,latest.choices))return;
    const selected=!captured.selected.length?latest.choices:latest.choices.filter(item=>captured.selected.some(value=>Object.is(value,item)));
    if(!equal(selected,latest.canonical))latest.change(Object.freeze([...selected]),selected.length===latest.choices.length);
  };
  useLayoutEffect(()=>{if(draft&&!open)updateDraft(null);},[draft,open]);
  useLayoutEffect(() => {
    if (!open || disabled) return;
    const update = () => {
      const rect = trigger.current!.getBoundingClientRect(), up = window.innerHeight - rect.bottom < 280 && rect.top > window.innerHeight - rect.bottom; setUpwards(up);
      if (menu.current) {
        menu.current.style.maxHeight = Math.max(0, Math.min(280, (up ? rect.top : window.innerHeight - rect.bottom) - 16)) + 'px';
        menu.current.style.transform = 'translateX(0px)'; const panel = menu.current.getBoundingClientRect();
        const shift = panel.right > window.innerWidth - 16 ? window.innerWidth - 16 - panel.right : panel.left < 16 ? 16 - panel.left : 0;
        menu.current.style.transform = `translateX(${shift}px)`;
      }
    };
    update(); window.addEventListener('resize', update); window.addEventListener('scroll', update, true);
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) finish(true); };
    document.addEventListener('pointerdown', outside);
    const observer = new ResizeObserver(update); if (trigger.current) observer.observe(trigger.current);
    return () => { observer.disconnect(); document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true); };
  }, [open, disabled, upwards]);
  return <div className="multi-filter" ref={root} onBlur={event=>{if(open&&event.relatedTarget&&!event.currentTarget.contains(event.relatedTarget))finish(true);}} onKeyDown={event => { if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); finish(false); trigger.current?.focus(); } }}>
    <button type="button" ref={trigger} className="ui-button filter-trigger" disabled={disabled} aria-expanded={open} aria-controls={id} aria-describedby={id+'-help'} title={label} onClick={() => {
      if(open)finish(true);else updateDraft({selected:Object.freeze([...canonical]),baseline:Object.freeze([...canonical]),choices:Object.freeze([...choices])});
    }}>
      <span>{label}</span><Icon name={open && !disabled ? 'up' : 'down'}/></button>
    <span className="sr-only" id={id+'-help'}>勾选后关闭筛选器应用，Esc取消；未选任何项表示全部。</span>
    {open && draft && <div ref={menu} id={id} role="group" className={'filter-menu' + (upwards ? ' filter-upwards' : '')} aria-label={name + '筛选'}>
      <div className="filter-options">{options.map((option, index) => {
        const selected = draft.selected.some(item => Object.is(item, option.value));
        return <label key={index} title={option.label} className={selected ? 'selected' : ''}>
          <input className="ui-input" type="checkbox" checked={selected} onChange={() => updateDraft({...draft,selected:selected?draft.selected.filter(item=>!Object.is(item,option.value)):[...draft.selected,option.value]})} />
          <span>{option.label}</span></label>;
      })}</div></div>}
  </div>;
}
export function SearchInput({ value, submitted, placeholder, disabled = false, draft, submit }: Readonly<{
  value: string; submitted: string; placeholder: string; disabled?: boolean; draft(value: string): void; submit(value: string): void;
}>) {
  const composing = useRef(false), input = useRef<HTMLInputElement>(null);
  const search = () => { if (!disabled && !composing.current) {
    let normalized = value; try { normalized = normalizeOrdinary(value); } catch { /* Parent reports invalid ordinary input. */ }
    submit(normalized);
  } };
  const clear = () => { if (disabled) return; draft(''); if (submitted !== '') submit(''); input.current?.focus(); };
  return <div className="search-input"><input className="ui-input" ref={input} value={value} disabled={disabled} placeholder={placeholder} aria-label={placeholder}
    onChange={event => draft(event.currentTarget.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
    onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !composing.current) { event.preventDefault(); search(); } }} />
    <button type="button" className={'ui-button '+('icon-button search-clear' + (!value ? ' hidden-control' : ''))} disabled={disabled || !value} tabIndex={value ? 0 : -1} aria-hidden={!value} aria-label="清除" title="清除" onClick={clear}><Icon name="close"/></button>
    <button type="button" className="ui-button icon-button" disabled={disabled} aria-label="搜索" title="搜索" onClick={search}><Icon name="search"/></button>
  </div>;
}
