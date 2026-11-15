import { useCallback, useId, useState, useSyncExternalStore } from 'react';
import { ApiRejected, ApiUnknown } from '../../api/client.ts';
import type { PagePagination } from '../../api/client.ts';
import type { RepositoryListItem } from '../../api/code-repositories.ts';
import type { WalleApi } from '../../api/walle.ts';
import { RecordList } from '../../shared/record-list.tsx';
import { Pagination } from '../../shared/pagination.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { useSettingsRead, useSettingsVisibility } from './read.ts';
import { ERROR_MESSAGES } from '../../api/code-errors.ts';
import type { CodeErrorCode } from '../../api/code-errors.ts';
import { CommandStorageError } from '../command-recovery-store.ts';
import type { CommandRecovery } from '../command-recovery.ts';
import type { RepositoryRefreshResult } from './settings.tsx';
import type { PendingSummary } from '../command-recovery-model.ts';
import type { RepositoryRegistrationOwner } from './repository-registration-owner.ts';
import { RepositoryRegistration } from './repository-registration-view.tsx';

type RepositoryPage = Readonly<{
  items: readonly RepositoryListItem[];
  pagination: PagePagination;
}>;

function observationLabel(observation: RepositoryListItem['latest_observation']): string {
  if (observation === null) return '暂无已保存观察';
  if (observation.status === 'READABLE') return '上次观察可读';
  if (observation.status === 'UNAVAILABLE') return '上次观察不可用';
  return '上次观察结果待核对';
}

