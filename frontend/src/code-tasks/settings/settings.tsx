import { useEffect, useState, useSyncExternalStore } from 'react';
import { positiveInteger } from '../../api/client.ts';
import type { RepositoryOperation } from '../../api/code-repository-operations.ts';
import type { WalleApi } from '../../api/walle.ts';
import { environmentBrowserStorage, type StoragePort } from '../../api/environment-storage.ts';
import { TEST_PLAN_RECOVERY_KINDS } from '../../api/testing-plans.ts';
import { PageHeader } from '../../application/header.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { CommandRecoveryStore } from '../command-recovery-store.ts';
import type { PendingSummary } from '../command-recovery-model.ts';
import type { CommandRecovery, RecoveryLookup } from '../command-recovery.ts';
import { RecoveryListReader } from './recovery-reader.ts';
import { RecoveryActions } from './recovery-actions.tsx';
import { codeSettingsSection, codeSettingsSections } from './section.ts';
import type { CodeSettingsSection } from './section.ts';
import { SingleSelect } from '../../shared/single-select.tsx';
import { IdentitySettingsOwner } from './identity-owner.ts';
import { IdentitySettings } from './identity-view.tsx';
import { RepositorySettings } from './repository-view.tsx';
import { RepositoryRegistrationOwner } from './repository-registration-owner.ts';
import { AuthorizationSettings } from './authorization-view.tsx';
import './settings.css';

const labels: Readonly<Record<string, string>> = {
  'APP-CODE-CMD-C01': '登记仓库',
  'APP-CODE-CMD-C02': '读取仓库信息',
  'APP-CODE-CMD-C05': '登记代码起点',
  'APP-CODE-CMD-C07': '发布执行配置版本',
  'APP-CODE-CMD-C08': '发布检查配置版本',
  'APP-CODE-CMD-C09': '创建执行配置',
  'APP-CODE-CMD-C10': '创建检查配置',
  'APP-CODE-CMD-C15': '批准执行授权',
  'APP-TEST-CMD-C01': '发布测试配置版本',
  'APP-TEST-CMD-C04': '批准独立测试授权',
  'APP-TEST-CMD-C06': '创建测试计划',
  'APP-TEST-CMD-C09': '创建测试计划草稿',
  'APP-TEST-CMD-C12': '保存测试计划草稿',
  'APP-TEST-CMD-C13': '发布固定测试计划',
  'APP-TEST-CMD-C14': '撤销测试计划资格',
  'APP-TEST-CMD-C15': '登记测试包草稿',
};
const replayAvailable = new Set([
  'APP-CODE-CMD-C01',
  'APP-CODE-CMD-C02',
  'APP-CODE-CMD-C07',
  'APP-CODE-CMD-C08',
  'APP-CODE-CMD-C09',
  'APP-CODE-CMD-C10',
  'APP-CODE-CMD-C15',
  'APP-TEST-CMD-C01',
  'APP-TEST-CMD-C04',
  ...TEST_PLAN_RECOVERY_KINDS,
]);
function status(record: PendingSummary): string {
  if (record.status === 'ACCEPTED') return '已接收，原操作待核对';
  if (record.close_state === 'ALREADY_RECEIVED') return '原请求已接收';
  if (record.close_state === 'REQUESTED') return '原请求关闭结果待核对';
  if (record.lookup_status === 'NOT_FOUND') return '暂未找到原回执';
  if (record.lookup_status === 'IN_PROGRESS') return '原请求正在处理';
  if (record.status === 'PREPARED') return '原请求已保存';
  return '原请求结果待核对';
}
export type RepositoryRefreshResult = Readonly<{
  operation: RepositoryOperation;
  observationId: number | null;
}>;

