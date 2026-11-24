/** Local raw fields remain drafts. Only a complete validated command can preview or save. */
import { ApiRejected, exact, snapshotObject, stableJson } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationDrafts } from './drafts.ts';
import type { FormationPathPreview } from '../api/formation-preview.ts';
import { nativeFormationCommand } from '../api/formation-commands.ts';
import { boundedText } from '../api/formation-values.ts';
import { id, time } from '../api/decoding.ts';
export const pathChangeLabels = {
  MOVE_STEP: '移动步骤',
  SET_GOAL: '修改文档目标',
  ADD_STEP: '新增步骤',
  RENAME_STEP: '修改步骤名称',
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
}>;
function captured<T extends object>(value: T): T {
  return snapshotObject(value) as T;
}
export class FormationPathEditor {
  private value: PathEditState;
  private readonly listeners = new Set<() => void>();
  private readonly owner: FormationWorkspace;
  private readonly drafts: FormationDrafts;
  private readonly release: () => void;
  private epoch = 0;
  private closed = false;
  private controller: AbortController | null = null;
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
      this.epoch++;
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
    if (this.value.changes.length === 0) return '这份草稿中没有可提交的调整';
    try {
      this.command();
      return null;
    } catch {
      return '原草稿未包含完整操作，可在对话中补充调整要求';
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
      if (this.closed || controller.signal.aborted || epoch !== this.epoch) return false;
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
  dispose(): void {
    this.closed = true;
    this.controller?.abort();
    this.release();
    this.listeners.clear();
  }
}
