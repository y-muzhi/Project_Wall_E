import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { positiveInteger, snapshotObject } from '../api/client.ts';
import { array, choices, count, id, nullable, shape, text } from '../api/decoding.ts';
import { money, moneyMicro } from '../api/code-values.ts';
import { testingAuthorizationPath } from '../api/testing-policy.ts';
import { createTestingTaskInput, testingTasksPath } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { environmentBrowserStorage } from '../api/environment-storage.ts';
import { optionPage, PagedTaskSelect } from '../code-tasks/create-selection.tsx';
import { useSettingsVisibility } from '../code-tasks/settings/read.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { AssetSelection } from './asset-selection.tsx';
import { errorText, ReadState, useTestingRead } from './plans/read.tsx';
import { PlanBasis } from './plan-editor/basis.tsx';
import { textId } from './task-controls.tsx';
import type { useTestingRecovery } from './task-recovery.tsx';

const STORAGE = 'walle:testing-create:v1';
const material = shape({ document_id: id, revision_id: id });
const decodeDraft = shape({
  requirement_id: nullable(id),
  document_id: nullable(id),
  design_revision_id: nullable(id),
  material_refs: array(material, 256),
  source: choices(['SNAPSHOT', 'CANDIDATE']),
  codingTask: text,
  sourceId: text,
  purpose: choices(['DIAGNOSTIC', 'ACCEPTANCE']),
  profile: nullable(id),
  authorization: text,
  budget: text,
  assets: nullable(shape({ plan: id, pack: id })),
  previous: nullable(id),
});
type Draft = ReturnType<typeof decodeDraft>;
export type CodingTestingSeed = Pick<
  Draft,
  'requirement_id' | 'document_id' | 'design_revision_id' | 'material_refs'
> &
  Readonly<{ task: number; candidate: number }>;
const defaults: Draft = {
  requirement_id: null,
  document_id: null,
  design_revision_id: null,
  material_refs: [],
  source: 'SNAPSHOT',
  codingTask: '',
  sourceId: '',
  purpose: 'DIAGNOSTIC',
  profile: null,
  authorization: '',
  budget: '0.000000',
  assets: null,
  previous: null,
};
const decodeSession = shape({
  draft: decodeDraft,
  revision: count,
  original: nullable(shape({ key: text, revision: count, kind: choices(['approve', 'create']) })),
});
type Session = ReturnType<typeof decodeSession>;
function restore(
  api: WalleApi,
  storage: string,
  fixed: Draft,
  pinned?: CodingTestingSeed,
): Session {
  try {
    const raw = environmentBrowserStorage('sessionStorage', api.environmentScope).getItem(storage);
    if (raw !== null) {
      const saved = decodeSession(JSON.parse(raw));
      if (pinned === undefined) return saved;
      return {
        ...saved,
        draft: {
          ...saved.draft,
          requirement_id: fixed.requirement_id,
          document_id: fixed.document_id,
          design_revision_id: fixed.design_revision_id,
          material_refs: fixed.material_refs,
          source: fixed.source,
          sourceId: fixed.sourceId,
          codingTask: fixed.codingTask,
        },
      };
    }
  } catch {
    // An invalid session draft has no authority over the command ledger.
  }
  return { draft: fixed, revision: 0, original: null };
}
export type CreationReceipt = Readonly<{ key: string; id: number; kind: 'approve' | 'create' }>;

