import {Icon,BusyIndicator} from '../shared/icon.tsx';
import { useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import { requirementCatalog } from './catalog.ts';
import type { CreateDraft, CreateState } from './create.ts';
import {SingleSelect} from '../shared/single-select.tsx';

export function CreateRequirementDrawer({ open, state, edit, create, cancel }: Readonly<{ open: boolean; state: CreateState;
  edit(draft: CreateDraft): void; create(): void; cancel(): void }>) {
  const dialog = useRef<HTMLDialogElement>(null), composing = useRef(false), id = useId();
  const locked = state.busy || state.unknown;
  useLayoutEffect(() => {
    if (!open) return;
    const element = dialog.current!, original = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element.showModal(); const release = registerModal(element); element.querySelector<HTMLInputElement>('input')?.focus();
    return () => { element.close(); release(); if (original?.isConnected && !original.closest('[inert]')) original.focus();
      else document.querySelector<HTMLElement>('[data-focus-fallback], main button:not(:disabled)')?.focus(); };
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    const first = (['title','type','idea'] as const).find(field => state.fields[field]);
    if (first) dialog.current?.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
  }, [open, state.fields]);
  if (!open) return null;
  const field = (name: keyof CreateDraft) => ({ id: id + '-' + name, 'data-field': name,
    'aria-invalid': !!state.fields[name], 'aria-describedby': state.fields[name] ? id + '-error-' + name : undefined, 'aria-required': true });
  const error = (name: keyof CreateDraft) => state.fields[name] && <p id={id + '-error-' + name} className="inline-error" role="alert">! {state.fields[name]}</p>;
  const selectField=(name:keyof CreateDraft)=>({id:id+'-'+name,field:name,invalid:!!state.fields[name],describedBy:state.fields[name]?id+'-error-'+name:undefined,required:true});
  const draft = state.draft;
  return createPortal(<dialog ref={dialog} className="create-drawer" tabIndex={-1} aria-labelledby={id + '-heading'} onKeyDown={trapModalTab}
    onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
    onCancel={event => { event.preventDefault(); if (!locked) cancel(); }}>
    <form noValidate onSubmit={event => { event.preventDefault(); if (!state.busy && !composing.current) create(); }}>
      <header><h2 id={id + '-heading'}>新建需求</h2><button type="button" className="ui-button icon-button" aria-label="关闭新建需求" disabled={locked} onClick={cancel}><Icon name="close"/></button></header>
      {state.error && <p role="alert" className="inline-error create-feedback">! {state.error}</p>}
      <div className="create-fields">
        <div><label htmlFor={id + '-title'}>需求标题</label><input className="ui-input" {...field('title')} value={draft.title} disabled={locked} autoComplete="off"
          onChange={event => edit({ ...draft, title: event.currentTarget.value })} /><small>1～20 个字符</small>{error('title')}</div>
        <div><label htmlFor={id + '-type'}>需求类型</label><SingleSelect {...selectField('type')} label="需求类型" value={draft.type ?? ''} disabled={locked} placeholder="请选择需求类型"
          options={[{value:'',label:'请选择需求类型'},...requirementCatalog.requirement_types]}
          change={value=>edit({...draft,type:value===''?null:value as CreateDraft['type']})}/>{error('type')}</div>
        <div><label htmlFor={id + '-idea'}>初始想法</label><textarea className="ui-input" {...field('idea')} rows={10} value={draft.idea} disabled={locked}
          onChange={event => edit({ ...draft, idea: event.currentTarget.value })} /><small>请描述目标、背景或已有想法，最多 10000 个字符</small>{error('idea')}</div>
        <p className="secondary-text">创建后可开始讨论并生成文档</p>
      </div>
      <footer><button className="ui-button" type="button" disabled={locked} onClick={cancel}>取消</button><button type="submit" className="ui-button primary" disabled={state.busy} aria-busy={state.busy}>
        <BusyIndicator busy={state.busy}/>{state.unknown ? '核实创建结果' : '创建需求'}</button></footer>
    </form>
  </dialog>, document.body);
}
