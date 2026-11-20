import { useState } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { memberDelta } from '../api/formation-history.ts';
import { FormationPage } from './page-view.tsx';
import { changeNames, historicalDescription } from './history-presentation.ts';
import type { HistoricalChange } from './history-presentation.ts';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import type { ReactNode } from 'react';
type Member = ReturnType<typeof memberDelta>;
const collectionNames = {
  GOAL_SOURCE: '目标来源',
  ISSUE_SOURCE: '问题来源',
  ISSUE_RESOLUTION_SOURCE: '问题解决来源',
  BRANCH_RESULT_SOURCE: '支线结果来源',
  ORIGIN_RANGE: '原始范围',
  CURRENT_RANGE: '当时核实范围',
  DEPENDENCY: '前置依赖',
  REPLACES: '替代步骤',
  TOPIC: '主题',
  BRANCH_TOPIC: '支线主题',
  ARTIFACT_RESULT: '覆盖成果',
} as const;
function MemberValue({
  owner,
  value,
}: Readonly<{ owner: FormationWorkspace; value: Member['before'] }>): ReactNode {
  if (value === null) return <span>无</span>;
  if (value.kind === 'REF') return <span>{value.ref}</span>;
  if (value.kind === 'SOURCE')
    return (
      <SourceReference
        label="查看原来源"
        read={(signal) => readSource(owner.requirementId, value.source_ref, owner.api, signal)}
      />
    );
  return (
    <SourceReference
      label={'版本#' + value.revision_id + ' · 区块' + value.block_id}
      read={(signal) =>
        readSource(
          owner.requirementId,
          {
            kind: 'REVISION',
            document_id: owner.documentId,
            revision_id: value.revision_id,
            block_ids: [value.block_id],
          },
          owner.api,
          signal,
        )
      }
    />
  );
}
function HistoricalMembers({
  owner,
  eventId,
  change,
}: Readonly<{ owner: FormationWorkspace; eventId: number; change: HistoricalChange }>) {
  const [open, setOpen] = useState(false);
  if (change.member_changes.count === 0) return null;
  const scope = [owner.documentId, eventId, change.ordinal, 'members'].join(':');
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>查看当时关联变化（{change.member_changes.count}）</summary>
      {open && (
        <FormationPage
          scope={scope}
          icon="history"
          empty="此项没有关联变化"
          load={(cursor, signal) =>
            owner.api.getFormationMembers(
              owner.requirementId,
              owner.documentId,
              eventId,
              change.ordinal,
              { limit: 20, ...(cursor === null ? {} : { cursor }) },
              signal,
            )
          }
          render={(row) => (
            <>
              <strong>{collectionNames[row.collection]}</strong>
              <div className="formation-history-pair">
                <div>
                  <small>变更前</small>
                  <MemberValue owner={owner} value={row.before} />
                </div>
                <div>
                  <small>变更后</small>
                  <MemberValue owner={owner} value={row.after} />
                </div>
              </div>
            </>
          )}
        />
      )}
    </details>
  );
}
function HistoryChange({
  owner,
  eventId,
  change,
}: Readonly<{ owner: FormationWorkspace; eventId: number; change: HistoricalChange }>) {
  const after = change.after;
  const sources = after !== null && 'source_refs' in after ? after.source_refs : [];
  return (
    <>
      <strong>
        {changeNames[change.entity_kind]} · {change.entity_ref}
      </strong>
      <div className="formation-history-pair">
        <div>
          <small>变更前</small>
          <p>{historicalDescription(change, 'before')}</p>
        </div>
        <div>
          <small>变更后</small>
          <p>{historicalDescription(change, 'after')}</p>
        </div>
      </div>
      {sources.map((source, index) => (
        <SourceReference
          key={index}
          label={'查看当时依据 ' + (index + 1)}
          read={(signal) => readSource(owner.requirementId, source, owner.api, signal)}
        />
      ))}
      {change.entity_kind === 'ARTIFACT_REVIEW' && change.after !== null && (
        <>
          <SourceReference
            label="查看触发复核的原回复"
            read={(signal) =>
              readSource(
                owner.requirementId,
                { kind: 'MESSAGE', message_id: change.after!.assistant_message_id },
                owner.api,
                signal,
              )
            }
          />
          <SourceReference
            label="查看当时核实的正文版本"
            read={(signal) =>
              readSource(
                owner.requirementId,
                {
                  kind: 'REVISION',
                  document_id: owner.documentId,
                  revision_id: change.after!.checked_against_revision_id,
                  block_ids: null,
                },
                owner.api,
                signal,
              )
            }
          />
        </>
      )}
      <HistoricalMembers owner={owner} eventId={eventId} change={change} />
    </>
  );
}
export function FormationEventChanges({
  owner,
  eventId,
  count,
  label = '查看当时变更',
}: Readonly<{
  owner: FormationWorkspace;
  eventId: number;
  count?: number;
  label?: string;
}>) {
  const [open, setOpen] = useState(false),
    scope = [owner.documentId, eventId, 'changes'].join(':');
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        {label}
        {count === undefined ? '' : '（' + count + '）'}
      </summary>
      {open && (
        <FormationPage
          scope={scope}
          icon="history"
          empty="此事件没有可显示的变更"
          load={(cursor, signal) =>
            owner.api.getFormationChanges(
              owner.requirementId,
              owner.documentId,
              eventId,
              { limit: 20, ...(cursor === null ? {} : { cursor }) },
              signal,
            )
          }
          render={(row) => <HistoryChange owner={owner} eventId={eventId} change={row} />}
        />
      )}
    </details>
  );
}