function pageOwner(api: WalleApi, observeRefresh: (operation: RepositoryOperation) => void) {
  const store = new CommandRecoveryStore({ scope: api.environmentScope });
  const recovery: CommandRecovery = api.configurationRecovery(
    store,
    async (original, association, signal) => {
      if (
        original.owner_module !== 'CODING' ||
        !['APP-CODE-CMD-C01', 'APP-CODE-CMD-C02'].includes(original.decoder_kind) ||
        association.task_id !== null ||
        association.testing_task_id !== null
      )
        throw new TypeError('Original operation reader is unavailable');
      const result = await api.repositoryOperation(association.operation_id, signal);
      const operation = result.data;
      if (
        operation.id !== association.operation_id ||
        operation.idempotency_key !== original.key ||
        (original.decoder_kind === 'APP-CODE-CMD-C01' &&
          operation.operation_type !== 'REGISTER_REPOSITORY') ||
        (original.decoder_kind === 'APP-CODE-CMD-C02' &&
          (operation.operation_type !== 'REFRESH_REPOSITORY' ||
            original.path !== '/api/v1/code-repositories/' + operation.resource_id + '/refresh'))
      )
        throw new TypeError('Original repository operation differs');
      if (!signal?.aborted) {
        if (operation.operation_type === 'REGISTER_REPOSITORY')
          registration.observeOperation(operation);
        else observeRefresh(operation);
      }
      return {
        operation_id: operation.id,
        task_id: null,
        testing_task_id: null,
        status: operation.status,
      };
    },
  );
  let draftStorage: StoragePort | null = null;
  try {
    draftStorage = environmentBrowserStorage('sessionStorage', api.environmentScope);
  } catch {
    // The forms retain their input in memory when drafts cannot be persisted.
  }
  const registration = new RepositoryRegistrationOwner(api, recovery, draftStorage);
  const execution = new IdentitySettingsOwner(api, recovery, 'EXECUTION_PROFILE', draftStorage);
  const checks = new IdentitySettingsOwner(api, recovery, 'CHECK_SET', draftStorage);
  async function applyOriginalResult(
    record: PendingSummary,
    result: RecoveryLookup,
    signal?: AbortSignal,
  ) {
    if (record.decoder_kind === 'APP-CODE-CMD-C09')
      await execution.reconcileCreated(record, result, signal);
    else if (record.decoder_kind === 'APP-CODE-CMD-C10')
      await checks.reconcileCreated(record, result, signal);
    else if (record.decoder_kind === 'APP-CODE-CMD-C01' && !signal?.aborted)
      registration.reconcileReceipt(record, result);
  }
  const reader = new RecoveryListReader(recovery, applyOriginalResult);
  return { recovery, reader, execution, checks, registration, applyOriginalResult };
}

