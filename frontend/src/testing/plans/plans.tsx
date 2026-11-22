import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { FormEvent } from 'react';
import { positiveInteger } from '../../api/client.ts';
import { normalizedName } from '../../api/code-configuration-identities.ts';
import {
  TEST_PLAN_RECOVERY_KINDS,
  testingPlanControlPath,
  testingPlansPath,
} from '../../api/testing-plans.ts';
import { PlanControls } from './plan-controls.tsx';
import { PlanPacks } from './plan-packs.tsx';
import { testingPackListPath, testingPackSealPath } from '../../api/testing-assets.ts';
import type { TestPack, TestingValidationReceipt } from '../../api/testing-assets.ts';
import type { TestingSealReceipt } from '../../api/testing-assets.ts';
import { PlanDraftEditor } from '../plan-editor/editor.tsx';
import { draftPath, importanceLabels, modeLabels, stageLabels } from '../plan-editor/draft.ts';
import type { DraftReceipt } from '../plan-editor/draft.ts';
import { errorText, meta, Pager, ReadState, useTestingRead } from './read.tsx';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import type { WalleApi } from '../../api/walle.ts';
import { PageHeader } from '../../application/header.tsx';
import { CommandRecoveryStore } from '../../code-tasks/command-recovery-store.ts';
import type { RecoveryLookup } from '../../code-tasks/command-recovery.ts';
import type { PendingSummary } from '../../code-tasks/command-recovery-model.ts';
import { RecoveryActions } from '../../code-tasks/settings/recovery-actions.tsx';
import { RecoveryListReader } from '../../code-tasks/settings/recovery-reader.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import '../../code-tasks/settings/settings.css';
import '../settings/settings.css';
import './plans.css';

