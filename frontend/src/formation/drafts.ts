import { uuid } from '../code-tasks/command-recovery-model.ts';
import { time, id } from '../api/decoding.ts';
/** Unsubmitted local targets only. Damaged records remain byte-for-byte untouched. */
import { exact, positiveInteger, snapshotObject } from '../api/client.ts';
import { formationSelection } from '../api/formation-workflow.ts';
import type { FormationSelection } from './workspace.ts';
type StoragePort = Pick<Storage, 'getItem' | 'setItem'>;
export type TargetDraft = Readonly<{
  schema_version: 1;
  owner_key: string;
  selection: FormationSelection;
  selection_epoch: string;
  updated_at: string;
}>;
export class FormationDrafts {
  private corrupt = false;
  private pathCorrupt = false;
  private pathDraft: unknown = null;
  private targetDraft: TargetDraft | null = null;
  private readonly key: string;
  readonly ownerKey: string;
  readonly requirementId: number;
  readonly documentId: number;
  private readonly storage: () => StoragePort;
  constructor(
    requirementId: number,
    documentId: number,
    origin: string,
    storage: () => StoragePort = () => sessionStorage,
  ) {
    this.requirementId = requirementId;
    this.documentId = documentId;
    this.storage = storage;
    positiveInteger(requirementId);
    positiveInteger(documentId);
    this.key = 'walle:v2.1:formation-draft:' + requirementId + ':' + documentId;
    this.ownerKey = JSON.stringify([origin, requirementId, documentId]);
  }
  load(): Readonly<{ target: TargetDraft | null; warning: string | null }> {
    try {
      const raw = this.storage().getItem(this.key);
      if (raw === null) return { target: null, warning: null };
      const row = exact(JSON.parse(raw), [
        'schema_version',
        'requirement_id',
        'document_id',
        'path_draft',
        'target_draft',
      ]);
      if (
        row.schema_version !== 1 ||
        row.requirement_id !== this.requirementId ||
        row.document_id !== this.documentId
      )
        throw TypeError('Draft identity differs');
      if (row.path_draft !== null) {
        const path = exact(row.path_draft, [
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
        if (
          path.schema_version !== 1 ||
          path.owner_key !== this.ownerKey ||
          !Array.isArray(path.changes) ||
          path.changes.length > 20 ||
          !Array.isArray(path.result_routes) ||
          typeof path.reason !== 'string'
        )
          throw TypeError('Route draft differs');
        id(path.base_D);
        id(path.base_F);
        id(path.base_V);
        time(path.updated_at);
        path.changes.forEach(snapshotObject);
        path.result_routes.forEach(snapshotObject);
        if (path.based_on_proposal !== null) {
          const proposal = exact(path.based_on_proposal, ['message_id', 'card_key']);
          id(proposal.message_id);
          if (typeof proposal.card_key !== 'string' || proposal.card_key.length === 0)
            throw TypeError('Proposal reference differs');
        }
      }
      this.pathDraft = row.path_draft;
      if (row.target_draft === null) return { target: null, warning: null };
      const target = exact(row.target_draft, [
        'schema_version',
        'owner_key',
        'selection',
        'selection_epoch',
        'updated_at',
      ]);
      if (
        target.schema_version !== 1 ||
        target.owner_key !== this.ownerKey ||
        typeof target.updated_at !== 'string' ||
        new Date(target.updated_at).toISOString() !== target.updated_at
      )
        throw TypeError('Target draft differs');
      uuid(target.selection_epoch);
      formationSelection(target.selection);
      this.targetDraft = snapshotObject(target) as unknown as TargetDraft;
      return { target: this.targetDraft, warning: null };
    } catch {
      this.corrupt = true;
      return { target: null, warning: '本地目标草稿无法读取，原记录保留；当前选择仅保存在此页面' };
    }
  }

  readPath(): unknown {
    return this.pathDraft;
  }
  private persist(): string | null {
    if (this.corrupt) return '原草稿无法核实，当前编辑仅保存在此页面';
    try {
      this.storage().setItem(
        this.key,
        JSON.stringify({
          schema_version: 1,
          requirement_id: this.requirementId,
          document_id: this.documentId,
          path_draft: this.pathDraft,
          target_draft: this.targetDraft,
        }),
      );
      return null;
    } catch {
      return '草稿暂存失败，当前编辑仍保留在此页面';
    }
  }
  protectPath(): void {
    this.pathCorrupt = true;
    this.corrupt = true;
  }
  clearPath(): string | null {
    this.pathCorrupt = false;
    this.pathDraft = null;
    return this.persist();
  }
  savePath(value: unknown): string | null {
    if (this.pathCorrupt) return '原路线草稿无法核实，原记录保留；请明确清除原草稿后重新暂存';
    this.pathDraft = value;
    return this.persist();
  }
  save(selection: FormationSelection | null, epoch: string): string | null {
    this.targetDraft =
      selection === null
        ? null
        : {
            schema_version: 1,
            owner_key: this.ownerKey,
            selection: formationSelection(selection),
            selection_epoch: epoch,
            updated_at: new Date().toISOString(),
          };
    return this.persist();
  }
}