function SavedObservation({
  api,
  repositoryId,
  observationId,
  visible,
}: Readonly<{
  api: WalleApi;
  repositoryId: number;
  observationId: number;
  visible: boolean;
}>) {
  const [attempt, retry] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      const result = await api.repositoryObservation(repositoryId, observationId, signal);
      return result.data;
    },
    [api, repositoryId, observationId, attempt],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取原观察');
  const data = state.value;
  return (
    <section
      className="code-settings-observation"
      aria-label="已保存观察"
      aria-busy={state.loading}
    >
      <h4>已保存观察 #{data?.id ?? observationId}</h4>
      {state.loading && <p role="status">正在读取原观察…</p>}
      {state.error && (
        <p className="inline-error" role="alert">
          {state.error}{' '}
          <button type="button" className="ui-button" onClick={() => retry((value) => value + 1)}>
            重试读取观察
          </button>
        </p>
      )}
      {data && data.id !== observationId && <p className="read-status">显示上次读取的观察</p>}
      {data && (
        <>
          <p>
            {observationLabel(data)} ·{' '}
            <time dateTime={data.observed_at}>{localTime(data.observed_at)}</time>
          </p>
          {data.status === 'READABLE' && (
            <>
              <p>HEAD　{data.head_commit ?? '未指向提交'}</p>
              <h4>本地分支</h4>
              {data.local_branches.length ? (
                <ul>
                  {data.local_branches.map((branch) => (
                    <li key={branch.full_ref}>
                      {branch.full_ref} · <code>{branch.commit_oid}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon="outline" compact message="此次观察未记录本地分支" />
              )}
              <h4>工作树</h4>
              {data.worktrees.length ? (
                <ul>
                  {data.worktrees.map((tree) => (
                    <li key={tree.canonical_path}>
                      {tree.canonical_path} · {tree.branch_ref ?? '无分支'}
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon="workbench" compact message="此次观察未记录工作树" />
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

type RefreshControl = Readonly<{
  recovery: Pick<CommandRecovery, 'stageIntent' | 'send'>;
  pending: PendingSummary | null;
  result: RepositoryRefreshResult | null;
  recoveryKnown: boolean;
  recoveryLoading: boolean;
  changed(): Promise<void>;
}>;

const refreshStatus = {
  PENDING: '等待读取仓库',
  RUNNING: '正在读取仓库',
  SUCCEEDED: '仓库观察已保存',
  FAILED: '仓库读取失败',
  UNKNOWN: '仓库读取结果待核对',
  CANCELLED: '仓库读取已取消',
};

function repositoryRefreshPath(id: number) {
  return '/api/v1/code-repositories/' + id + '/refresh';
}

function RefreshRepository({
  id,
  disabled,
  control,
}: Readonly<{ id: number; disabled: boolean; control: RefreshControl }>) {
  const { recovery, pending, result, recoveryKnown, recoveryLoading, changed } = control;
  const [submitting, setSubmitting] = useState(false);
  const [attemptKey, setAttemptKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const statusId = useId();
  const operation =
    pending === null || result?.operation.idempotency_key === pending.key
      ? result?.operation
      : undefined;
  const operationId = pending?.operation_id ?? operation?.id;
  let disabledReason: string | null = null;
  if (submitting) disabledReason = '正在提交读取请求';
  else if (pending !== null) disabledReason = '请先核对当前仓库的原读取请求';
  else if (!recoveryKnown || recoveryLoading) disabledReason = '请先核对待处理请求';
  else if (disabled) disabledReason = '请先重新读取仓库详情';

  async function submit() {
    if (disabledReason !== null) return;
    setError(null);
    setAttemptKey(null);
    setSubmitting(true);
    try {
      const staged = await recovery.stageIntent(repositoryRefreshPath(id), {});
      if (staged.kind !== 'PREPARED') {
        setError('已有原请求，请先核对原结果');
        return;
      }
      setAttemptKey(staged.record.key);
      await recovery.send(staged.record.key, staged.record.record_revision);
    } catch (cause) {
      setError(
        cause instanceof ApiRejected ||
          cause instanceof ApiUnknown ||
          cause instanceof CommandStorageError
          ? cause.message
          : '暂时无法确认读取请求，请核对原结果',
      );
    } finally {
      try {
        await changed();
      } finally {
        setSubmitting(false);
      }
    }
  }

  return (
    <div aria-label="读取仓库信息" aria-busy={submitting}>
      <div className="code-settings-form-actions">
        <button
          type="button"
          className="ui-button"
          disabled={disabledReason !== null}
          aria-describedby={statusId}
          onClick={() => void submit()}
        >
          {submitting ? '正在提交…' : '读取仓库信息'}
        </button>
        <p id={statusId} className="read-status" role="status">
          {disabledReason}
        </p>
        {pending && (
          <button
            type="button"
            className="ui-button"
            disabled={recoveryLoading}
            title={recoveryLoading ? '正在核对原读取请求' : '查询原读取请求'}
            onClick={() => void changed()}
          >
            核对原读取请求
          </button>
        )}
      </div>
      {error && (attemptKey === null || operation?.idempotency_key !== attemptKey) && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {operationId !== undefined && (
        <p role="status">
          原操作 #{operationId} ·{' '}
          {operation ? refreshStatus[operation.status] : '已接收，结果待核对'}
        </p>
      )}
      {operation?.failure_code && (
        <p className="inline-error" role="alert">
          {ERROR_MESSAGES[operation.failure_code as CodeErrorCode]}
        </p>
      )}
    </div>
  );
}

function RepositoryDetailPanel({
  api,
  id,
  visible,
  refresh,
}: Readonly<{ api: WalleApi; id: number; visible: boolean; refresh: RefreshControl }>) {
  const [attempt, retry] = useState(0);
  const [chosen, setChosen] = useState<Readonly<{ id: number; baseline: number | null }> | null>(
    null,
  );
  const original = refresh.result?.observationId ?? null;
  const observation = chosen?.baseline === original ? chosen.id : original;
  const load = useCallback(
    async (signal: AbortSignal) => {
      const result = await api.codeRepository(id, signal);
      return result.data;
    },
    [api, id, attempt, original],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取仓库详情');
  const data = state.value;
  const latest = data?.latest_observation ?? null;
  return (
    <section
      className="code-settings-resource-detail"
      aria-label="仓库详情"
      aria-busy={state.loading}
    >
      <header className="code-settings-section-heading">
        <h3>{data ? data.name : '仓库 #' + id}</h3>
        <button
          type="button"
          className="ui-button"
          disabled={state.loading}
          onClick={() => retry((value) => value + 1)}
        >
          {state.loading ? '正在读取详情…' : '重新读取详情'}
        </button>
      </header>
      {state.error && (
        <p className="inline-error" role="alert">
          {state.error}
        </p>
      )}
      {state.error && data && <p className="read-status">显示上次读取的仓库详情</p>}
      {data && (
        <>
          <dl className="code-settings-resource-facts">
            <dt>本地路径</dt>
            <dd>
              <code>{data.root_path}</code>
            </dd>
            <dt>对象格式</dt>
            <dd>{data.object_format}</dd>
            <dt>登记时间</dt>
            <dd>
              <time dateTime={data.created_at}>{localTime(data.created_at)}</time>
            </dd>
            <dt>最近观察</dt>
            <dd>
              {observationLabel(latest)}
              {latest && (
                <>
                  {' '}
                  · <time dateTime={latest.observed_at}>{localTime(latest.observed_at)}</time>
                </>
              )}
            </dd>
          </dl>
          <RefreshRepository
            id={id}
            control={refresh}
            disabled={!visible || state.loading || state.error !== null}
          />
          {latest && latest.id !== observation && (
            <button
              type="button"
              className="ui-button"
              onClick={() => setChosen({ id: latest.id, baseline: original })}
            >
              查看已保存观察
            </button>
          )}
        </>
      )}
      {observation !== null && (
        <SavedObservation
          api={api}
          repositoryId={id}
          observationId={observation}
          visible={visible}
        />
      )}
    </section>
  );
}

export function RepositorySettings({
  api,
  registration,
  pending,
  recovery,
  refreshes,
  refreshRecords,
  recoveryKnown,
  recoveryLoading,
  changed,
}: Readonly<{
  api: WalleApi;
  registration: RepositoryRegistrationOwner;
  pending: PendingSummary | null;
  recovery: RefreshControl['recovery'];
  refreshes: Readonly<Record<number, RepositoryRefreshResult>>;
  refreshRecords: readonly PendingSummary[];
  recoveryKnown: boolean;
  recoveryLoading: boolean;
  changed(): Promise<void>;
}>) {
  const { operation } = useSyncExternalStore(registration.subscribe, registration.getSnapshot);
  const savedRegistration = operation?.status === 'SUCCEEDED' ? operation.resource_id : null;
  const [page, setPage] = useState(1);
  const [attempt, retry] = useState(0);
  const [selected, select] = useState<number | null>(null);
  const visible = useSettingsVisibility();
  const load = useCallback(
    async (signal: AbortSignal): Promise<RepositoryPage> => {
      const response = await api.codeRepositories(page, signal);
      const pagination = response.meta.pagination;
      if (pagination === undefined || !('page' in pagination)) throw new ApiUnknown(false);
      return { items: response.data.items, pagination };
    },
    [api, page, attempt, savedRegistration],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取仓库列表');
  const saved = state.value;
  const overflow =
    saved !== null && saved.pagination.page > Math.max(1, saved.pagination.total_pages);
  const reread = () => retry((value) => value + 1);
  return (
    <section className="code-settings-resource" aria-label="仓库">
      <h2>仓库</h2>
      <RepositoryRegistration
        owner={registration}
        pending={pending}
        recoveryKnown={recoveryKnown}
        changed={changed}
        openRepository={select}
      />
      <RecordList
        title="已登记仓库"
        total={saved?.pagination.total ?? null}
        loading={state.loading}
        error={state.error}
        retry={reread}
        retryDisabled={state.loading}
        items={(saved?.items ?? []).map((row) => ({
          id: row.id,
          title: row.name,
          metadata: observationLabel(row.latest_observation),
          label: '查看仓库 ' + row.name,
          selected: selected === row.id,
          disabled: false,
          open: () => select(row.id),
        }))}
        empty={{
          icon: 'workbench',
          message: overflow ? '本页暂无仓库，请返回有效页' : '暂无已登记仓库',
        }}
        filters={
          <button type="button" className="ui-button" disabled={state.loading} onClick={reread}>
            {state.loading ? '正在读取列表…' : '重新读取仓库列表'}
          </button>
        }
        footer={
          saved &&
          (overflow && saved.pagination.total === 0 ? (
            <button
              type="button"
              className="ui-button"
              disabled={state.loading}
              onClick={() => setPage(1)}
            >
              返回有效页
            </button>
          ) : (
            <Pagination
              value={saved.pagination}
              loading={state.loading}
              showLoadingStatus={false}
              compactSingle
              change={setPage}
            />
          ))
        }
      />
      {selected === null ? (
        <EmptyState icon="workbench" compact message="请选择仓库查看详情" />
      ) : (
        <RepositoryDetailPanel
          key={selected}
          api={api}
          id={selected}
          visible={visible}
          refresh={{
            recovery,
            pending:
              refreshRecords.find((record) => record.path === repositoryRefreshPath(selected)) ??
              null,
            result: refreshes[selected] ?? null,
            recoveryKnown,
            recoveryLoading,
            changed,
          }}
        />
      )}
    </section>
  );
}
