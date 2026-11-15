import type { AuthorizationScope } from '../../api/code-authorizations.ts';
import { useCallback, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiUnknown } from '../../api/client.ts';
import type { PagePagination } from '../../api/client.ts';
import { AUTHORIZATION_STATUSES } from '../../api/code-authorizations.ts';
import type {
  AuthorizationFilters,
  AuthorizationGrant,
  AuthorizationStatus,
} from '../../api/code-authorizations.ts';
import type { WalleApi } from '../../api/walle.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { RecordList } from '../../shared/record-list.tsx';
import { Pagination } from '../../shared/pagination.tsx';
import { SingleSelect } from '../../shared/single-select.tsx';
import { localTime } from '../../shared/time.ts';
import { useSettingsRead, useSettingsVisibility } from './read.ts';

const labels: Record<AuthorizationStatus, string> = {
  APPROVED_UNBOUND: '已批准，未绑定任务',
  BOUND_PENDING_APPLY: '已绑定，等待生效',
  EFFECTIVE: '已生效',
  APPLY_FAILED: '生效失败',
  APPLY_UNKNOWN: '生效结果待核对',
  RETIRED: '已退役',
};
const options = [
  { value: '', label: '全部状态' },
  ...AUTHORIZATION_STATUSES.map((status) => ({ value: status, label: labels[status] })),
];

type AuthorizationPage = Readonly<{
  items: readonly AuthorizationGrant[];
  pagination: PagePagination;
  filters: AuthorizationFilters;
}>;

function AuthorizationDetails({
  api,
  id,
  visible,
}: Readonly<{
  api: WalleApi;
  id: number;
  visible: boolean;
}>) {
  const [attempt, retry] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      return (await api.codeAuthorization(id, signal)).data;
    },
    [api, id, attempt],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取授权详情');
  const authorization = state.value;
  const scope = authorization?.scope;
  return (
    <section
      className="code-settings-resource-detail"
      aria-label="授权详情"
      aria-busy={state.loading}
    >
      <header className="code-settings-section-heading">
        <h3>授权 #{id}</h3>
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
      {state.error && authorization && <p className="read-status">显示上次读取的授权详情</p>}
      {authorization && scope && (
        <>
          <dl className="code-settings-resource-facts">
            <dt>状态</dt>
            <dd>{labels[authorization.status]}</dd>
            <dt>关联任务</dt>
            <dd>{authorization.task_id === null ? '未绑定' : '任务 #' + authorization.task_id}</dd>
            <dt>执行配置版本</dt>
            <dd>#{authorization.profile_version_id}</dd>
            <dt>批准时间</dt>
            <dd>
              <time dateTime={authorization.approved_at}>
                {localTime(authorization.approved_at)}
              </time>
            </dd>
            <AuthorizationScopeFacts scope={scope} />
          </dl>
        </>
      )}
    </section>
  );
}

const managedReadRootNames: Readonly<Record<string, string>> = {
  'READ20-WORKSPACE-1': '任务工作区',
  'READ20-BASIS-1': '任务固定依据',
};

export function AuthorizationScopeFacts({ scope }: Readonly<{ scope: AuthorizationScope }>) {
  return (
    <>
      <dt>目录读取</dt>
      <dd>
        {scope.read_roots.length
          ? scope.read_roots.map((ref) => managedReadRootNames[ref] ?? ref).join('、')
          : '未批准读取目录'}
      </dd>
      <dt>写入范围</dt>
      <dd>仅任务工作区</dd>
      <dt>允许命令</dt>
      <dd>
        {scope.allowed_command_ids.length ? scope.allowed_command_ids.join('、') : '未批准命令'}
      </dd>
      <dt>网络目标</dt>
      <dd>{scope.network_targets.length ? scope.network_targets.join('、') : '未批准网络目标'}</dd>
      <dt>允许模型</dt>
      <dd>
        {scope.model_profile_refs.length ? scope.model_profile_refs.join('、') : '未批准模型'}
      </dd>
      <dt>本地交付</dt>
      <dd>{scope.allow_local_delivery ? '已批准' : '未批准'}</dd>
      <dt>运行时长上限</dt>
      <dd>{scope.limits.max_active_seconds} 秒</dd>
      <dt>模型请求上限</dt>
      <dd>{scope.limits.max_model_requests} 次</dd>
      <dt>输出上限</dt>
      <dd>{scope.limits.max_output_tokens} Token</dd>
    </>
  );
}

