import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiRejected, ApiUnknown, positiveInteger } from '../../api/client.ts';
import { normalizedName } from '../../api/code-configuration-identities.ts';
import { testingAuthorizationPath, testingProfilePath } from '../../api/testing-policy.ts';
import type {
  TestingAuthorization,
  TestingAuthorizationScope,
  TestingProfile,
} from '../../api/testing-policy.ts';
import type { WalleApi } from '../../api/walle.ts';
import { TEST_PLAN_RECOVERY_KINDS } from '../../api/testing-plans.ts';
import { SectionPageHeader } from '../../application/header.tsx';
import {
  CommandRecoveryStore,
  CommandStorageError,
} from '../../code-tasks/command-recovery-store.ts';
import type { RecoveryLookup } from '../../code-tasks/command-recovery.ts';
import type { PendingSummary } from '../../code-tasks/command-recovery-model.ts';
import { RecoveryActions } from '../../code-tasks/settings/recovery-actions.tsx';
import { RecoveryListReader } from '../../code-tasks/settings/recovery-reader.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { TestingProfileForm } from './profile-form.tsx';
import '../../code-tasks/settings/settings.css';
import './settings.css';

type ProfilesPage = Awaited<ReturnType<WalleApi['testingProfiles']>>;
type Approval = {
  profile_version_id: number;
  scope_kind: TestingAuthorizationScope;
  budget_limit_cny: string;
};
const selectedProfileKey = 'walle:v20:testing-settings:profile';
const selectedAuthorizationKey = 'walle:v20:testing-settings:authorization';
function savedIdentity(key: string): number | null {
  try {
    const value = window.sessionStorage.getItem(key);
    return value !== null && /^[1-9][0-9]*$/.test(value) ? positiveInteger(Number(value)) : null;
  } catch {
    return null;
  }
}
function rememberIdentity(key: string, identity: number | null) {
  try {
    if (identity === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, String(identity));
  } catch {
    // Read-only access remains possible when session storage is unavailable.
  }
}
const labels = { TASK: '产品测试', PACK_VALIDATION: '测试包验证' } as const;
const configReasons: Readonly<Record<string, string>> = {
  'Q20-CHECKS': '独立测试执行器尚未准入',
  'Q20-CONFIG': '所选配置资源不可用或无法核实',
  'Q20-BROWSER': '浏览器运行环境尚未准入',
  'Q20-WINDOWS': 'Windows 隔离环境尚未准入',
  'Q20-MODEL': '计划起草模型尚未准入',
  AUTHORIZATION_NOT_APPLICABLE: '授权已退役',
};

function failure(error: unknown, fallback: string) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : fallback;
}
function Readiness({ value }: Readonly<{ value: Pick<TestingProfile, 'ready' | 'reason_codes'> }>) {
  return value.ready ? (
    <p>资源已就绪</p>
  ) : (
    <ul>
      {value.reason_codes.map((reason) => (
        <li key={reason}>{configReasons[reason] ?? reason}</li>
      ))}
    </ul>
  );
}

function ownerFor(
  api: WalleApi,
  observed: (record: PendingSummary, result: RecoveryLookup) => void,
) {
  const store = new CommandRecoveryStore();
  const recovery = api.configurationRecovery(store, async () => {
    throw new TypeError('测试配置与授权无后台操作');
  });
  const reader = new RecoveryListReader(
    {
      store: {
        list: async () =>
          (await store.list()).filter((record) => record.owner_module === 'TESTING'),
      },
      lookup: (key, signal) => recovery.lookup(key, signal),
      reconcileOperation: (key, signal) => recovery.reconcileOperation(key, signal),
    },
    async (record, result, signal) => {
      if (!signal.aborted) observed(record, result);
    },
  );
  return { recovery, reader };
}

