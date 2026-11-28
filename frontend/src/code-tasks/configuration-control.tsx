import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { configurationPath, fixedContentChanged } from '../api/code-task-configuration.ts';
import { exact, positiveInteger } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import { environmentBrowserStorage } from '../api/environment-storage.ts';
import type { OperationReader } from './command-recovery.ts';
import { optionPage, PagedTaskSelect } from './create-selection.tsx';
import { useCodeTaskCommand } from './handoff-command.ts';
import { AuthorizationScopeFacts } from './settings/authorization-view.tsx';
import { useSettingsRead } from './settings/read.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Draft = Readonly<{
  profile: number | null;
  version: number | null;
  grant: number | null;
  reason: string;
}>;
const emptyDraft: Draft = { profile: null, version: null, grant: null, reason: '' };
const draftId = (value: unknown) => (value === null ? null : positiveInteger(value));

function savedDraft(api: WalleApi, storageKey: string): Draft {
  try {
    const raw = environmentBrowserStorage('sessionStorage', api.environmentScope).getItem(
      storageKey,
    );
    if (raw === null) return emptyDraft;
    const row = exact(JSON.parse(raw), ['profile', 'version', 'grant', 'reason']);
    if (typeof row.reason !== 'string') return emptyDraft;
    const profile = draftId(row.profile);
    const version = profile === null ? null : draftId(row.version);
    return {
      profile,
      version,
      grant: version === null ? null : draftId(row.grant),
      reason: row.reason,
    };
  } catch {
    return emptyDraft;
  }
}

