import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { EmptyState } from '../shared/empty-state.tsx';
import { ManagementReadError } from './api.ts';
import { ManagementCommands, newPreparationKeys, type PreparationKeys } from './command-owner.ts';
import { ManagementStorageError } from './command-store.ts';
import {
  commandIntent,
  recoverIntent,
  type ManagementControl,
  type EnvironmentAction,
  type PendingCommand,
} from './command-intent.ts';
import type { candidateCatalog, environment } from './model.ts';
import { Panel, ReadStatus, useRead } from './ui.tsx';
import type { ReleaseAction, releasePlan, ReleaseSelection } from './release-model.ts';
import type { backupPlan } from './backup-model.ts';

type Candidate = ReturnType<typeof candidateCatalog>[number];
type Environment = ReturnType<typeof environment>;
type Common = Readonly<{
  commands: ManagementCommands;
  back: () => void;
  changed: () => void;
  openReceipt: (operationId: string) => void;
}>;

export type CommandFormProps = Common;

const states: Readonly<Record<Candidate['state'], string>> = {
  READY: '已核对，可登记',
  REATTACH_READY: '原环境已核对，可重新登记',
  EVIDENCE_REQUIRED: '等待宿主核对',
  REGISTERED: '已登记',
  BLOCKED: '仍有未决操作',
};
const titles: Readonly<Record<PendingCommand['action'], string>> = {
  ATTACH: '环境登记',
  REGISTER_DELIVERY: '交付登记',
  RELEASE: '固定发布',
  ROLLBACK_CODE: '程序回退',
  RECONFIGURE: '切换配置',
  BACKUP: '独立备份',
  RESTORE: '恢复环境',
  START: '普通启动',
  STOP: '正常停止',
  ARCHIVE: '归档环境',
  RECONCILE: '原结果核对',
  CANCEL: '原操作撤回',
  CONTINUE: '原启动额度复核',
};

export function commandReason(code: string | null) {
  return (
    (
      {
        MANAGEMENT_ACCESS_DENIED: '当前账号没有写入权限。',
        MANAGEMENT_RESOURCE_UNVERIFIED: '宿主尚未核对可登记资源。',
        MANAGEMENT_OPERATION_CONFLICT: '该环境仍有未决操作。',
        ACTION_NOT_AVAILABLE: '当前环境尚未准入此动作。',
      } as Readonly<Record<string, string>>
    )[code ?? ''] ?? '该操作当前不可用。'
  );
}

export function useWork() {
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  function run(work: (signal: AbortSignal) => Promise<void>) {
    if (active.current) return;
    const owner = new AbortController();
    active.current = owner;
    setError(null);
    setBusy(true);
    void work(owner.signal)
      .catch((failure: unknown) => {
        if (owner.signal.aborted) return;
        if (failure instanceof ManagementStorageError || failure instanceof ManagementReadError) {
          setError(failure.message);
        } else if (failure instanceof TypeError) {
          setError('无法完成当前操作。请核对输入或网络，已有原键仍可查询。');
        } else {
          setError('未能确认本次结果，请先查询原请求。');
        }
      })
      .finally(() => {
        if (active.current === owner) active.current = null;
        if (!owner.signal.aborted) setBusy(false);
      });
  }
  return { busy, error, run };
}

export function usePreparation() {
  const keys = useRef<PreparationKeys | null>(null);
  return () => {
    keys.current ??= newPreparationKeys();
    return keys.current;
  };
}

function isPrepared(candidate: Candidate) {
  return candidate.state === 'READY' || candidate.state === 'REATTACH_READY';
}

