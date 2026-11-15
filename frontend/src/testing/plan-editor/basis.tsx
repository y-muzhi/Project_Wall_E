import { useCallback, useRef, useState } from 'react';
import type { WalleApi } from '../../api/walle.ts';
import { optionPage, PagedTaskSelect } from '../../code-tasks/create-selection.tsx';
import { useSettingsVisibility } from '../../code-tasks/settings/read.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { ReadState, useTestingRead } from '../plans/read.tsx';
import type { Behavior, Draft, Source } from './draft.ts';

type SourceUsage = 'MAIN' | 'MATERIAL';
function RevisionChoice({
  api,
  requirement,
  document,
  usage,
  value,
  change,
  disabled,
  confirmed,
}: Readonly<{
  api: WalleApi;
  requirement: number;
  document: number;
  usage: SourceUsage;
  value: number | null;
  change(value: number | null): void;
  disabled: boolean;
  confirmed: boolean;
}>) {
  const visible = useSettingsVisibility();
  const load = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.codeDesignRevisions(document, usage, page, signal), (row) => ({
        id: row.revision_id,
        label: '版本 ' + row.version_no + (row.eligible ? ' · 已确认' : ' · 待确认或正文为空'),
        disabled:
          row.requirement_id !== requirement ||
          row.reason_code === 'UNAVAILABLE' ||
          (confirmed && !row.eligible),
      })),
    [api, document, requirement, usage, confirmed],
  );
  return (
    <PagedTaskSelect
      label={usage === 'MAIN' ? '固定主 Revision' : '固定材料 Revision'}
      load={load}
      visible={visible}
      disabled={disabled}
      value={value}
      change={change}
    />
  );
}

type DraftBasis = Pick<
  Draft,
  'requirement_id' | 'document_id' | 'design_revision_id' | 'material_refs'
