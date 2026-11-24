import { useState } from 'react';
import type { ProgressBrief } from '../api/models.ts';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import { FormationPage } from './page-view.tsx';
import { FormationReadSources } from './source-list.tsx';
import type { FormationWorkspace } from './workspace.ts';

type Group = 'decisions' | 'issues';
function entries(brief: ProgressBrief, group: Group) {
  return group === 'decisions'
    ? brief.decisions.map((row) => ({
        ref: row.evidence_ref,
        text: row.text,
        writing: row.writing,
        sources: row.source_refs,
      }))
    : brief.issues.map((row) => ({
        ref: row.issue_ref,
        text: row.question,
        writing: null,
        sources: row.source_refs,
      }));
}

export function ProgressGroup({
  owner,
  brief,
  group,
  stepRef,
}: Readonly<{
  owner: FormationWorkspace;
  brief: ProgressBrief;
  group: Group;
  stepRef?: string | null;
}>) {
  const [expanded, setExpanded] = useState(false);
  const decisions = group === 'decisions';
  const title = decisions ? '已经确定' : '还有待定';
  const total = decisions ? brief.decision_total : brief.issue_total;
  const items = entries(brief, group);
  if (total === 0) return null;
  const render = (row: (typeof items)[number]) => (
    <>
      {row.text}
      {row.writing && row.writing.state !== 'FAILED' && (
        <FormationReadSources
          owner={owner}
          sources={row.writing.source_refs.filter((source) => source.kind === 'REVISION')}
          label={
            row.writing.state === 'HISTORICAL'
              ? '曾写入 V' + row.writing.version
              : '当前正文含此结论（写入 V' + row.writing.version + '）'
          }
        />
      )}
      {row.writing?.source_refs.some((source) => source.kind === 'MESSAGE') && (
        <FormationReadSources
          owner={owner}
          sources={row.writing.source_refs.filter((source) => source.kind === 'MESSAGE')}
          label="最近一次正文写入失败"
        />
      )}
      {row.sources.length > 0 && (
        <FormationReadSources
          owner={owner}
          sources={row.sources}
          label={decisions ? '结论依据' : '问题来源'}
        />
      )}
    </>
  );
  const load = async (cursor: string | null, signal: AbortSignal) => {
    const response = await owner.api.getRequirementDetail(
      owner.requirementId,
      signal,
      true,
      owner.documentId,
      20,
      { group, cursor, ...(stepRef !== undefined ? { stepRef } : {}) },
    );
    const page =
      stepRef !== undefined
        ? response.data.discussion?.view_progress
        : response.data.discussion?.progress_brief;
    if (!page || page.document_id !== brief.document_id) throw new ApiUnknown(false);
    if (
      page.discussion_version !== brief.discussion_version ||
      page.formation_version !== brief.formation_version ||
      page.revision_id !== brief.revision_id
    )
      throw new ApiRejected(
        'STATE_CONFLICT',
        '讨论进展已更新，正在读取最新记录',
        { reason: 'PATH_CHANGED' },
        response.meta.request_id,
        409,
      );
    const next = decisions ? page.decision_next_cursor : page.issue_next_cursor;
    return {
      data: { items: entries(page, group), total },
      meta: { pagination: { next_cursor: next, has_more: next !== null, page_size: 20 } },
    };
  };
  return (
    <section aria-label={title}>
      <h3>{title}</h3>
      {expanded ? (
        <FormationPage
          scope={group}
          load={load}
          identity={(row) => row.ref}
          render={render}
          icon="document"
          empty={decisions ? '暂无已定结论' : '暂无待定问题'}
          compactControls
          onPathChanged={() => void owner.refresh(false)}
        />
      ) : (
        <ul>
          {items.map((row) => (
            <li key={row.ref}>{render(row)}</li>
          ))}
        </ul>
      )}
      {total > items.length && (
        <button
          type="button"
          className="ui-button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? '收起' : '查看全部'}
          {decisions ? '结论' : '待定问题'}（{total}）
        </button>
      )}
    </section>
  );
}

export function ViewedProgress({
  owner,
  stepRef,
}: Readonly<{ owner: FormationWorkspace; stepRef: string | null }>) {
  const scope = [
    owner.documentId,
    stepRef ?? 'document',
    owner.discussionVersion,
    owner.revisionId,
    owner.read.getSnapshot().summary.data?.formation_version,
  ].join('/');
  return (
    <FormationPage
      key={scope}
      scope={scope}
      compactControls
      showTotal={false}
      icon="document"
      empty={stepRef ? '此步骤暂无已定结论或待定问题' : '暂无文档级结论或待定问题'}
      load={async (_, signal) => {
        const response = await owner.api.getRequirementDetail(
          owner.requirementId,
          signal,
          true,
          owner.documentId,
          3,
          { group: 'decisions', cursor: null, stepRef },
        );
        const brief = response.data.discussion?.view_progress;
        if (!brief || (brief.focus?.step_ref ?? null) !== stepRef) throw new ApiUnknown(false);
        const items = brief.decision_total || brief.issue_total ? [brief] : [];
        return {
          data: { items, total: items.length },
          meta: { pagination: { next_cursor: null, has_more: false, page_size: 1 } },
        };
      }}
      identity={(brief) => String(brief.document_id)}
      render={(brief) => (
        <>
          <ProgressGroup owner={owner} brief={brief} stepRef={stepRef} group="decisions" />
          <ProgressGroup owner={owner} brief={brief} stepRef={stepRef} group="issues" />
        </>
      )}
    />
  );
}