export function CreateTestingTaskDrawer({
  api,
  access,
  received,
  pinned,
  close,
  created,
}: Readonly<{
  api: WalleApi;
  access: ReturnType<typeof useTestingRecovery>;
  received: CreationReceipt | null;
  pinned?: CodingTestingSeed;
  close(): void;
  created(id: number): void;
}>) {
  const heading = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const live = useRef(false);
  const sending = useRef(false);
  const storage =
    pinned === undefined
      ? STORAGE
      : 'walle:v2.0:testing:create:' +
        location.origin +
        ':CODING:' +
        pinned.task +
        ':' +
        pinned.candidate;
  const fixed: Draft =
    pinned === undefined
      ? defaults
      : {
          ...defaults,
          requirement_id: pinned.requirement_id,
          document_id: pinned.document_id,
          design_revision_id: pinned.design_revision_id,
          material_refs: pinned.material_refs,
          source: 'CANDIDATE',
          codingTask: String(pinned.task),
          sourceId: String(pinned.candidate),
          purpose: 'ACCEPTANCE',
        };
  const [session, setSession] = useState(() => restore(api, storage, fixed, pinned));
  const snapshot = useRef(session);
  snapshot.current = session;
  const draft = session.draft;
  const [busy, setBusy] = useState<'approve' | 'create' | null>(null);
  const [confirmApproval, setConfirmApproval] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceCheck, setSourceCheck] = useState<{
    kind: Draft['source'];
    id: number;
    task: number | null;
  } | null>(() =>
    pinned === undefined
      ? null
      : {
          kind: 'CANDIDATE',
          id: pinned.candidate,
          task: pinned.task,
        },
  );
  const [grantCheck, setGrantCheck] = useState<number | null>(null);
  const visible = useSettingsVisibility();

  function save(next: Session) {
    snapshot.current = next;
    setSession(next);
    try {
      environmentBrowserStorage('sessionStorage', api.environmentScope).setItem(
        storage,
        JSON.stringify(next),
      );
    } catch {
      setError('此浏览器暂时无法保存会话草稿');
    }
  }
  function change(values: Partial<Draft>) {
    const current = snapshot.current;
    save({ ...current, draft: { ...current.draft, ...values }, revision: current.revision + 1 });
  }
  useEffect(() => {
    live.current = true;
    dialog.current?.showModal();
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (received === null) return;
    const current = snapshot.current,
      original = current.original;
    if (original === null || original.key !== received.key || original.kind !== received.kind)
      return;
    if (original.revision !== current.revision) {
      save({ ...current, original: null });
    } else if (received.kind === 'approve') {
      save({
        ...current,
        original: null,
        draft: { ...current.draft, authorization: String(received.id) },
      });
      setGrantCheck(received.id);
    } else {
      save({ draft: fixed, revision: current.revision + 1, original: null });
      created(received.id);
    }
  }, [received, created]);

  const profiles = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.testingProfiles(page, null, signal), (row) => ({
        id: row.id,
        label: row.name + ' · 版本 ' + row.version,
      })),
    [api],
  );
  const fixedSource = useCallback(
    async (signal: AbortSignal) => {
      const wanted = sourceCheck!;
      if (wanted.kind === 'SNAPSHOT') {
        const response = await api.codeSnapshot(wanted.id, signal);
        return {
          ...response,
          data: {
            kind: 'SNAPSHOT' as const,
            id: response.data.id,
            reference: response.data.commit_oid,
            published: false,
          },
        };
      }
      const response = await api.codeTaskCandidate(wanted.task!, wanted.id, signal);
      return {
        ...response,
        data: {
          kind: 'CANDIDATE' as const,
          id: response.data.id,
          reference: response.data.content_tree_oid,
          published:
            response.data.role === 'INTEGRATION' && response.data.published_for_testing_at !== null,
        },
      };
    },
    [api, sourceCheck],
  );
  const source = useTestingRead(
    'creation-source:' + JSON.stringify(sourceCheck),
    sourceCheck === null ? null : fixedSource,
  );
  const approval = useCallback(
    (signal: AbortSignal) => api.testingAuthorization(grantCheck!, signal),
    [api, grantCheck],
  );
  const grant = useTestingRead(
    'creation-approval:' + grantCheck,
    grantCheck === null ? null : approval,
  );
  const getRevision = useCallback(
    (signal: AbortSignal) => api.getRevision(draft.design_revision_id!, signal),
    [api, draft.design_revision_id],
  );
  const revision = useTestingRead(
    'creation-basis:' + draft.design_revision_id,
    draft.design_revision_id === null ? null : getRevision,
  );

  const target = textId(draft.sourceId),
    coding = textId(draft.codingTask);
  const scope = source.data?.data;
  const authorized = grant.data?.data;
  let amount: string | null = null;
  try {
    amount = money(draft.budget);
  } catch {
    /* Wait for a complete decimal. */
  }
  const fixedBasis =
    draft.requirement_id !== null && draft.document_id !== null && draft.design_revision_id !== null
      ? {
          requirement_id: draft.requirement_id,
          document_id: draft.document_id,
          design_revision_id: draft.design_revision_id,
          material_refs: draft.material_refs,
        }
      : null;
  let createBlock = access.blocked(testingTasksPath);
  if (
    createBlock === null &&
    (fixedBasis === null ||
      revision.loading ||
      revision.error !== null ||
      revision.data?.data.id !== fixedBasis.design_revision_id)
  )
    createBlock = '请选择并核对固定设计版本';
  if (
    createBlock === null &&
    (source.loading ||
      source.error !== null ||
      scope?.id !== target ||
      scope?.kind !== draft.source ||
      (pinned !== undefined && scope?.published !== true))
  )
    createBlock = '请核对固定受测来源';
  if (
    createBlock === null &&
    draft.source === 'CANDIDATE' &&
    draft.purpose === 'ACCEPTANCE' &&
    scope?.published !== true
  )
    createBlock = '验收需要已发布的联调候选';
  if (createBlock === null && (draft.profile === null || amount === null))
    createBlock = '请选择独立测试配置和有效预算';
  if (
    createBlock === null &&
    (grant.loading ||
      grant.error !== null ||
      authorized?.id !== textId(draft.authorization) ||
      authorized.scope_kind !== 'TASK' ||
      authorized.status !== 'APPROVED_UNBOUND' ||
      authorized.profile_version_id !== draft.profile ||
      moneyMicro(authorized.budget_limit_cny) < moneyMicro(amount))
  )
    createBlock = '请核对适用于此配置和预算的独立授权';
  const approveBlock =
    access.blocked(testingAuthorizationPath) ??
    (draft.profile === null || amount === null ? '请选择独立测试配置和有效预算' : null);

  async function send(kind: 'approve' | 'create') {
    if (
      sending.current ||
      (kind === 'approve' ? !confirmApproval || approveBlock !== null : createBlock !== null)
    )
      return;
    const stamp = snapshot.current.revision;
    const body =
      kind === 'approve'
        ? { profile_version_id: draft.profile!, scope_kind: 'TASK', budget_limit_cny: amount! }
        : createTestingTaskInput({
            ...fixedBasis!,
            target_kind: draft.source,
            candidate_id: draft.source === 'CANDIDATE' ? target : null,
            snapshot_id: draft.source === 'SNAPSHOT' ? target : null,
            purpose: draft.purpose,
            profile_version_id: draft.profile!,
            authorization_id: authorized!.id,
            budget_limit_cny: amount!,
            plan_version_id: draft.assets?.plan ?? null,
            test_pack_version_id: draft.assets?.pack ?? null,
            previous_testing_task_id: draft.previous,
          });
    sending.current = true;
    setBusy(kind);
    setError(null);
    try {
      const staged = await access.recovery.stageIntent(
        kind === 'approve' ? testingAuthorizationPath : testingTasksPath,
        snapshotObject(body),
      );
      if (staged.kind !== 'PREPARED') {
        if (live.current) setError('已有原请求，请先核对');
        return;
      }
      if (!live.current) return;
      save({ ...snapshot.current, original: { key: staged.record.key, revision: stamp, kind } });
      const response = await access.recovery.send(staged.record.key, staged.record.record_revision);
      if (!live.current || snapshot.current.revision !== stamp) return;
      if (kind === 'approve') {
        const grantId = positiveInteger((response.response.data as { id: number }).id);
        save({
          ...snapshot.current,
          original: null,
          draft: { ...snapshot.current.draft, authorization: String(grantId) },
        });
        setGrantCheck(grantId);
      } else {
        const taskId = positiveInteger(
          (response.response.data as { testing_task_id: number }).testing_task_id,
        );
        save({ draft: fixed, revision: stamp + 1, original: null });
        created(taskId);
      }
    } catch (failure) {
      if (live.current) setError(errorText(failure, '暂时无法核实独立任务原请求'));
    } finally {
      sending.current = false;
      if (live.current) {
        setBusy(null);
        setConfirmApproval(false);
        void access.reader.refresh();
      }
    }
  }
  const busyReason = busy !== null ? '正在提交原请求' : null;
  return (
    <dialog
      ref={dialog}
      className="create-drawer code-task-drawer"
      aria-labelledby={heading}
      onCancel={(event) => {
        event.preventDefault();
        if (busy === null) close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send('create');
        }}
      >
        <header>
          <h2 id={heading}>创建独立测试任务</h2>
        </header>
        <div className="code-task-drawer-fields">
          <PlanBasis
            api={api}
            draft={draft}
            confirmed
            frozen={pinned !== undefined}
            disabled={busy !== null}
            change={(next) => change({ ...next, assets: null })}
          />
          <ReadState
            loading={revision.loading}
            error={revision.error}
            stale={revision.data !== null}
            retry={revision.reload}
          />
          {revision.data && (
            <details>
              <summary>查看固定设计原文</summary>
              <pre className="testing-design-preview">{revision.data.data.markdown_content}</pre>
            </details>
          )}
          <fieldset disabled={busy !== null}>
            <legend>固定受测代码</legend>
            <div className="code-settings-form-actions">
              {pinned !== undefined && (
                <p>
                  Coding 任务 #{pinned.task} · 固定候选 #{pinned.candidate}
                </p>
              )}
              {pinned === undefined && (
                <label>
                  来源{' '}
                  <select
                    className="ui-input"
                    value={draft.source}
                    onChange={(event) => {
                      setSourceCheck(null);
                      change({
                        source: event.currentTarget.value as Draft['source'],
                        sourceId: '',
                        codingTask: '',
                      });
                    }}
                  >
                    <option value="SNAPSHOT">仓库快照</option>
                    <option value="CANDIDATE">Coding 候选</option>
                  </select>
                </label>
              )}
              {pinned === undefined && draft.source === 'CANDIDATE' && (
                <label>
                  Coding 任务编号{' '}
                  <input
                    className="ui-input"
                    inputMode="numeric"
                    value={draft.codingTask}
                    onChange={(event) => {
                      setSourceCheck(null);
                      change({ codingTask: event.currentTarget.value });
                    }}
                  />
                </label>
              )}
              {pinned === undefined && (
                <>
                  {' '}
                  <label>
                    {draft.source === 'CANDIDATE' ? '候选编号' : '已登记快照编号'}{' '}
                    <input
                      className="ui-input"
                      inputMode="numeric"
                      value={draft.sourceId}
                      onChange={(event) => {
                        setSourceCheck(null);
                        change({ sourceId: event.currentTarget.value });
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="ui-button"
                    disabled={target === null || (draft.source === 'CANDIDATE' && coding === null)}
                    onClick={() =>
                      setSourceCheck({ kind: draft.source, id: target!, task: coding })
                    }
                  >
                    核对固定来源
                  </button>
                </>
              )}
              <label>
                用途{' '}
                <select
                  className="ui-input"
                  value={draft.purpose}
                  onChange={(event) =>
                    change({ purpose: event.currentTarget.value as Draft['purpose'] })
                  }
                >
                  <option value="DIAGNOSTIC">诊断</option>
                  <option value="ACCEPTANCE">验收</option>
                </select>
              </label>
            </div>
            <ReadState
              loading={source.loading}
              error={source.error}
              stale={scope !== undefined}
              retry={source.reload}
            />
            {scope && (
              <p>
                固定来源 #{scope.id} · <code>{scope.reference}</code>
              </p>
            )}
          </fieldset>
          <fieldset disabled={busy !== null}>
            <legend>独立配置与授权</legend>
            <PagedTaskSelect
              label="独立测试配置"
              load={profiles}
              visible={visible}
              value={draft.profile}
              disabled={busy !== null}
              change={(profile) => {
                setGrantCheck(null);
                change({ profile, authorization: '' });
              }}
            />
            <div className="code-settings-form-actions">
              <label>
                模型总预算（元）{' '}
                <input
                  className="ui-input"
                  inputMode="decimal"
                  value={draft.budget}
                  onChange={(event) => change({ budget: event.currentTarget.value })}
                />
              </label>
              <label>
                独立授权编号{' '}
                <input
                  className="ui-input"
                  inputMode="numeric"
                  value={draft.authorization}
                  onChange={(event) => {
                    setGrantCheck(null);
                    change({ authorization: event.currentTarget.value });
                  }}
                />
              </label>
              <button
                type="button"
                className="ui-button"
                disabled={textId(draft.authorization) === null}
                onClick={() => {
                  const value = textId(draft.authorization);
                  if (value === grantCheck) grant.reload();
                  else setGrantCheck(value);
                }}
              >
                核对授权
              </button>
              <button
                type="button"
                className="ui-button"
                disabled={approveBlock !== null}
                title={approveBlock ?? undefined}
                onClick={() => setConfirmApproval(true)}
              >
                批准独立测试授权
              </button>
            </div>
            <ReadState
              loading={grant.loading}
              error={grant.error}
              stale={authorized !== undefined}
              retry={grant.reload}
            />
            {authorized && (
              <p>
                授权 #{authorized.id} · 批准上限 {authorized.budget_limit_cny} 元
              </p>
            )}
          </fieldset>
          {fixedBasis !== null && (
            <details>
              <summary>选择计划与测试包（可选）</summary>
              <AssetSelection
                key={JSON.stringify(fixedBasis)}
                api={api}
                basis={fixedBasis}
                disabled={busy !== null}
                change={(assets) => change({ assets })}
              />
              {draft.assets && (
                <p>
                  已选计划版本 #{draft.assets.plan} · 测试包 #{draft.assets.pack}
                  <button
                    className="ui-button"
                    type="button"
                    onClick={() => change({ assets: null })}
                  >
                    清除选择
                  </button>
                </p>
              )}
            </details>
          )}
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <footer className="code-settings-form-actions">
          <button type="button" className="ui-button" disabled={busy !== null} onClick={close}>
            取消
          </button>
          <button
            type="submit"
            className="ui-button"
            disabled={busy !== null || createBlock !== null}
            title={busyReason ?? createBlock ?? undefined}
          >
            创建测试任务
          </button>
          {(busyReason ?? createBlock) && (
            <p className="read-status">{busyReason ?? createBlock}</p>
          )}
        </footer>
      </form>
      <Confirmation
        open={confirmApproval}
        title="批准独立测试授权"
        description={'批准所选 Testing 配置，模型总预算上限 ' + (amount ?? '—') + ' 元。'}
        busy={busy === 'approve'}
        confirmDisabled={approveBlock !== null && busy === null}
        confirmLabel="确认批准"
        confirm={() => void send('approve')}
        cancel={() => setConfirmApproval(false)}
      />
    </dialog>
  );
}