export function AuthorizationSettings({ api }: Readonly<{ api: WalleApi }>) {
  const [task, setTask] = useState('');
  const [status, setStatus] = useState('');
  const [filterError, setFilterError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AuthorizationFilters>({});
  const [page, setPage] = useState(1);
  const [attempt, retry] = useState(0);
  const [selected, select] = useState<number | null>(null);
  const visible = useSettingsVisibility();
  const load = useCallback(
    async (signal: AbortSignal): Promise<AuthorizationPage> => {
      const result = await api.codeAuthorizations(page, filters, signal);
      const pagination = result.meta.pagination;
      if (pagination === undefined || !('page' in pagination)) throw new ApiUnknown(false);
      return { items: result.data.items, pagination, filters };
    },
    [api, page, filters, attempt],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取授权列表');
  const last = state.value;
  const saved =
    last !== null &&
    last.filters.task_id === filters.task_id &&
    last.filters.status === filters.status
      ? last
      : null;
  const filtered = filters.task_id !== undefined || filters.status !== undefined;
  const overflow =
    saved !== null && saved.pagination.page > Math.max(1, saved.pagination.total_pages);
  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = task.trim();
    const taskId = text ? Number(text) : null;
    if (taskId !== null && (!/^[1-9][0-9]*$/.test(text) || !Number.isSafeInteger(taskId))) {
      setFilterError('请输入有效的任务 ID');
      return;
    }
    const current = AUTHORIZATION_STATUSES.find((option) => option === status);
    setFilterError(null);
    setPage(1);
    select(null);
    setFilters({
      ...(taskId === null ? {} : { task_id: taskId }),
      ...(current === undefined ? {} : { status: current }),
    });
  }
  const reread = () => retry((value) => value + 1);
  return (
    <section className="code-settings-resource" aria-label="授权">
      <h2>授权</h2>
      <RecordList
        title="执行授权"
        total={saved?.pagination.total ?? null}
        loading={state.loading}
        error={state.error}
        retry={reread}
        retryDisabled={state.loading}
        items={(saved?.items ?? []).map((row) => ({
          id: row.id,
          title: '授权 #' + row.id,
          metadata: labels[row.status],
          description: row.task_id === null ? '未绑定任务' : '任务 #' + row.task_id,
          selected: selected === row.id,
          label: '查看授权 ' + row.id,
          disabled: false,
          open: () => select(row.id),
        }))}
        empty={{
          icon: 'settings',
          message: overflow
            ? '本页暂无授权，请返回有效页'
            : filtered
              ? '没有匹配的授权'
              : '暂无执行授权',
        }}
        filters={
          <form
            className="code-settings-authorization-filters"
            aria-label="筛选授权"
            onSubmit={applyFilters}
          >
            <label htmlFor="authorization-task">任务 ID</label>
            <input
              className="ui-input"
              id="authorization-task"
              inputMode="numeric"
              value={task}
              onChange={(event) => {
                setTask(event.target.value);
                setFilterError(null);
              }}
              aria-invalid={filterError !== null}
              aria-describedby={filterError ? 'authorization-filter-error' : undefined}
            />
            <SingleSelect label="授权状态" value={status} options={options} change={setStatus} />
            <button type="submit" className="ui-button" disabled={state.loading}>
              {state.loading ? '正在读取…' : '应用筛选'}
            </button>
            {filterError && (
              <p id="authorization-filter-error" className="inline-error" role="alert">
                {filterError}
              </p>
            )}
          </form>
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
        <EmptyState icon="settings" compact message="请选择授权查看详情" />
      ) : (
        <AuthorizationDetails key={selected} api={api} id={selected} visible={visible} />
      )}
    </section>
  );
}
