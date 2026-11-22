import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { EmptyState } from '../shared/empty-state.tsx';
import { ManagementReadError } from './api.ts';
import type { PendingCommand } from './command-intent.ts';
import {
  OriginalCommand,
  usePreparation,
  useWork,
  type CommandFormProps,
} from './command-panels.tsx';
import type { environment } from './model.ts';
import type { restoreOptions, restorePlan } from './restore-model.ts';
import { Panel, ReadStatus, useRead } from './ui.tsx';

type RestorePlan = ReturnType<typeof restorePlan>;

const unavailable: Readonly<Partial<Record<ReturnType<typeof restoreOptions>['state'], string>>> = {
  SOURCE_NOT_STOPPED: '请先正常停止源环境，等待宿主核对关闭状态。',
  OPERATION_ACTIVE: '此环境仍有未决操作。请先核对原操作。',
  CAPACITY_RESERVED: '此环境仍占用运行额度。请先核对原停止操作。',
};

function shownTime(value: string) {
  return new Date(value).toLocaleString('zh-HK');
}

function RestoreComparison({ plan }: { plan: RestorePlan }) {
  return (
    <>
      <dl className="definitions">
        <div>
          <dt>选定恢复点</dt>
          <dd>
            <code>{plan.backup.id}</code>
          </dd>
        </div>
        <div>
          <dt>备份截止时间</dt>
          <dd>
            <time dateTime={plan.backup.cutoff}>{shownTime(plan.backup.cutoff)}</time>
          </dd>
        </div>
        <div>
          <dt>源数据代次</dt>
          <dd>
            <code>{plan.source.generation}</code>
          </dd>
        </div>
        <div>
          <dt>目标新数据代次</dt>
          <dd>
            <code>{plan.target.generation}</code>
          </dd>
        </div>
        <div>
          <dt>固定发布包</dt>
          <dd>
            <code>{plan.variables.target_release_ref}</code>
          </dd>
        </div>
        <div>
          <dt>计划有效至</dt>
          <dd>
            <time dateTime={plan.expires}>{shownTime(plan.expires)}</time>
          </dd>
        </div>
      </dl>
      <p>执行前会保全当前数据。恢复后的环境以选定备份为准，截止后的变更留在原代次。</p>
      <details>
        <summary>查看固定凭证</summary>
        <dl className="definitions">
          <div>
            <dt>保全点编号</dt>
            <dd>
              <code>{plan.preserved}</code>
            </dd>
          </div>
          <div>
            <dt>固定包摘要</dt>
            <dd>
              <code>{plan.manifest}</code>
            </dd>
          </div>
          <div>
            <dt>计划摘要</dt>
            <dd>
              <code>{plan.digest}</code>
            </dd>
          </div>
        </dl>
      </details>
    </>
  );
}

