import { useCallback, useState } from 'react';
import { ApiUnknown } from '../../api/client.ts';
import type { ConfigurationIdentityKind } from '../../api/code-configuration-identities.ts';
import type {
  ConfigurationOption,
  ConfigurationOptionKind,
} from '../../api/code-configuration-options.ts';
import type { WalleApi } from '../../api/walle.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { Pagination } from '../../shared/pagination.tsx';
import { SingleSelect } from '../../shared/single-select.tsx';
import { useSettingsRead, useSettingsVisibility } from './read.ts';

type CatalogApi = Pick<WalleApi, 'codeConfigurationOptions'>;
const names: Readonly<Record<ConfigurationOptionKind, string>> = {
  EXECUTOR: '执行器',
  MODEL: '模型',
  RUNTIME: '运行环境',
  COMMAND: '登记命令',
  RUNNER: '检查运行器',
  SCOPE: '执行范围',
  PRICE: '计价版本',
  SECRET_REF: '秘密引用',
  CAPABILITY: '能力证据',
  CONTENT_POLICY: '内容策略',
  GIT: 'Git 工具',
  CASE_PACK: '用例包',
};
const kinds: Readonly<Record<ConfigurationIdentityKind, readonly ConfigurationOptionKind[]>> = {
  EXECUTION_PROFILE: [
    'EXECUTOR',
    'MODEL',
    'RUNTIME',
    'COMMAND',
    'SCOPE',
    'PRICE',
    'SECRET_REF',
    'CAPABILITY',
    'CONTENT_POLICY',
    'GIT',
  ],
  CHECK_SET: ['COMMAND', 'RUNNER', 'CASE_PACK', 'CAPABILITY'],
};

function registeredVersion(value: ConfigurationOption['value']) {
  if ('version' in value) return value.version;
  if ('model_profile_ref' in value) return value.model_profile_ref;
  if ('scope_ref' in value) return value.scope_ref;
  return value.content_policy_version + ' · ' + value.secret_policy_ref;
}

function CatalogPage({ api, kind }: { api: CatalogApi; kind: ConfigurationOptionKind }) {
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const visible = useSettingsVisibility();
  const load = useCallback(
    async (signal: AbortSignal) => {
      const result = await api.codeConfigurationOptions(kind, page, signal);
      const pagination = result.meta.pagination;
      if (pagination === undefined || !('page' in pagination)) throw new ApiUnknown(false);
      return { items: result.data.items, pagination };
    },
    [api, kind, page, attempt],
  );
  const state = useSettingsRead(load, visible, '暂时无法读取配置资源');
  const last = state.value;
  const overflow = last !== null && last.pagination.page > Math.max(1, last.pagination.total_pages);
  return (
    <div aria-busy={state.loading}>
      {state.loading && <p role="status">正在读取资源…</p>}
      {state.error && (
        <>
          <p className="inline-error" role="alert">
            {state.error}
          </p>
          <button type="button" className="ui-button" onClick={() => setAttempt(attempt + 1)}>
            重试读取资源
          </button>
          {last !== null && <p className="read-status">显示上次读取的资源</p>}
        </>
      )}
      {last !== null && last.items.length > 0 && (
        <ol className="code-settings-version-items">
          {last.items.map((option) => (
            <li key={option.option_id}>
              <div className="code-settings-pending-heading">
                <strong>{option.label}</strong>
                <span>{option.ready ? '可用' : '尚未就绪'}</span>
              </div>
              <p>{registeredVersion(option.value)}</p>
              <p>待准备条件　{option.unresolved_capability_codes.join('、')}</p>
            </li>
          ))}
        </ol>
      )}
      {last !== null && last.items.length === 0 && !state.loading && !state.error && (
        <EmptyState
          icon="settings"
          message={overflow ? '本页暂无资源，请返回有效页' : '暂无已登记的' + names[kind]}
          compact
        />
      )}
      {last !== null &&
        (overflow && last.pagination.total === 0 ? (
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
            value={last.pagination}
            loading={state.loading}
            compactSingle
            showLoadingStatus={false}
            change={setPage}
          />
        ))}
    </div>
  );
}

export function ConfigurationCatalog({
  api,
  identityKind,
}: {
  api: CatalogApi;
  identityKind: ConfigurationIdentityKind;
}) {
  const [kind, setKind] = useState<ConfigurationOptionKind | null>(null);
  const allowed = kinds[identityKind];
  function select(value: string) {
    setKind(allowed.find((option) => option === value) ?? null);
  }
  return (
    <section className="code-settings-versions" aria-label="配置资源目录">
      <header className="code-settings-section-heading">
        <h3>配置资源目录</h3>
        <SingleSelect
          label="资源类型"
          value={kind ?? ''}
          placeholder="请选择资源类型"
          options={allowed.map((value) => ({ value, label: names[value] }))}
          change={select}
        />
      </header>
      {kind === null ? (
        <EmptyState icon="settings" message="请选择要查看的资源类型" compact />
      ) : (
        <CatalogPage key={kind} api={api} kind={kind} />
      )}
    </section>
  );
}
