import { useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import { requirementCatalog } from './catalog.ts';
import type { CreateDraft, CreateState } from './create.ts';

export function CreateRequirementDrawer({ open, state, edit, create, cancel }: Readonly<{ open: boolean; state: CreateState;
  edit(draft: CreateDraft): void; create(): void; cancel(): void }>) {
  const dialog = useRef<HTMLDialogElement>(null), composing = useRef(false), id = useId();
  const locked = state.busy || state.unknown;
  const templates = requirementCatalog.templates.filter(template => template.requirement_types.includes(state.draft.type!));
  useLayoutEffect(() => {
    if (!open) return;
    const element = dialog.current!, original = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element.showModal(); const release = registerModal(element); element.querySelector<HTMLInputElement>('input')?.focus();
    return () => { element.close(); release(); if (original?.isConnected && !original.closest('[inert]')) original.focus();
      else document.querySelector<HTMLElement>('[data-focus-fallback], main button:not(:disabled)')?.focus(); };
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    const first = (['title','type','template','idea','mode'] as const).find(field => state.fields[field]);
    if (first) dialog.current?.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
  }, [open, state.fields]);
  if (!open) return null;
  const field = (name: keyof CreateDraft) => ({ id: id + '-' + name, 'data-field': name,
    'aria-invalid': !!state.fields[name], 'aria-describedby': state.fields[name] ? id + '-error-' + name : undefined, 'aria-required': true });
  const error = (name: keyof CreateDraft) => state.fields[name] && <p id={id + '-error-' + name} className="inline-error" role="alert">! {state.fields[name]}</p>;
  const draft = state.draft;
  const templateIndex = templates.findIndex(value => value.template_key === draft.template?.template_key && value.template_version === draft.template.template_version);
  return createPortal(<dialog ref={dialog} className="create-drawer" tabIndex={-1} aria-labelledby={id + '-heading'} onKeyDown={trapModalTab}
    onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
    onCancel={event => { event.preventDefault(); if (!locked) cancel(); }}>
    <form noValidate onSubmit={event => { event.preventDefault(); if (!state.busy && !composing.current) create(); }}>
      <header><h2 id={id + '-heading'}>新建需求</h2><button type="button" className="icon-button" aria-label="关闭新建需求" disabled={locked} onClick={cancel}>×</button></header>
      {state.error && <p role="alert" className="inline-error create-feedback">! {state.error}</p>}
      <div className="create-fields">
        <div><label htmlFor={id + '-title'}>需求标题</label><input {...field('title')} value={draft.title} disabled={locked} autoComplete="off"
          onChange={event => edit({ ...draft, title: event.currentTarget.value })} /><small>1～20 个字符</small>{error('title')}</div>
        <div><label htmlFor={id + '-type'}>需求类型</label><select {...field('type')} value={draft.type ?? ''} disabled={locked}
          onChange={event => edit({ ...draft, type: event.currentTarget.value === '' ? null : event.currentTarget.value as CreateDraft['type'] })}>
          <option value="">请选择需求类型</option>{requirementCatalog.requirement_types.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>{error('type')}</div>
        <div><label htmlFor={id + '-template'}>需求模板</label><select {...field('template')} value={templateIndex < 0 ? '' : String(templateIndex)} disabled={locked || !draft.type}
          onChange={event => { const template = templates[Number(event.currentTarget.value)]; edit({ ...draft, template: event.currentTarget.value === '' || !template ? null : { template_key: template.template_key, template_version: template.template_version } }); }}>
          <option value="">请选择需求模板</option>{templates.map((template,index) => <option key={template.template_key + ':' + template.template_version} value={String(index)}>{template.label}</option>)}
        </select>{error('template')}</div>
        <div><label htmlFor={id + '-idea'}>初始想法</label><textarea {...field('idea')} rows={10} value={draft.idea} disabled={locked}
          onChange={event => edit({ ...draft, idea: event.currentTarget.value })} /><small>请描述目标、背景或已有想法，最多 10000 个字符</small>{error('idea')}</div>
        <div><label htmlFor={id + '-mode'}>初始化模式</label><select {...field('mode')} value={draft.mode ?? ''} disabled={locked}
          onChange={event => edit({ ...draft, mode: event.currentTarget.value === '' ? null : event.currentTarget.value as CreateDraft['mode'] })}>
          <option value="">请选择初始化模式</option>{requirementCatalog.initialization_modes.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>{error('mode')}</div>
      </div>
      <footer><button type="button" disabled={locked} onClick={cancel}>取消</button><button type="submit" className="primary" disabled={state.busy} aria-busy={state.busy}>
        <span className="busy-slot" aria-hidden="true">{state.busy ? '◌' : ''}</span>{state.unknown ? '核实创建结果' : '创建需求'}</button></footer>
    </form>
  </dialog>, document.body);
}
