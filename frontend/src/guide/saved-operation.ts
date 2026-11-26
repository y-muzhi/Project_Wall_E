import type { GuideOperationReceipt } from '../api/models.ts';
import type { Revision } from '../revisions/read.ts';
import type { WalleApi } from '../api/walle.ts';
import { compareRevisionBlocks } from '../revisions/changes.ts';
import type { RevisionChange } from '../revisions/changes.ts';

export type OperationDetailKind = 'VERSION' | 'COMPARE';
export type OperationDetail =
  | Readonly<{ kind: 'VERSION'; saved: Revision }>
  | Readonly<{
      kind: 'COMPARE';
      base: Revision;
      saved: Revision;
      changes: readonly RevisionChange[];
    }>;

export type OperationReadApi = Pick<
  WalleApi,
  'getGuideRun' | 'getRevision' | 'listRevisions' | 'revisionBlocks'
>;

export async function readOperationDetail(
  api: OperationReadApi,
  requirement: number,
  receipt: GuideOperationReceipt,
  kind: OperationDetailKind,
  signal: AbortSignal,
): Promise<OperationDetail> {
  const { data: run } = await api.getGuideRun(receipt.run_id, signal);
  if (run.id !== receipt.run_id || run.requirement_id !== requirement)
    throw Error('运行归属不匹配');

  const { document_effect: effect } = run;
  if (
    receipt.state !== 'SAVED' ||
    run.application_result !== 'APPLIED' ||
    !effect ||
    effect.document_id !== receipt.document_id ||
    effect.after_content_version !== receipt.saved_content_version ||
    effect.before_content_version !== receipt.base_content_version
  )
    throw Error('无法核实本次保存的版本');

  async function revision(id: number, version: number, document: number) {
    const { data } = await api.getRevision(id, signal);
    if (
      data.requirement_id !== requirement ||
      data.document_id !== document ||
      data.source_content_version !== version
    )
      throw Error('版本归属不匹配');
    return data;
  }

  const saved = await revision(
    effect.revision_id,
    effect.after_content_version,
    effect.document_id,
  );
  if (kind === 'VERSION') return { kind, saved };
  const baseVersion = effect.before_content_version;
  if (baseVersion === null) throw Error('本次创建没有基准版本');
  for (let page = 1; ; page++) {
    const { data: versions, meta } = await api.listRevisions(
      requirement,
      saved.document_id,
      page,
      signal,
    );
    const pagination = meta.pagination;
    if (!pagination || !('page' in pagination) || pagination.page !== page)
      throw Error('版本分页不匹配');
    const match = versions.items.find((entry) => entry.source_content_version === baseVersion);
    if (match) {
      const base = await revision(match.id, baseVersion, saved.document_id);
      return {
        kind,
        base,
        saved,
        changes: compareRevisionBlocks(api.revisionBlocks(base), api.revisionBlocks(saved)),
      };
    }
    if (page >= pagination.total_pages) throw Error('找不到本次保存的基准版本');
  }
}