>;
export function PlanBasis<T extends DraftBasis>({
  api,
  draft,
  frozen,
  disabled,
  change,
  confirmed = false,
}: Readonly<{
  api: WalleApi;
  draft: T;
  frozen: boolean;
  disabled: boolean;
  change(value: T): void;
  confirmed?: boolean;
}>) {
  const [material, setMaterial] = useState<{ document: number; revision: number | null } | null>(
    null,
  );
  const visible = useSettingsVisibility();
  const requirements = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.listRequirements({ page }, signal), (row) => ({
        id: row.id,
        label: row.requirement_no + ' · ' + row.title,
      })),
    [api],
  );
  const requirementId = draft.requirement_id;
  const load = useCallback(
    (signal: AbortSignal) => api.getRequirementDetail(requirementId!, signal),
    [api, requirementId],
  );
  const detail = useTestingRead(
    'plan-source:' + requirementId,
    requirementId === null || frozen ? null : load,
  );
  const documents =
    detail.data?.data.documents.filter((row) => row.document_type === 'CURRENT') ?? [];
  const primary = documents.some((row) => row.id === draft.document_id) ? draft.document_id : null;
  const choices = documents.filter(
    (row) => row.id !== primary && !draft.material_refs.some((item) => item.document_id === row.id),
  );
  const chosenMaterial = choices.find((row) => row.id === material?.document) ?? null;

  function chooseRequirement(value: number | null) {
    setMaterial(null);
    change({
      ...draft,
      requirement_id: value,
      document_id: null,
      design_revision_id: null,
      material_refs: [],
    });
  }
  function choosePrimary(value: number | null) {
    setMaterial(null);
    change({
      ...draft,
      document_id: value,
      design_revision_id: null,
      material_refs: draft.material_refs.filter((item) => item.document_id !== value),
    });
  }
  function addMaterial() {
    if (
      disabled ||
      material?.revision == null ||
      chosenMaterial === null ||
      draft.material_refs.length >= 256
    )
      return;
    change({
      ...draft,
      material_refs: [
        ...draft.material_refs,
        { document_id: chosenMaterial.id, revision_id: material.revision },
      ],
    });
    setMaterial(null);
  }
  return (
    <section className="testing-editor-panel" aria-label="固定测试依据">
      <h4>固定测试依据</h4>
      {frozen ? (
        <p>
          需求 #{requirementId} · 主文档 #{draft.document_id} · 固定版本 #{draft.design_revision_id}
        </p>
      ) : (
        <>
          <PagedTaskSelect
            label="依据需求"
            load={requirements}
            value={requirementId}
            change={chooseRequirement}
            visible={visible}
            disabled={disabled}
          />
          {requirementId !== null && (
            <>
              <ReadState
                loading={detail.loading}
                error={detail.error}
                stale={detail.data !== null}
                retry={detail.reload}
              />
              {detail.data && documents.length === 0 && !detail.loading && !detail.error && (
                <EmptyState icon="outline" message="所选需求没有可用工作文档" compact />
              )}
              {documents.length > 0 && (
                <label>
                  主设计文档{' '}
                  <select
                    value={primary ?? ''}
                    disabled={disabled || detail.loading || detail.error !== null}
                    onChange={(event) =>
                      choosePrimary(
                        event.currentTarget.value ? Number(event.currentTarget.value) : null,
                      )
                    }
                  >
                    <option value="">请选择主文档</option>
                    {documents.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {primary !== null && (
                <RevisionChoice
                  key={primary}
                  api={api}
                  requirement={requirementId}
                  document={primary}
                  usage="MAIN"
                  confirmed={confirmed}
                  value={draft.design_revision_id}
                  disabled={disabled}
                  change={(revision) => change({ ...draft, design_revision_id: revision })}
                />
              )}
            </>
          )}
          {primary !== null && requirementId !== null && choices.length > 0 && (
            <div className="testing-editor-panel">
              <label>
                附加材料文档{' '}
                <select
                  value={chosenMaterial?.id ?? ''}
                  disabled={disabled}
                  onChange={(event) =>
                    setMaterial(
                      event.currentTarget.value
                        ? { document: Number(event.currentTarget.value), revision: null }
                        : null,
                    )
                  }
                >
                  <option value="">请选择材料</option>
                  {choices.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              {chosenMaterial && (
                <RevisionChoice
                  key={chosenMaterial.id}
                  api={api}
                  requirement={requirementId}
                  document={chosenMaterial.id}
                  usage="MATERIAL"
                  confirmed={confirmed}
                  value={material?.revision ?? null}
                  disabled={disabled}
                  change={(revision) => setMaterial({ document: chosenMaterial.id, revision })}
                />
              )}
              <div className="code-settings-form-actions">
                <button
                  className="ui-button"
                  type="button"
                  disabled={
                    disabled || material?.revision == null || draft.material_refs.length >= 256
                  }
                  title={
                    material?.revision == null
                      ? '请先选择材料及固定版本'
                      : draft.material_refs.length >= 256
                        ? '已达材料数量上限'
                        : undefined
                  }
                  onClick={addMaterial}
                >
                  加入固定材料
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {draft.material_refs.length > 0 && (
        <ul>
          {draft.material_refs.map((item) => (
            <li key={item.document_id} className="code-settings-form-actions">
              <span>
                {documents.find((row) => row.id === item.document_id)?.name ??
                  '文档 #' + item.document_id}{' '}
                · 固定版本 #{item.revision_id}
              </span>
              {!frozen && (
                <button
                  type="button"
                  className="ui-button"
                  disabled={disabled}
                  onClick={() =>
                    change({
                      ...draft,
                      material_refs: draft.material_refs.filter(
                        (row) => row.document_id !== item.document_id,
                      ),
                    })
                  }
                >
                  移除此材料
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function draftSources(draft: Draft): readonly Source[] {
  const primary =
    draft.document_id !== null && draft.design_revision_id !== null
      ? [{ document_id: draft.document_id, revision_id: draft.design_revision_id }]
      : [];
  return [...primary, ...draft.material_refs];
}

export function QuotePicker({
  api,
  requirement,
  sources,
  added,
  refs,
  disabled,
}: Readonly<{
  api: WalleApi;
  requirement: number;
  sources: readonly Source[];
  refs: Behavior['basis_refs'];
  added(value: Behavior['basis_refs'][number]): void;
  disabled: boolean;
}>) {
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const source = sources.find((item) => item.revision_id === revision) ?? null;
  const document = source?.document_id ?? null;
  const revisionId = source?.revision_id ?? null;
  const load = useCallback(
    async (signal: AbortSignal) => {
      const result = await api.getRevision(revisionId!, signal);
      if (result.data.requirement_id !== requirement || result.data.document_id !== document)
        throw new TypeError('Original Revision owner differs');
      return result.data.markdown_content;
    },
    [api, revisionId, requirement, document],
  );
  const reading = useTestingRead('quote:' + revisionId, revisionId === null ? null : load);

  function addQuote() {
    const control = textarea.current;
    if (control === null || source === null || reading.data === null || disabled || reading.error)
      return;
    const quote = reading.data.slice(control.selectionStart, control.selectionEnd);
    if (!quote.trim() || [...quote].length > 4096) {
      setError('请选择 1 到 4096 个原文字符');
      return;
    }
    if (
      refs.length >= 256 ||
      refs.some(
        (ref) =>
          ref.document_id === source.document_id &&
          ref.revision_id === source.revision_id &&
          ref.quote === quote,
      )
    ) {
      setError('引用已存在，或此行为已达引用数量上限');
      return;
    }
    setError(null);
    added({ ...source, quote });
  }
  return (
    <div className="testing-editor-panel">
      <label>
        引用来源{' '}
        <select
          value={revisionId ?? ''}
          disabled={disabled}
          onChange={(event) => {
            setRevision(event.currentTarget.value ? Number(event.currentTarget.value) : null);
            setError(null);
          }}
        >
          <option value="">请选择固定版本</option>
          {sources.map((item) => (
            <option key={item.revision_id} value={item.revision_id}>
              文档 #{item.document_id} · 版本 #{item.revision_id}
            </option>
          ))}
        </select>
      </label>
      <ReadState
        loading={reading.loading}
        error={reading.error}
        stale={reading.data !== null}
        retry={reading.reload}
      />
      {reading.data === '' && !reading.loading && !reading.error && (
        <EmptyState icon="outline" message="所选版本原文为空" compact />
      )}
      {reading.data && (
        <label>
          原文选段 <textarea ref={textarea} readOnly value={reading.data} rows={5} />
        </label>
      )}
      {reading.data && (
        <div className="code-settings-form-actions">
          <button
            type="button"
            className="ui-button"
            disabled={disabled || reading.loading || !!reading.error}
            onClick={addQuote}
          >
            加入所选原文
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
    </div>
  );
}