export function AttachForm(props: Common & { archivedEnvironment: string | undefined }) {
  const { commands, back, changed, openReceipt, archivedEnvironment } = props;
  const query = useCallback(
    (signal: AbortSignal) => commands.client.catalog(signal, archivedEnvironment),
    [commands.client, archivedEnvironment],
  );
  const state = useRead(commands.store.scopeId + '|' + (archivedEnvironment ?? ''), query);
  const prepare = usePreparation();
  const work = useWork();
  const [selection, choose] = useState('');
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const candidate = state.value?.find((row) => row.id === selection);
  const allowed =
    commands.session.phase === 'READY' &&
    !state.error &&
    !state.waiting &&
    candidate !== undefined &&
    isPrepared(candidate);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!allowed || !candidate) return;
    const input = {
      action: 'ATTACH',
      candidate_ref: candidate.id,
      expected_candidate_sha256: candidate.digest,
      ...(candidate.state === 'REATTACH_READY' && {
        environment_id: candidate.environment,
        expected_record_version: candidate.version,
      }),
    };
    work.run(async (signal) => {
      const command = await commands.prepare(input, prepare());
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
  return (
    <Panel
      title={archivedEnvironment ? '重新登记环境' : '登记已有环境'}
      back={back}
      backLabel="返回环境"
    >
      <ReadStatus state={state} />
      {state.value?.length === 0 && (
        <EmptyState icon="workbench" message="宿主暂未提供可核对的候选。" />
      )}
      {state.value && state.value.length > 0 && (
        <form className="card command-form" onSubmit={submit}>
          <p>登记会保留已有安装、配置和数据。</p>
          <label>
            宿主候选
            <select
              value={selection}
              onChange={(event) => choose(event.target.value)}
              disabled={work.busy}
            >
              <option value="">选择候选</option>
              {state.value.map((row) => (
                <option key={row.id} value={row.id} disabled={!isPrepared(row)}>
                  {row.name} · {states[row.state]}
                </option>
              ))}
            </select>
          </label>
          {candidate?.state === 'REATTACH_READY' && (
            <dl className="definitions">
              <div>
                <dt>原环境编号</dt>
                <dd>
                  <code>{candidate.environment}</code>
                </dd>
              </div>
              <div>
                <dt>当前登记版本</dt>
                <dd>{candidate.version}</dd>
              </div>
            </dl>
          )}
          {candidate?.at && (
            <small>最近一次准备核对 {new Date(candidate.at).toLocaleString('zh-HK')}</small>
          )}
          {state.value.every((row) => !isPrepared(row)) && (
            <p className="muted">当前候选已登记或需要宿主重新核对。</p>
          )}
          {commands.session.phase !== 'READY' && <p className="muted">管理登记仍在核对。</p>}
          {work.error && (
            <p role="alert" className="feedback error">
              {work.error}
            </p>
          )}
          <div className="summary-line">
            <button type="submit" className="command-primary" disabled={!allowed || work.busy}>
              登记所选环境
            </button>
            <button type="button" onClick={state.retry} disabled={state.waiting || work.busy}>
              刷新候选
            </button>
          </div>
        </form>
      )}
    </Panel>
  );
}

function lines(value: FormDataEntryValue | null) {
  return String(value ?? '')
    .split(/\r?\n/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function DeliveryForm(props: Common & { target: Environment }) {
  const { commands, target, changed, back } = props;
  const keys = usePreparation();
  const work = useWork();
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const [invalid, setInvalid] = useState(false);
  const integration = target.purpose === 'INTEGRATION';
  const allowed = target.actions.find((action) => action.action === 'REGISTER_DELIVERY');
  const enabled = allowed?.enabled && commands.session.phase !== 'BLOCKED';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enabled) return;
    const form = new FormData(event.currentTarget);
    const sources = lines(form.get('sources')).map((line) => line.split(/\s+/));
    const raw = {
      action: 'REGISTER_DELIVERY',
      environment_id: target.id,
      expected_record_version: target.recordVersion,
      expected_assignment_generation: target.generation,
      commit: String(form.get('commit') ?? '').trim(),
      resource_refs: lines(form.get('resources')),
      check_refs: lines(form.get('checks')),
      manual_notes: String(form.get('manual') ?? '').trim(),
      not_covered: lines(form.get('uncovered')),
      ...(integration && {
        source_environment_ids: sources.map(([id]) => id),
        source_commits: sources.map(([, commit]) => commit),
      }),
    };
    try {
      if (integration && sources.some((source) => source.length !== 2)) throw new TypeError();
      const input = commandIntent(raw);
      setInvalid(false);
      work.run(async (signal) => {
        const prepared = await commands.prepare(input, keys());
        if (!signal.aborted) {
          setOriginal(prepared);
          changed();
        }
      });
    } catch {
      setInvalid(true);
    }
  }

  if (original) return <OriginalCommand {...props} original={original} />;
  return (
    <Panel title="登记交付" back={back} backLabel="返回环境详情">
      <form onSubmit={submit} className="card command-form">
        <p>
          {target.name} · 记录版本 {target.recordVersion} · 分配代次 {target.generation}
        </p>
        <label>
          固定提交
          <input name="commit" maxLength={64} required autoComplete="off" />
        </label>
        {integration && (
          <label>
            集成来源（每行填写环境编号和固定提交，中间以空格分隔）
            <textarea name="sources" rows={3} required />
          </label>
        )}
        <label>
          已登记资源引用（每行一个编号）
          <textarea name="resources" rows={2} />
        </label>
        <label>
          独立检查引用（每行一个编号）
          <textarea name="checks" rows={2} />
        </label>
        <label>
          人工说明
          <textarea name="manual" rows={3} />
        </label>
        <label>
          未覆盖范围（每行一项）
          <textarea name="uncovered" rows={2} />
        </label>
        {invalid && (
          <p role="alert" className="feedback error">
            请检查固定提交、登记引用或说明格式。
          </p>
        )}
        {work.error && (
          <p role="alert" className="feedback error">
            {work.error}
          </p>
        )}
        {!enabled && <p className="muted">{commandReason(allowed?.reason ?? null)}</p>}
        <div className="summary-line">
          <button type="submit" className="command-primary" disabled={!enabled || work.busy}>
            保存原请求
          </button>
        </div>
      </form>
    </Panel>
  );
}

export function PendingList(
  props: Readonly<{
    commands: ManagementCommands;
    back: () => void;
    select: (operation: PendingCommand) => void;
    revision: number;
  }>,
) {
  const { commands, select, back, revision } = props;
  const load = useCallback(() => commands.store.list(), [commands]);
  const items = useRead(commands.store.scopeId + '|' + revision, load);
  return (
    <Panel title="本机待核对" back={back} backLabel="返回操作记录">
      <ReadStatus state={items} />
      {items.value?.length === 0 && (
        <EmptyState icon="history" message="本机没有需要核对的管理原请求。" />
      )}
      {items.value && items.value.length > 0 && (
        <ul className="card pending-list">
          {items.value.map((item) => (
            <li key={item.command_key}>
              <div>
                <strong>{titles[item.action]}</strong>
                <code>{item.command_key}</code>
              </div>
              <button type="button" onClick={() => select(item)}>
                查看本机原请求
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const releaseStates: Readonly<Record<ReleaseSelection['state'], string>> = {
  READY: '已核验',
  SOURCE_UNVERIFIED: '源环境尚未核对为正常停止',
  CANDIDATE_UNVERIFIED: '固定包尚无当前宿主的完整验证',
  RECOVERY_NOT_ADMITTED: '发布所需的恢复凭证尚未准入',
  ENVIRONMENT_BUSY: '环境仍有未决操作',
};

type ConfirmedReleasePlan = ReturnType<typeof releasePlan>;

function ReleaseComparison({
  plan,
  selected,
}: {
  plan: ConfirmedReleasePlan;
  selected: ReleaseSelection;
}) {
  return (
    <>
      <p>当前与目标使用同一数据代次。核验固定新版并开放后，管理登记才会更新。</p>
      <div className="detail-grid">
        <section className="card">
          <h3>当前部署</h3>
          <dl className="definitions">
            <div>
              <dt>部署编号</dt>
              <dd>{plan.source.id}</dd>
            </div>
            <div>
              <dt>程序摘要</dt>
              <dd>
                <code>{plan.source.program}</code>
              </dd>
            </div>
            <div>
              <dt>配置摘要</dt>
              <dd>
                <code>{plan.source.configuration}</code>
              </dd>
            </div>
          </dl>
        </section>
        <section className="card">
          <h3>目标部署</h3>
          <dl className="definitions">
            <div>
              <dt>部署编号</dt>
              <dd>{plan.target.id}</dd>
            </div>
            <div>
              <dt>程序摘要</dt>
              <dd>
                <code>{plan.target.program}</code>
              </dd>
            </div>
            <div>
              <dt>配置摘要</dt>
              <dd>
                <code>{plan.target.configuration}</code>
              </dd>
            </div>
          </dl>
        </section>
      </div>
      <dl className="definitions">
        <div>
          <dt>候选验证平台</dt>
          <dd>
            {selected.os} {selected.architecture}
          </dd>
        </div>
        <div>
          <dt>固定提交</dt>
          <dd>
            <code>{selected.commit}</code>
          </dd>
        </div>
        <div>
          <dt>数据代次</dt>
          <dd>{plan.source.generation}</dd>
        </div>
        <div>
          <dt>数据兼容</dt>
          <dd>同一数据结构</dd>
        </div>
        <div>
          <dt>恢复要求</dt>
          <dd>
            {plan.recovery === 'OFFHOST_VERIFIED'
              ? '本机恢复点与异机副本均须核验'
              : '本机恢复点须核验'}
          </dd>
        </div>
        <div>
          <dt>计划完成状态</dt>
          <dd>开放目标部署</dd>
        </div>
        <div>
          <dt>业务能力</dt>
          <dd>
            {plan.capabilities
              .map((capability) => (capability === 'DOCUMENT_READ' ? '文档读取' : '文档保存'))
              .join('、')}
          </dd>
        </div>
        <div>
          <dt>计划有效至</dt>
          <dd>
            <time dateTime={plan.expires}>{new Date(plan.expires).toLocaleString('zh-HK')}</time>
          </dd>
        </div>
      </dl>
      <details>
        <summary>固定包与计划摘要</summary>
        <dl className="definitions">
          <div>
            <dt>包摘要</dt>
            <dd>
              <code>{plan.manifest}</code>
            </dd>
          </div>
          {plan.accessPolicy && (
            <div>
              <dt>目标访问策略摘要</dt>
              <dd>
                <code>{plan.accessPolicy}</code>
              </dd>
            </div>
          )}
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

export function ReleaseForm(props: Common & { target: Environment; action: ReleaseAction }) {
  const { target, commands, back, changed, openReceipt, action } = props;
  const rollback = action === 'ROLLBACK_CODE';
  const configure = action === 'RECONFIGURE';
  const title = titles[action];
  const operation = { RELEASE: '发布', ROLLBACK_CODE: '回退', RECONFIGURE: '配置切换' }[action];
  const choiceLabel = {
    RELEASE: '固定发布候选',
    ROLLBACK_CODE: '前一固定程序',
    RECONFIGURE: '访问配置',
  }[action];
  const query = useCallback(
    (signal: AbortSignal) => commands.client.releaseOptions(target.id, signal, action),
    [commands.client, target.id, action],
  );
  const state = useRead(commands.store.scopeId + '|' + target.id + '|' + action, query);
  const prepare = usePreparation();
  const work = useWork();
  const [selection, choose] = useState('');
  const [plan, confirmPlan] = useState<ConfirmedReleasePlan | null>(null);
  const [expired, setExpired] = useState(false);
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const selected = state.value?.options.find(
    (option) => option.refs.configuration_ref === selection,
  );
  const current =
    state.value?.recordVersion === target.recordVersion &&
    state.value.generation === target.generation;
  const enabled =
    commands.session.phase !== 'BLOCKED' &&
    commands.session.role === 'MANAGER' &&
    !state.waiting &&
    !state.error &&
    current &&
    selected?.state === 'READY';
  useEffect(() => {
    if (!plan) return;
    const timer = window.setTimeout(
      () => setExpired(true),
      Math.max(0, new Date(plan.expires).getTime() - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [plan]);

  function preview(event: FormEvent) {
    event.preventDefault();
    if (!enabled || !selected) return;
    setExpired(false);
    confirmPlan(null);
    work.run(async (signal) => {
      const planned = await commands.client.planRelease(
        commands.session,
        {
          ...selected.refs,
          ...(rollback && { repair_of_operation_id: null }),
          expected_record_version: target.recordVersion,
          expected_assignment_generation: target.generation,
        },
        AbortSignal.any([signal, AbortSignal.timeout(20000)]),
        action,
      );
      if (
        planned.manifest !== selected.manifest ||
        planned.source.id !== target.work.deployment ||
        planned.source.generation !== target.work.generation ||
        planned.source.configuration !== target.configuration ||
        planned.source.program !== target.program
      )
        throw new ManagementReadError('RELEASE_PLAN_CHANGED', '源环境或固定包已变化，请重新读取。');
      if (!signal.aborted) confirmPlan(planned);
    });
  }

  function confirm() {
    if (!plan || !enabled || expired || new Date(plan.expires).getTime() <= Date.now()) return;
    const input = {
      action,
      ...plan.variables,
      plan_id: plan.id,
      plan_sha256: plan.digest,
    };
    work.run(async (signal) => {
      const command = await commands.prepare(input, prepare());
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
  return (
    <Panel title={title} back={back} backLabel="返回环境">
      <ReadStatus state={state} />
      {work.error && (
        <p role="alert" className="feedback error">
          {work.error}
        </p>
      )}
      {work.busy && (
        <p role="status" className="feedback">
          正在核对{operation}计划…
        </p>
      )}
      {state.value?.options.length === 0 && (
        <EmptyState
          icon="workbench"
          message={
            {
              RELEASE: '此环境尚无已登记的发布候选。',
              ROLLBACK_CODE: '此环境暂无已登记的前一固定程序。',
              RECONFIGURE: '此环境暂无已登记的访问配置。',
            }[action]
          }
        />
      )}
      {state.value && state.value.options.length > 0 && (
        <form className="card command-form" onSubmit={preview}>
          <strong>{target.name}</strong>
          <label>
            {choiceLabel}
            <select
              value={selection}
              required
              disabled={work.busy || state.waiting || Boolean(state.error) || !!plan}
              onChange={(event) => {
                choose(event.target.value);
                confirmPlan(null);
              }}
            >
              <option value="">请选择</option>
              {state.value.options.map((option) => (
                <option key={option.refs.configuration_ref} value={option.refs.configuration_ref}>
                  {(configure
                    ? option.refs.configuration_ref
                    : (option.commit ?? option.refs.configuration_ref)
                  ).slice(0, 12)}{' '}
                  · {option.architecture ?? '平台待核验'} · {releaseStates[option.state]}
                </option>
              ))}
            </select>
          </label>
          {!current && <p role="alert">环境登记已变化，请返回环境重新读取。</p>}
          {selected && selected.state !== 'READY' && (
            <p className="muted">{releaseStates[selected.state]}。</p>
          )}
          {!plan && (
            <button type="submit" className="command-primary" disabled={!enabled || work.busy}>
              生成{operation}计划
            </button>
          )}
          {plan && selected && (
            <>
              <ReleaseComparison plan={plan} selected={selected} />
              {rollback && <p>使用前一固定程序，保留当前数据库和数据代次。</p>}
              {configure && <p>采用所选访问策略，保留当前程序、数据库和数据代次。</p>}
              {expired && <p role="alert">计划已过期，请重新生成。</p>}
              <div className="summary-line">
                <button
                  type="button"
                  disabled={work.busy}
                  onClick={() => {
                    confirmPlan(null);
                    setExpired(false);
                  }}
                >
                  返回候选选择
                </button>
                <button
                  type="button"
                  className="command-primary"
                  disabled={!enabled || expired || work.busy}
                  onClick={confirm}
                >
                  确认{operation}计划
                </button>
              </div>
            </>
          )}
        </form>
      )}
    </Panel>
  );
}

export function BackupForm(props: Common & { target: Environment }) {
  const { commands, target, back, changed, openReceipt } = props;
  const query = useCallback(
    (signal: AbortSignal) => commands.client.backupOptions(target.id, signal),
    [commands.client, target.id],
  );
  const state = useRead(target.id, query);
  const prepare = usePreparation();
  const work = useWork();
  const [selection, choose] = useState('');
  const [plan, setPlan] = useState<ReturnType<typeof backupPlan> | null>(null);
  const [expired, setExpired] = useState(false);
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const choice = state.value?.options.find((item) => item.policy === selection);
  const current =
    state.value?.recordVersion === target.recordVersion &&
    state.value.generation === target.generation;
  const enabled =
    choice?.state === 'READY' &&
    current &&
    commands.session.role === 'MANAGER' &&
    commands.session.phase !== 'BLOCKED' &&
    !state.waiting &&
    !state.error;
  const optionLabels = {
    READY: '可生成备份计划',
    SOURCE_UNVERIFIED: '源环境尚未核对为正常停止',
    ENVIRONMENT_BUSY: '源环境已有未决操作',
    OFFHOST_REQUIRED: '需要异机核验，当前尚未准入',
  } as const;
  const assetNames = {
    BUSINESS_DATABASE: '业务数据库',
    COUNT_AUDIT: '计数审计',
    FIXED_RESOURCES: '固定资源',
    ORIGINAL_RESULTS: '原操作结果',
  } as const;
  useEffect(() => {
    if (!plan) return;
    const timer = window.setTimeout(
      () => setExpired(true),
      Math.max(0, Date.parse(plan.expires) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [plan]);

  function preview(event: FormEvent) {
    event.preventDefault();
    if (!enabled || !choice) return;
    setExpired(false);
    work.run(async (signal) => {
      const planned = await commands.client.planBackup(
        commands.session,
        {
          environment_id: target.id,
          expected_record_version: target.recordVersion,
          expected_assignment_generation: target.generation,
          backup_policy_ref: choice.policy,
          after_completion: 'KEEP_STOPPED',
        },
        AbortSignal.any([signal, AbortSignal.timeout(20000)]),
      );
      if (
        planned.source.deployment !== target.work.deployment ||
        planned.source.generation !== target.work.generation ||
        planned.source.configuration !== target.configuration ||
        planned.source.program !== target.program ||
        planned.verification !== choice.verification
      )
        throw new ManagementReadError('STALE', '备份源环境或策略已变化，请重新读取。');
      if (!signal.aborted) setPlan(planned);
    });
  }

  function confirm() {
    if (!plan || !enabled || expired || Date.parse(plan.expires) <= Date.now()) return;
    const payload = {
      action: 'BACKUP',
      ...plan.requested,
      plan_id: plan.id,
      plan_sha256: plan.digest,
    };
    work.run(async (signal) => {
      const command = await commands.prepare(payload, prepare());
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
  return (
    <Panel title="创建恢复点" back={back} backLabel="返回环境">
      <ReadStatus state={state} />
      {work.error && (
        <p role="alert" className="feedback error">
          {work.error}
        </p>
      )}
      {work.busy && (
        <p role="status" className="feedback">
          正在核对备份计划…
        </p>
      )}
      {state.value?.options.length === 0 && (
        <EmptyState icon="workbench" message="此环境尚无已登记的备份策略。" />
      )}
      {state.value && state.value.options.length > 0 && (
        <form className="card command-form" onSubmit={preview}>
          <strong>{target.name}</strong>
          <label>
            固定备份策略
            <select
              value={selection}
              required
              disabled={work.busy || state.waiting || Boolean(state.error) || !!plan}
              onChange={(event) => {
                choose(event.target.value);
                setPlan(null);
              }}
            >
              <option value="">请选择</option>
              {state.value.options.map((item) => (
                <option key={item.policy} value={item.policy}>
                  {item.policy.slice(0, 8)} ·{' '}
                  {item.verification === 'OFFHOST_VERIFIED' ? '异机备份' : '本机备份'} ·{' '}
                  {optionLabels[item.state]}
                </option>
              ))}
            </select>
          </label>
          {!current && <p role="alert">环境登记已变化，请返回环境重新读取。</p>}
          {choice && choice.state !== 'READY' && (
            <p className="muted">{optionLabels[choice.state]}。</p>
          )}
          {!plan && (
            <button type="submit" className="command-primary" disabled={!enabled || work.busy}>
              生成备份计划
            </button>
          )}
          {plan && (
            <>
              <dl className="definitions">
                <div>
                  <dt>恢复点编号</dt>
                  <dd>{plan.backup}</dd>
                </div>
                <div>
                  <dt>源部署</dt>
                  <dd>{plan.source.deployment}</dd>
                </div>
                <div>
                  <dt>源数据代次</dt>
                  <dd>{plan.source.generation}</dd>
                </div>
                <div>
                  <dt>备份覆盖范围</dt>
                  <dd>{plan.assets.map((asset) => assetNames[asset]).join('、')}</dd>
                </div>
                <div>
                  <dt>验证要求</dt>
                  <dd>
                    {plan.verification === 'OFFHOST_VERIFIED'
                      ? '本机封存、恢复演练和独立宿主取回'
                      : '本机封存和独立恢复核验'}
                  </dd>
                </div>
                <div>
                  <dt>完成后</dt>
                  <dd>保持环境停止</dd>
                </div>
                <div>
                  <dt>计划有效至</dt>
                  <dd>
                    <time dateTime={plan.expires}>
                      {new Date(plan.expires).toLocaleString('zh-HK')}
                    </time>
                  </dd>
                </div>
              </dl>
              {expired && <p role="alert">备份计划已过期，请重新生成。</p>}
              <div className="summary-line">
                <button
                  type="button"
                  disabled={work.busy}
                  onClick={() => {
                    setPlan(null);
                    setExpired(false);
                  }}
                >
                  返回策略选择
                </button>
                <button
                  type="button"
                  className="command-primary"
                  disabled={!enabled || expired || work.busy}
                  onClick={confirm}
                >
                  确认备份计划
                </button>
              </div>
            </>
          )}
        </form>
      )}
    </Panel>
  );
}

export function EnvironmentActionForm(
  props: Common & { target: Environment; action: EnvironmentAction },
) {
  const { commands, back, changed, openReceipt, target, action } = props;
  const prepare = usePreparation();
  const work = useWork();
  const query = useCallback(
    (signal: AbortSignal) => commands.client.environment(target.id, signal),
    [commands.client, target.id],
  );
  const state = useRead(target.id, query);
  const actual = state.value;
  const [original, setOriginal] = useState<PendingCommand | null>(null);
  const status = actual?.actions.find((item) => item.action === action);
  const versionMatches =
    actual?.recordVersion === target.recordVersion && actual.generation === target.generation;
  const sameTarget =
    action === 'STOP'
      ? actual?.observation.run !== null && actual?.observation.run === target.observation.run
      : actual?.configuration === target.configuration &&
        actual?.work.deployment === target.work.deployment;
  const reason = !actual
    ? null
    : !versionMatches || !sameTarget
      ? '环境登记或原运行已变化，请返回环境重新读取。'
      : commands.session.phase === 'BLOCKED'
        ? '管理入口暂不可用。'
        : status?.enabled
          ? null
          : commandReason(status?.reason ?? null);
  const allowed = Boolean(
    actual &&
    status?.enabled &&
    versionMatches &&
    sameTarget &&
    reason === null &&
    !state.waiting &&
    !state.error,
  );
  const details = {
    START: {
      title: '普通启动',
      context: '启动当前登记的部署。宿主核对原控制与运行额度后会执行。',
      confirm: '确认启动',
    },
    STOP: {
      title: '正常停止',
      context: '只停止下列原运行。宿主核对该进程组正常退出后会登记停止结果。',
      confirm: '确认正常停止',
    },
    ARCHIVE: {
      title: '归档环境',
      context: '归档后退出活动列表。工作区、数据库及原操作回执会保留。',
      confirm: '提交归档',
    },
  }[action];

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!allowed || !actual) return;
    const scope = {
      environment_id: actual.id,
      expected_record_version: actual.recordVersion,
      expected_assignment_generation: actual.generation,
    };
    const input =
      action === 'START'
        ? { ...scope, action, expected_configuration_sha256: actual.configuration }
        : action === 'STOP'
          ? { ...scope, action, target: { kind: 'RUN', run_id: actual.observation.run } }
          : { ...scope, action };
    work.run(async (signal) => {
      const command = await commands.prepare(input, prepare());
      if (signal.aborted) return;
      setOriginal(command);
      changed();
      try {
        const outcome = await commands.dispatch(command, signal);
        if (!signal.aborted) openReceipt(outcome.original.id);
      } finally {
        if (!signal.aborted) changed();
      }
    });
  }

  if (original)
    return (
      <OriginalCommand {...props} original={original} performing={work.busy} notice={work.error} />
    );
  return (
    <Panel title={details.title} back={back} backLabel="返回环境">
      <ReadStatus state={state} />
      {actual && (
        <form className="card command-form" onSubmit={submit}>
          <strong>{actual.name}</strong>
          <p>{details.context}</p>
          <dl className="definitions">
            <div>
              <dt>{action === 'STOP' ? '原运行' : '当前部署'}</dt>
              <dd>
                <code>{action === 'STOP' ? actual.observation.run : actual.work.deployment}</code>
              </dd>
            </div>
            <div>
              <dt>数据代次</dt>
              <dd>{actual.work.generation}</dd>
            </div>
          </dl>
          {reason && (
            <p id="runtime-action-reason" className="muted">
              {reason}
            </p>
          )}
          {work.error && (
            <p role="alert" className="feedback error">
              {work.error}
            </p>
          )}
          <button
            type="submit"
            className="command-primary"
            disabled={!allowed || work.busy}
            aria-describedby={reason ? 'runtime-action-reason' : undefined}
          >
            {details.confirm}
          </button>
        </form>
      )}
    </Panel>
  );
}

const reconciliationText = {
  RELEASE: { title: '发布结果核对', waiting: '已核对，原发布仍等待宿主开放凭证。' },
  ROLLBACK_CODE: { title: '回退结果核对', waiting: '已核对，原回退仍等待宿主开放凭证。' },
  RECONFIGURE: { title: '配置切换结果核对', waiting: '已核对，原配置切换仍等待宿主开放凭证。' },
  BACKUP: { title: '备份结果核对', waiting: '已核对，仍等待原恢复点的验证。' },
  RESTORE: { title: '恢复结果核对', waiting: '已核对，原恢复仍等待宿主开放凭证。' },
  START: { title: '运行结果核对', waiting: '已核对，仍等待原运行结果。' },
  STOP: { title: '运行结果核对', waiting: '已核对，仍等待原运行结果。' },
  ARCHIVE: { title: '归档状态核对', waiting: '等待宿主核对实际停止与资源归属。' },
} as const;

export function OperationReconcile({
  action,
  commands,
  operation,
  revision,
  disabled,
  canWithdraw,
  waitingCapacity,
  changed,
  openOriginal,
  refresh,
}: {
  action: ReleaseAction | 'BACKUP' | 'RESTORE' | EnvironmentAction;
  commands: ManagementCommands;
  operation: string;
  revision: number;
  disabled: boolean;
  canWithdraw: boolean;
  waitingCapacity: boolean;
  changed: () => void;
  openOriginal: (command: PendingCommand) => void;
  refresh: () => void;
}) {
  const work = useWork();
  const [received, setReceived] = useState<'CAPACITY' | 'WAITING' | 'FINISHED' | null>(null);
  const [pending, setPending] = useState<PendingCommand | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);

  function sendControl(action: ManagementControl) {
    if (
      disabled ||
      (action === 'CANCEL' && !canWithdraw) ||
      (action === 'CONTINUE' && !waitingCapacity)
    )
      return;
    setReceived(null);
    work.run(async (signal) => {
      const command = await commands.prepareControl(operation, revision, action);
      if (signal.aborted) return;
      changed();
      if (command.state !== 'PREPARED' || command.action !== action) {
        openOriginal(command);
        return;
      }
      setPending(command);
      try {
        const outcome = await commands.dispatch(command, signal);
        if (signal.aborted) return;
        setPending(null);
        if (outcome.original.state === 'WAITING_CAPACITY') {
          setReceived('CAPACITY');
        } else if (['SUCCEEDED', 'CANCELLED'].includes(outcome.original.state)) {
          setReceived('FINISHED');
        } else {
          setReceived('WAITING');
        }
        refresh();
      } finally {
        if (!signal.aborted) changed();
      }
    });
  }

  return (
    <section className="card lower" aria-labelledby="operation-reconciliation-heading">
      <div className="summary-line">
        <h2 id="operation-reconciliation-heading">{reconciliationText[action].title}</h2>
        <button
          type="button"
          onClick={
            action === 'ARCHIVE'
              ? refresh
              : () => sendControl(waitingCapacity ? 'CONTINUE' : 'RECONCILE')
          }
          disabled={disabled || work.busy || !!pending || confirmWithdraw}
        >
          {action === 'ARCHIVE'
            ? '刷新归档状态'
            : waitingCapacity
              ? '重新核对额度并继续启动'
              : '核对原结果'}
        </button>
        {canWithdraw && !confirmWithdraw && (
          <button
            type="button"
            disabled={disabled || work.busy || !!pending}
            onClick={() => setConfirmWithdraw(true)}
          >
            撤回未派发操作
          </button>
        )}
        {pending && !work.busy && (
          <button type="button" onClick={() => openOriginal(pending)}>
            查看本机原核对
          </button>
        )}
      </div>
      {action === 'ARCHIVE' && <p className="muted">{reconciliationText.ARCHIVE.waiting}</p>}
      {confirmWithdraw && canWithdraw && (
        <div>
          <p>仅能撤回尚未派发的原操作。宿主取得执行授权后仍可核对原结果。</p>
          <div className="summary-line">
            <button type="button" disabled={work.busy} onClick={() => setConfirmWithdraw(false)}>
              返回核对
            </button>
            <button
              type="button"
              disabled={disabled || work.busy || !!pending}
              onClick={() => sendControl('CANCEL')}
            >
              确认撤回
            </button>
          </div>
        </div>
      )}
      {work.busy && (
        <p role="status" className="feedback">
          正在核对原操作…
        </p>
      )}
      {work.error && (
        <p role="alert" className="feedback error">
          {work.error}
        </p>
      )}
      {received === 'CAPACITY' && <p role="status">原启动仍在等待运行额度。</p>}
      {received === 'WAITING' && <p role="status">{reconciliationText[action].waiting}</p>}
      {received === 'FINISHED' && <p role="status">已登记原操作结果。</p>}
    </section>
  );
}

export function OriginalCommand(
  props: Common & {
    original: PendingCommand;
    performing?: boolean;
    notice?: string | null;
  },
) {
  const { commands, original, openReceipt, back, changed, performing = false, notice } = props;
  const [present, setPresent] = useState<PendingCommand | null>(original);
  const [body, setBody] = useState<string | null>(null);
  const [lookup, setLookup] = useState<'IDLE' | 'ABSENT' | 'OPEN'>('IDLE');
  const work = useWork();
  const busy = performing || work.busy;
  const intent = original.kind === 'ACTION' ? recoverIntent(original.body) : null;
  const locallyPending = present !== null;
  const canDispatch =
    locallyPending &&
    commands.session.role !== 'VIEWER' &&
    ((original.action !== 'ATTACH' &&
      original.action !== 'RELEASE' &&
      original.action !== 'ROLLBACK_CODE' &&
      original.action !== 'RECONFIGURE' &&
      original.action !== 'BACKUP' &&
      original.action !== 'RESTORE' &&
      original.action !== 'ARCHIVE') ||
      commands.session.role === 'MANAGER') &&
    commands.session.phase !== 'BLOCKED' &&
    (original.action !== 'ATTACH' || commands.session.phase === 'READY');
  const reload = useCallback(
    async () => setPresent(await commands.store.read(original.command_key)),
    [commands, original.command_key],
  );
  useEffect(() => {
    if (!performing && commands.session.principal === original.actor) {
      let active = true;
      void commands.store
        .read(original.command_key)
        .then((item) => {
          if (active) setPresent(item);
        })
        .catch(() => {
          /* Explicit lookup remains available for the original key. */
        });
      return () => {
        active = false;
      };
    }
  }, [commands, original, performing]);

  function check() {
    if (commands.session.bindingChanged) return;
    work.run(async (signal) => {
      const result = await commands.lookup(original, signal);
      if (signal.aborted) return;
      if (result) {
        setLookup('OPEN');
        changed();
        openReceipt(result.original.id);
      } else {
        setLookup('ABSENT');
        await reload();
      }
    });
  }

  function dispatch() {
    if (!canDispatch) return;
    work.run(async (signal) => {
      try {
        const result = await commands.dispatch(original, signal);
        if (!signal.aborted) openReceipt(result.original.id);
      } finally {
        if (!signal.aborted) {
          await reload().catch(() => undefined);
          changed();
        }
      }
    });
  }

  function showRequest() {
    work.run(async (signal) => {
      const request = await commands.frozenRequest(original);
      if (!signal.aborted) setBody(request);
    });
  }

  return (
    <Panel title="本机原请求" back={back} backLabel="返回">
      <section className="card command-form">
        <p>
          <strong>{titles[original.action]}</strong> ·{' '}
          {locallyPending && present.state === 'PREPARED' ? '已在本机保存' : '等待核对原结果'}
        </p>
        <p>
          {original.kind === 'CONTROL' ? '原控制键' : '原请求键'}{' '}
          <code>{original.command_key}</code>
        </p>
        {intent?.action === 'BACKUP' && (
          <p>
            原备份计划 <code>{intent.plan_id}</code>
          </p>
        )}
        {(intent?.action === 'RELEASE' ||
          intent?.action === 'ROLLBACK_CODE' ||
          intent?.action === 'RECONFIGURE') && (
          <p>
            {
              { RELEASE: '原发布计划', ROLLBACK_CODE: '原回退计划', RECONFIGURE: '原配置切换计划' }[
                intent.action
              ]
            }{' '}
            <code>{intent.plan_id}</code>
          </p>
        )}
        {intent?.action === 'RESTORE' && (
          <p>
            原恢复计划 <code>{intent.plan_id}</code>
          </p>
        )}
        {intent?.action === 'REGISTER_DELIVERY' && (
          <p>
            固定提交 <code>{intent.commit}</code>
          </p>
        )}
        {intent?.action === 'REGISTER_DELIVERY' && (
          <div>
            <p>宿主维护人员须先用此原请求核对 Git 和登记资料。</p>
            <button type="button" onClick={showRequest} disabled={busy}>
              显示宿主核对请求
            </button>
            {body && (
              <label className="command-export">
                供宿主核对的原请求
                <textarea
                  rows={5}
                  readOnly
                  value={body}
                  onFocus={(event) => event.currentTarget.select()}
                />
              </label>
            )}
          </div>
        )}
        {busy && (
          <p role="status" className="feedback">
            正在处理此原请求…
          </p>
        )}
        {(work.error || notice) && (
          <p role="alert" className="feedback error">
            {work.error ?? notice}
          </p>
        )}
        {lookup === 'ABSENT' && <p role="status">当前尚未找到可返回的原回执，已保留原键。</p>}
        {commands.session.bindingChanged && (
          <p className="muted">当前只保留本机记录。服务器原回执须由原管理入口核对。</p>
        )}
        {!commands.session.bindingChanged && !canDispatch && !busy && (
          <p className="muted">当前仅能核对原回执。</p>
        )}
        <div className="summary-line">
          <button type="button" onClick={check} disabled={busy || commands.session.bindingChanged}>
            核对原请求
          </button>
          {canDispatch && (
            <button type="button" className="command-primary" onClick={dispatch} disabled={busy}>
              {present.state === 'PREPARED' ? '发送原请求' : '查询后再次发送原请求'}
            </button>
          )}
        </div>
      </section>
    </Panel>
  );
}