export function CodeSettings({
  api,
  reset,
  openTesting,
  selectSection,
}: Readonly<{
  api: WalleApi;
  reset(): void;
  openTesting(): void;
  selectSection(section: CodeSettingsSection): void;
}>) {
  const [refreshes, setRefreshes] = useState<Readonly<Record<number, RepositoryRefreshResult>>>({});
  const [owner] = useState(() =>
    pageOwner(api, (operation) => {
      setRefreshes((current) => {
        const previous = current[operation.resource_id];
        if (previous && previous.operation.id > operation.id) return current;
        const observationId =
          operation.status === 'SUCCEEDED'
            ? positiveInteger(operation.steps[1]?.result_ref?.observation_id)
            : (previous?.observationId ?? null);
        return { ...current, [operation.resource_id]: { operation, observationId } };
      });
    }),
  );
  const [operationNotice, setOperationNotice] = useState<string | null>(null);
  async function actionSettled(
    record: PendingSummary,
    result: RecoveryLookup | null,
    message: string,
  ) {
    setOperationNotice(message);
    try {
      if (result !== null) await owner.applyOriginalResult(record, result);
    } finally {
      if (!document.hidden) await owner.reader.refresh();
    }
  }
  useEffect(() => {
    const previous = document.title;
    document.title = 'WALL-E · 代码设置';
    return () => {
      document.title = previous;
    };
  }, []);

  const section = codeSettingsSection(window.location.search);
  const state = useSyncExternalStore(owner.reader.subscribe, owner.reader.getSnapshot);
  const identity =
    section === 'execution' ? owner.execution : section === 'checks' ? owner.checks : null;
  useEffect(() => {
    function readRecovery() {
      if (section !== null && document.visibilityState !== 'hidden') void owner.reader.refresh();
    }
    function readVisible() {
      if (section === null || document.visibilityState === 'hidden') {
        owner.reader.pause();
        identity?.pause();
        owner.registration.pause();
      } else {
        readRecovery();
        identity?.resume();
        if (section === 'repositories') owner.registration.resume();
      }
    }
    readVisible();
    window.addEventListener('focus', readRecovery);
    window.addEventListener('online', readVisible);
    document.addEventListener('visibilitychange', readVisible);
    return () => {
      window.removeEventListener('focus', readRecovery);
      window.removeEventListener('online', readVisible);
      document.removeEventListener('visibilitychange', readVisible);
      owner.reader.pause();
      identity?.pause();
      owner.registration.pause();
    };
  }, [owner, section, identity]);
  useEffect(() => {
    if (state.loading || state.records === null) return;
    void identity?.syncPending();
    if (section === 'repositories') void owner.registration.restoreCompletion(state.records);
  }, [owner, section, identity, state.loading, state.records]);
  useEffect(
    () => () => {
      owner.reader.dispose();
      owner.execution.dispose();
      owner.checks.dispose();
      owner.registration.dispose();
      owner.recovery.dispose();
    },
    [owner],
  );
  return (
    <main className="code-settings">
      <PageHeader>
        <header className="code-settings-heading">
          <h1>代码设置</h1>
        </header>
      </PageHeader>
      <div className="code-settings-form-actions code-settings-testing-entry">
        <button type="button" className="ui-button" onClick={openTesting}>
          测试配置与恢复
        </button>
      </div>
      {section === null && (
        <p className="inline-error" role="alert">
          设置分区无效，请返回代码设置。
          <button type="button" className="ui-button" onClick={reset}>
            返回代码设置
          </button>
        </p>
      )}
      {section !== null && (
        <>
          <nav className="code-settings-sections" aria-label="设置分区">
            {codeSettingsSections.map((option) => (
              <button
                type="button"
                className="ui-button"
                key={option.value}
                aria-current={option.value === section ? 'page' : undefined}
                onClick={() => {
                  if (section !== option.value) selectSection(option.value);
                }}
              >
                {option.label}
              </button>
            ))}
          </nav>
          <div className="code-settings-section-select">
            <SingleSelect
              value={section}
              label="设置分区"
              options={codeSettingsSections}
              change={(value) => {
                const option = codeSettingsSections.find((item) => item.value === value);
                if (option && option.value !== section) selectSection(option.value);
              }}
            />
          </div>
        </>
      )}
      {section !== null && (
        <section
          className="code-settings-recovery"
          aria-label="待核对操作"
          aria-busy={state.loading}
        >
          <header className="code-settings-section-heading">
            <h2>待核对操作</h2>
            <button
              className="ui-button"
              type="button"
              disabled={state.loading}
              title={state.loading ? '正在核对原请求' : '重新查询已保存请求的原结果'}
              data-focus-fallback
              onClick={() => void owner.reader.refresh()}
            >
              {state.loading ? '正在核对…' : '重新核对'}
            </button>
          </header>
          {operationNotice && <p role="status">{operationNotice}</p>}
          {state.records === null && state.loading && <p role="status">正在读取待核对操作…</p>}
          {state.error && (
            <p className="inline-error" role="alert">
              {state.error}
            </p>
          )}
          {state.error && state.records !== null && (
            <p className="read-status">显示上次读取的记录</p>
          )}
          {state.records !== null && state.records.length > 0 && (
            <ol className="code-settings-pending">
              {state.records.map((record) => (
                <li key={record.identity_sha256}>
                  <div className="code-settings-pending-heading">
                    <h3>
                      {labels[record.decoder_kind] ??
                        (record.owner_module === 'TESTING' ? '测试验收操作' : '代码开发操作')}
                    </h3>
                    <span>{status(record)}</span>
                  </div>
                  <p>
                    {record.operation_id !== null && <span>原操作 #{record.operation_id} · </span>}
                    <time dateTime={record.updated_at}>{localTime(record.updated_at)}</time>
                  </p>
                  {state.rowErrors[record.key] && (
                    <p className="inline-error" role="alert">
                      {state.rowErrors[record.key]}
                    </p>
                  )}
                  <details>
                    <summary>请求标识</summary>
                    <code>{record.key}</code>
                  </details>
                  <RecoveryActions
                    record={record}
                    recovery={owner.recovery}
                    replayEnabled={replayAvailable.has(record.decoder_kind)}
                    settled={(original, result, message) => {
                      void actionSettled(original, result, message).catch(() => {
                        setOperationNotice('已核对原请求，暂时无法更新配置列表');
                      });
                    }}
                  />
                </li>
              ))}
            </ol>
          )}
          {state.records !== null &&
            state.records.length === 0 &&
            !state.loading &&
            !state.error && <EmptyState icon="outline" message="当前没有待核对操作" />}
        </section>
      )}
      {section === 'repositories' && (
        <RepositorySettings
          api={api}
          registration={owner.registration}
          pending={
            state.records?.find((record) => record.decoder_kind === 'APP-CODE-CMD-C01') ?? null
          }
          recovery={owner.recovery}
          refreshes={refreshes}
          refreshRecords={
            state.records?.filter((record) => record.decoder_kind === 'APP-CODE-CMD-C02') ?? []
          }
          recoveryKnown={state.records !== null && state.error === null}
          recoveryLoading={state.loading}
          changed={async () => {
            if (!document.hidden) await owner.reader.refresh();
          }}
        />
      )}
      {section === 'authorizations' && <AuthorizationSettings api={api} />}
      {identity && (
        <IdentitySettings
          key={identity.kind}
          api={api}
          owner={identity}
          changed={() => {
            if (!document.hidden) void owner.reader.refresh();
          }}
        />
      )}
    </main>
  );
}
