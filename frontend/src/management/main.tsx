import { useCallback, useMemo, useState, useSyncExternalStore } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { EmptyState } from '../shared/empty-state.tsx';
import { ManagementClient } from './api.ts';
import { ManagementCommands } from './command-owner.ts';
import { ManagementCommandStore } from './command-store.ts';
import {
  AttachForm,
  BackupForm,
  DeliveryForm,
  OriginalCommand,
  PendingList,
  OperationReconcile,
  ReleaseForm,
  EnvironmentActionForm,
  commandReason,
} from './command-panels.tsx';
import type { EnvironmentAction, PendingCommand } from './command-intent.ts';
import { RestoreForm } from './restore-panel.tsx';
import { PriorResults } from './prior-result-panel.tsx';
import { Panel, ReadStatus, useRead } from './ui.tsx';
import type { Filter, Session } from './api.ts';
import { operationStates, uuid } from './model.ts';
import type { environment, operationDetail } from './model.ts';
import type { ReleaseAction } from './release-model.ts';
import './styles.css';

const client = new ManagementClient(window.location.origin);
const purposeNames: Readonly<Record<string, string>> = {
  DEVELOPMENT: '开发',
  INTEGRATION: '集成',
  CANDIDATE: '候选',
  PRODUCTION: '生产',
};
const roleNames: Readonly<Record<string, string>> = {
  MANAGER: '管理者',
  DEVELOPER: '开发者',
  VIEWER: '只读',
};
const registrations: Readonly<Record<string, string>> = { ACTIVE: '活动', ARCHIVED: '已归档' };
const progress: Readonly<Record<string, string>> = {
  PREPARING: '准备中',
  PREPARED: '已登记准备结果',
  INCOMPLETE: '准备不完整',
  WAITING_CAPACITY: '等待容量',
  ACCEPTED: '已受理',
  RUNNING: '进行中',
  SUCCEEDED: '已完成',
  FAILED: '已失败',
  CANCELLED: '已取消',
  UNKNOWN: '待核实',
  PLANNED: '未开始',
  DISPATCHING: '正在派发',
  SKIPPED: '已跳过',
};
const actionNames: Readonly<Record<string, string>> = {
  ATTACH: '环境登记',
  REGISTER_DELIVERY: '交付登记',
  START: '普通启动',
  STOP: '正常停止',
  ARCHIVE: '归档环境',
  RELEASE: '固定发布',
  ROLLBACK_CODE: '程序回退',
  RECONFIGURE: '切换配置',
  BACKUP: '独立备份',
  RESTORE: '恢复环境',
};
const resourceNames: Readonly<Record<string, string>> = {
  INSTALLATION_ROOT: '环境安装',
  WORKTREE: '工作区',
  DATA_ROOT: '数据目录',
  CONTROL_ROOT: '控制记录',
  BUSINESS_DATABASE: '业务数据库',
  STABLE_LOCK: '环境锁',
  UPSTREAM_SOCKET: '应用连接',
  GIT_BRANCH: 'Git 分支',
  PUBLIC_ORIGIN: '业务域名',
};
const date = new Intl.DateTimeFormat('zh-HK', { dateStyle: 'medium', timeStyle: 'short' });
function at(value: string | null) {
  return value === null ? '尚未核对' : date.format(new Date(value));
}
function short(value: string) {
  return value.slice(0, 12);
}

function Badge({
  label,
  tone = 'neutral',
}: {
  label: string;
  tone?: 'neutral' | 'positive' | 'warning';
}) {
  return <span className={'badge ' + tone}>{label}</span>;
}