export function TaskConfigurationControl({
  api,
  task,
  visible,
  ready,
  changed,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  ready: boolean;
  changed(): void;
}>) {
  const key = 'walle:v2:coding-configuration:' + task.id;
  const [draft, setDraft] = useState(() => savedDraft(api, key));
  const [open, setOpen] = useState(false);
  const [attempt, retry] = useState(0);
  const [storageIssue, setStorageIssue] = useState(false);
  useEffect(() => {
    try {
      const storage = environmentBrowserStorage('sessionStorage', api.environmentScope);
      if (draft.profile === null && !draft.reason) storage.removeItem(key);
      else storage.setItem(key, JSON.stringify(draft));
      setStorageIssue(false);
    } catch {
      setStorageIssue(true);
    }
  }, [api, draft, key]);

  const readOperation = useCallback<OperationReader>(
    async (original, association, signal) => {
      if (association.task_id !== task.id || association.testing_task_id !== null)
        throw Error('原配置应用不属于当前任务');
      const { data } = await api.codeTaskOperation(task.id, association.operation_id, signal);
      if (data.operation_type !== 'APPLY_CONFIGURATION' || data.idempotency_key !== original.key)
        throw Error('原配置应用操作不一致');
      return {
        task_id: data.task_id,
        testing_task_id: null,
        operation_id: data.id,
        status: data.status,
      };
    },
    [api, task.id],
  );

  function accepted() {
    setDraft(emptyDraft);
    setOpen(false);
  }
  const command = useCodeTaskCommand(
    api,
    configurationPath(task.id),
    accepted,
    changed,
    '配置应用',
    '配置与授权已选定，等待执行实例核对生效。',
    readOperation,
  );
  const loadProfiles = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.codeExecutionProfiles(page, signal), (row) => ({
        id: row.id,
        label: row.name,
      })),
    [api],
  );
  const loadVersions = useCallback(
    async (page: number, signal: AbortSignal) => {
      if (draft.profile === null) throw Error('请先选择执行配置');
      return optionPage(
        await api.codeExecutionProfileVersions(draft.profile, page, signal),
        (row) => ({
          id: row.id,
          label: '版本 ' + row.version + (row.ready ? '' : ' · 执行条件未就绪'),
        }),
      );
    },
    [api, draft.profile],
  );
  const loadGrants = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(
        await api.codeAuthorizations(page, { status: 'APPROVED_UNBOUND' }, signal),
        (row) =>
          row.profile_version_id === draft.version
            ? { id: row.id, label: '授权 #' + row.id + ' · 已批准，未绑定' }
            : null,
      ),
    [api, draft.version],
  );

  const loadSelected = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      if (draft.grant === null || draft.version === null) return null;
      const [previous, next, grant] = await Promise.all([
        api.codeExecutionProfileVersion(task.execution_profile_version_id, signal),
        api.codeExecutionProfileVersion(draft.version, signal),
        api.codeAuthorization(draft.grant, signal),
      ]);
      return { previous: previous.data, next: next.data, grant: grant.data };
    },
    [api, attempt, draft.grant, draft.version, task.execution_profile_version_id],
  );
  const selected = useSettingsRead(
    loadSelected,
    visible && open && draft.grant !== null,
    '暂时无法核对所选配置与授权',
  );
  const pair = selected.value;
  const review =
    !selected.loading &&
    !selected.error &&
    pair &&
    pair.next.id === draft.version &&
    pair.next.profile_id === draft.profile &&
    pair.previous.id === task.execution_profile_version_id &&
    pair.grant.id === draft.grant &&
    pair.grant.profile_version_id === draft.version &&
    pair.grant.status === 'APPROVED_UNBOUND' &&
    pair.grant.task_id === null
      ? pair
      : null;

  const application = task.configuration_application;
  const verifyGrant =
    application?.status === 'APPLIED' &&
    application.evidence_result === 'VERIFIED' &&
    application.new_profile_version_id === task.execution_profile_version_id &&
    application.authorization_id === task.authorization_id;
  const loadEffectiveGrant = useCallback(
    async (signal: AbortSignal) =>
      (await api.codeAuthorization(task.authorization_id, signal)).data,
    [api, task.authorization_id],
  );
  const effective = useSettingsRead(
    loadEffectiveGrant,
    visible && verifyGrant,
    '暂时无法核实当前授权',
  );
  const isEffective =
    verifyGrant &&
    !effective.loading &&
    !effective.error &&
    effective.value?.task_id === task.id &&
    effective.value.id === task.authorization_id &&
    effective.value.profile_version_id === task.execution_profile_version_id &&
    effective.value.status === 'EFFECTIVE';
  const action = task.available_actions.find((entry) => entry.action === 'APPLY_CONFIGURATION');
  const unavailable = !ready
    ? '当前任务状态正在核对'
    : command.busy
      ? '正在处理配置应用请求'
      : !command.ready
        ? '正在核对本地请求'
        : command.pending
          ? '请先核对原配置请求'
          : application?.status === 'PENDING'
            ? task.started_at === null
              ? '所选配置将在启动时核对'
              : '原配置应用正在等待核对'
            : application?.status === 'UNKNOWN'
              ? '原配置结果待核对'
              : !action?.enabled
                ? action?.reason_code === 'OPERATION_IN_PROGRESS'
                  ? '请先完成或核对原操作'
                  : action?.reason_code === 'CONFIG_NOT_READY'
                    ? '运行配置核对服务尚未就绪'
                    : action?.reason_code === 'WRITER_ACTIVE'
                      ? '须先完成原写入与检查，再应用控制配置'
                      : '当前任务状态不能更换配置'
                : null;
  const gitChanged =
    review && JSON.stringify(review.previous.git) !== JSON.stringify(review.next.git);
  const nativeChanged =
    task.started_at !== null &&
    review &&
    (['executor', 'models', 'environment'] as const).some(
      (field) => JSON.stringify(review.previous[field]) !== JSON.stringify(review.next[field]),
    );
  const contentChanged = review && fixedContentChanged(review.previous, review.next);
  const formIssue =
    draft.profile === null || draft.version === null || draft.grant === null
      ? '请选择配置版本与适用授权'
      : !review
        ? '请先核对所选配置与授权'
        : gitChanged
          ? '此版本变更了固定 Git，须使用新任务'
          : contentChanged
            ? '此版本更改了固定内容规则或容量，须使用新任务'
            : nativeChanged
              ? '此版本涉及执行器、模型或环境变更，须使用新任务'
              : !draft.reason.trim()
                ? '请输入变更说明'
                : null;

  function selectProfile(profile: number | null) {
    setDraft((before) => ({ ...before, profile, version: null, grant: null }));
  }
  function selectVersion(version: number | null) {
    setDraft((before) => ({ ...before, version, grant: null }));
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unavailable || formIssue || draft.version === null || draft.grant === null) return;
    command.submit({
      expected_state_version: task.state_version,
      execution_profile_version_id: draft.version,
      authorization_id: draft.grant,
      reason: draft.reason,
    });
  }
  return (
    <section className="code-task-controls" aria-label="任务配置与授权">
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          aria-expanded={open}
          disabled={!open && unavailable !== null}
          title={unavailable ?? undefined}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? '收起配置选择' : '更换任务配置'}
        </button>
        {unavailable && <span className="read-status">{unavailable}</span>}
      </div>
      {application && (
        <p role="status">
          配置版本 #{application.new_profile_version_id} · 授权 #{application.authorization_id} ·{' '}
          {isEffective
            ? '已核实生效'
            : application.status === 'PENDING'
              ? task.started_at === null
                ? '待启动核对'
                : '待核对生效'
              : application.status === 'APPLYING'
                ? '正在应用'
                : application.status === 'FAILED'
                  ? '应用未完成'
                  : '配置结果待核对'}
          {application.difference_kinds.length > 0 &&
            ' · ' + application.difference_kinds.join('、')}
        </p>
      )}
      {verifyGrant && effective.error && <p role="alert">{effective.error}</p>}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {command.busy && (
        <button className="ui-button" type="button" onClick={command.stop}>
          停止等待本次响应
        </button>
      )}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            type="button"
            className="ui-button"
            disabled={command.busy}
            onClick={command.lookup}
          >
            核对原配置请求
          </button>
          {command.pending.status === 'ACCEPTED' && (
            <button
              type="button"
              className="ui-button"
              disabled={command.busy}
              onClick={command.observe}
            >
              读取原应用进度
            </button>
          )}
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={false}
            settled={command.settled}
          />
        </div>
      )}
      {open && (
        <form className="code-task-result" aria-label="选择任务配置" onSubmit={submit}>
          <p>
            当前选定版本 #{task.execution_profile_version_id} · 授权 #{task.authorization_id}
          </p>
          {task.started_at !== null && (
            <p>
              运行中的任务可调整调用与等待限制、检查标准、检查输出上限，以及原启动范围内固定依据的读取授权。应用后须重新自检；更改执行器、模型或环境须新建任务。
            </p>
          )}
          <PagedTaskSelect
            label="新执行配置"
            value={draft.profile}
            change={selectProfile}
            load={loadProfiles}
            visible={visible}
            disabled={unavailable !== null}
          />
          {draft.profile !== null && (
            <PagedTaskSelect
              key={draft.profile}
              label="新配置版本"
              value={draft.version}
              change={selectVersion}
              load={loadVersions}
              visible={visible}
              disabled={unavailable !== null}
            />
          )}
          {draft.version !== null && (
            <PagedTaskSelect
              key={'grant-' + draft.version}
              label="新适用授权"
              value={draft.grant}
              change={(grant) => setDraft((before) => ({ ...before, grant }))}
              load={loadGrants}
              visible={visible}
              disabled={unavailable !== null}
            />
          )}
          <a href="/settings/code?section=authorizations">查看授权设置</a>
          {draft.grant !== null && selected.loading && <p role="status">正在核对新配置与授权…</p>}
          {selected.error && (
            <p role="alert">
              {selected.error}{' '}
              <button
                className="ui-button"
                type="button"
                onClick={() => retry((value) => value + 1)}
              >
                重试核对
              </button>
            </p>
          )}
          {review && (
            <>
              <p aria-label="检查标准变更">
                当前检查标准版本 #{review.previous.check_set_version_id} · 目标检查标准版本 #
                {review.next.check_set_version_id}
                {review.previous.check_set_version_id !== review.next.check_set_version_id &&
                  ' · 生效后须重新自检，原发布及检查历史保留'}
              </p>
              {review.grant.scope.model_profile_refs.length === 0 && (
                <p role="status" aria-label="模型调用授权提示">
                  此授权不允许后续模型调用，应用配置不会自动继续执行。
                </p>
              )}
              <p aria-label="目标检查输出上限">
                目标检查输出上限：
                {Math.min(
                  review.next.limits.max_check_output_bytes,
                  review.grant.scope.limits.max_check_output_bytes,
                )}{' '}
                字节
              </p>
              <dl className="code-settings-resource-facts" aria-label="待应用授权范围">
                <AuthorizationScopeFacts scope={review.grant.scope} />
              </dl>
            </>
          )}
          <label>
            变更说明{' '}
            <textarea
              value={draft.reason}
              disabled={unavailable !== null}
              onChange={(event) => {
                const reason = event.target.value;
                setDraft((before) => ({ ...before, reason }));
              }}
            />
          </label>
          {storageIssue && <p role="status">浏览器暂时无法保存未提交的选择。</p>}
          {formIssue && <p className="read-status">{formIssue}</p>}
          <div className="code-task-toolbar">
            <button
              type="submit"
              className="ui-button primary"
              disabled={unavailable !== null || formIssue !== null}
            >
              应用配置
            </button>
            <button type="button" className="ui-button" onClick={() => setOpen(false)}>
              取消
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