export function RestoreForm(props: CommandFormProps & { target: ReturnType<typeof environment> }) {
  const { target, commands, back, changed, openReceipt } = props;
  const query = useCallback(
    (signal: AbortSignal) => commands.client.restoreOptions(target.id, signal),
    [commands.client, target.id],
  );
  const state = useRead(commands.store.scopeId + '|' + target.id, query);
  const work = useWork();
  const prepare = usePreparation();
  const [selected, select] = useState('');
  const [plan, setPlan] = useState<RestorePlan | null>(null);
  const [cutoffAccepted, confirmCutoff] = useState(false);
  const [expired, setExpired] = useState(false);
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const choice = state.value?.options.find(
    (option) => option.refs.target_configuration_ref === selected,
  );
  const sameVersion =
    state.value?.recordVersion === target.recordVersion &&
    state.value.assignmentGeneration === target.generation;
  const ready =
    state.value?.state === 'READY' &&
    sameVersion &&
    commands.session.role === 'MANAGER' &&
    commands.session.phase !== 'BLOCKED' &&
    !state.waiting &&
    !state.error;

  useEffect(() => {
    if (!plan) return;
    const timer = window.setTimeout(
      () => setExpired(true),
      Math.max(0, new Date(plan.expires).getTime() - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [plan]);

  function clearPlan() {
    setPlan(null);
    confirmCutoff(false);
    setExpired(false);
  }

  function preview(event: FormEvent) {
    event.preventDefault();
    if (!ready || !choice || plan) return;
    clearPlan();
    work.run(async (signal) => {
      const proposed = await commands.client.planRestore(
        commands.session,
        {
          ...choice.refs,
          environment_id: target.id,
          expected_record_version: target.recordVersion,
          expected_assignment_generation: target.generation,
        },
        AbortSignal.any([signal, AbortSignal.timeout(20000)]),
      );
      if (
        proposed.source.generation !== target.work.generation ||
        proposed.source.deployment !== target.work.deployment ||
        proposed.source.configuration !== target.configuration ||
        proposed.source.program !== target.program ||
        proposed.backup.cutoff !== choice.cutoff ||
        proposed.backup.manifest !== choice.backupManifest ||
        proposed.backup.generation !== choice.backupGeneration
      )
        throw new ManagementReadError('RELEASE_PLAN_CHANGED', '源环境或恢复点已变化，请重新读取。');
      if (!signal.aborted) setPlan(proposed);
    });
  }

  function confirm() {
    if (
      !plan ||
      !ready ||
      !cutoffAccepted ||
      expired ||
      new Date(plan.expires).getTime() <= Date.now()
    )
      return;
    work.run(async (signal) => {
      const command = await commands.prepare(
        { action: 'RESTORE', ...plan.variables, plan_id: plan.id, plan_sha256: plan.digest },
        prepare(),
      );
      if (signal.aborted) return;
      setOriginal(command);
      changed();
      try {
        const result = await commands.dispatch(command, signal);
        if (!signal.aborted) openReceipt(result.original.id);
      } finally {
        if (!signal.aborted) changed();
      }
    });
  }

  if (original)
    return (
      <OriginalCommand {...props} original={original} performing={work.busy} notice={work.error} />
    );

  const blocked = state.value ? unavailable[state.value.state] : undefined;
  return (
    <Panel title="恢复环境" back={back} backLabel="返回环境">
      <ReadStatus state={state} />
      {work.error && (
        <p role="alert" className="feedback error">
          {work.error}
        </p>
      )}
      {work.busy && (
        <p role="status" className="feedback">
          正在核对恢复计划…
        </p>
      )}
      {state.value && !state.waiting && !state.error && (
        <>
          {!sameVersion && <p role="alert">环境登记已变化。请返回环境重新读取。</p>}
          {sameVersion && blocked && (
            <div className="feedback">
              <p>{blocked}</p>
              <button type="button" onClick={state.retry}>
                重新核对
              </button>
            </div>
          )}
          {sameVersion && state.value.state === 'NO_VERIFIED_CONFIGURATION' && (
            <EmptyState icon="history" message="此环境暂无可用的恢复配置及已核验恢复点。" />
          )}
        </>
      )}
      {state.value?.state === 'READY' && (
        <form className="card command-form" onSubmit={preview}>
          <strong>{target.name}</strong>
          <label>
            恢复点与固定发布包
            <select
              value={selected}
              onChange={(event) => {
                select(event.target.value);
                clearPlan();
              }}
              required
              disabled={!ready || work.busy || Boolean(plan)}
            >
              <option value="">请选择</option>
              {state.value.options.map((option) => (
                <option
                  key={option.refs.target_configuration_ref}
                  value={option.refs.target_configuration_ref}
                >
                  {shownTime(option.cutoff)} · {option.refs.backup_id.slice(0, 8)} ·{' '}
                  {option.refs.target_release_ref.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {!plan && (
            <button
              type="submit"
              className="command-primary"
              disabled={!ready || !choice || work.busy}
            >
              生成恢复计划
            </button>
          )}
          {plan && (
            <>
              <RestoreComparison plan={plan} />
              <label className="restore-cutoff">
                <input
                  type="checkbox"
                  checked={cutoffAccepted}
                  onChange={(event) => confirmCutoff(event.target.checked)}
                  disabled={!ready || work.busy || expired}
                />
                <span>我已核对备份截止时间，并接受仅恢复至该时间点。</span>
              </label>
              {expired && <p role="alert">恢复计划已过期，请重新生成。</p>}
              <div className="summary-line">
                <button type="button" disabled={work.busy} onClick={clearPlan}>
                  返回恢复点选择
                </button>
                <button
                  type="button"
                  className="command-primary"
                  disabled={!ready || !cutoffAccepted || work.busy || expired}
                  onClick={confirm}
                >
                  确认恢复计划
                </button>
              </div>
            </>
          )}
        </form>
      )}
    </Panel>
  );
}
