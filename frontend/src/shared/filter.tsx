import { useLayoutEffect, useId, useRef, useState } from 'react';
import { normalizeOrdinary } from './text.ts';

export type FilterValue = string | number;
export type FilterOption<T extends FilterValue> = Readonly<{ value: T; label: string }>;
export function MultiFilter<T extends FilterValue>({ name, options, value, disabled = false, change }: Readonly<{
  name: string; options: readonly FilterOption<T>[]; value: readonly T[]; disabled?: boolean;
  change(selectedValues: readonly T[], isAllSelected: boolean): void;
}>) {
  const [open, setOpen] = useState(false), [upwards, setUpwards] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null), id = useId();
  if (options.length < 2 || new Set(options.map(option => option.value)).size !== options.length || value.length < 1 || new Set(value).size !== value.length || value.some(item => !options.some(option => Object.is(item, option.value)))) throw new TypeError('Valid controlled filter required');
  const all = value.length === options.length;
  const label = `${name}：${all ? '全部' : value.length === 1 ? options.find(option => Object.is(option.value, value[0]))!.label : '已选 ' + value.length + ' 项'}`;
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
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    const observer = new ResizeObserver(update); if (trigger.current) observer.observe(trigger.current);
    return () => { observer.disconnect(); document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true); };
  }, [open, disabled, upwards]);
  const select = (selected: readonly T[]) => { if (!selected.length) return; change(Object.freeze([...selected]), selected.length === options.length); };
  return <div className="multi-filter" ref={root} onKeyDown={event => { if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); trigger.current?.focus(); } }}>
    <button type="button" ref={trigger} className="filter-trigger" disabled={disabled} aria-expanded={open && !disabled} aria-controls={id} title={label} onClick={() => setOpen(!open)}>
      <span>{label}</span><span aria-hidden="true">{open && !disabled ? '⌃' : '⌄'}</span></button>
    {open && !disabled && <div ref={menu} id={id} className={'filter-menu' + (upwards ? ' filter-upwards' : '')} aria-label={name + '筛选'}>
      <button type="button" disabled={all} onClick={() => select(options.map(option => option.value))}>一键全选</button>
      <div className="filter-options">{options.map((option, index) => {
        const selected = value.some(item => Object.is(item, option.value)), last = selected && value.length === 1;
        return <label key={index} title={last ? '至少保留一个选项' : option.label} className={selected ? 'selected' : ''}>
          <input type="checkbox" checked={selected} disabled={last} onChange={() => select(selected ? value.filter(item => !Object.is(item, option.value)) : [...value, option.value])} />
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
  return <div className="search-input"><input ref={input} value={value} disabled={disabled} placeholder={placeholder} aria-label={placeholder}
    onChange={event => draft(event.currentTarget.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
    onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && !composing.current) { event.preventDefault(); search(); } }} />
    <button type="button" className={'icon-button search-clear' + (!value ? ' hidden-control' : '')} disabled={disabled || !value} tabIndex={value ? 0 : -1} aria-hidden={!value} aria-label="清除" title="清除" onClick={clear}>×</button>
    <button type="button" className="icon-button" disabled={disabled} aria-label="搜索" title="搜索" onClick={search}>⌕</button>
  </div>;
}