export function TestingSettings({
  api,
  openCoding,
  openPlans,
}: Readonly<{ api: WalleApi; openCoding(): void; openPlans(): void }>) {
  const [page, setPage] = useState(1);
  const [filterDraft, setFilterDraft] = useState('');
  const [filterError, setFilterError] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [profiles, setProfiles] = useState<ProfilesPage | null>(null);
  const [profileId, setProfileId] = useState<number | null>(() =>
    savedIdentity(selectedProfileKey),
  );
  const [profile, setProfile] = useState<TestingProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [scope, setScope] = useState<TestingAuthorizationScope>('TASK');
  const [authorizationId, setAuthorizationId] = useState<number | null>(() =>
    savedIdentity(selectedAuthorizationKey),
  );
  const [authorizationText, setAuthorizationText] = useState(() => {
    const identity = savedIdentity(selectedAuthorizationKey);
    return identity === null ? '' : String(identity);
  });
  const [authorization, setAuthorization] = useState<TestingAuthorization | null>(null);
  const [authorizationLoading, setAuthorizationLoading] = useState(false);
  const [authorizationError, setAuthorizationError] = useState<string | null>(null);
  const [authorizationAttempt, setAuthorizationAttempt] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Approval | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const authorizationInputEdited = useRef(false);
  const disposed = useRef(false);
  function observe(record: PendingSummary, result: RecoveryLookup) {
    const outcome = result.original_receipt?.original_outcome;
    if (outcome?.success !== true) return;
    if (record.path === testingAuthorizationPath) {
      const id = positiveInteger((outcome.data as TestingAuthorization).id);
      if (!authorizationInputEdited.current) {
        setAuthorizationText(String(id));
        setAuthorizationId(id);
        setAuthorizationAttempt((current) => current + 1);
      }
      setNotice('已核实原独立测试授权 #' + id);
    } else if (record.path === testingProfilePath) {
      setProfileId(positiveInteger((outcome.data as TestingProfile).id));
      setRefresh((current) => current + 1);
      setNotice('已核实原测试配置版本');
    }
  }
  const [owner] = useState(() => ownerFor(api, observe));
  const recovery = useSyncExternalStore(owner.reader.subscribe, owner.reader.getSnapshot);

  useEffect(() => {
    disposed.current = false;
    const title = document.title;
    document.title = 'WALL-E · 测试配置与恢复';
    function update() {
      if (document.hidden) owner.reader.pause();
      else void owner.reader.refresh();
    }
    update();
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    return () => {
      disposed.current = true;
      document.title = title;
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('focus', update);
      owner.reader.dispose();
      owner.recovery.dispose();
    };
  }, [owner]);

  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    setListError(null);
    void api
      .testingProfiles(page, name, request.signal)
      .then(
        (result) => {
          if (!request.signal.aborted) setProfiles(result);
        },
        (error) => {
          if (!request.signal.aborted) setListError(failure(error, '暂时无法读取测试配置'));
        },
      )
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [api, page, name, refresh]);

  useEffect(() => {
    rememberIdentity(selectedProfileKey, profileId);
    if (profileId === null) return;
    const request = new AbortController();
    setProfileLoading(true);
    setProfileError(null);
    void api
      .testingProfile(profileId, request.signal)
      .then(
        (result) => {
          if (!request.signal.aborted) setProfile(result.data);
        },
        (error) => {
          if (!request.signal.aborted) setProfileError(failure(error, '暂时无法读取所选版本'));
        },
      )
      .finally(() => {
        if (!request.signal.aborted) setProfileLoading(false);
      });
    return () => request.abort();
  }, [api, profileId, refresh]);

  useEffect(() => {
    rememberIdentity(selectedAuthorizationKey, authorizationId);
    if (authorizationId === null) return;
    const request = new AbortController();
    setAuthorizationLoading(true);
    setAuthorizationError(null);
    void api
      .testingAuthorization(authorizationId, request.signal)
      .then(
        (result) => {
          if (!request.signal.aborted) setAuthorization(result.data);
        },
        (error) => {
          if (!request.signal.aborted)
            setAuthorizationError(failure(error, '暂时无法读取独立测试授权'));
        },
      )
      .finally(() => {
        if (!request.signal.aborted) setAuthorizationLoading(false);
      });
    return () => request.abort();
  }, [api, authorizationId, authorizationAttempt]);

  const matchingProfile = profile?.id === profileId ? profile : null;
  const matchingAuthorization = authorization?.id === authorizationId ? authorization : null;
  const pending = recovery.records?.some((record) => record.path === testingAuthorizationPath);

  const disabledReason = saving
    ? '正在保存批准'
    : recovery.records === null || recovery.error !== null
      ? '请先核对原请求存储'
      : pending
        ? '请先核对上一条授权请求'
        : profileLoading || profileError !== null
          ? '请先核实所选测试配置'
          : matchingProfile === null
            ? '请选择测试配置版本'
            : null;
  const pagination = profiles?.meta.pagination;
  const totalPages = pagination && 'total_pages' in pagination ? pagination.total_pages : 0;

  async function approve() {
    if (confirmation === null || disabledReason !== null || savingRef.current) return;
    const fixed = confirmation;
    savingRef.current = true;
    setSaving(true);
    setActionError(null);
    try {
      const staged = await owner.recovery.stageIntent(testingAuthorizationPath, fixed);
      if (staged.kind !== 'PREPARED') {
        setActionError('已有原授权请求，请先核对');
        return;
      }
      const result = await owner.recovery.send(staged.record.key, staged.record.record_revision);
      if (!disposed.current) {
        const id = positiveInteger((result.response.data as TestingAuthorization).id);
        setAuthorizationText(String(id));
        setAuthorizationId(id);
        setAuthorizationAttempt((current) => current + 1);
        setNotice('已保存独立测试授权');
      }
    } catch (error) {
      if (!disposed.current) setActionError(failure(error, '暂时无法核实授权结果，请检查原请求'));
    } finally {
      savingRef.current = false;
      if (!disposed.current) {
        setSaving(false);
        setConfirmation(null);
        if (!document.hidden) void owner.reader.refresh();
      }
    }
  }

  function queryAuthorization() {
    if (
      !/^[1-9][0-9]*$/.test(authorizationText) ||
      !Number.isSafeInteger(Number(authorizationText))
    ) {
      setAuthorizationError('请输入有效的授权编号');
      return;
    }
    setAuthorizationId(Number(authorizationText));
    setAuthorizationAttempt((current) => current + 1);
  }

  return (
    <main className="testing-page">
      <SectionPageHeader title="测试配置与恢复">
        <button type="button" className="ui-button" onClick={openCoding}>
          代码设置
        </button>
        <button type="button" className="ui-button" onClick={() => openPlans()}>
          测试计划与资源管理
        </button>
      </SectionPageHeader>
      <section
        className="code-settings-recovery"
        aria-label="待核对操作"
        aria-busy={recovery.loading}
      >
        <header className="code-settings-section-heading">
          <h2>待核对操作</h2>
          <button
            className="ui-button"
            type="button"
            disabled={recovery.loading}
            title={recovery.loading ? '正在核对原请求' : '重新查询已保存的测试原请求'}
            data-focus-fallback
            onClick={() => void owner.reader.refresh()}
          >
            {recovery.loading ? '正在核对…' : '重新核对'}
          </button>
        </header>
        {notice && <p role="status">{notice}</p>}
        {recovery.error && (
          <p className="inline-error" role="alert">
            {recovery.error}
          </p>
        )}
        {recovery.loading && recovery.records === null && <p role="status">正在读取待核对操作…</p>}
        {recovery.records?.length === 0 && !recovery.loading && !recovery.error && (
          <EmptyState icon="outline" message="当前没有待核对操作" />
        )}
        {recovery.records && recovery.records.length > 0 && (
          <ol className="code-settings-pending">
            {recovery.records.map((record) => (
              <li key={record.identity_sha256}>
                <h3>
                  {record.path === testingAuthorizationPath
                    ? '批准独立测试授权'
                    : record.path === testingProfilePath
                      ? '发布测试配置版本'
                      : '测试验收操作'}
                </h3>
                <p>
                  <time dateTime={record.updated_at}>{localTime(record.updated_at)}</time> ·
                  原请求结果待核对
                </p>
                {recovery.rowErrors[record.key] && (
                  <p className="inline-error" role="alert">
                    {recovery.rowErrors[record.key]}
                  </p>
                )}
                <RecoveryActions
                  record={record}
                  recovery={owner.recovery}
                  replayEnabled={
                    record.path === testingAuthorizationPath ||
                    record.path === testingProfilePath ||
                    TEST_PLAN_RECOVERY_KINDS.has(record.decoder_kind)
                  }
                  settled={(original, result, message) => {
                    setNotice(message);
                    if (result !== null) observe(original, result);
                    if (!document.hidden) void owner.reader.refresh();
                  }}
                />
              </li>
            ))}
          </ol>
        )}
      </section>
      <section className="code-settings-resource" aria-label="测试配置版本">
        <div className="code-settings-versions" aria-busy={loading}>
          <header className="code-settings-section-heading">
            <h2>测试配置版本</h2>
            <button
              className="ui-button"
              type="button"
              disabled={loading}
              title={loading ? '正在读取测试配置' : undefined}
              onClick={() => setRefresh((current) => current + 1)}
            >
              重新读取
            </button>
          </header>
          <form
            className="code-settings-form-actions"
            onSubmit={(event) => {
              event.preventDefault();
              try {
                const filter = filterDraft.trim() === '' ? null : normalizedName(filterDraft);
                if (filter !== null && [...filter].length > 200) {
                  setFilterError('配置名称最多 200 个字符');
                  return;
                }
                setFilterError(null);
                setName(filter);
                setPage(1);
              } catch {
                setFilterError('请输入有效的配置名称');
              }
            }}
          >
            <label>
              配置名称{' '}
              <input
                className="ui-input"
                value={filterDraft}
                onChange={(event) => setFilterDraft(event.currentTarget.value)}
              />
            </label>
            <button type="submit" className="ui-button">
              筛选
            </button>
          </form>
          {filterError && (
            <p className="inline-error" role="alert">
              {filterError}
            </p>
          )}
          {loading && <p role="status">正在读取测试配置…</p>}
          {listError && (
            <p className="inline-error" role="alert">
              {listError}
            </p>
          )}
          {listError && profiles && <p className="read-status">显示上次读取的配置</p>}
          {profiles?.data.items.length === 0 && !loading && !listError && (
            <EmptyState
              icon="outline"
              message={
                page > 1
                  ? '此页没有测试配置'
                  : name
                    ? '没有符合筛选条件的测试配置'
                    : '当前没有测试配置'
              }
            />
          )}
          {profiles && profiles.data.items.length > 0 && (
            <ol className="code-settings-version-items">
              {profiles.data.items.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="ui-button"
                    aria-pressed={profileId === row.id}
                    onClick={() => setProfileId(row.id)}
                  >
                    {row.name} · 版本 {row.version}
                  </button>
                  <Readiness value={row} />
                </li>
              ))}
            </ol>
          )}
          {profiles && (
            <div className="code-settings-form-actions">
              <button
                className="ui-button"
                type="button"
                disabled={loading || page === 1}
                title={loading ? '正在读取' : page === 1 ? '已是首页' : undefined}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </button>
              <span>第 {page} 页</span>
              <button
                className="ui-button"
                type="button"
                disabled={loading || page >= totalPages}
                title={loading ? '正在读取' : page >= totalPages ? '没有下一页' : undefined}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </div>
        <TestingProfileForm
          api={api}
          recovery={owner.recovery}
          selected={matchingProfile}
          unavailable={
            recovery.records === null || recovery.error !== null
              ? '请先核对原请求存储'
              : recovery.records.some((record) => record.path === testingProfilePath)
                ? '请先核对上一条配置请求'
                : null
          }
          published={(id) => {
            setProfileId(id);
            setRefresh((current) => current + 1);
            setNotice('已保存测试配置版本');
          }}
          settled={() => {
            if (!document.hidden) void owner.reader.refresh();
          }}
        />
        {profileLoading && <p role="status">正在核对所选配置版本…</p>}
        {profileError && (
          <p className="inline-error" role="alert">
            {profileError}
          </p>
        )}
        {matchingProfile && (
          <section className="code-settings-resource-detail" aria-label="所选测试配置">
            <h3>
              {matchingProfile.name} · 版本 {matchingProfile.version}
            </h3>
            <p>
              配置 #{matchingProfile.id} · {localTime(matchingProfile.created_at)}
            </p>
            <Readiness value={matchingProfile} />
            <dl className="code-settings-resource-facts">
              <div>
                <dt>运行器</dt>
                <dd>{matchingProfile.runner_refs.join('、')}</dd>
              </div>
              <div>
                <dt>环境</dt>
                <dd>{matchingProfile.environment_refs.join('、')}</dd>
              </div>
              <div>
                <dt>计划模型</dt>
                <dd>{matchingProfile.model_binding?.model_profile_ref ?? '未配置'}</dd>
              </div>
            </dl>
          </section>
        )}
      </section>
      <section className="code-settings-resource" aria-label="独立测试授权">
        <div className="code-settings-create">
          <h2>独立测试授权</h2>
          <p>
            {matchingProfile
              ? '批准所选固定配置。授权保存后待绑定。'
              : '请选择要批准的测试配置版本。'}
          </p>
          <label>
            授权范围{' '}
            <select
              className="ui-input"
              value={scope}
              disabled={saving}
              onChange={(event) => {
                setScope(
                  event.currentTarget.value === 'PACK_VALIDATION' ? 'PACK_VALIDATION' : 'TASK',
                );
              }}
            >
              <option value="TASK">{labels.TASK}</option>
              <option value="PACK_VALIDATION">{labels.PACK_VALIDATION}</option>
            </select>
          </label>
          <div className="code-settings-form-actions">
            <button
              type="button"
              className="ui-button"
              disabled={disabledReason !== null}
              title={disabledReason ?? undefined}
              onClick={() => {
                if (matchingProfile === null || disabledReason !== null) return;
                setActionError(null);
                setConfirmation({
                  profile_version_id: matchingProfile.id,
                  scope_kind: scope,
                  budget_limit_cny: '0.000000',
                });
              }}
            >
              批准授权
            </button>
            {disabledReason && <p className="read-status">{disabledReason}</p>}
          </div>
          {actionError && (
            <p className="inline-error" role="alert">
              {actionError}
            </p>
          )}
          <form
            className="code-settings-form-actions"
            onSubmit={(event) => {
              event.preventDefault();
              queryAuthorization();
            }}
          >
            <label>
              授权编号{' '}
              <input
                className="ui-input"
                inputMode="numeric"
                value={authorizationText}
                onChange={(event) => {
                  authorizationInputEdited.current = true;
                  setAuthorizationText(event.currentTarget.value);
                }}
              />
            </label>
            <button
              type="submit"
              className="ui-button"
              disabled={authorizationLoading}
              title={authorizationLoading ? '正在核对授权' : undefined}
            >
              查询授权
            </button>
          </form>
          {authorizationLoading && <p role="status">正在读取独立测试授权…</p>}
          {authorizationError && (
            <p className="inline-error" role="alert">
              {authorizationError}
            </p>
          )}
          {matchingAuthorization && (
            <div>
              <p>
                授权 #{matchingAuthorization.id} · 配置 #{matchingAuthorization.profile_version_id}{' '}
                · {labels[matchingAuthorization.scope_kind]}
              </p>
              <p>
                {matchingAuthorization.status === 'APPROVED_UNBOUND'
                  ? '待绑定'
                  : matchingAuthorization.status === 'EFFECTIVE'
                    ? '已绑定'
                    : '已退役'}
              </p>
              <p>批准时间 {localTime(matchingAuthorization.approved_at)}</p>
              <Readiness value={matchingAuthorization} />
            </div>
          )}
        </div>
      </section>
      <Confirmation
        open={confirmation !== null}
        title="批准独立测试授权"
        description={
          confirmation === null
            ? ''
            : '确认批准配置 #' +
              confirmation.profile_version_id +
              '，范围为' +
              labels[confirmation.scope_kind] +
              '。'
        }
        busy={saving}
        confirmLabel="确认批准"
        confirm={() => void approve()}
        cancel={() => setConfirmation(null)}
      />
    </main>
  );
}
