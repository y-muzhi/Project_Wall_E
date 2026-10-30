import { useState, useSyncExternalStore } from 'react';
import type { RequirementLifecycle, LifecycleOutcome, LifecycleOperation } from './lifecycle.ts';
import { requirementStatuses } from '../api/models.ts';
import { SingleSelect } from '../shared/single-select.tsx';
import { REQUIREMENT_STATUS_LABELS } from '../shared/status-labels.ts';

export function RequirementLifecycleControl(
  props: Readonly<{
    flow: RequirementLifecycle;
    blocked: boolean;
    writeReady?: boolean;
    changed(outcome: LifecycleOutcome): void | Promise<void>;
  }>,
) {
  const state = useSyncExternalStore(props.flow.subscribe, props.flow.getSnapshot),
    [refreshError, setRefreshError] = useState<string | null>(null);
  const busy = ['SUBMITTING', 'READING'].includes(state.phase);
  const adopt = async () => {
    const outcome = props.flow.getSnapshot().outcome;
    if (!outcome) return;
    try {
      await props.changed(outcome);
      setRefreshError(null);
    } catch {
      setRefreshError('状态已保存，暂时无法读取最新详情');
    }
  };
  const select = async (value: string) => {
    if (await props.flow.select(value as LifecycleOperation)) await adopt();
  };
  return (
    <div className="requirement-lifecycle-control">
      <SingleSelect
        label="需求状态"
        value={state.actual.status}
        options={requirementStatuses.map((value) => ({
          value,
          label: REQUIREMENT_STATUS_LABELS[value],
        }))}
        disabled={
          props.blocked ||
          props.writeReady === false ||
          busy ||
          ['UNKNOWN', 'CONFIRMED'].includes(state.phase)
        }
        change={(value) => void select(value)}
      />
      {busy && <span role="status">正在保存状态…</span>}
      {state.phase === 'UNKNOWN' && (
        <button
          className="ui-button"
          type="button"
          disabled={busy || props.blocked}
          onClick={() =>
            void props.flow.retryUnknown().then(async (confirmed) => {
              if (confirmed) await adopt();
            })
          }
        >
          核实状态变更
        </button>
      )}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
        </p>
      )}
      {refreshError && (
        <>
          <p role="alert" className="inline-error">
            {refreshError}
          </p>
          <button className="ui-button" type="button" onClick={() => void adopt()}>
            重新读取详情
          </button>
        </>
      )}
    </div>
  );
}
