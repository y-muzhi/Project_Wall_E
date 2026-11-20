import { useState } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { RemainingChoices, RemainingDisposition } from './completion-state.ts';
import { changeRemaining } from './completion-state.ts';
import { FormationNextStep } from './next-step-view.tsx';
import { FormationPage } from './page-view.tsx';
function DispositionFields({
  owner,
  step,
  refId,
  description,
  values,
  onChange,
}: Readonly<{
  owner: FormationWorkspace;
  step: string;
  refId: string;
  description: string;
  values: RemainingChoices;
  onChange: (values: RemainingChoices) => void;
}>) {
  const selected = values[refId],
    full = selected === undefined && Object.keys(values).length >= 20;
  const update = (value: Partial<RemainingDisposition>) => {
    if (selected !== undefined) onChange({ ...values, [refId]: { ...selected, ...value } });
  };
  return (
    <div className="formation-disposition">
      <strong>{description}</strong>
      <label>
        遗留处理
        <select
          aria-label={'遗留处理 ' + refId}
          value={selected?.disposition ?? 'KEEP_OPEN'}
          disabled={full}
          onChange={(event) =>
            onChange(
              changeRemaining(
                values,
                refId,
                event.target.value as RemainingDisposition['disposition'] | 'KEEP_OPEN',
              ),
            )
          }
        >
          <option value="KEEP_OPEN">保持开放</option>
          <option value="TRANSFER">转交其他步骤</option>
          <option value="DEFERRED">暂缓</option>
          <option value="DROPPED">放弃</option>
        </select>
      </label>
      {full && <p>本次已选择20项，其余保持开放；可先移除已选处理。</p>}
      {selected?.disposition === 'TRANSFER' && (
        <FormationNextStep
          owner={owner}
          current={step}
          value={selected.to_step_ref}
          label="转交到步骤"
          allowKeep={false}
          onChange={(ref) => update({ to_step_ref: ref })}
        />
      )}
      {selected !== undefined && selected.disposition !== 'TRANSFER' && (
        <label>
          处理原因
          <textarea
            aria-label={'处理原因 ' + refId}
            maxLength={2000}
            value={selected.reason ?? ''}
            onChange={(event) => update({ reason: event.target.value })}
          />
        </label>
      )}
    </div>
  );
}
export function FormationCompletionDispositions({
  owner,
  step,
  issues,
  branches,
  onIssues,
  onBranches,
}: Readonly<{
  owner: FormationWorkspace;
  step: string;
  issues: RemainingChoices;
  branches: RemainingChoices;
  onIssues: (values: RemainingChoices) => void;
  onBranches: (values: RemainingChoices) => void;
}>) {
  const [open, setOpen] = useState(false);
  const f = owner.read.getSnapshot().summary.data?.formation_version;
  if (f === null || f === undefined) return null;
  const scope = [owner.documentId, step, f, 'completion'].join(':');
  const query = (cursor: string | null) => ({
    limit: 20,
    known_f: f,
    step_ref: step,
    state: 'OPEN' as const,
    ...(cursor === null ? {} : { cursor }),
  });
  return (
    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>高级遗留处置（可选）</summary>
      <p>未明确处理的事项保持开放；每类最多处置20项。翻页不会移除已选处理。</p>
      {open && (
        <>
          <section aria-label="结束时处理问题">
            <h4>开放问题 · 已选 {Object.keys(issues).length} 项</h4>
            <FormationPage
              key={scope + ':issues'}
              scope={scope + ':issues'}
              icon="comment"
              empty="本步骤没有开放问题"
              onPathChanged={() => void owner.refresh()}
              load={(cursor, signal) =>
                owner.api.getFormationIssues(
                  owner.requirementId,
                  owner.documentId,
                  query(cursor),
                  signal,
                )
              }
              render={(row) => (
                <DispositionFields
                  owner={owner}
                  step={step}
                  refId={row.issue_ref}
                  description={row.description}
                  values={issues}
                  onChange={onIssues}
                />
              )}
            />
          </section>
          <section aria-label="结束时处理支线">
            <h4>开放支线 · 已选 {Object.keys(branches).length} 项</h4>
            <FormationPage
              key={scope + ':branches'}
              scope={scope + ':branches'}
              icon="outline"
              empty="本步骤没有开放支线"
              onPathChanged={() => void owner.refresh()}
              load={(cursor, signal) =>
                owner.api.getFormationBranches(
                  owner.requirementId,
                  owner.documentId,
                  query(cursor),
                  signal,
                )
              }
              render={(row) => (
                <DispositionFields
                  owner={owner}
                  step={step}
                  refId={row.branch_ref}
                  description={row.question}
                  values={branches}
                  onChange={onBranches}
                />
              )}
            />
          </section>
        </>
      )}
    </details>
  );
}
