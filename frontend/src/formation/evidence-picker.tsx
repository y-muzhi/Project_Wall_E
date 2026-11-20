import { useState } from 'react';
import type { JsonObject } from '../api/client.ts';
import { ApiUnknown, stableJson } from '../api/client.ts';
import type { FormationStepDetail } from '../api/formation-values.ts';
import type { FormationWorkspace } from './workspace.ts';
import { FormationPage } from './page-view.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import { EmptyState } from '../shared/empty-state.tsx';

export function sourceLabel(source: JsonObject): string {
  if (source.kind === 'MESSAGE') return '讨论消息 #' + source.message_id;
  if (source.kind === 'CARD_ANSWER')
    return '正式回答 #' + source.message_id + ' · ' + source.card_key;
  if (source.kind === 'REVISION')
    return '文档 #' + source.document_id + ' · 版本 #' + source.revision_id;
  if (source.kind === 'RUN_RESULT') return '运行 #' + source.guide_run_id + ' · 分析结果';
  return '运行 #' + source.guide_run_id + ' · 已携带材料 ' + source.material_ref;
}
export function stepEvidence(step: FormationStepDetail): readonly JsonObject[] {
  const sources = [
    ...step.sources
      .filter((item) => item.availability === 'AVAILABLE')
      .map((item) => item.source_ref),
    ...(step.assessment?.source_refs ?? []),
    ...(step.assessment === null
      ? []
      : [{ kind: 'MESSAGE', message_id: step.assessment.assistant_message_id }]),
  ];
  return [...new Map(sources.map((source) => [stableJson(source), source])).values()];
}
export function FormationSourceChoice({
  owner,
  source,
  selected,
  onChange,
  disabled = false,
}: Readonly<{
  owner: FormationWorkspace;
  source: JsonObject;
  selected: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}>) {
  return (
    <div className="formation-source-choice">
      <label>
        <input
          type="checkbox"
          checked={selected}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
        {sourceLabel(source)}
      </label>
      <SourceReference
        label="查看依据原文"
        read={(signal) => readSource(owner.requirementId, source, owner.api, signal)}
      />
    </div>
  );
}
const modes = { STEP: '步骤依据', MESSAGES: '讨论记录', REVISIONS: '文档版本' } as const;
export function FormationEvidencePicker({
  owner,
  step,
  values,
  onChange,
}: Readonly<{
  owner: FormationWorkspace;
  step: FormationStepDetail;
  values: readonly JsonObject[];
  onChange: (values: readonly JsonObject[]) => void;
}>) {
  const [mode, setMode] = useState<keyof typeof modes>('STEP');
  const [page, setPage] = useState(0);
  const candidates = stepEvidence(step);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(candidates.length / 20) - 1));
  const unavailable = step.sources.filter((item) => item.availability !== 'AVAILABLE');
  const choose = (source: JsonObject, checked: boolean) => {
    const key = stableJson(source);
    if (checked) {
      if (values.length < 100 && !values.some((item) => stableJson(item) === key))
        onChange([...values, source]);
    } else onChange(values.filter((item) => stableJson(item) !== key));
  };
  const render = (source: JsonObject) => {
    const selected = values.some((item) => stableJson(item) === stableJson(source));
    return (
      <FormationSourceChoice
        owner={owner}
        source={source}
        selected={selected}
        disabled={!selected && values.length >= 100}
        onChange={(checked) => choose(source, checked)}
      />
    );
  };
  return (
    <section className="formation-evidence-picker" aria-label="成果依据选择">
      <h5>依据 · 已选 {values.length} / 100</h5>
      {values.length > 0 && (
        <details>
          <summary>查看已选依据（{values.length}）</summary>
          <ul className="formation-records">
            {values.map((source) => (
              <li key={stableJson(source)!}>{render(source)}</li>
            ))}
          </ul>
        </details>
      )}
      {values.length >= 100 && <p>已达到100条上限，可先取消已选依据。</p>}
      <label>
        依据来源
        <select
          aria-label={'依据来源 ' + step.step_ref}
          value={mode}
          onChange={(event) => {
            setMode(event.currentTarget.value as keyof typeof modes);
            setPage(0);
          }}
        >
          {Object.entries(modes).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {mode === 'STEP' ? (
        <section aria-label="步骤已有依据">
          {unavailable.length > 0 && (
            <div role="status">
              <p>另有 {unavailable.length} 条步骤来源暂不可选：</p>
              <ul>
                {unavailable.map((item) => (
                  <li key={stableJson(item.source_ref)!}>
                    {sourceLabel(item.source_ref)} ·{' '}
                    {item.availability === 'MISSING' ? '来源已缺失' : '来源资源暂不支持'}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {step.assessment?.validity === 'STALE' && (
            <p>最近评估的依据已变化；选择历史来源不代表当前成果已完成。</p>
          )}
          {candidates.length === 0 ? (
            <EmptyState
              icon="document"
              message="暂无可选步骤依据，可从讨论记录或文档版本选择"
              compact
            />
          ) : (
            <>
              <ul className="formation-records">
                {candidates.slice(currentPage * 20, (currentPage + 1) * 20).map((source) => (
                  <li key={stableJson(source)!}>{render(source)}</li>
                ))}
              </ul>
              <nav className="formation-pagination" aria-label="步骤依据分页">
                <span>共 {candidates.length} 条</span>
                <button
                  type="button"
                  className="ui-button"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  上一页依据
                </button>
                <button
                  type="button"
                  className="ui-button"
                  disabled={(currentPage + 1) * 20 >= candidates.length}
                  onClick={() => setPage(currentPage + 1)}
                >
                  下一页依据
                </button>
              </nav>
            </>
          )}
        </section>
      ) : mode === 'MESSAGES' ? (
        <FormationPage
          key="messages"
          scope={owner.documentId + ':completion-messages'}
          icon="comment"
          empty="此文档暂无讨论记录"
          showTotal={false}
          load={async (cursor, signal) => {
            const response = await owner.api.listMessages(
              owner.requirementId,
              cursor === null ? null : Number(cursor),
              signal,
            );
            const pagination = response.meta.pagination;
            if (pagination === undefined || !('has_more' in pagination))
              throw new ApiUnknown(false);
            return {
              data: { items: response.data.items, total: response.data.items.length },
              meta: {
                pagination: {
                  page_size: 20,
                  has_more: pagination.has_more,
                  next_cursor:
                    pagination.next_cursor === null ? null : String(pagination.next_cursor),
                },
              },
            };
          }}
          identity={(row) => row.id}
          render={(row) => (
            <>
              <p>{row.content || '结构化讨论记录'}</p>
              {render({ kind: 'MESSAGE', message_id: row.id })}
            </>
          )}
        />
      ) : (
        <FormationPage
          key="revisions"
          scope={owner.documentId + ':completion-revisions'}
          icon="history"
          empty="此文档暂无可选版本"
          load={async (cursor, signal) => {
            const response = await owner.api.listRevisions(
              owner.requirementId,
              owner.documentId,
              cursor === null ? 1 : Number(cursor),
              signal,
            );
            const pagination = response.meta.pagination;
            if (pagination === undefined || !('total_pages' in pagination))
              throw new ApiUnknown(false);
            return {
              data: { items: response.data.items, total: pagination.total },
              meta: {
                pagination: {
                  page_size: 20,
                  has_more: pagination.page < pagination.total_pages,
                  next_cursor:
                    pagination.page < pagination.total_pages ? String(pagination.page + 1) : null,
                },
              },
            };
          }}
          identity={(row) => row.id}
          render={(row) => (
            <>
              <p>正文 V{row.source_content_version}</p>
              {render({
                kind: 'REVISION',
                document_id: owner.documentId,
                revision_id: row.id,
                block_ids: null,
              })}
            </>
          )}
        />
      )}
    </section>
  );
}