function Definitions({ values }: { values: ReadonlyArray<readonly [string, ReactNode]> }) {
  return (
    <dl className="facts">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function DataTable({ labels, children }: { labels: string[]; children: ReactNode }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {labels.map((label) => (
              <th scope="col" key={label}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

type Environment = ReturnType<typeof environment>;
function Runtime({ data }: { data: Environment['observation'] }) {
  if (data.runtime === 'UNKNOWN') return <Badge label="状态待核实" tone="warning" />;
  if (data.freshness !== 'FRESH') return <Badge label="观察已过期" tone="warning" />;
  if (data.runtime === 'STOPPED') return <Badge label="已停止" tone="positive" />;
  const ready = data.reason === 'MANAGED_APPLICATION_READY';
  return (
    <Badge
      label={ready ? '运行中，应用已就绪' : '运行中，应用待核实'}
      tone={ready ? 'positive' : 'warning'}
    />
  );
}

function EnvironmentPage({
  open,
  attach,
}: {
  open: (id: string) => void;
  attach: { start: () => void; reason: string | null } | undefined;
}) {
  const [purpose, setPurpose] = useState('');
  const [registration, setRegistration] = useState('');
  const [cursor, setCursor] = useState('');
  const query = useCallback(
    (signal: AbortSignal) =>
      client.environments({ purpose, registration_state: registration, cursor }, signal),
    [purpose, registration, cursor],
  );
  const state = useRead(purpose + '|' + registration + '|' + cursor, query);
  return (
    <Panel title="环境">
      {attach && (
        <div className="summary-line management-actions">
          <button
            type="button"
            className="command-primary"
            onClick={attach.start}
            disabled={attach.reason !== null}
            aria-describedby={attach.reason === null ? undefined : 'attach-reason'}
          >
            登记已有环境
          </button>
          {attach.reason !== null && <small id="attach-reason">{attach.reason}</small>}
        </div>
      )}
      <div className="filters">
        <label>
          用途
          <select
            value={purpose}
            onChange={(e) => {
              setPurpose(e.target.value);
              setCursor('');
            }}
          >
            <option value="">全部用途</option>
            {Object.entries(purposeNames).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          登记状态
          <select
            value={registration}
            onChange={(e) => {
              setRegistration(e.target.value);
              setCursor('');
            }}
          >
            <option value="">全部状态</option>
            {Object.entries(registrations).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={state.retry} disabled={state.waiting}>
          刷新
        </button>
      </div>
      <ReadStatus state={state} />
      {state.value &&
        (state.value.entries.length ? (
          <DataTable labels={['环境', '负责人', '准备状态', '实际运行', '上次核对']}>
            {state.value.entries.map((item) => (
              <tr key={item.id}>
                <td>
                  <button
                    className="text-button"
                    type="button"
                    aria-label={item.name + ' 环境详情'}
                    onClick={() => open(item.id)}
                  >
                    {item.name}
                  </button>
                  <small>
                    {purposeNames[item.purpose]} · {registrations[item.registration]}
                  </small>
                </td>
                <td>{item.owner}</td>
                <td>{progress[item.preparation]}</td>
                <td>
                  <Runtime data={item.observation} />
                </td>
                <td>{at(item.observation.observedAt)}</td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState
            icon="workbench"
            message={
              purpose || registration
                ? '没有符合当前筛选条件的环境。'
                : '当前账号没有可查看的环境。'
            }
          />
        ))}
      <div className="pagination">
        {cursor && (
          <button type="button" onClick={() => setCursor('')}>
            返回第一页
          </button>
        )}
        {state.value?.next && (
          <button type="button" onClick={() => setCursor(state.value?.next ?? '')}>
            下一页
          </button>
        )}
      </div>
    </Panel>
  );
}

const backupAttempts: Readonly<Record<string, string>> = {
  CREATING: '正在创建',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  UNVERIFIED: '尚未核实',
  PENDING_RECONCILIATION: '待核对原操作',
};
const backupFreshness: Readonly<Record<string, string>> = {
  UNVERIFIED: '尚未核实',
  MET: '符合目标',
  MISSED: '已超出目标',
};
const auditAssets: Readonly<Record<string, string>> = {
  ABSENT: '无计数审计目录',
  EMPTY: '计数审计目录为空',
  FILES: '含计数审计',
};
const recoveryScopeNames = {
  DOCUMENT_CONTENT: '文档正文',
  DOCUMENT_HISTORY: '文档历史',
  EXISTING_REPORTS: '已保存的报告',
} as const;
const backupNumber = new Intl.NumberFormat('zh-HK', { maximumFractionDigits: 1 });

function formatSize(bytes: number) {
  if (bytes < 1024) return backupNumber.format(bytes) + ' B';
  if (bytes < 1024 ** 2) return backupNumber.format(bytes / 1024) + ' KiB';
  if (bytes < 1024 ** 3) return backupNumber.format(bytes / 1024 ** 2) + ' MiB';
  return backupNumber.format(bytes / 1024 ** 3) + ' GiB';
}

function formatTarget(seconds: number) {
  if (seconds < 60) return backupNumber.format(seconds) + ' 秒';
  if (seconds < 3600) return backupNumber.format(seconds / 60) + ' 分钟';
  return backupNumber.format(seconds / 3600) + ' 小时';
}

function BackupHistory({ id }: { id: string }) {
  const [cursor, setCursor] = useState('');
  const load = useCallback(
    (signal: AbortSignal) => client.backups(id, cursor, signal),
    [id, cursor],
  );
  const state = useRead(id + '/' + cursor, load);
  const current = state.error ? null : state.value;
  const attempt = current?.attempt;
  return (
    <section className="card lower" aria-label="恢复点">
      <h2>恢复点</h2>
      <ReadStatus state={{ ...state, value: current }} />
      {current && (
        <>
          <Definitions
            values={[
              [
                '最近备份尝试',
                attempt ? backupAttempts[attempt.status] + ' · ' + at(attempt.at) : '尚无记录',
              ],
              ...(attempt ? [['最近原操作', <code>{attempt.id}</code>] as const] : []),
              ['本机最新截止时间', at(current.local?.cutoff ?? null)],
              ...(current.local
                ? [['本机最新核验时间', at(current.local.verifiedAt)] as const]
                : []),
              ['异机最新截止时间', at(current.offhost?.cutoff ?? null)],
              ...(current.offhost
                ? [['异机最新核验时间', at(current.offhost.verifiedAt)] as const]
                : []),
              ['备份时效', backupFreshness[current.rpo]],
              ...(current.rpoTarget
                ? [['备份时效目标', formatTarget(current.rpoTarget)] as const]
                : []),
              ...(current.rtoTarget
                ? [
                    [
                      '资料只读恢复目标',
                      formatTarget(current.rtoTarget) + ' · 实际耗时尚未核验',
                    ] as const,
                  ]
                : []),
            ]}
          />
          {attempt?.reason && attempt.status !== 'SUCCEEDED' && (
            <p className="muted">
              {attempt.reason === 'OFFHOST_VERIFICATION_REQUIRED' ? (
                '本机恢复点已核验，等待独立宿主取回快照。'
              ) : (
                <>
                  本次尝试的原因代码 <code>{attempt.reason}</code>
                </>
              )}
            </p>
          )}
          {current.entries.length ? (
            <DataTable
              labels={['原截止时间', '来源代次', '本机核验', '本地快照', '异机副本', '备份资料']}
            >
              {current.entries.map((item) => (
                <tr key={item.id}>
                  <td>{at(item.cutoff)}</td>
                  <td>
                    <code title={item.generation}>{short(item.generation)}</code>
                  </td>
                  <td>
                    <Badge
                      label={item.local ? '本机恢复点已核验' : '尚未核实'}
                      tone={item.local ? 'positive' : 'neutral'}
                    />
                    {item.local && <small>{at(item.local.verifiedAt)}</small>}
                  </td>
                  <td>
                    {item.retrieval ? '已取回 · ' + at(item.retrieval.retrievedAt) : '尚无取回记录'}
                  </td>
                  <td>
                    {item.offhost ? (
                      <>
                        <Badge label="异机副本已验证" tone="positive" />
                        <small>{at(item.offhost.retrievedAt)}</small>
                      </>
                    ) : (
                      '尚未核实'
                    )}
                  </td>
                  <td>
                    <details>
                      <summary>查看资料</summary>
                      <Definitions
                        values={[
                          ['备份编号', <code>{item.id}</code>],
                          ['来源部署', <code>{item.deployment}</code>],
                          ['控制修订', item.revision],
                          [
                            '备份资产',
                            formatSize(item.bytes) +
                              ' 数据库 · ' +
                              auditAssets[item.audit] +
                              ' · 原回执索引',
                          ],
                          ['固定程序', <code title={item.program}>{short(item.program)}</code>],
                          [
                            '配置摘要',
                            <code title={item.configuration}>{short(item.configuration)}</code>,
                          ],
                          ['清单摘要', <code title={item.manifest}>{short(item.manifest)}</code>],
                          ...(item.local
                            ? ([
                                [
                                  '只读核验范围',
                                  item.local.scopes
                                    .map((scope) => recoveryScopeNames[scope])
                                    .join('、'),
                                ],
                                ['核验证据编号', <code>{item.local.id}</code>],
                              ] as const)
                            : []),
                          ...(item.retrieval
                            ? [
                                [
                                  '本地快照摘要',
                                  <code title={item.retrieval.snapshot}>
                                    {short(item.retrieval.snapshot)}
                                  </code>,
                                ] as const,
                              ]
                            : []),
                          ...(item.offhost
                            ? ([
                                ['异机核验证据编号', <code>{item.offhost.id}</code>],
                                [
                                  '异机快照摘要',
                                  <code title={item.offhost.snapshot}>
                                    {short(item.offhost.snapshot)}
                                  </code>,
                                ],
                              ] as const)
                            : []),
                        ]}
                      />
                    </details>
                  </td>
                </tr>
              ))}
            </DataTable>
          ) : (
            !state.waiting && (
              <EmptyState
                icon="outline"
                message={cursor ? '当前页没有恢复点。' : '此环境尚无登记的恢复点。'}
                compact
              />
            )
          )}
        </>
      )}
      {(cursor || current?.next) && (
        <div className="pagination">
          {cursor && (
            <button type="button" disabled={state.waiting} onClick={() => setCursor('')}>
              返回第一页
            </button>
          )}
          {current?.next && (
            <button
              type="button"
              disabled={state.waiting}
              onClick={() => setCursor(current.next ?? '')}
            >
              下一页
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function MaintenanceDetails({
  id,
  openOperation,
}: {
  id: string;
  openOperation: (id: string) => void;
}) {
  const read = useCallback((signal: AbortSignal) => client.maintenance(id, signal), [id]);
  const state = useRead(id, read);
  const value = state.value;
  const current = state.error || state.waiting ? null : value?.actual;
  const recovery = state.error || state.waiting ? null : value?.recovery;
  const last = value?.last;
  const opening = (current ?? last?.control)?.lastOpen;
  const operation = value?.operation;
  const phase = {
    OBSERVATION_UNAVAILABLE: '当前维护状态待核实',
    IDLE: '无进行中的维护',
    MAINTENANCE_UNTRACKED: '环境处于维护，待核对原操作',
    WAITING_FOR_MAINTENANCE: '等待进入维护',
    MAINTENANCE_CLOSED: '已停写，等待核验',
    TARGET_SELECTED: '已选择目标，尚未开放',
    OPENED_AWAITING_REGISTRY: '已开放，等待管理登记',
  } as const;
  return (
    <section className="card lower" aria-labelledby="maintenance-heading">
      <div className="summary-line">
        <h2 id="maintenance-heading">维护与发布</h2>
        {value && !state.error && (
          <button type="button" onClick={state.retry} disabled={state.waiting}>
            更新状态
          </button>
        )}
        {operation && (
          <button type="button" onClick={() => openOperation(operation.id)}>
            查看原发布
          </button>
        )}
      </div>
      <ReadStatus state={state} />
      {value && (
        <>
          <Definitions
            values={[
              ['当前维护', current ? phase[value.phase] : phase.OBSERVATION_UNAVAILABLE],
              ['期望部署', value.desired?.id ?? '尚未登记'],
              ['当前实际部署', current?.id ?? '待核实'],
              ['当前数据代次', current?.generation ?? '待核实'],
              ['外发限制', current ? (current.hold ? '已冻结' : '未设置维护冻结') : '待核实'],
              ['最近宿主观察', at(last?.at ?? null)],
              ...(opening
                ? ([
                    ['最近开放时间', at(opening.at)],
                    ['最近开放部署', opening.deployment],
                  ] as const)
                : []),
            ]}
          />
          {!current && last && (
            <p className="muted">
              最近观察的部署为 <code>{last.control.id}</code>，当前状态待核实。
            </p>
          )}
          {recovery?.status === 'BLOCKED' && (
            <Definitions
              values={[
                ['资料读取', '恢复资料的读取状态待核实。'],
                [
                  '待核对事项',
                  recovery.blockers
                    .map(
                      (code) =>
                        ({
                          SOURCE_UNVERIFIED: '恢复来源',
                          BINDING_UNVERIFIED: '当前部署与数据代次',
                          ASSET_UNVERIFIED: '当前部署的只读资料',
                          EXECUTION_NOT_FENCED: '外发冻结',
                          OBSERVATION_UNAVAILABLE: '当前宿主状态',
                          RECOVERY_RECONCILIATION_REQUIRED: '原恢复操作',
                        })[code],
                    )
                    .join('、'),
                ],
                ['读取状态观察时间', at(recovery.observed)],
              ]}
            />
          )}
          {recovery?.status === 'AVAILABLE' && (
            <Definitions
              values={[
                ['资料读取', '只读资料已核验'],
                ...(recovery.blockers.includes('RECOVERY_RECONCILIATION_REQUIRED')
                  ? [['恢复操作', '仍需核对原操作'] as const]
                  : []),
                ['核验范围', recovery.scopes.map((scope) => recoveryScopeNames[scope]).join('、')],
                ['读取状态观察时间', at(recovery.observed)],
              ]}
            />
          )}
          {!last && <EmptyState icon="outline" message="尚无宿主维护观察。" compact />}
          {(value.registered || value.desired || current) && (
            <details>
              <summary>配置与程序摘要</summary>
              <Definitions
                values={[
                  ['登记部署', value.registered?.id ?? '尚未登记'],
                  ['期望程序', value.desired?.program ?? '尚未登记'],
                  ['期望配置', value.desired?.configuration ?? '尚未登记'],
                  ['实际程序', current?.program ?? '待核实'],
                  ['实际配置', current?.configuration ?? '待核实'],
                ]}
              />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function PreparedDeploymentAction({
  target,
  action,
  unavailable,
  apply,
}: {
  target: Environment;
  action: Exclude<ReleaseAction, 'RELEASE'>;
  unavailable: string | null;
  apply: () => void;
}) {
  const query = useCallback(
    (signal: AbortSignal) => client.releaseOptions(target.id, signal, action),
    [target.id, action],
  );
  const options = useRead(
    target.id + '|' + target.recordVersion + '|' + target.generation + '|' + action,
    query,
  );
  const current =
    options.value?.recordVersion === target.recordVersion &&
    options.value.generation === target.generation;
  let reason: string | null = null;
  const subject = action === 'ROLLBACK_CODE' ? '回退候选' : '访问配置';
  if (unavailable) reason = unavailable;
  else if (options.waiting) reason = '正在核对' + subject;
  else if (options.error) reason = '暂时无法核对' + subject;
  else if (!current) reason = '环境登记已变化，请重新读取';
  else if (!options.value?.options.some((option) => option.state === 'READY'))
    reason =
      action === 'ROLLBACK_CODE' ? '当前没有可回退的前一固定程序' : '当前没有可采用的访问配置';
  const reasonId = 'deployment-action-reason-' + action + '-' + target.id;
  return (
    <span className="runtime-action">
      <button
        type="button"
        disabled={reason !== null}
        aria-describedby={reason ? reasonId : undefined}
        onClick={apply}
      >
        {actionNames[action]}
      </button>
      {reason && <small id={reasonId}>{reason}</small>}
    </span>
  );
}

function EnvironmentDetail({
  id,
  back,
  showOperations,
  showReleaseOperation,
  startRelease,
  startBackup,
  startRestore,
  changeEnvironment,
  reattach,
  deliver,
}: {
  id: string;
  back: () => void;
  showOperations: () => void;
  showReleaseOperation: (operation: string) => void;
  startRelease: ((environment: Environment, action: ReleaseAction) => void) | undefined;
  startBackup: ((environment: Environment) => void) | undefined;
  startRestore: ((environment: Environment) => void) | undefined;
  changeEnvironment: ((environment: Environment, action: EnvironmentAction) => void) | undefined;
  reattach: (() => void) | undefined;
  deliver: ((target: Environment) => void) | undefined;
}) {
  const query = useCallback((signal: AbortSignal) => client.environment(id, signal), [id]);
  const state = useRead(id, query);
  const item = state.value;
  const delivery = item?.actions.find((action) => action.action === 'REGISTER_DELIVERY');
  return (
    <Panel title={item?.name ?? '环境详情'} back={back}>
      <ReadStatus state={state} />
      {item && (
        <>
          <div className="summary-line">
            <Badge label={purposeNames[item.purpose] ?? item.purpose} />
            <Badge label={progress[item.preparation] ?? item.preparation} />
            {item.registration === 'ARCHIVED' && <Badge label="已归档" />}
            {item.registration === 'ARCHIVED' && reattach && (
              <button
                type="button"
                disabled={state.waiting || Boolean(state.error)}
                onClick={reattach}
              >
                重新登记环境
              </button>
            )}
            <Runtime data={item.observation} />
            <button type="button" onClick={showOperations}>
              查看原操作
            </button>
            {deliver &&
              delivery &&
              (delivery.enabled || delivery.reason !== 'MANAGEMENT_ACCESS_DENIED') && (
                <button
                  type="button"
                  onClick={() => deliver(item)}
                  disabled={!delivery.enabled || state.waiting || Boolean(state.error)}
                  aria-describedby={!delivery.enabled ? 'delivery-reason' : undefined}
                >
                  登记交付
                </button>
              )}
            {deliver &&
              delivery &&
              !delivery.enabled &&
              delivery.reason !== 'MANAGEMENT_ACCESS_DENIED' && (
                <small id="delivery-reason">{commandReason(delivery.reason)}</small>
              )}
            {changeEnvironment &&
              item.actions.map((action) => {
                const name = action.action;
                if (
                  (name !== 'START' && name !== 'STOP' && name !== 'ARCHIVE') ||
                  (name === 'ARCHIVE' && item.registration !== 'ACTIVE') ||
                  action.reason === 'MANAGEMENT_ACCESS_DENIED'
                )
                  return null;
                const reason = action.enabled
                  ? null
                  : action.reason === 'MANAGEMENT_RESOURCE_UNVERIFIED'
                    ? name === 'START'
                      ? '宿主尚未核对为正常停止。'
                      : name === 'STOP'
                        ? '尚无可确认的当前运行。'
                        : '宿主尚未核对为正常停止，归档不可用。'
                    : commandReason(action.reason);
                const reasonId = 'environment-action-reason-' + name.toLowerCase();
                return (
                  <span className="runtime-action" key={name}>
                    <button
                      type="button"
                      disabled={!action.enabled || state.waiting || Boolean(state.error)}
                      onClick={() => changeEnvironment(item, name)}
                      aria-describedby={reason ? reasonId : undefined}
                    >
                      {actionNames[name]}
                    </button>
                    {reason && <small id={reasonId}>{reason}</small>}
                  </span>
                );
              })}
            {startRelease && (item.purpose === 'INTEGRATION' || item.purpose === 'DEVELOPMENT') && (
              <button
                type="button"
                disabled={state.waiting || Boolean(state.error)}
                onClick={() => startRelease(item, 'RELEASE')}
              >
                固定发布
              </button>
            )}
            {startRelease &&
              (item.purpose === 'INTEGRATION' || item.purpose === 'DEVELOPMENT') &&
              (['ROLLBACK_CODE', 'RECONFIGURE'] as const).map((action) => (
                <PreparedDeploymentAction
                  key={action}
                  target={item}
                  action={action}
                  unavailable={
                    state.error ? '环境详情暂时无法读取' : state.waiting ? '正在读取环境详情' : null
                  }
                  apply={() => startRelease(item, action)}
                />
              ))}
            {startBackup && (item.purpose === 'INTEGRATION' || item.purpose === 'DEVELOPMENT') && (
              <button
                type="button"
                disabled={state.waiting || Boolean(state.error)}
                onClick={() => startBackup(item)}
              >
                创建恢复点
              </button>
            )}
            {startRestore && (item.purpose === 'INTEGRATION' || item.purpose === 'DEVELOPMENT') && (
              <button
                type="button"
                disabled={state.waiting || Boolean(state.error)}
                onClick={() => startRestore(item)}
              >
                恢复环境
              </button>
            )}
            {item.business && (
              <a href={item.business} target="_blank" rel="noopener noreferrer">
                打开业务入口（新标签）
              </a>
            )}
          </div>
          <div className="detail-grid">
            <section className="card">
              <h2>当前工作</h2>
              <Definitions
                values={[
                  ['负责人', item.owner],
                  ['目标', item.work.goal],
                  ['范围', item.work.scope],
                  ['检查要求', item.work.checks],
                  ['分支', item.work.branch],
                  ['固定基线', <code title={item.baseline}>{short(item.baseline)}</code>],
                ]}
              />
            </section>
            <section className="card">
              <h2>运行与核对</h2>
              <Definitions
                values={[
                  ['实际进程', <Runtime data={item.observation} />],
                  ['最近观察', at(item.observation.observedAt)],
                  ...(item.observation.run
                    ? [['原运行', <code>{item.observation.run}</code>] as const]
                    : []),
                  ['业务入口', item.business ? '已登记' : '尚未登记'],
                  ['记录版本', item.recordVersion],
                  ['分配代次', item.generation],
                ]}
              />
              {item.observation.runtime === 'UNKNOWN' && (
                <p className="muted">当前尚无受管进程的核对结果。</p>
              )}
            </section>
          </div>
          <section className="card lower">
            <h2>登记资源</h2>
            {item.resources.length ? (
              <ul className="resources">
                {item.resources.map((resource) => (
                  <li key={resource.id}>
                    <IconMark />
                    <span>{resourceNames[resource.kind] ?? resource.kind}</span>
                    <Badge label={resource.claimed ? '已占用' : '已释放'} />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="outline" message="该环境尚无资源归属记录。" compact />
            )}
          </section>
          <MaintenanceDetails key={id} id={id} openOperation={showReleaseOperation} />
          <BackupHistory key={id} id={id} />
          <PriorResults key={id} id={id} client={client} />
          <details className="card lower">
            <summary>版本和环境标识</summary>
            <Definitions
              values={[
                ['环境编号', item.id],
                ['工作包编号', item.task],
                ['数据代次', item.work.generation],
                ['部署编号', item.work.deployment],
                ['程序摘要', item.program ?? '尚未登记'],
                ['配置摘要', item.configuration ?? '尚未登记'],
              ]}
            />
          </details>
        </>
      )}
    </Panel>
  );
}

function IconMark() {
  return <span aria-hidden="true" className="mark" />;
}

type OperationTarget = { id: string; byKey: boolean; priorGeneration?: string };
function OperationPage({
  environment,
  session,
  open,
}: {
  environment: string;
  session: Session;
  open: (target: OperationTarget) => void;
}) {
  const [status, setStatus] = useState('');
  const [cursor, setCursor] = useState('');
  const [search, setSearch] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [historyKey, setHistoryKey] = useState<string | null>(null);
  const store = useMemo(() => new ManagementCommandStore(session), [session]);
  const loadHistory = useCallback(
    () => (historyKey ? store.historicalGenerations(historyKey) : Promise.resolve([])),
    [store, historyKey],
  );
  const history = useRead(
    historyKey ?? '',
    loadHistory,
    historyKey !== null && !session.bindingChanged,
  );
  const query = useCallback(
    (signal: AbortSignal) => {
      const filter: Filter = { status, cursor, environment_id: environment };
      return client.operations(filter, signal);
    },
    [environment, status, cursor],
  );
  const state = useRead([environment, status, cursor].join('|'), query);
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      open({ id: uuid(search.trim()), byKey: true });
    } catch {
      setInvalid(true);
    }
  }
  function inspectHistory() {
    try {
      const key = uuid(search.trim());
      if (key === historyKey) history.retry();
      else setHistoryKey(key);
      setInvalid(false);
    } catch {
      setInvalid(true);
    }
  }
  return (
    <Panel title="操作记录">
      <form onSubmit={submit} className="filters lookup">
        <label htmlFor="receipt-key">原请求键</label>
        <input
          id="receipt-key"
          value={search}
          aria-invalid={invalid}
          onChange={(e) => {
            setSearch(e.target.value);
            setInvalid(false);
            setHistoryKey(null);
          }}
          placeholder="输入完整的请求键"
          maxLength={36}
          spellCheck={false}
          required
        />
        <button type="submit">核对原回执</button>
        <button
          type="button"
          onClick={inspectHistory}
          disabled={history.waiting || session.bindingChanged}
        >
          核对旧登记
        </button>
        {invalid && <p role="alert">请输入有效的原请求键。</p>}
      </form>
      {historyKey && !session.bindingChanged && (
        <>
          <ReadStatus state={history} />
          {!history.waiting &&
            !history.error &&
            history.value &&
            (history.value.length ? (
              <div className="filters" aria-label="本机旧登记回执">
                {history.value.map((generation) => (
                  <button
                    key={generation}
                    type="button"
                    title={generation}
                    onClick={() =>
                      open({ id: historyKey, byKey: true, priorGeneration: generation })
                    }
                  >
                    查看旧登记 {short(generation)}
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState icon="history" message="本机没有此请求键的旧登记记录。" compact />
            ))}
        </>
      )}
      <div className="filters">
        <label>
          操作状态
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setCursor('');
            }}
          >
            <option value="">全部状态</option>
            {operationStates.map((key) => (
              <option key={key} value={key}>
                {progress[key]}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={state.retry} disabled={state.waiting}>
          刷新
        </button>
        {environment && <small>仅查看所选环境的操作</small>}
      </div>
      <ReadStatus state={state} />
      {state.value &&
        (state.value.entries.length ? (
          <DataTable labels={['操作', '状态', '提交者', '记录时间']}>
            {state.value.entries.map((item) => (
              <tr key={item.id}>
                <td>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => open({ id: item.id, byKey: false })}
                  >
                    {actionNames[item.action]}
                  </button>
                  <small title={item.id}>{short(item.id)}</small>
                </td>
                <td>
                  <Badge
                    label={progress[item.state] ?? item.state}
                    tone={item.state === 'SUCCEEDED' ? 'positive' : 'neutral'}
                  />
                </td>
                <td>{item.by}</td>
                <td>{at(item.at)}</td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState
            icon="history"
            message={status ? '没有符合当前状态的操作。' : '当前范围内没有操作记录。'}
          />
        ))}
      <div className="pagination">
        {cursor && (
          <button type="button" onClick={() => setCursor('')}>
            返回第一页
          </button>
        )}
        {state.value?.next && (
          <button type="button" onClick={() => setCursor(state.value?.next ?? '')}>
            下一页
          </button>
        )}
      </div>
    </Panel>
  );
}

type Detail = ReturnType<typeof operationDetail>;
type HistoricalDetail = Awaited<ReturnType<ManagementClient['historicalOriginal']>>;
type OperationRecordDetail = Detail & Partial<Pick<HistoricalDetail, 'recoveryDisposition'>>;

function StepDetail({
  step,
  open,
}: {
  step: Detail['steps'][number];
  open: ((target: OperationTarget) => void) | undefined;
}) {
  const result = step.result;
  const title = {
    ATTACH_REGISTERED: '登记回执',
    DELIVERY_REGISTERED: '交付回执',
    RUNTIME_STARTED: '启动核对',
    RUNTIME_STOPPED: '停止核对',
    RELEASE_DEPLOYMENT: '发布核对',
    BACKUP_RECOVERY_POINT: '恢复点核对',
    RESTORE_ENVIRONMENT: '恢复开放核对',
    ENVIRONMENT_ARCHIVED: '归档核对',
    RUNTIME_START_CANCELLED: '取消启动核对',
    RUNTIME_PREPARATION_CANCELLED: '取消启动准备核对',
  }[step.kind];
  return (
    <section className="card lower">
      <div className="summary-line">
        <h2>{title}</h2>
        <Badge label={progress[step.status] ?? step.status} />
      </div>
      {(result?.kind === 'RUNTIME_STARTED' ||
        result?.kind === 'RUNTIME_STOPPED' ||
        result?.kind === 'RUNTIME_START_CANCELLED') && (
        <Definitions
          values={[
            ['原运行', <code>{result.run}</code>],
            [
              '实际结果',
              {
                RUNNING: '应用已就绪',
                STARTED_UNREADY: '进程曾运行，应用未确认就绪',
                STOPPED: '原运行已关闭',
              }[result.state],
            ],
            ['核对时间', at(result.observed)],
            ['证据编号', result.proof],
          ]}
        />
      )}
      {result?.kind === 'RUNTIME_PREPARATION_CANCELLED' && (
        <Definitions
          values={[
            ['实际结果', result.outcome === 'RETIRED' ? '启动准备已撤回' : '准备未改变环境控制'],
            ['控制版本', result.controlRevision],
            ['核对时间', at(result.observed)],
            ['证据编号', result.proof],
          ]}
        />
      )}
      {result?.kind === 'ENVIRONMENT_ARCHIVED' && (
        <Definitions
          values={[
            ['登记状态', '已归档'],
            ['归档时间', at(result.archivedAt)],
            ['环境记录版本', result.recordVersion],
            ['保留内容', '工作区、数据库及原操作回执'],
          ]}
        />
      )}
      {step.wait && (
        <Definitions
          values={[
            [
              '缺少资源',
              step.wait.missing
                .map(
                  (key) =>
                    ({
                      memory_bytes: '内存',
                      cpu_percent: 'CPU',
                      tasks: '进程数',
                      run_slots: '运行槽',
                    })[key],
                )
                .join('、'),
            ],
            ['容量核对时间', at(step.wait.at)],
          ]}
        />
      )}
      {!step.wait &&
        !result &&
        (step.kind === 'RUNTIME_STARTED' || step.kind === 'RUNTIME_STOPPED') && (
          <p className="muted">
            {step.status === 'UNKNOWN'
              ? '等待核对原运行效果。'
              : step.status === 'SKIPPED'
                ? '宿主启动未派发。'
                : '等待宿主执行。'}
          </p>
        )}
      {result?.kind === 'BACKUP_RECOVERY_POINT' && (
        <Definitions
          values={[
            ['恢复点编号', result.point.id],
            ['截止时间', at(result.point.cutoff)],
            ['本机验证', at(result.point.local?.verifiedAt ?? null)],
            ...(result.point.offhost
              ? [['异机取回', at(result.point.offhost.retrievedAt)] as const]
              : []),
            ['源数据代次', result.point.generation],
          ]}
        />
      )}
      {!result && step.kind === 'BACKUP_RECOVERY_POINT' && (
        <p className="muted">等待宿主核验恢复点。</p>
      )}
      {!result && step.kind === 'RELEASE_DEPLOYMENT' && (
        <p className="muted">等待宿主核对发布结果。</p>
      )}
      {!result && step.kind === 'RESTORE_ENVIRONMENT' && step.status !== 'SKIPPED' && (
        <p className="muted">等待宿主核对恢复结果。</p>
      )}
      {(result?.kind === 'RELEASE_DEPLOYMENT' || result?.kind === 'RESTORE_ENVIRONMENT') && (
        <Definitions
          values={[
            ...(result.kind === 'RESTORE_ENVIRONMENT'
              ? [
                  ['源数据代次', result.source] as const,
                  ['选定恢复点', result.backup] as const,
                  ['备份截止时间', at(result.cutoff)] as const,
                ]
              : []),
            ['开放时间', at(result.opened)],
            ['发布编号', result.release],
            ['部署编号', result.deployment],
            ['数据代次', result.dataGeneration],
            ['运行编号', result.run],
            ['登记版本', result.recordVersion],
          ]}
        />
      )}
      {result?.kind === 'ATTACH_REGISTERED' && (
        <Definitions
          values={[
            ['上次准备核对', at(result.observed)],
            ['登记时间', at(result.at)],
            ['数据代次', result.dataGeneration],
            ['配置摘要', result.configuration],
            ['记录版本', result.recordVersion],
          ]}
        />
      )}
      {result?.kind === 'DELIVERY_REGISTERED' && (
        <>
          <Definitions
            values={[
              ['固定提交', <code>{result.commit}</code>],
              ['分支', result.branch],
              ['提交者', result.by],
              ['核对时间', at(result.at)],
              ['登记版本', result.recordVersion],
            ]}
          />
          <h3>独立检查</h3>
          {result.evidence.length ? (
            <ul className="evidence">
              {result.evidence.map((item) => (
                <li key={item.id}>
                  <Badge
                    label={
                      { PASSED: '通过', FAILED: '失败', INCONCLUSIVE: '结果待核实' }[item.result]
                    }
                    tone={item.result === 'PASSED' ? 'positive' : 'warning'}
                  />
                  <span>
                    {at(item.at)} · <code title={item.digest}>{short(item.digest)}</code>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">此交付未附登记的独立检查。</p>
          )}
          {result.manual && (
            <>
              <h3>人工说明</h3>
              <p className="preserve">{result.manual}</p>
            </>
          )}
          {result.uncovered.length > 0 && (
            <>
              <h3>未覆盖</h3>
              <ul>
                {result.uncovered.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {result.sources.length > 0 && (
            <>
              <h3>集成来源</h3>
              <ul>
                {result.sources.map((item) => (
                  <li key={item.operation}>
                    <code>{short(item.commit)}</code>{' '}
                    {open && (
                      <button
                        type="button"
                        onClick={() => open({ id: item.operation, byKey: false })}
                      >
                        查看来源交付
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

function ControlReceipt({
  operationId,
  controlKey,
  priorGeneration,
}: {
  operationId: string;
  controlKey: string;
  priorGeneration: string | undefined;
}) {
  const query = useCallback(
    (signal: AbortSignal) =>
      priorGeneration
        ? client.historicalControl(priorGeneration, operationId, controlKey, signal)
        : client.control(operationId, controlKey, signal),
    [operationId, controlKey, priorGeneration],
  );
  const state = useRead([operationId, controlKey, priorGeneration].join('|'), query);
  const result = state.value;
  return (
    <>
      <ReadStatus state={state} />
      {result && (
        <Definitions
          values={[
            [
              '控制请求',
              { CONTINUE: '继续', CANCEL: '取消', RECONCILE: '核对原结果' }[result.command],
            ],
            [
              '回执结果',
              {
                WAITING_CAPACITY: '等待容量',
                ACCEPTED: '已受理继续',
                CANCELLED: '已取消',
                CANCELLATION_REQUESTED: '已申请取消',
                RECONCILED: '已核对',
              }[result.result],
            ],
            ['原操作版本', result.operationRevision],
            ['记录时间', at(result.recorded)],
          ]}
        />
      )}
    </>
  );
}

function ControlLookup({
  operationId,
  priorGeneration,
}: {
  operationId: string;
  priorGeneration: string | undefined;
}) {
  const [input, setInput] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      setSelected(uuid(input.trim()));
      setInvalid(false);
    } catch {
      setInvalid(true);
    }
  }
  return (
    <section className="card lower">
      <h2>原控制回执</h2>
      <form onSubmit={submit} className="filters lookup">
        <label htmlFor="management-control-key">控制键</label>
        <input
          id="management-control-key"
          value={input}
          aria-invalid={invalid}
          required
          maxLength={36}
          spellCheck={false}
          onChange={(event) => {
            setInput(event.target.value);
            setInvalid(false);
            setSelected(null);
          }}
        />
        <button type="submit">查询控制回执</button>
        {invalid && <p role="alert">请输入有效的原控制键。</p>}
      </form>
      {selected && (
        <ControlReceipt
          operationId={operationId}
          controlKey={selected}
          priorGeneration={priorGeneration}
        />
      )}
    </section>
  );
}

function OperationRecord({
  target,
  back,
  open,
  reconcile,
}: {
  target: OperationTarget;
  back: () => void;
  open: (target: OperationTarget) => void;
  reconcile:
    | {
        commands: ManagementCommands;
        changed: () => void;
        openOriginal: (pending: PendingCommand) => void;
      }
    | undefined;
}) {
  const query = useCallback(
    (signal: AbortSignal): Promise<OperationRecordDetail> => {
      if (target.priorGeneration)
        return client.historicalOriginal(target.priorGeneration, target.id, signal);
      return target.byKey
        ? client.original(target.id, signal)
        : client.operation(target.id, signal);
    },
    [target],
  );
  const state = useRead([target.id, target.byKey, target.priorGeneration].join('|'), query);
  const result = state.value;
  const recoveryDisposition = result?.recoveryDisposition;
  const recoveryDispositionLabels = {
    BACKUP_COMPLETED: '已核实原备份完成。使用备份前须另行核验恢复资产。',
    STOP_COMPLETED: '已核实原停止完成。',
    RESTORE_RETIRED: '已核实原恢复在选择目标前撤回。',
    RELEASE_RETIRED: '已核实原部署变更在选择目标前撤回。',
    OPENED_DEPLOYMENT_ADOPTED: '已将正常停止的目标部署登记到所选管理代次。',
    UNDISPATCHED_CANCELLED: '已核实未派发，等待已结束。',
    UNDISPATCHED_RESERVED_CANCELLED: '已核实未派发，原启动和额度保留已结束。',
    UNSTARTED_OPERATION_CANCELLED: '已核实原操作未派发，已结束等待。',
  };
  const action = result?.original.action;
  const waitingCapacity = action === 'START' && result?.original.state === 'WAITING_CAPACITY';
  const permitted =
    reconcile &&
    (reconcile.commands.session.role === 'MANAGER' ||
      ((action === 'START' || action === 'STOP') &&
        result?.original.by === reconcile.commands.session.principal));
  const controlAction =
    action === 'RELEASE' ||
    action === 'ROLLBACK_CODE' ||
    action === 'RECONFIGURE' ||
    action === 'START' ||
    action === 'STOP' ||
    action === 'ARCHIVE' ||
    action === 'BACKUP' ||
    action === 'RESTORE'
      ? action
      : null;
  return (
    <Panel
      title={result ? (actionNames[result.original.action] ?? '原操作') : '原操作'}
      back={back}
    >
      {target.priorGeneration && <p className="muted">旧登记回执 · 只读</p>}
      <ReadStatus state={state} />
      {result && (
        <>
          <section className="card">
            <h2>操作状态</h2>
            <Definitions
              values={[
                [
                  target.priorGeneration ? '原状态' : '状态',
                  progress[result.original.state] ?? result.original.state,
                ],
                ...(recoveryDisposition
                  ? ([
                      ['恢复核对', recoveryDispositionLabels[recoveryDisposition.kind]],
                      ['处置记录时间', at(recoveryDisposition.recordedAt)],
                    ] as const)
                  : []),
                ['提交者', result.original.by],
                ...(result.original.cancelling && result.original.state !== 'CANCELLED'
                  ? ([['取消请求', '等待核对原运行。']] as [string, string][])
                  : []),
                ['记录时间', at(result.original.at)],
                ['原请求键', <code>{result.original.key}</code>],
                ['操作编号', result.original.id],
              ]}
            />
          </section>
          {result.steps.length ? (
            result.steps.map((step) => (
              <StepDetail
                key={step.ordinal}
                step={step}
                open={target.priorGeneration ? undefined : open}
              />
            ))
          ) : (
            <EmptyState icon="history" message="此操作还没有登记的步骤。" compact />
          )}
          {!target.priorGeneration &&
            reconcile &&
            permitted &&
            controlAction &&
            (waitingCapacity ||
              ['ACCEPTED', 'RUNNING', 'UNKNOWN'].includes(result.original.state)) && (
              <OperationReconcile
                {...reconcile}
                action={controlAction}
                operation={result.original.id}
                revision={result.original.revision}
                waitingCapacity={waitingCapacity}
                canWithdraw={
                  !result.original.cancelling &&
                  result.steps[0]?.status === 'PLANNED' &&
                  (waitingCapacity ||
                    (reconcile.commands.session.role === 'MANAGER' &&
                      (controlAction === 'RELEASE' ||
                        controlAction === 'ROLLBACK_CODE' ||
                        controlAction === 'RECONFIGURE' ||
                        controlAction === 'ARCHIVE' ||
                        controlAction === 'BACKUP' ||
                        controlAction === 'RESTORE') &&
                      result.original.state === 'ACCEPTED'))
                }
                disabled={state.waiting || Boolean(state.error)}
                refresh={state.retry}
              />
            )}
          {(result.original.action === 'START' ||
            result.original.action === 'STOP' ||
            result.original.action === 'ARCHIVE' ||
            result.original.action === 'RELEASE' ||
            result.original.action === 'ROLLBACK_CODE' ||
            result.original.action === 'RECONFIGURE' ||
            result.original.action === 'BACKUP' ||
            result.original.action === 'RESTORE') && (
            <ControlLookup
              key={result.original.id}
              operationId={result.original.id}
              priorGeneration={target.priorGeneration}
            />
          )}
        </>
      )}
    </Panel>
  );
}

const memoryMiB = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });

function memoryDisplay(bytes: number | null, missing: string) {
  return bytes === null ? missing : `${memoryMiB.format(bytes / 1024 ** 2)} MiB`;
}

function CapacityPage() {
  const query = useCallback((signal: AbortSignal) => client.capacity(signal), []);
  const state = useRead('capacity', query);
  const result = state.value;
  return (
    <Panel title="宿主容量">
      <ReadStatus state={state} />
      {result && (
        <section className="card">
          <h2>资源观察</h2>
          <Definitions
            values={[
              ['管理内存额度', memoryDisplay(result.total, '尚未核对')],
              ['已预留内存', memoryDisplay(result.reserved, '尚未核对')],
              ['宿主可用内存', memoryDisplay(result.available, '暂无法观测')],
              ['可见的等待操作', result.waiting],
              ['观察时间', at(result.at)],
            ]}
          />
        </section>
      )}
    </Panel>
  );
}

type CommandView =
  | { kind: 'ATTACH'; archivedEnvironment?: string }
  | { kind: 'DELIVERY'; target: Environment }
  | { kind: 'RELEASE'; target: Environment; action: ReleaseAction }
  | { kind: 'BACKUP'; target: Environment }
  | { kind: 'RESTORE'; target: Environment }
  | { kind: 'ENVIRONMENT_ACTION'; target: Environment; action: EnvironmentAction }
  | { kind: 'PENDING' }
  | { kind: 'ORIGINAL'; record: PendingCommand };

function App() {
  const start = useCallback((signal: AbortSignal) => client.check(signal), []);
  const identity = useRead('identity', start);
  const session = useSyncExternalStore(client.subscribe, client.current);
  const owner = session
    ? [session.config.manager, session.config.generation, session.principal, session.role].join('|')
    : 'connecting';
  return <ManagementWorkspace key={owner} session={session} identity={identity} />;
}

function ManagementWorkspace({
  session,
  identity,
}: {
  session: Session | null;
  identity: ReturnType<typeof useRead<Session>>;
}) {
  const [tab, setTab] = useState<'environment' | 'operation' | 'capacity'>('environment');
  const [environment, setEnvironment] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [operation, setOperation] = useState<OperationTarget | null>(null);
  const [commandView, setCommandView] = useState<CommandView | null>(null);
  const [localRevision, localChange] = useState(0);
  const commands = useMemo(
    () => (session ? new ManagementCommands(client, session) : null),
    [session],
  );
  const changed = useCallback(() => localChange((value) => value + 1), []);
  const local = useRead(
    (commands?.store.scopeId ?? '') + '|' + localRevision,
    useCallback(() => commands?.store.list() ?? Promise.resolve([]), [commands]),
    commands !== null,
  );
  const registration = session?.actions.find((action) => action.action === 'ATTACH');
  const readOnly = session?.phase === 'BLOCKED' && !session.bindingChanged;
  const links = [
    ['environment', '环境'],
    ['operation', '操作记录'],
    ['capacity', '宿主容量'],
  ] as const;
  function navigate(page: typeof tab) {
    setTab(page);
    setEnvironment(null);
    setOperation(null);
    setFilter('');
    setCommandView(null);
  }
  function openReceipt(id: string) {
    navigate('operation');
    setOperation({ id, byKey: false });
  }
  function closeCommand() {
    setCommandView(null);
  }
  return (
    <>
      <header>
        <div className="brand">
          <span className="brand-icon" aria-hidden="true">
            W
          </span>
          <div>
            <strong>{session?.config.name ?? 'WALL-E 环境管理'}</strong>
            <p>WALL-E · 环境管理</p>
          </div>
        </div>
        {session && (
          <div className="identity">
            <Badge label={roleNames[session.role] ?? session.role} />
            <span>{session.principal}</span>
          </div>
        )}
      </header>
      {session && (
        <nav aria-label="管理导航">
          {links.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-current={tab === id ? 'page' : undefined}
              onClick={() => navigate(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      )}
      <main>
        {(identity.waiting || identity.error) && <ReadStatus state={identity} />}
        {!session && !identity.waiting && !identity.error && <p role="status">正在核对管理身份…</p>}
        {session?.bindingChanged && (
          <div className="feedback error" role="alert">
            <span>管理入口或登记代次已变化。当前页保留本机原请求及其原作用域。</span>
            <button type="button" onClick={() => window.location.reload()}>
              重新进入管理页
            </button>
          </div>
        )}
        {readOnly && (
          <div className="feedback summary-line">
            <span role="status">管理登记当前只读。可以查看环境、原操作和回执。</span>
            <button type="button" disabled={identity.waiting} onClick={identity.retry}>
              更新写入状态
            </button>
          </div>
        )}
        {session?.phase === 'RECOVERING' && (
          <p role="status" className="feedback">
            部分原操作正在核对。各环境按自身状态开放操作。
          </p>
        )}
        {commands && !commandView && (Boolean(local.value?.length) || tab === 'operation') && (
          <div className="summary-line local-actions">
            <button type="button" onClick={() => setCommandView({ kind: 'PENDING' })}>
              本机待核对{local.value?.length ? '（' + local.value.length + '）' : ''}
            </button>
          </div>
        )}
        {commands && commandView?.kind === 'ATTACH' && (
          <AttachForm
            key={commandView.archivedEnvironment ?? 'new-attachment'}
            commands={commands}
            archivedEnvironment={commandView.archivedEnvironment}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'DELIVERY' && (
          <DeliveryForm
            commands={commands}
            target={commandView.target}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'ENVIRONMENT_ACTION' && (
          <EnvironmentActionForm
            commands={commands}
            target={commandView.target}
            action={commandView.action}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'BACKUP' && (
          <BackupForm
            commands={commands}
            target={commandView.target}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'RELEASE' && (
          <ReleaseForm
            commands={commands}
            target={commandView.target}
            action={commandView.action}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'RESTORE' && (
          <RestoreForm
            commands={commands}
            target={commandView.target}
            back={closeCommand}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {commands && commandView?.kind === 'PENDING' && (
          <PendingList
            commands={commands}
            back={closeCommand}
            revision={localRevision}
            select={(record) => setCommandView({ kind: 'ORIGINAL', record })}
          />
        )}
        {commands && commandView?.kind === 'ORIGINAL' && (
          <OriginalCommand
            commands={commands}
            original={commandView.record}
            back={() => setCommandView({ kind: 'PENDING' })}
            changed={changed}
            openReceipt={openReceipt}
          />
        )}
        {session &&
          !commandView &&
          tab === 'environment' &&
          (environment ? (
            <EnvironmentDetail
              id={environment}
              back={() => setEnvironment(null)}
              deliver={
                session.role === 'VIEWER' || session.phase === 'BLOCKED'
                  ? undefined
                  : (target) => setCommandView({ kind: 'DELIVERY', target })
              }
              changeEnvironment={
                session.role !== 'VIEWER' && session.phase !== 'BLOCKED'
                  ? (target, action) =>
                      setCommandView({ kind: 'ENVIRONMENT_ACTION', target, action })
                  : undefined
              }
              reattach={
                session.role === 'MANAGER' && session.phase !== 'BLOCKED'
                  ? () => setCommandView({ kind: 'ATTACH', archivedEnvironment: environment })
                  : undefined
              }
              startBackup={
                session.role === 'MANAGER' && session.phase !== 'BLOCKED'
                  ? (target) => setCommandView({ kind: 'BACKUP', target })
                  : undefined
              }
              startRestore={
                session.role === 'MANAGER' && session.phase !== 'BLOCKED'
                  ? (target) => setCommandView({ kind: 'RESTORE', target })
                  : undefined
              }
              startRelease={
                session.role === 'MANAGER' && session.phase !== 'BLOCKED'
                  ? (target, action) => setCommandView({ kind: 'RELEASE', target, action })
                  : undefined
              }
              showReleaseOperation={(id) => {
                setFilter(environment);
                setOperation({ id, byKey: false });
                setTab('operation');
              }}
              showOperations={() => {
                setFilter(environment);
                setTab('operation');
              }}
            />
          ) : (
            <EnvironmentPage
              open={setEnvironment}
              attach={
                session.role !== 'MANAGER'
                  ? undefined
                  : {
                      start: () => setCommandView({ kind: 'ATTACH' }),
                      reason: readOnly
                        ? '管理登记当前只读。'
                        : session.phase !== 'READY'
                          ? '管理登记仍在核对。'
                          : registration?.enabled
                            ? null
                            : commandReason(registration?.reason ?? null),
                    }
              }
            />
          ))}
        {session &&
          !commandView &&
          tab === 'operation' &&
          (operation ? (
            <OperationRecord
              target={operation}
              open={setOperation}
              back={() => setOperation(null)}
              reconcile={
                !operation.priorGeneration &&
                commands &&
                session.role !== 'VIEWER' &&
                session.phase !== 'BLOCKED'
                  ? {
                      commands,
                      changed,
                      openOriginal: (record) => setCommandView({ kind: 'ORIGINAL', record }),
                    }
                  : undefined
              }
            />
          ) : (
            <OperationPage environment={filter} session={session} open={setOperation} />
          ))}
        {session && !commandView && tab === 'capacity' && <CapacityPage />}
      </main>
    </>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing management mount');
createRoot(container).render(<App />);
