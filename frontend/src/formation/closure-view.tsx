import { useState } from 'react';
import { ApiUnknown } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import type { FormationWorkspace } from './workspace.ts';
import { FormationPage } from './page-view.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import { branchLabels, issueLabels } from './labels.ts';
type ClosureRow = Awaited<ReturnType<WalleApi['getFormationClosure']>>['data']['items'][number];
type Evidence = Awaited<
  ReturnType<WalleApi['getFormationClosureEvidence']>
>['data']['items'][number];
type Kind = 'RESULT' | 'ISSUE' | 'BRANCH';
const kinds = ['RESULT', 'ISSUE', 'BRANCH'] as const;
const names = { RESULT: '成果', ISSUE: '问题', BRANCH: '支线' } as const;
const statuses = { LANDED: '已落入文档', ANALYZED: '已形成分析', OUTSTANDING: '尚未完成' } as const;
const dispositions = {
  KEEP_OPEN: '继续开放',
  TRANSFER: '转交其他步骤',
  DEFERRED: '暂缓',
  DROPPED: '放弃',
  RESOLVED: '已解决',
} as const;
function EvidenceView({
  owner,
  eventId,
  kind,
  itemRef,
}: Readonly<{ owner: FormationWorkspace; eventId: number; kind: Kind; itemRef: string }>) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>查看结束时的证据</summary>
      {open && (
        <FormationPage<Evidence>
          scope={[eventId, kind, itemRef].join(':')}
          icon="history"
          empty="暂无结束证据"
          load={(cursor, signal) =>
            owner.api.getFormationClosureEvidence(
              owner.requirementId,
              owner.documentId,
              eventId,
              kind,
              itemRef,
              { limit: 20, ...(cursor === null ? {} : { cursor }) },
              signal,
            )
          }
          render={(row) =>
            row.kind === 'SOURCE' ? (
              <SourceReference
                label="查看原来源"
                read={(signal) =>
                  readSource(owner.requirementId, row.source_ref, owner.api, signal)
                }
              />
            ) : row.kind === 'RANGE' ? (
              <p>
                原关联 {row.artifact_ref} · {row.role === 'ORIGIN' ? '原始范围' : '复核时范围'} ·
                区块 {row.block_id}
              </p>
            ) : (
              <p>
                关联 {row.artifact_ref} ·{' '}
                {row.freshness === 'CURRENT'
                  ? '当时有效'
                  : row.freshness === 'NEEDS_REVIEW'
                    ? '当时待复核'
                    : '当时已移除'}{' '}
                · 范围 {row.range_count}
              </p>
            )
          }
        />
      )}
    </details>
  );
}
export function FormationClosure({
  owner,
  eventId,
}: Readonly<{ owner: FormationWorkspace; eventId: number }>) {
  const [open, setOpen] = useState(false),
    [kind, setKind] = useState<Kind>('RESULT');
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>查看完整结束记录</summary>
      {open && (
        <>
          <label>
            记录类型
            <select
              aria-label="记录类型"
              value={kind}
              onChange={(event) => setKind(event.target.value as Kind)}
            >
              {kinds.map((value) => (
                <option key={value} value={value}>
                  {names[value]}
                </option>
              ))}
            </select>
          </label>
          <FormationPage<ClosureRow>
            key={kind}
            scope={[eventId, kind].join(':')}
            icon="history"
            empty={'结束时没有' + names[kind] + '记录'}
            load={(cursor, signal) =>
              owner.api.getFormationClosure(
                owner.requirementId,
                owner.documentId,
                eventId,
                kind,
                { limit: 20, ...(cursor === null ? {} : { cursor }) },
                signal,
              )
            }
            render={(row) => (
              <>
                <strong>{row.description}</strong>
                {row.kind === 'RESULT' ? (
                  <p>
                    {statuses[row.status]} · 关联 {row.artifact_count} · 范围 {row.range_count} ·
                    来源 {row.source_count}
                  </p>
                ) : (
                  <>
                    <p>
                      结束时
                      {
                        (row.kind === 'ISSUE' ? issueLabels : branchLabels)[row.state_at_close]
                      } · {dispositions[row.disposition]}
                      {row.to_step_ref === null ? '' : ' · 转至 ' + row.to_step_ref}
                    </p>
                    {row.reason && <p>{row.reason}</p>}
                  </>
                )}
                {row.evidence_count > 0 && (
                  <EvidenceView
                    owner={owner}
                    eventId={eventId}
                    kind={kind}
                    itemRef={row.kind === 'RESULT' ? row.result_ref : row.ref}
                  />
                )}
              </>
            )}
          />
        </>
      )}
    </details>
  );
}

/** A result definition has at most20 members: one bounded original result page. */
export function FormationClosureResults({
  owner,
  eventId,
  resultKind,
}: Readonly<{
  owner: FormationWorkspace;
  eventId: number;
  resultKind: 'CONTENT' | 'ANALYSIS';
}>) {
  const [open, setOpen] = useState(false);
  type ResultRow = Extract<ClosureRow, { kind: 'RESULT' }>;
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>查看结束时的成果记录</summary>
      {open && (
        <FormationPage<ResultRow>
          key={[eventId, resultKind].join(':')}
          scope={[eventId, resultKind, 'results'].join(':')}
          icon="history"
          empty={resultKind === 'ANALYSIS' ? '结束时未设置分析类成果' : '结束时未设置文档类成果'}
          load={async (cursor, signal) => {
            if (cursor !== null) throw new ApiUnknown(false);
            const result = await owner.api.getFormationClosure(
              owner.requirementId,
              owner.documentId,
              eventId,
              'RESULT',
              { limit: 20 },
              signal,
            );
            if (
              result.meta.pagination.has_more ||
              result.data.total > 20 ||
              result.data.items.length !== result.data.total
            )
              throw new ApiUnknown(false);
            const items = result.data.items.filter(
              (row): row is ResultRow => row.kind === 'RESULT' && row.result_kind === resultKind,
            );
            return { ...result, data: { ...result.data, items, total: items.length } };
          }}
          render={(row) => (
            <>
              <strong>{row.description}</strong>
              <p>
                {statuses[row.status]} · 来源 {row.source_count} 条
              </p>
              {row.evidence_count > 0 && (
                <EvidenceView
                  owner={owner}
                  eventId={eventId}
                  kind="RESULT"
                  itemRef={row.result_ref}
                />
              )}
            </>
          )}
        />
      )}
    </details>
  );
}