type Selection = {
  plan: number | null;
  version: number | null;
  pack: number | null;
  validation: number | null;
};
const statuses = { DRAFT: '草稿', PUBLISHED: '已发布', REVOKED: '已撤销' } as const;
function selection(query: string): Selection | null {
  const params = new URLSearchParams(query);
  const allowed = new Set(['plan_id', 'plan_version_id', 'pack_id', 'validation_id']);
  if ([...params.keys()].some((key) => !allowed.has(key) || params.getAll(key).length !== 1))
    return null;
  function read(key: string): number | null {
    const value = params.get(key);
    if (value === null) return null;
    if (!/^[1-9][0-9]*$/.test(value)) throw new TypeError('Invalid Testing plan identity');
    return positiveInteger(Number(value));
  }
  try {
    const plan = read('plan_id');
    const version = read('plan_version_id');
    const pack = read('pack_id');
    const validation = read('validation_id');
    return (plan === null && version !== null) ||
      (version === null && pack !== null) ||
      (pack === null && validation !== null)
      ? null
      : { plan, version, pack, validation };
  } catch {
    return null;
  }
}
function FixedVersion({ version }: Readonly<{ version: TestPlanVersion }>) {
  return (
    <section className="code-settings-versions testing-plan-version" aria-label="固定测试计划版本">
      <header className="code-settings-section-heading">
        <h2>计划版本 {version.version}</h2>
        <span>{statuses[version.status]}</span>
      </header>
      <p>
        需求 #{version.requirement_id} · 文档 #{version.document_id} · 固定设计版本 #
        {version.design_revision_id}
      </p>
      {version.published_at && <p>发布时间 {localTime(version.published_at)}</p>}
      {version.revocation_reason && <p>撤销原因 {version.revocation_reason}</p>}
      <h3>固定材料</h3>
      {version.material_refs.length === 0 ? (
        <EmptyState icon="outline" message="此版本没有附加材料" compact />
      ) : (
        <ul>
          {version.material_refs.map((item) => (
            <li key={item.document_id}>
              文档 #{item.document_id} · 版本 #{item.revision_id}
            </li>
          ))}
        </ul>
      )}
      <h3>行为与覆盖</h3>
      {version.behaviors.length === 0 ? (
        <EmptyState icon="outline" message="此版本尚无测试行为" compact />
      ) : (
        <ol>
          {version.behaviors.map((item) => (
            <li key={item.behavior_id}>
              <details>
                <summary>
                  {item.name} · {modeLabels[item.mode]}
                </summary>
                <p>
                  {importanceLabels[item.importance]} ·{' '}
                  {item.stages.map((stage) => stageLabels[stage]).join('、')}
                </p>
                {item.explanation && <p>{item.explanation}</p>}
                {item.case_ids.length > 0 && <p>关联用例 {item.case_ids.join('、')}</p>}
                <ul>
                  {item.basis_refs.map((ref) => (
                    <li key={JSON.stringify(ref)}>
                      <p>
                        文档 #{ref.document_id} · 版本 #{ref.revision_id}
                      </p>
                      <blockquote>{ref.quote}</blockquote>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          ))}
        </ol>
      )}
      <h3>用例</h3>
      {version.cases.length === 0 ? (
        <EmptyState icon="outline" message="此版本尚无结构化用例" compact />
      ) : (
        <ol>
          {version.cases.map((item) => (
            <li key={item.case_id}>
              <details>
                <summary>
                  {item.name} · {item.visibility === 'HELD_OUT' ? '保留' : '公开'}
                </summary>
                <p>
                  {item.driver_kind} · {item.steps.length} 步骤 · {item.assertions.length} 断言
                </p>
                <p>关联行为 {item.behavior_ids.join('、')}</p>
              </details>
            </li>
          ))}
        </ol>
      )}
      <h3>待解决问题</h3>
      {version.unresolved_questions.length === 0 ? (
        <EmptyState icon="outline" message="此版本没有待解决问题" compact />
      ) : (
        <ul>
          {version.unresolved_questions.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function TestingPlans({
  api,
  query,
  select,
  openTask,
  settings,
}: Readonly<{
  api: WalleApi;
  query: string;
  select(
    plan?: number | null,
    version?: number | null,
    pack?: number | null,
    validation?: number | null,
  ): void;
  openTask(id: number): void;
  settings(): void;
}>) {
  const selected = selection(query);
  const planId = selected?.plan ?? null;
  const versionId = selected?.version ?? null;
  const packId = selected?.pack ?? null;
  const validationId = selected?.validation ?? null;
  const [page, setPage] = useState(1);
  const [versionPage, setVersionPage] = useState({ plan: planId, page: 1 });
  const currentVersionPage = versionPage.plan === planId ? versionPage.page : 1;
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const writing = useRef(false);
  const live = useRef(true);
  const currentSelection = useRef({ planId, versionId, packId });
  currentSelection.current = { planId, versionId, packId };
  const loadPlans = useCallback(
    (signal: AbortSignal) => api.testingPlans(page, signal),
    [api, page],
  );
  const loadPlan = useCallback(
    (signal: AbortSignal) => api.testingPlan(planId!, signal),
    [api, planId],
  );
  const plans = useTestingRead('plans:' + page, selected === null ? null : loadPlans);
  const plan = useTestingRead('plan:' + planId, planId === null ? null : loadPlan);
  const ownerPlan = plan.data?.data.id ?? null;
  const loadVersions = useCallback(
    (signal: AbortSignal) => api.testingPlanVersions(ownerPlan!, currentVersionPage, signal),
    [api, ownerPlan, currentVersionPage],
  );
  const loadVersion = useCallback(
    (signal: AbortSignal) => api.testingPlanVersion(ownerPlan!, versionId!, signal),
    [api, ownerPlan, versionId],
  );
  const versions = useTestingRead(
    'versions:' + ownerPlan + ':' + currentVersionPage,
    ownerPlan === null ? null : loadVersions,
  );
  const version = useTestingRead(
    'version:' + ownerPlan + ':' + versionId,
    ownerPlan === null || versionId === null ? null : loadVersion,
  );
  const [receipts, setReceipts] = useState<Readonly<Record<string, DraftReceipt>>>({});
  const [packReceipts, setPackReceipts] = useState<Readonly<Record<string, number>>>({});
  const [sealReceipts, setSealReceipts] = useState<Readonly<Record<string, number>>>({});
  const [packControls, setPackControls] = useState<Readonly<Record<number, number>>>({});
  const [validations, setValidations] = useState<Readonly<Record<number, number>>>({});
  const [dirtyVersion, setDirtyVersion] = useState<number | null>(null);
  const dirty = useCallback(
    (value: boolean) => {
      setDirtyVersion((current) => (value ? versionId : current === versionId ? null : current));
    },
    [versionId],
  );

  function applyOriginal(record: PendingSummary, result: RecoveryLookup) {
    const outcome = result.original_receipt?.original_outcome;
    if (outcome?.success !== true) return;
    if (record.path === testingPlansPath) {
      plans.reload();
      setNotice('已核实原计划创建');
    } else {
      versions.reload();
      version.reload();
      if (
        record.decoder_kind === 'APP-TEST-CMD-C09' ||
        record.decoder_kind === 'APP-TEST-CMD-C12'
      ) {
        const receipt = { key: record.key, version: outcome.data as TestPlanVersion };
        setReceipts((current) => ({ ...current, [record.path]: receipt }));
        if (record.decoder_kind === 'APP-TEST-CMD-C09') {
          plan.reload();
          plans.reload();
        }
        setNotice('已核实原草稿保存');
      } else if (record.decoder_kind === 'APP-TEST-CMD-C15') {
        const result = outcome.data as { test_pack_version_id: number };
        setPackReceipts((current) => ({ ...current, [record.path]: result.test_pack_version_id }));
        setNotice('已核实原测试包登记');
      } else if (record.decoder_kind === 'APP-TEST-CMD-C18') {
        const result = outcome.data as TestingSealReceipt;
        setSealReceipts((current) => ({
          ...current,
          [record.path]: Math.max(current[record.path] ?? 0, result.operation_id),
        }));
      } else if (record.decoder_kind === 'APP-TEST-CMD-C19') {
        const accepted = outcome.data as TestingValidationReceipt;
        setValidations((current) => ({
          ...current,
          [accepted.test_pack_version_id]: accepted.validation_id,
        }));
        setNotice('已核实原有效性验证请求');
      } else if (
        record.decoder_kind === 'APP-TEST-CMD-C21' ||
        record.decoder_kind === 'APP-TEST-CMD-C22'
      ) {
        const pack = outcome.data as TestPack;
        setPackControls((current) => ({ ...current, [pack.id]: pack.state_version }));
        setNotice(pack.status === 'REVOKED' ? '已核实原测试包撤销' : '已核实原测试包发布');
      } else setNotice('已核实原计划控制结果');
    }
  }
  const [recovery] = useState(() => {
    const store = new CommandRecoveryStore({ scope: api.environmentScope });
    const commands = api.configurationRecovery(store, async (original, association, signal) => {
      const pack = positiveInteger(original.parameters.id);
      const operation =
        original.decoder_kind === 'APP-TEST-CMD-C18'
          ? await api.testingSeal(pack, association.operation_id, signal)
          : original.decoder_kind === 'APP-TEST-CMD-C19'
            ? await api.testingValidationOperation(pack, association.operation_id, signal)
            : null;
      if (operation === null) throw new TypeError('计划命令没有对应后台操作');
      return {
        operation_id: operation.data.id,
        task_id: operation.data.task_id,
        testing_task_id: operation.data.testing_task_id,
        status: operation.data.status,
      };
    });
    const reader = new RecoveryListReader(
      {
        store: {
          list: async () =>
            (await store.list()).filter(
              (item) =>
                item.owner_module === 'TESTING' && TEST_PLAN_RECOVERY_KINDS.has(item.decoder_kind),
            ),
        },
        lookup: (key, signal) => commands.lookup(key, signal),
        reconcileOperation: (key, signal) => commands.reconcileOperation(key, signal),
      },
      async (record, result, signal) => {
        if (!signal.aborted) applyOriginal(record, result);
      },
    );
    return { commands, reader };
  });
  const recoveryState = useSyncExternalStore(
    recovery.reader.subscribe,
    recovery.reader.getSnapshot,
  );
  useEffect(() => {
    live.current = true;
    const previous = document.title;
    document.title = 'WALL-E · 测试计划与资源管理';
    function read() {
      if (document.hidden) recovery.reader.pause();
      else void recovery.reader.refresh();
    }
    read();
    window.addEventListener('focus', read);
    document.addEventListener('visibilitychange', read);
    return () => {
      live.current = false;
      document.title = previous;
      window.removeEventListener('focus', read);
      document.removeEventListener('visibilitychange', read);
      recovery.reader.dispose();
      recovery.commands.dispose();
    };
  }, [recovery]);
  function refreshDraft() {
    version.reload();
    versions.reload();
    if (!document.hidden) void recovery.reader.refresh();
  }
  function draftUnavailable(path: string) {
    if (recoveryState.error || recoveryState.records === null) return '请先核对原请求存储';
    if (recoveryState.records.some((record) => record.path === path))
      return '请先核对当前草稿的原请求';
    return null;
  }
  function savedDraft(stored: TestPlanVersion, newlyCreated: boolean) {
    setNotice(newlyCreated ? '计划草稿已创建' : '计划草稿已保存');
    plans.reload();
    if (newlyCreated) plan.reload();
    versions.reload();
    if (newlyCreated && currentSelection.current.planId === stored.plan_id)
      select(stored.plan_id, stored.id);
    else if (currentSelection.current.versionId === stored.id) version.reload();
    if (!document.hidden) void recovery.reader.refresh();
  }

  let nameError: string | null = null;
  try {
    if ([...normalizedName(name)].length > 200) nameError = '计划名称最多 200 个字符';
  } catch {
    nameError = '请输入有效的计划名称';
  }
  const reason = busy
    ? '正在保存测试计划'
    : recoveryState.error || recoveryState.records === null
      ? '请先核对原请求存储'
      : recoveryState.records.some((record) => record.path === testingPlansPath)
        ? '请先核对上一条计划请求'
        : nameError;

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason !== null || writing.current) return;
    writing.current = true;
    const originalName = name;
    const originalSelection = currentSelection.current;
    setBusy(true);
    setError(null);
    try {
      const staged = await recovery.commands.stageIntent(testingPlansPath, { name: originalName });
      if (staged.kind !== 'PREPARED') {
        setError('已有原请求，请先核对');
        return;
      }
      const result = await recovery.commands.send(staged.record.key, staged.record.record_revision);
      if (!live.current) return;
      const created = result.response.data as { plan_id: number };
      setName((current) => (current === originalName ? '' : current));
      setNotice('测试计划已创建');
      plans.reload();
      if (
        currentSelection.current.planId === originalSelection.planId &&
        currentSelection.current.versionId === originalSelection.versionId
      )
        select(positiveInteger(created.plan_id));
    } catch (failure) {
      if (live.current) setError(errorText(failure, '暂时无法确认计划创建结果，请核对原请求'));
    } finally {
      writing.current = false;
      if (live.current) {
        setBusy(false);
        if (!document.hidden) void recovery.reader.refresh();
      }
    }
  }

  return (
    <main className="code-settings testing-plans">
      <PageHeader>
        <header className="code-settings-heading">
          <h1>测试计划与资源管理</h1>
        </header>
      </PageHeader>
      <div className="code-settings-form-actions testing-settings-nav">
        <button type="button" className="ui-button" onClick={settings}>
          测试配置与恢复
        </button>
      </div>
      {selected === null ? (
        <div className="code-settings-form-actions">
          <p className="inline-error" role="alert">
            测试计划定位无效，或所引用的测试包与验证尚无法核实。
          </p>
          <button type="button" className="ui-button" onClick={() => select()}>
            返回测试计划目录
          </button>
        </div>
      ) : (
        <>
          <section className="code-settings-versions" aria-label="测试计划目录">
            <header className="code-settings-section-heading">
              <h2>测试计划目录</h2>
            </header>
            <form className="code-settings-form-actions" onSubmit={(event) => void create(event)}>
              <label>
                新计划名称{' '}
                <input
                  className="ui-input"
                  value={name}
                  disabled={busy}
                  onChange={(event) => setName(event.currentTarget.value)}
                />
              </label>
              <button
                className="ui-button"
                type="submit"
                disabled={reason !== null}
                title={reason ?? undefined}
              >
                创建测试计划
              </button>
              {reason && <p className="read-status">{reason}</p>}
            </form>
            {notice && <p role="status">{notice}</p>}
            {error && (
              <p className="inline-error" role="alert">
                {error}
              </p>
            )}
            {recoveryState.error && (
              <p className="inline-error" role="alert">
                {recoveryState.error}
              </p>
            )}
            {recoveryState.records && recoveryState.records.length > 0 && (
              <section aria-label="原计划请求">
                <button
                  type="button"
                  className="ui-button"
                  disabled={recoveryState.loading}
                  title={recoveryState.loading ? '正在核对原请求' : undefined}
                  onClick={() => void recovery.reader.refresh()}
                >
                  核对原计划请求
                </button>
                {recoveryState.records.map((row) => (
                  <div key={row.key}>
                    <p>
                      {row.path === testingPlansPath
                        ? '原创建请求结果待核对'
                        : '原计划控制结果待核对'}
                    </p>
                    {recoveryState.rowErrors[row.key] && (
                      <p role="alert" className="inline-error">
                        {recoveryState.rowErrors[row.key]}
                      </p>
                    )}
                    <RecoveryActions
                      record={row}
                      recovery={recovery.commands}
                      replayEnabled
                      settled={(original, result, message) => {
                        setNotice(message);
                        if (result !== null) applyOriginal(original, result);
                        if (!document.hidden) void recovery.reader.refresh();
                      }}
                    />
                  </div>
                ))}
              </section>
            )}
            <ReadState
              loading={plans.loading}
              error={plans.error}
              stale={plans.data !== null}
              retry={plans.reload}
            />
            {plans.data && (
              <>
                <ol className="code-settings-version-items">
                  {plans.data.data.items.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        className="ui-button"
                        aria-pressed={item.id === planId}
                        onClick={() => select(item.id)}
                      >
                        {item.name} · {item.versions_count} 个版本
                      </button>
                    </li>
                  ))}
                </ol>
                {plans.data.data.items.length === 0 && !plans.loading && !plans.error && (
                  <EmptyState
                    icon="outline"
                    message={page === 1 ? '当前没有测试计划' : '此页没有测试计划'}
                  />
                )}
                <Pager
                  meta={meta(plans.data.meta.pagination)}
                  page={page}
                  busy={plans.loading}
                  select={setPage}
                />
              </>
            )}
          </section>
          <section className="code-settings-versions" aria-label="测试计划版本">
            <h2>{plan.data?.data.name ?? '测试计划版本'}</h2>
            <ReadState
              loading={plan.loading}
              error={plan.error}
              stale={plan.data !== null}
              retry={plan.reload}
            />
            {planId === null && <EmptyState icon="outline" message="请选择测试计划" />}
            {plan.data && (
              <>
                <ReadState
                  loading={versions.loading}
                  error={versions.error}
                  stale={versions.data !== null}
                  retry={versions.reload}
                />
                {versions.data && (
                  <>
                    <ol className="code-settings-version-items">
                      {versions.data.data.items.map((item) => (
                        <li key={item.id}>
                          <button
                            type="button"
                            className="ui-button"
                            aria-pressed={item.id === versionId}
                            onClick={() => select(item.plan_id, item.id)}
                          >
                            版本 {item.version} · {statuses[item.status]}
                          </button>
                        </li>
                      ))}
                    </ol>
                    {versions.data.data.items.length === 0 &&
                      !versions.loading &&
                      !versions.error && (
                        <EmptyState
                          icon="outline"
                          message={currentVersionPage === 1 ? '此计划尚无版本' : '此页没有计划版本'}
                        />
                      )}
                    <Pager
                      meta={meta(versions.data.meta.pagination)}
                      page={currentVersionPage}
                      busy={versions.loading}
                      select={(page) => setVersionPage({ plan: planId, page })}
                    />
                  </>
                )}
                <ReadState
                  loading={version.loading}
                  error={version.error}
                  stale={version.data !== null}
                  retry={version.reload}
                />
                {versionId === null && (
                  <EmptyState icon="outline" message="请选择测试计划版本" compact />
                )}
              </>
            )}
          </section>
          {ownerPlan !== null && plan.error === null && (
            <PlanDraftEditor
              key={ownerPlan + ':new'}
              api={api}
              planId={ownerPlan}
              version={null}
              recovery={recovery.commands}
              blocked={draftUnavailable(draftPath(ownerPlan, null))}
              recovered={receipts[draftPath(ownerPlan, null)]}
              saved={(result) => savedDraft(result, true)}
              refresh={refreshDraft}
            />
          )}
          {version.data && (
            <>
              <FixedVersion version={version.data.data} />
              {version.data.data.status === 'DRAFT' && ownerPlan !== null && (
                <PlanDraftEditor
                  key={version.data.data.id}
                  api={api}
                  planId={ownerPlan}
                  version={version.data.data}
                  recovery={recovery.commands}
                  blocked={
                    version.error
                      ? '请先核实原草稿版本'
                      : draftUnavailable(draftPath(ownerPlan, version.data.data.id))
                  }
                  recovered={receipts[draftPath(ownerPlan, version.data.data.id)]}
                  saved={(result) => savedDraft(result, false)}
                  refresh={refreshDraft}
                  dirty={dirty}
                />
              )}
              <PlanControls
                key={version.data.data.id + ':' + version.data.data.status}
                version={version.data.data}
                recovery={recovery.commands}
                unavailable={
                  version.error || version.loading
                    ? '请先核实固定计划版本'
                    : dirtyVersion === version.data.data.id
                      ? '请先保存或清除当前版本的本地草稿改动'
                      : recoveryState.error || recoveryState.records === null
                        ? '请先核对原请求存储'
                        : recoveryState.records.some(
                              (record) =>
                                record.path ===
                                  testingPlanControlPath(version.data!.data.id, 'publish') ||
                                record.path ===
                                  testingPlanControlPath(version.data!.data.id, 'revoke') ||
                                record.path ===
                                  draftPath(version.data!.data.plan_id, version.data!.data.id),
                            )
                          ? '请先核对当前版本的原计划请求'
                          : null
                }
                refresh={(message, reload) => {
                  if (message !== null) setNotice(message);
                  if (reload) {
                    version.reload();
                    versions.reload();
                  }
                  if (!document.hidden) void recovery.reader.refresh();
                }}
              />
              <PlanPacks
                key={version.data.data.id}
                api={api}
                version={version.data.data}
                packId={packId}
                validationId={validationId}
                validationReceipt={packId === null ? undefined : validations[packId]}
                controlVersion={packId === null ? undefined : packControls[packId]}
                pending={draftUnavailable}
                openTask={openTask}
                recovery={recovery.commands}
                unavailable={
                  version.error || version.loading
                    ? '请先核实所选计划版本'
                    : draftUnavailable(testingPackListPath(version.data.data.id))
                }
                receipt={packReceipts[testingPackListPath(version.data.data.id)]}
                sealReceipt={
                  packId === null ? undefined : sealReceipts[testingPackSealPath(packId)]
                }
                sealUnavailable={
                  packId === null ? null : draftUnavailable(testingPackSealPath(packId))
                }
                select={(id, validation) => {
                  const selectedVersion = version.data?.data;
                  if (selectedVersion && currentSelection.current.versionId === selectedVersion.id)
                    select(selectedVersion.plan_id, selectedVersion.id, id, validation);
                }}
                refresh={() => {
                  if (!document.hidden) void recovery.reader.refresh();
                }}
              />
            </>
          )}
        </>
      )}
    </main>
  );
}
