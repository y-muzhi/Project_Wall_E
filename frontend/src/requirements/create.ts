import type { WalleApi, CreateRequirement } from '../api/walle.ts';
import { ApiRejected, snapshotObject } from '../api/client.ts';
import { requirementCatalog } from './catalog.ts';
import { ordinaryInput } from '../shared/text.ts';

export type CreateDraft = Readonly<{ title: string; type: 'NEW' | 'CHANGE' | null; template: Readonly<{ template_key: string; template_version: string }> | null;
  idea: string; mode: 'IDEATION' | 'DESIGN' | null }>;
export const emptyCreateDraft: CreateDraft = Object.freeze({ title: '', type: null, template: null, idea: '', mode: null });
export type CreateErrors = Readonly<Partial<Record<keyof CreateDraft, string>>>;
type Created = Awaited<ReturnType<ReturnType<WalleApi['prepareCreateRequirement']>['submit']>>['data'];
export type CreateState = Readonly<{ draft: CreateDraft; busy: boolean; unknown: boolean; error: string | null; fields: CreateErrors; result: Created | null }>;
export function createPayload(draft: CreateDraft): { payload: CreateRequirement | null; fields: CreateErrors } {
  const errors: Partial<Record<keyof CreateDraft, string>> = {}; let title = '', idea = '';
  try { title = ordinaryInput(draft.title, 'title', 1, 20, false); } catch (error) { errors.title = (error as Error).message; }
  if (!draft.type || !requirementCatalog.requirement_types.some(option => option.value === draft.type)) errors.type = '请选择需求类型';
  if (!draft.template || !requirementCatalog.templates.some(option => option.template_key === draft.template!.template_key && option.template_version === draft.template!.template_version && option.requirement_types.includes(draft.type!))) errors.template = '请选择适用于此类型的模板';
  try { idea = ordinaryInput(draft.idea, 'idea', 1, 10000); } catch (error) { errors.idea = (error as Error).message; }
  if (!draft.mode || !requirementCatalog.initialization_modes.some(option => option.value === draft.mode)) errors.mode = '请选择初始化模式';
  return { fields: Object.freeze(errors), payload: Object.keys(errors).length ? null : Object.freeze({ title, requirement_type: draft.type!,
    template_key: draft.template!.template_key, template_version: draft.template!.template_version, initial_idea: idea, initialization_mode: draft.mode! }) };
}
export class CreateRequirementFlow {
  private readonly api: Pick<WalleApi, 'prepareCreateRequirement'>; private action: ReturnType<WalleApi['prepareCreateRequirement']> | undefined;
  private readonly listeners = new Set<(state: CreateState) => void>();
  private value: CreateState = Object.freeze({ draft: emptyCreateDraft, busy: false, unknown: false, error: null, fields: Object.freeze({}), result: null });
  private pending: Promise<void> | undefined; private closed = false;
  constructor(api: Pick<WalleApi, 'prepareCreateRequirement'>) { this.api = api; }
  get state(): CreateState { return this.value; }
  get hasInput(): boolean { const draft = this.value.draft; return !!(draft.title || draft.idea || draft.type || draft.template || draft.mode); }
  subscribe(listener: (state: CreateState) => void): () => void { this.listeners.add(listener); listener(this.value); return () => this.listeners.delete(listener); }
  private publish(changes: Partial<CreateState>): void {
    if (this.closed) return; this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) { try { listener(this.value); } catch (error) { console.error('WALL-E create observer failed', error); } }
  }
  edit(value: CreateDraft): void {
    if (this.closed || this.value.busy || this.value.unknown || this.value.result) throw new Error('Original create action must be resolved first');
    const captured = snapshotObject(value) as unknown as CreateDraft;
    if (Object.keys(captured).sort().join(',') !== 'idea,mode,template,title,type') throw new TypeError('Five controlled fields required');
    let template = captured.template;
    if (captured.type !== this.value.draft.type) {
      const choices = requirementCatalog.templates.filter(option => option.requirement_types.includes(captured.type!));
      if (!choices.some(option => option.template_key === template?.template_key && option.template_version === template.template_version)) template = null;
      if (choices.length === 1) template = Object.freeze({ template_key: choices[0]!.template_key, template_version: choices[0]!.template_version });
    }
    const next = Object.freeze({ ...captured, template });
    if (JSON.stringify(next) === JSON.stringify(this.value.draft)) return;
    this.action = undefined; this.publish({ draft: next, fields: Object.freeze({}), error: null });
  }
  submit(): Promise<void> {
    if (this.closed || this.value.result) return Promise.resolve(); if (this.pending) return this.pending;
    if (!this.action) {
      const validated = createPayload(this.value.draft);
      if (!validated.payload) { this.publish({ fields: validated.fields, error: null }); return Promise.resolve(); }
      this.action = this.api.prepareCreateRequirement(validated.payload);
    }
    const action = this.action;
    const pending = Promise.resolve().then(async () => {
      try { const result = (await action.submit()).data; if (!this.closed) this.publish({ result, busy: false, unknown: false, error: null, fields: Object.freeze({}) }); }
      catch (error) {
        if (this.closed) return;
        if (error instanceof ApiRejected) {
          const fields: Partial<Record<keyof CreateDraft, string>> = {};
          const mapping: Record<string, keyof CreateDraft> = { title: 'title', requirement_type: 'type', template_key: 'template', template_version: 'template', initial_idea: 'idea', initialization_mode: 'mode' };
          if (error.code === 'VALIDATION_FAILED' && Array.isArray(error.details?.field_errors)) {
            for (const entry of error.details.field_errors) { const row = entry as { field: string; message: string }; const name = mapping[row.field]; if (name) fields[name] = row.message; }
          }
          this.publish({ busy: false, unknown: false, fields: Object.freeze(fields), error: Object.keys(fields).length ? null : error.message });
        } else this.publish({ busy: false, unknown: true, error: '创建结果待核实，请使用原请求重试；不要重复新建' });
      }
    }).finally(() => { if (this.pending === pending) this.pending = undefined; });
    this.pending = pending; this.publish({ busy: true, error: null }); return pending;
  }
  dispose(): void { this.closed = true; this.listeners.clear(); }
}
