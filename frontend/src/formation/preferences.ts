import { exact, snapshotObject } from '../api/client.ts';
import { stepRef } from '../api/formation-values.ts';
export const formationTabs = ['OVERVIEW', 'RESULTS', 'ISSUES', 'BRANCHES', 'HISTORY'] as const;
export type FormationTab = (typeof formationTabs)[number];
export type FormationPreference = Readonly<{
  schema_version: 1;
  requirement_id: number;
  document_id: number;
  selected_step_ref: string | null;
  tab: FormationTab;
  show_cancelled: boolean;
  show_branches: boolean;
  scroll_anchor: string | null;
}>;
export class FormationPreferences {
  private readonly key: string;
  private readonly storage: () => Pick<Storage, 'getItem' | 'setItem'>;
  private corrupt = false;
  readonly initial: FormationPreference;
  readonly warning: string | null;
  constructor(
    requirementId: number,
    documentId: number,
    storage: () => Pick<Storage, 'getItem' | 'setItem'> = () => localStorage,
  ) {
    this.key = 'walle:v2.1:formation-view:' + requirementId + ':' + documentId;
    this.storage = storage;
    const defaults: FormationPreference = {
      schema_version: 1,
      requirement_id: requirementId,
      document_id: documentId,
      selected_step_ref: null,
      tab: 'OVERVIEW',
      show_cancelled: false,
      show_branches: true,
      scroll_anchor: null,
    };
    try {
      const raw = storage().getItem(this.key);
      if (raw === null) {
        this.initial = Object.freeze(defaults);
        this.warning = null;
        return;
      }
      const row = exact(JSON.parse(raw), Object.keys(defaults));
      if (
        row.schema_version !== 1 ||
        row.requirement_id !== requirementId ||
        row.document_id !== documentId ||
        !formationTabs.includes(row.tab as FormationTab) ||
        typeof row.show_cancelled !== 'boolean' ||
        typeof row.show_branches !== 'boolean'
      )
        throw TypeError('Formation preferences differ');
      for (const field of ['selected_step_ref', 'scroll_anchor'])
        if (row[field] !== null) stepRef(row[field]);
      this.initial = snapshotObject(row) as FormationPreference;
      this.warning = null;
    } catch {
      this.corrupt = true;
      this.initial = Object.freeze(defaults);
      this.warning = '本地主线显示设置无法读取，原记录已保留';
    }
  }
  save(value: FormationPreference): string | null {
    if (this.corrupt) return this.warning;
    try {
      this.storage().setItem(this.key, JSON.stringify(value));
      return null;
    } catch {
      return '显示设置暂存失败，当前页面的选择仍保留';
    }
  }
}
