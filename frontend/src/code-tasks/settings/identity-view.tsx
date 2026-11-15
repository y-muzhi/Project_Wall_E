import { useSyncExternalStore } from 'react';
import type { FormEvent } from 'react';
import type { WalleApi } from '../../api/walle.ts';
import { RecordList } from '../../shared/record-list.tsx';
import { Pagination } from '../../shared/pagination.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import type { IdentitySettingsOwner } from './identity-owner.ts';
import { ConfigurationVersionDetails } from './version-details.tsx';

import { ConfigurationCatalog } from './configuration-catalog.tsx';

export function IdentitySettings({
  api,
  owner,
  changed,
}: Readonly<{
  api: Pick<WalleApi, 'codeConfigurationOptions'>;
  owner: IdentitySettingsOwner;
  changed(): void;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  const label = owner.kind === 'EXECUTION_PROFILE' ? '执行配置' : '检查配置';
  const disabledReason = state.busy
    ? '正在提交原请求'
    : state.blockedKey !== null
      ? '已有原请求待核对，请在待核对操作区域查询原结果'
      : null;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await owner.submit();
    changed();
  }
  const identities = state.identities;
  const versions = state.versions;
  return (
    <section className="code-settings-resource" aria-label={label}>
      <h2>{label}</h2>
      <form
        className="code-settings-create"
        onSubmit={(event) => void submit(event)}
        aria-label={'创建' + label}
        aria-busy={state.busy}
      >
        <label htmlFor={'name-' + owner.kind}>新配置名称</label>
        <input
          id={'name-' + owner.kind}
          name="name"
          className="ui-input"
          value={state.name}
          autoComplete="off"
          disabled={disabledReason !== null}
          onChange={(event) => owner.edit(event.target.value)}
          aria-describedby={'create-status-' + owner.kind}
        />
        <div className="code-settings-form-actions">
          <button
            type="submit"
            className="ui-button"
            disabled={disabledReason !== null || state.name.length === 0}
          >
            {state.busy ? '正在创建…' : '创建' + label}
          </button>
          <p id={'create-status-' + owner.kind} className="read-status" role="status">
            {disabledReason ?? (state.name.length === 0 ? '填写名称后可创建配置' : '')}
          </p>
        </div>
        {state.draftWarning && (
          <p className="read-status" role="status">
            {state.draftWarning}
          </p>
        )}
        {state.submitError && (
          <p className="inline-error" role="alert">
            {state.submitError}
          </p>
        )}
      </form>
      <RecordList
        title={label + '列表'}
        total={identities?.pagination.total ?? null}
        loading={state.loading}
        error={state.readError}
        retry={() => void owner.read(state.requestedPage)}
        retryDisabled={state.loading}
        items={(identities?.items ?? []).map((row) => ({
          id: row.id,
          title: row.name,
          metadata: row.latest_version_id === null ? '暂无版本' : '已有发布版本',
          selected: state.selectedId === row.id,
          disabled: state.busy,
          label: '查看' + label + ' ' + row.name,
          open: () => owner.select(row.id),
        }))}
        empty={{
          icon: 'settings',
          message: identities?.pagination.total ? '本页暂无配置，请返回有效页' : '暂无' + label,
        }}
        filters={
          <button
            type="button"
            className="ui-button"
            disabled={state.loading}
            onClick={() => void owner.read(state.requestedPage)}
          >
            {state.loading ? '正在读取…' : '重新读取列表'}
          </button>
        }
        footer={
          identities && (
            <Pagination
              value={identities.pagination}
              loading={state.loading}
              showLoadingStatus={false}
              compactSingle
              change={(page) => void owner.read(page)}
            />
          )
        }
      />
      <section
        className="code-settings-versions"
        aria-label={label + '版本'}
        aria-busy={state.versionsLoading}
      >
        <header className="code-settings-section-heading">
          <h3>
            {label}版本{state.selectedId !== null && ' · 配置 #' + state.selectedId}
          </h3>
          {state.selectedId !== null && (
            <button
              type="button"
              className="ui-button"
              disabled={state.versionsLoading}
              onClick={() => void owner.readVersions(state.requestedVersionPage)}
            >
              {state.versionsLoading ? '正在读取…' : '重新读取版本'}
            </button>
          )}
        </header>
        {state.selectedId === null && (
          <EmptyState icon="history" message="请选择配置查看版本" compact />
        )}
        {state.versionsLoading && <p role="status">正在读取配置版本…</p>}
        {state.versionsError && (
          <p className="inline-error" role="alert">
            {state.versionsError}
          </p>
        )}
        {state.versionsError && versions !== null && (
          <p className="read-status">显示上次读取的版本</p>
        )}
        {versions !== null && versions.items.length > 0 && (
          <ol className="code-settings-version-items">
            {versions.items.map((version) => (
              <li key={version.id}>
                <div className="code-settings-pending-heading">
                  <strong>
                    版本 {version.version} · #{version.id}
                  </strong>
                  <span>{version.ready ? '可用' : '尚未就绪'}</span>
                </div>
                <time dateTime={version.created_at}>{localTime(version.created_at)}</time>
                {version.unresolved_capability_codes.length > 0 && (
                  <p>待准备条件　{version.unresolved_capability_codes.join('、')}</p>
                )}
                <ConfigurationVersionDetails version={version} />
              </li>
            ))}
          </ol>
        )}
        {versions !== null &&
          versions.items.length === 0 &&
          !state.versionsLoading &&
          !state.versionsError && (
            <EmptyState
              icon="history"
              compact
              message={
                versions.pagination.total > 0 ? '本页暂无版本，请返回有效页' : '此配置暂无发布版本'
              }
            />
          )}
        {versions !== null && (
          <Pagination
            value={versions.pagination}
            loading={state.versionsLoading}
            showLoadingStatus={false}
            compactSingle
            change={(page) => void owner.readVersions(page)}
          />
        )}
      </section>
      <ConfigurationCatalog api={api} identityKind={owner.kind} />
    </section>
  );
}
