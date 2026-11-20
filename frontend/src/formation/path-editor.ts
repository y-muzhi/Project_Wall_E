/** Local raw fields remain drafts. Only a complete validated command can preview or save. */
import { ApiRejected, exact, snapshotObject, stableJson } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationDrafts } from './drafts.ts';
import type { FormationPathPreview } from '../api/formation-preview.ts';
import type { FormationStepDetail } from '../api/formation-values.ts';
import { nativeFormationCommand } from '../api/formation-commands.ts';
import { boundedText } from '../api/formation-values.ts';
import { id, time } from '../api/decoding.ts';
export const pathChangeLabels = {
  SET_GOAL: '修改文档目标',
  ADD_STEP: '新增步骤',
  RENAME_STEP: '修改步骤名称',
  MOVE_STEP: '移动步骤',
  SET_DEPENDENCIES: '设置前置步骤',
  UPDATE_RESULT: '修改成果说明',
  ADD_RESULT: '新增预期成果',
  CANCEL_STEP: '取消步骤并处理成果',
  LINK_CONTENT: '关联已有文档内容',
  MOVE_ISSUE: '转交问题',
  SET_BRANCH_RETURN: '修改支线返回步骤',
  DISPOSE_ISSUE: '暂缓或放弃问题',
  DISPOSE_BRANCH: '暂缓或放弃支线',
  RESUME_ISSUE: '恢复问题',
} as const;
export type PathChangeType = keyof typeof pathChangeLabels;
export type EditorChange = Readonly<{ local_key: string; value: JsonObject }>;
type Proposal = Readonly<{ message_id: number; card_key: string }>;
export type PathEditState = Readonly<{
  base_D: number;
  base_F: number;
  base_V: number;
  based_on_proposal: Proposal | null;
  changes: readonly EditorChange[];
  result_routes: readonly JsonObject[];
  reason: string;
  phase: 'DIRTY' | 'PREVIEWING' | 'PREVIEW_READY' | 'STALE' | 'SAVING' | 'UNKNOWN' | 'SAVED';
  preview: FormationPathPreview | null;
  preview_signature: string | null;
  error: string | null;
  warning: string | null;
  cancellations: Readonly<
    Record<
      string,
      Readonly<{ loading: boolean; step: FormationStepDetail | null; error: string | null }>
    >
  >;
}>;
function captured<T extends object>(value: T): T {
  return snapshotObject(value) as T;
}
const freshRef = (kind: 'step' | 'result') => 'new_' + kind + '_';
export class FormationPathEditor {
  private value: PathEditState;
  private readonly listeners = new Set<() => void>();
  private readonly owner: FormationWorkspace;
  private readonly drafts: FormationDrafts;
  private readonly release: () => void;
  private epoch = 0;
  private closed = false;
  private controller: AbortController | null = null;
  private readonly cancellationReads = new Map<string, AbortController>();
  constructor(owner: FormationWorkspace, drafts: FormationDrafts) {
    this.owner = owner;
    this.drafts = drafts;
    const f = owner.read.getSnapshot().summary.data?.formation_version;
    if (f === null || f === undefined) throw TypeError('Existing actual formation required');
    this.value = Object.freeze({
      base_D: owner.discussionVersion,
      base_F: f,
      base_V: owner.contentVersion,
      based_on_proposal: null,
      changes: [],
      result_routes: [],
      reason: '',
      phase: 'DIRTY',
      preview: null,
      preview_signature: null,
      error: null,
      warning: null,
      cancellations: {},
    });
    const raw = drafts.readPath();
    if (raw !== null) {
      try {
        const row = exact(raw, [
          'schema_version',
          'owner_key',
          'base_D',
          'base_F',
          'base_V',
          'based_on_proposal',
          'changes',
          'result_routes',
          'reason',
          'updated_at',
        ]);
        if (row.schema_version !== 1 || row.owner_key !== drafts.ownerKey)
          throw TypeError('Wrong route draft owner');
        id(row.base_D);
        id(row.base_F);
        id(row.base_V);
        time(row.updated_at);
        if (
          !Array.isArray(row.changes) ||
          row.changes.length > 20 ||
          !Array.isArray(row.result_routes) ||
          typeof row.reason !== 'string'
        )
          throw TypeError('Wrong route draft fields');
        let proposal: Proposal | null = null;
        if (row.based_on_proposal !== null) {
          const ref = exact(row.based_on_proposal, ['message_id', 'card_key']);
          proposal = { message_id: id(ref.message_id), card_key: boundedText(100)(ref.card_key) };
        }
        this.value = Object.freeze({
          ...this.value,
          base_D: row.base_D as number,
          base_F: row.base_F as number,
          base_V: row.base_V as number,
          based_on_proposal: proposal,
          reason: row.reason,
          changes: row.changes.map((value) =>
            Object.freeze({ local_key: crypto.randomUUID(), value: snapshotObject(value) }),
          ),
          result_routes: row.result_routes.map(snapshotObject),
          phase: 'STALE',
        });
      } catch {
        drafts.protectPath();
        this.value = Object.freeze({
          ...this.value,
          warning: '原路线草稿无法自动恢复，原记录保留，请核对后重新开始',
        });
      }
    }
    this.release = owner.subscribe(() => this.observeVersions());
    for (const change of this.value.changes)
      if (change.value.type === 'CANCEL_STEP' && typeof change.value.step_ref === 'string')
        void this.loadCancellation(change.local_key, change.value.step_ref);
  }
  getSnapshot = () => this.value;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(update: Partial<PathEditState>) {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...update });
    for (const listener of this.listeners) listener();
  }
  private persist(): void {
    const v = this.value;
    this.publish({
      warning: this.drafts.savePath({
        schema_version: 1,
        owner_key: this.drafts.ownerKey,
        base_D: v.base_D,
        base_F: v.base_F,
        base_V: v.base_V,
        based_on_proposal: v.based_on_proposal,
        changes: v.changes.map((row) => row.value),
        result_routes: v.result_routes,
        reason: v.reason,
        updated_at: new Date().toISOString(),
      }),
    });
  }
  private edited(change: Partial<PathEditState>) {
    this.epoch++;
    this.controller?.abort();
    this.publish({ ...change, phase: 'DIRTY', error: null });
    this.persist();
  }
  private observeVersions(): void {
    const v = this.value,
      f = this.owner.read.getSnapshot().summary.data?.formation_version;
    if (
      v.base_D === this.owner.discussionVersion &&
      v.base_F === f &&
      v.base_V === this.owner.contentVersion
    )
      return;
    if (['SAVING', 'UNKNOWN', 'SAVED'].includes(v.phase)) return;
    if (v.phase !== 'STALE') {
      this.controller?.abort();
      this.publish({ phase: 'STALE', error: '主线或正文版本已变化，请按最新状态重新核对草稿' });
    }
  }
  get stale(): boolean {
    return (
      this.value.base_D !== this.owner.discussionVersion ||
      this.value.base_F !== this.owner.read.getSnapshot().summary.data?.formation_version ||
      this.value.base_V !== this.owner.contentVersion
    );
  }
  get validation(): string | null {
    if (this.value.changes.length === 0) return '请添加需要调整的内容';
    try {
      this.command();
      return null;
    } catch {
      return '请补齐各项必填内容，并为取消步骤的每项成果明确去向；单次最多20项调整、64KiB';
    }
  }
  get canSave(): boolean {
    return (
      this.value.phase === 'PREVIEW_READY' &&
      !this.stale &&
      this.owner.writeReason === null &&
      this.value.preview_signature === this.signature()
    );
  }
  private signature(): string {
    return stableJson(this.body())!;
  }
  command(): JsonObject {
    return nativeFormationCommand({
      type: 'FORMATION',
      action: 'ADJUST_PATH',
      expected_formation_version: this.value.base_F,
      expected_content_version: this.value.base_V,
      based_on_proposal: this.value.based_on_proposal,
      changes: this.value.changes.map((row) => row.value),
      result_routes: this.value.result_routes,
      reason: this.value.reason,
    });
  }
  private body() {
    return { expected_discussion_version: this.value.base_D, discussion_command: this.command() };
  }
  private nextTemp(kind: 'step' | 'result'): string {
    const used = JSON.stringify(this.value.changes.map((row) => row.value));
    let n = 1;
    while (used.includes('"' + freshRef(kind) + n + '"')) n++;
    return freshRef(kind) + n;
  }
  add(type: PathChangeType): void {
    if (this.value.changes.length >= 20) return;
    const selected = this.owner.read.getSnapshot().selected_step_ref ?? '';
    let value: JsonObject;
    switch (type) {
      case 'SET_GOAL':
        value = {
          type,
          text: this.owner.read.getSnapshot().summary.data?.goal?.text ?? '',
          source_refs: [],
        };
        break;
      case 'ADD_STEP':
        value = {
          type,
          temp_step_ref: this.nextTemp('step'),
          title: '',
          expected_results: [
            { temp_result_ref: this.nextTemp('result'), description: '', kind: 'CONTENT' },
          ],
          dependencies: [],
          replaces_step_refs: [],
          before_step_ref: null,
        };
        break;
      case 'RENAME_STEP':
        value = { type, step_ref: selected, title: '' };
        break;
      case 'MOVE_STEP':
        value = { type, step_ref: selected, before_step_ref: null };
        break;
      case 'SET_DEPENDENCIES':
        value = { type, step_ref: selected, dependencies: [] };
        break;
      case 'UPDATE_RESULT':
        value = { type, result_ref: '', description: '' };
        break;
      case 'ADD_RESULT':
        value = {
          type,
          step_ref: selected,
          temp_result_ref: this.nextTemp('result'),
          description: '',
          kind: 'CONTENT',
        };
        break;
      case 'CANCEL_STEP':
        value = { type, step_ref: selected, replacement_step_refs: [] };
        break;
      case 'LINK_CONTENT':
        value = {
          type,
          step_ref: selected,
          result_refs: [],
          revision_id: this.owner.revisionId,
          block_ids: [],
        };
        break;
      case 'MOVE_ISSUE':
        value = { type, issue_ref: '', to_step_ref: selected };
        break;
      case 'SET_BRANCH_RETURN':
        value = { type, branch_ref: '', return_step_ref: selected };
        break;
      case 'DISPOSE_ISSUE':
        value = { type, issue_ref: '', disposition: 'DEFERRED', reason: '' };
        break;
      case 'DISPOSE_BRANCH':
        value = { type, branch_ref: '', disposition: 'DEFERRED', reason: '' };
        break;
      case 'RESUME_ISSUE':
        value = { type, issue_ref: '' };
        break;
    }
    const change = { local_key: crypto.randomUUID(), value: snapshotObject(value) };
    this.edited({ changes: Object.freeze([...this.value.changes, change]) });
    if (type === 'CANCEL_STEP' && selected !== '')
      void this.loadCancellation(change.local_key, selected);
  }
  update(key: string, fields: JsonObject): void {
    const previous = this.value.changes.find((row) => row.local_key === key);
    const changedStep =
      previous?.value.type === 'CANCEL_STEP' &&
      typeof fields.step_ref === 'string' &&
      fields.step_ref !== previous.value.step_ref;
    this.edited({
      ...(changedStep
        ? {
            cancellations: {
              ...this.value.cancellations,
              [key]: { loading: false, step: null, error: null },
            },
          }
        : {}),
      ...(changedStep && !this.hasOtherCancellation(key, previous.value.step_ref)
        ? {
            result_routes: this.value.result_routes.filter(
              (row) =>
                !String(row.from_result_ref).startsWith(String(previous.value.step_ref) + '.o'),
            ),
          }
        : {}),
      changes: this.value.changes.map((row) =>
        row.local_key === key
          ? Object.freeze({ ...row, value: snapshotObject({ ...row.value, ...fields }) })
          : row,
      ),
    });
    if (
      typeof fields.step_ref === 'string' &&
      this.value.changes.find((row) => row.local_key === key)?.value.type === 'CANCEL_STEP'
    )
      void this.loadCancellation(key, fields.step_ref);
  }
  private hasOtherCancellation(key: string, stepRef: unknown): boolean {
    return (
      typeof stepRef === 'string' &&
      this.value.changes.some(
        (row) =>
          row.local_key !== key &&
          row.value.type === 'CANCEL_STEP' &&
          row.value.step_ref === stepRef,
      )
    );
  }
  remove(key: string): void {
    this.cancellationReads.get(key)?.abort();
    this.cancellationReads.delete(key);
    const removed = this.value.changes.find((row) => row.local_key === key);
    const prefix =
      removed?.value.type === 'CANCEL_STEP' &&
      !this.hasOtherCancellation(key, removed.value.step_ref)
        ? String(removed.value.step_ref) + '.o'
        : null;
    const cancellations = { ...this.value.cancellations };
    delete cancellations[key];
    this.edited({
      cancellations,
      changes: this.value.changes.filter((row) => row.local_key !== key),
      result_routes:
        prefix === null
          ? this.value.result_routes
          : this.value.result_routes.filter(
              (row) => !String(row.from_result_ref).startsWith(prefix),
            ),
    });
  }
  move(key: string, offset: -1 | 1): void {
    const rows = [...this.value.changes],
      index = rows.findIndex((row) => row.local_key === key),
      to = index + offset;
    if (index < 0 || to < 0 || to >= rows.length) return;
    [rows[index], rows[to]] = [rows[to]!, rows[index]!];
    this.edited({ changes: rows });
  }
  reason(value: string): void {
    this.edited({ reason: value });
  }
  updateRoute(ref: string, fields: JsonObject): void {
    this.edited({
      result_routes: this.value.result_routes.map((row) =>
        row.from_result_ref === ref ? snapshotObject({ ...row, ...fields }) : row,
      ),
    });
  }
  addExpected(key: string): void {
    const change = this.value.changes.find((row) => row.local_key === key);
    if (
      change === undefined ||
      !Array.isArray(change.value.expected_results) ||
      change.value.expected_results.length >= 20
    )
      return;
    this.update(key, {
      expected_results: [
        ...change.value.expected_results,
        { temp_result_ref: this.nextTemp('result'), description: '', kind: 'CONTENT' },
      ],
    });
  }
  private async loadCancellation(key: string, ref: string): Promise<void> {
    this.cancellationReads.get(key)?.abort();
    this.cancellationReads.delete(key);
    if (ref === '') return;
    const controller = new AbortController(),
      baseF = this.value.base_F;
    this.cancellationReads.set(key, controller);
    this.publish({
      cancellations: {
        ...this.value.cancellations,
        [key]: { loading: true, step: null, error: null },
      },
    });
    try {
      const step = (
        await this.owner.api.getFormationStep(
          this.owner.requirementId,
          this.owner.documentId,
          ref,
          baseF,
          controller.signal,
        )
      ).data;
      if (
        this.closed ||
        controller.signal.aborted ||
        baseF !== this.value.base_F ||
        this.value.changes.find((row) => row.local_key === key)?.value.step_ref !== ref
      )
        return;
      const actualResults = new Set(step.expected_results.map((row) => row.result_ref));
      const retainedRoutes = this.value.result_routes.filter(
        (row) =>
          !String(row.from_result_ref).startsWith(ref + '.o') ||
          actualResults.has(String(row.from_result_ref)),
      );
      const existing = new Set(retainedRoutes.map((row) => row.from_result_ref));
      const routes = step.expected_results
        .filter((row) => !existing.has(row.result_ref))
        .map((row) => ({
          from_result_ref: row.result_ref,
          disposition: 'REPLACED',
          target_result_refs: [],
          reason: '',
        }));
      this.publish({
        cancellations: {
          ...this.value.cancellations,
          [key]: { loading: false, step, error: null },
        },
      });
      if (routes.length > 0 || retainedRoutes.length !== this.value.result_routes.length)
        this.edited({ result_routes: [...retainedRoutes, ...routes] });
    } catch (error) {
      if (
        !this.closed &&
        !controller.signal.aborted &&
        baseF === this.value.base_F &&
        this.value.changes.find((row) => row.local_key === key)?.value.step_ref === ref
      )
        this.publish({
          cancellations: {
            ...this.value.cancellations,
            [key]: {
              loading: false,
              step: null,
              error:
                error instanceof ApiRejected
                  ? error.message
                  : '无法读取被取消步骤的完整成果，请重试',
            },
          },
        });
    }
  }
  async rebase(): Promise<boolean> {
    if (this.owner.getSnapshot().pending.length > 0) return false;
    if (!(await this.owner.refresh(false))) return false;
    const f = this.owner.read.getSnapshot().summary.data?.formation_version;
    if (f === null || f === undefined) return false;
    this.edited({
      base_D: this.owner.discussionVersion,
      base_F: f,
      base_V: this.owner.contentVersion,
      preview: null,
      preview_signature: null,
    });
    for (const change of this.value.changes)
      if (change.value.type === 'CANCEL_STEP')
        void this.loadCancellation(change.local_key, String(change.value.step_ref));
    return true;
  }
  async preview(section?: 'AFFECTED' | 'WARNINGS', cursor?: string): Promise<boolean> {
    if (this.validation !== null || this.stale) return false;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const epoch = this.epoch,
      body = captured(this.body()),
      signature = this.signature();
    this.publish({ phase: 'PREVIEWING', error: null });
    try {
      const response = await this.owner.api.previewFormationPath(
        this.owner.requirementId,
        this.owner.documentId,
        body,
        {
          limit: 20,
          ...(section === undefined ? {} : { section }),
          ...(cursor === undefined ? {} : { cursor }),
        },
        controller.signal,
      );
      if (this.closed || epoch !== this.epoch) return false;
      const previous = this.value.preview;
      const preview =
        section === undefined || previous === null
          ? response.data
          : {
              ...previous,
              ...(section === 'AFFECTED'
                ? { affected_items: response.data.affected_items }
                : { warnings: response.data.warnings }),
            };
      this.publish({ phase: 'PREVIEW_READY', preview, preview_signature: signature });
      return true;
    } catch (error) {
      if (!this.closed && epoch === this.epoch)
        this.publish({
          phase: 'DIRTY',
          error: error instanceof ApiRejected ? error.message : '无法读取调整预览，请重试',
        });
      return false;
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }
  async save(): Promise<boolean> {
    if (!this.canSave) return false;
    const command = this.command(),
      epoch = this.epoch;
    this.publish({ phase: 'SAVING', error: null });
    const success = await this.owner.execute(command);
    if (this.closed) return success;
    if (success || this.owner.getSnapshot().phase === 'CONFIRMED') {
      if (epoch === this.epoch) {
        this.publish({ phase: 'SAVED', warning: this.drafts.savePath(null) });
        const added = this.owner
          .getSnapshot()
          .receipt?.reference_map.find((row) => row.temp_ref.startsWith('new_step_'));
        if (added !== undefined) void this.owner.selectView(added.resolved_ref);
      } else
        this.publish({
          phase: 'STALE',
          error: '原调整已保存；后续编辑仍保留，请核对并移除已执行的内容再重新预览',
        });
    } else
      this.publish({
        phase: this.owner.getSnapshot().phase === 'UNKNOWN' ? 'UNKNOWN' : 'DIRTY',
        error: this.owner.getSnapshot().error ?? '保存未完成，草稿保留',
      });
    return success;
  }
  useProposal(proposal: Proposal, payload: JsonObject): void {
    const changes = payload.changes,
      routes = payload.result_routes;
    if (!Array.isArray(changes) || !Array.isArray(routes))
      throw TypeError('Original path proposal required');
    this.edited({
      based_on_proposal: proposal,
      changes: changes.map((value) => ({
        local_key: crypto.randomUUID(),
        value: snapshotObject(value),
      })),
      result_routes: routes.map(snapshotObject),
      reason: typeof payload.change_summary === 'string' ? payload.change_summary : '',
    });
  }
  dispose(): void {
    this.closed = true;
    this.controller?.abort();
    for (const controller of this.cancellationReads.values()) controller.abort();
    this.cancellationReads.clear();
    this.release();
    this.listeners.clear();
  }
}
