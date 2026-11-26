import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { WalleApi } from '../api/walle.ts';
import type { DocumentSummary } from '../api/models.ts';
import type { DesignRevisionUsage } from '../api/code-design-revisions.ts';
import type { ExecutionProfileVersion } from '../api/code-execution-profiles.ts';
import { snapshotObject } from '../api/client.ts';
import { gitObjectId } from '../api/code-repository-observations.ts';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Icon } from '../shared/icon.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { SingleSelect } from '../shared/single-select.tsx';
import type { RefObject } from 'react';
import { useSettingsRead } from './settings/read.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { optionPage, PagedTaskSelect } from './create-selection.tsx';
import { useCreationCommands } from './create-commands.ts';
import { createTaskPath, freshDraft, proposedScope, restoreCreateDraft } from './create-draft.ts';
import type { CreateTaskDraft } from './create-draft.ts';
import { ACTIVE_TASK_STATUSES } from './list-model.ts';

type Props = Readonly<{
  api: WalleApi;
  requirementId: number;
  documentId: number;
  documentTitle: string;
  revisionId: number | null;
  visible: boolean;
  activeTaskId: number | null;
  close(): void;
  returnFocus: RefObject<HTMLButtonElement | null>;
  created(taskId: number): void;
  conflict(taskId: number): void;
  settings(): void;
}>;

function unavailable(reason: string | null) {
  return reason === 'EMPTY_MAIN' ? '正文为空' : reason === 'UNCONFIRMED' ? '尚未确认' : '暂不可用';
}

async function selectedDesign(
  api: WalleApi,
  requirementId: number,
  documentId: number,
  revisionId: number,
  usage: DesignRevisionUsage,
  signal: AbortSignal,
) {
  for (let page = 1; page <= 100000; page++) {
    const result = await api.codeDesignRevisions(documentId, usage, page, signal);
    const row = result.data.items.find((item) => item.revision_id === revisionId);
    if (row) return row.requirement_id === requirementId && row.eligible;
    const pagination = result.meta.pagination;
    if (!pagination || !('page' in pagination) || page >= pagination.total_pages || signal.aborted)
      return false;
  }
  return false;
}

function RevisionSelect({
  api,
  requirementId,
  documentId,
  usage,
  value,
  change,
  disabled,
  visible,
}: Readonly<{
  api: WalleApi;
  requirementId: number;
  documentId: number;
  usage: DesignRevisionUsage;
  value: number | null;
  change(id: number | null): void;
  disabled: boolean;
  visible: boolean;
}>) {
  const load = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.codeDesignRevisions(documentId, usage, page, signal), (row) => ({
        id: row.revision_id,
        label:
          '版本 ' +
          row.version_no +
          (row.eligible ? ' · 已确认' : ' · ' + unavailable(row.reason_code)),
        disabled: !row.eligible || row.requirement_id !== requirementId,
      })),
    [api, requirementId, documentId, usage],
  );
  return (
    <PagedTaskSelect
      label={usage === 'MAIN' ? '固定设计版本' : '材料版本'}
      value={value}
      change={change}
      load={load}
      disabled={disabled}
      visible={visible}
    />
  );
}

function RevisionPreview({
  api,
  id,
  requirementId,
  documentId,
  visible,
}: Readonly<{
  api: WalleApi;
  id: number;
  requirementId: number;
  documentId: number;
  visible: boolean;
}>) {
  const load = useCallback(
    async (signal: AbortSignal) => {
      const row = (await api.getRevision(id, signal)).data;
      if (row.document_id !== documentId || row.requirement_id !== requirementId)
        throw Error('Fixed document owner differs');
      return row;
    },
    [api, id, requirementId, documentId],
  );
  const preview = useSettingsRead(load, visible, '暂时无法读取所选版本');
  return (
    <section aria-label="原版本正文">
      {preview.loading && <p role="status">正在读取原版本…</p>}
      {preview.error && <p role="alert">{preview.error}</p>}
      {preview.value &&
        (preview.value.markdown_content ? (
          <pre>{preview.value.markdown_content}</pre>
        ) : (
          <EmptyState icon="outline" message="所选版本正文为空" compact />
        ))}
    </section>
  );
}

function MaterialChoices({
  api,
  documents,
  draft,
  update,
  disabled,
  visible,
}: Readonly<{
  api: WalleApi;
  documents: readonly DocumentSummary[];
  draft: CreateTaskDraft;
  update(change: Partial<CreateTaskDraft>): void;
  disabled: boolean;
  visible: boolean;
}>) {
  const materialInput = useId();
  const [documentId, setDocumentId] = useState<number | null>(null);
  const [preview, setPreview] = useState(false);
  const selected = draft.material_refs.find((item) => item.document_id === documentId);
  const materials = documents.filter((doc) => doc.id !== draft.document_id);
  function choose(revisionId: number | null) {
    if (documentId === null) return;
    const other = draft.material_refs.filter((item) => item.document_id !== documentId);
    update({
      material_refs:
        revisionId === null
          ? other
          : [...other, { document_id: documentId, revision_id: revisionId }],
    });
    setPreview(false);
  }
  return (
    <>
      <div className="code-drawer-field">
        <label htmlFor={materialInput}>材料文档（可选）</label>
        <SingleSelect
          id={materialInput}
          label="材料文档"
          value={documentId === null ? '' : String(documentId)}
          disabled={disabled || materials.length === 0}
          placeholder={materials.length === 0 ? '暂无可选材料文档' : '选择材料文档'}
          options={
            materials.length === 0
              ? []
              : [
                  { value: '', label: '暂不选择' },
                  ...materials.map((doc) => ({ value: String(doc.id), label: doc.name })),
                ]
          }
          change={(value) => {
            setDocumentId(value ? Number(value) : null);
            setPreview(false);
          }}
        />
      </div>
      {documentId !== null && (
        <RevisionSelect
          key={documentId}
          api={api}
          requirementId={draft.requirement_id}
          documentId={documentId}
          usage="MATERIAL"
          value={selected?.revision_id ?? null}
          change={choose}
          disabled={disabled}
          visible={visible}
        />
      )}
      {selected && (
        <button
          type="button"
          className="ui-button"
          aria-expanded={preview}
          onClick={() => setPreview(!preview)}
        >
          阅读所选材料
        </button>
      )}
      {selected && preview && (
        <RevisionPreview
          key={selected.revision_id}
          api={api}
          id={selected.revision_id}
          documentId={selected.document_id}
          requirementId={draft.requirement_id}
          visible={visible}
        />
      )}
      {draft.material_refs.length > 0 && (
        <ul aria-label="已选固定材料">
          {draft.material_refs.map((item) => (
            <li key={item.document_id}>
              {materials.find((doc) => doc.id === item.document_id)?.name ??
                '文档 #' + item.document_id}{' '}
              · 版本 #{item.revision_id}{' '}
              <button
                type="button"
                className="ui-button"
                disabled={disabled}
                onClick={() =>
                  update({
                    material_refs: draft.material_refs.filter(
                      (row) => row.document_id !== item.document_id,
                    ),
                  })
                }
              >
                移除材料
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Approval({
  profile,
  disabled,
  approve,
}: Readonly<{
  profile: ExecutionProfileVersion;
  disabled: boolean;
  approve(scope: ReturnType<typeof proposedScope>): void;
}>) {
  const [commands, setCommands] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [delivery, setDelivery] = useState(false);
  const [review, setReview] = useState(false);
  const modelRefs = [profile.models.primary_profile_ref, ...profile.models.auxiliary_profile_refs];
  function toggle(values: string[], id: string) {
    return values.includes(id) ? values.filter((value) => value !== id) : [...values, id];
  }
  const scope = proposedScope(profile, commands, models, delivery);
  return (
    <details>
      <summary>审阅并批准新授权</summary>
      <p>只允许写入任务工作区。此授权不额外开放读取目录或网络目标。</p>
      {profile.commands.map((command) => (
        <label key={command.command_id}>
          <input
            type="checkbox"
            disabled={disabled}
            checked={commands.includes(command.command_id)}
            onChange={() => setCommands(toggle(commands, command.command_id))}
          />{' '}
          命令 {command.command_id}
        </label>
      ))}
      {modelRefs.map((id) => (
        <label key={id}>
          <input
            type="checkbox"
            disabled={disabled}
            checked={models.includes(id)}
            onChange={() => setModels(toggle(models, id))}
          />{' '}
          模型 {id}
        </label>
      ))}
      {profile.delivery !== null && (
        <label>
          <input
            type="checkbox"
            checked={delivery}
            disabled={disabled}
            onChange={(event) => setDelivery(event.target.checked)}
          />
          允许本地交付
        </label>
      )}
      <p>
        请求上限 {scope.limits.max_model_requests}，输出上限 {scope.limits.max_output_tokens}{' '}
        Token。
      </p>
      <button
        type="button"
        className="ui-button"
        disabled={disabled}
        onClick={() => setReview(true)}
      >
        审阅授权
      </button>
      {review && (
        <Confirmation
          open
          title="批准任务授权"
          description={
            '模型 ' +
            (models.join('、') || '无') +
            '；命令 ' +
            (commands.join('、') || '无') +
            '；' +
            (delivery ? '允许本地交付。' : '不授权本地交付。')
          }
          confirmLabel="批准授权"
          cancelLabel="取消"
          busy={disabled}
          confirm={() => {
            setReview(false);
            approve(scope);
          }}
          cancel={() => setReview(false)}
        />
      )}
    </details>
  );
}

export function CreateCodeTaskDrawer(props: Props) {
  const { api, requirementId, documentId, visible } = props;
  const key = 'walle:v2.0:code:create:' + location.origin + ':' + requirementId + ':' + documentId;
  const [initial] = useState(() => {
    try {
      return {
        draft: restoreCreateDraft(sessionStorage.getItem(key), requirementId, documentId),
        warning: null,
      };
    } catch {
      return {
        draft: freshDraft(requirementId, documentId),
        warning: '原草稿暂不可读，待核对请求仍保留。',
      };
    }
  });
  const [draft, setDraft] = useState<CreateTaskDraft>(initial.draft);
  const saved = useRef(draft);
  const [warning, setWarning] = useState(initial.warning);
  const [preview, setPreview] = useState(false);
  const [attempt, retry] = useState(0);
  const [openFiles, setOpenFiles] = useState(false);
  const [filePage, setFilePage] = useState(1);
  const [activeError, setActiveError] = useState<string | null>(null);
  const heading = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const configurationHeading = useRef<HTMLHeadingElement>(null);
  const returnFocus = props.returnFocus;
  const preflight = useRef<AbortController | null>(null);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => () => preflight.current?.abort(), []);

  function update(change: Partial<CreateTaskDraft>) {
    const next = { ...saved.current, ...change };
    saved.current = next;
    setDraft(next);
    try {
      sessionStorage.setItem(key, JSON.stringify(next));
    } catch {
      setWarning('草稿暂存不可用，当前输入仍保留。');
    }
  }

  function created(id: number, commandKey: string) {
    if (saved.current.original_key !== commandKey) return;
    try {
      const stored = restoreCreateDraft(sessionStorage.getItem(key), requirementId, documentId);
      if (stored.original_key === commandKey) sessionStorage.removeItem(key);
    } catch {}
    props.created(id);
  }

  const commands = useCreationCommands(api, draft, update, created, props.conflict);
  const locked =
    submitting || commands.busy || !commands.ledgerReady || draft.original_key !== null;
  useLayoutEffect(() => {
    const element = dialog.current!;
    const focus = returnFocus.current;
    element.showModal();
    const release = registerModal(element);
    element.querySelector<HTMLElement>('h2')?.focus();
    return () => {
      element.close();
      release();
      if (focus?.isConnected && !focus.closest('[inert]')) focus.focus({ preventScroll: true });
    };
  }, [returnFocus]);

  useEffect(() => {
    if (
      !visible ||
      commands.busy ||
      !draft.original_key ||
      !commands.operation ||
      !['PENDING', 'RUNNING'].includes(commands.operation.status)
    )
      return;
    const timer = window.setTimeout(commands.check, 1200);
    return () => window.clearTimeout(timer);
  }, [visible, commands.busy, commands.check, commands.operation, draft.original_key]);

  const initialRevision = useCallback(
    async (signal: AbortSignal) => {
      const revisionId = props.revisionId;
      if (revisionId === null || saved.current.design_revision_id !== null) return null;
      return (await selectedDesign(api, requirementId, documentId, revisionId, 'MAIN', signal))
        ? revisionId
        : null;
    },
    [api, requirementId, documentId, props.revisionId],
  );
  const initialChoice = useSettingsRead(initialRevision, visible, '暂时无法核对原阅读版本');
  const attemptedPreselect = useRef(false);
  useEffect(() => {
    if (
      !attemptedPreselect.current &&
      initialChoice.value !== null &&
      saved.current.design_revision_id === null
    ) {
      attemptedPreselect.current = true;
      update({ design_revision_id: initialChoice.value });
    }
  });

  const loadDirectory = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return (await api.getRequirementDetail(requirementId, signal, false, documentId)).data
        .documents;
    },
    [api, requirementId, documentId, attempt],
  );
  const loadRepositoryOptions = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.codeRepositories(page, signal), (row) => ({
        id: row.id,
        label: row.name,
      })),
    [api],
  );
  const loadProfileOptions = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.codeExecutionProfiles(page, signal), (row) => ({
        id: row.id,
        label: row.name,
      })),
    [api],
  );
  const loadProfileVersions = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(
        await api.codeExecutionProfileVersions(draft.execution_profile_id!, page, signal),
        (row) => ({
          id: row.id,
          label: '版本 ' + row.version + (row.ready ? ' · 可开始' : ' · 执行条件未就绪'),
        }),
      ),
    [api, draft.execution_profile_id],
  );
  const loadGrants = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(
        await api.codeAuthorizations(page, { status: 'APPROVED_UNBOUND' }, signal),
        (row) =>
          row.profile_version_id === draft.execution_profile_version_id
            ? { id: row.id, label: '授权 #' + row.id + ' · 已批准，未绑定' }
            : null,
      ),
    [api, draft.execution_profile_version_id],
  );
  const loadDesign = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      const main = draft.design_revision_id;
      if (main === null) return null;
      const checks = await Promise.all([
        selectedDesign(api, requirementId, documentId, main, 'MAIN', signal),
        ...draft.material_refs.map((row) =>
          selectedDesign(api, requirementId, row.document_id, row.revision_id, 'MATERIAL', signal),
        ),
      ]);
      return { main, materials: draft.material_refs, valid: checks.every(Boolean) };
    },
    [api, requirementId, documentId, draft.design_revision_id, draft.material_refs, attempt],
  );
  const loadRepository = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return draft.repository_id === null
        ? null
        : (await api.codeRepository(draft.repository_id, signal)).data;
    },
    [api, draft.repository_id, attempt],
  );
  const loadProfile = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return draft.execution_profile_version_id === null
        ? null
        : (await api.codeExecutionProfileVersion(draft.execution_profile_version_id, signal)).data;
    },
    [api, draft.execution_profile_version_id, attempt],
  );
  const loadGrant = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return draft.authorization_id === null
        ? null
        : (await api.codeAuthorization(draft.authorization_id, signal)).data;
    },
    [api, draft.authorization_id, attempt],
  );
  const loadObservation = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return draft.repository_id === null || draft.observation_id === null
        ? null
        : (await api.repositoryObservation(draft.repository_id, draft.observation_id, signal)).data;
    },
    [api, draft.repository_id, draft.observation_id, attempt],
  );
  const loadSnapshot = useCallback(
    async (signal: AbortSignal) => {
      void attempt;
      return draft.base_snapshot_id === null
        ? null
        : (await api.codeSnapshot(draft.base_snapshot_id, signal)).data;
    },
    [api, draft.base_snapshot_id, attempt],
  );
  const loadFiles = useCallback(
    (signal: AbortSignal) => api.codeBaselineFiles(draft.base_snapshot_id!, filePage, signal),
    [api, draft.base_snapshot_id, filePage],
  );

  const directory = useSettingsRead(loadDirectory, visible, '暂时无法读取材料目录');
  const design = useSettingsRead(loadDesign, visible, '暂时无法核对固定设计和材料');
  const repository = useSettingsRead(loadRepository, visible, '暂时无法读取原仓库');
  const profile = useSettingsRead(loadProfile, visible, '暂时无法读取所选配置');
  const grant = useSettingsRead(loadGrant, visible, '暂时无法核对所选授权');
  const observation = useSettingsRead(loadObservation, visible, '暂时无法读取原仓库观察');
  const snapshot = useSettingsRead(loadSnapshot, visible, '暂时无法核对固定起点');
  const files = useSettingsRead(
    loadFiles,
    visible && openFiles && draft.base_snapshot_id !== null,
    '暂时无法读取固定起点文件',
  );

  const selectedProfile =
    !profile.loading &&
    !profile.error &&
    profile.value &&
    profile.value.id === draft.execution_profile_version_id &&
    profile.value.profile_id === draft.execution_profile_id
      ? profile.value
      : null;
  const selectedRepository =
    !repository.loading && !repository.error && repository.value?.id === draft.repository_id
      ? repository.value
      : null;
  const selectedObservation =
    !observation.loading &&
    !observation.error &&
    observation.value?.id === draft.observation_id &&
    observation.value?.repository_id === draft.repository_id
      ? observation.value
      : null;
  const selectedSnapshot =
    !snapshot.loading &&
    !snapshot.error &&
    snapshot.value?.id === draft.base_snapshot_id &&
    snapshot.value?.repository_id === draft.repository_id &&
    snapshot.value.content_profile_version_id === draft.execution_profile_version_id
      ? snapshot.value
      : null;
  const selectedGrant =
    !grant.loading &&
    !grant.error &&
    grant.value?.id === draft.authorization_id &&
    grant.value?.profile_version_id === draft.execution_profile_version_id &&
    grant.value.status === 'APPROVED_UNBOUND' &&
    grant.value.task_id === null
      ? grant.value
      : null;
  const validDesign =
    !design.loading &&
    !design.error &&
    design.value?.main === draft.design_revision_id &&
    design.value?.materials === draft.material_refs &&
    design.value.valid;
  const checkedOut = new Set(selectedObservation?.worktrees.map((row) => row.branch_ref));
  const validBranch =
    selectedObservation?.status === 'READABLE' &&
    selectedObservation.local_branches.some((row) => row.full_ref === draft.target_branch) &&
    !checkedOut.has(draft.target_branch);
  const commit = draft.commit_oid.trim().toLowerCase();
  let validCommit = false;
  try {
    validCommit =
      gitObjectId(commit).length === (selectedRepository?.object_format === 'sha1' ? 40 : 64);
  } catch {}
  const reason = !commands.ledgerReady
    ? '正在核对原请求记录'
    : draft.original_key
      ? '请先核对原请求'
      : props.activeTaskId
        ? '当前文档已有活动任务'
        : !validDesign
          ? '请选择并核实固定设计和材料'
          : !selectedRepository || !selectedSnapshot?.ready
            ? '请登记并核实固定代码起点'
            : !validBranch
              ? '请选择原观察中未检出的目标分支'
              : !selectedProfile || !selectedGrant
                ? '请核实执行配置和未绑定授权'
                : null;

  const closeLocked = commands.busy || submitting;
  const submitStatus = submitting
    ? '正在核对并创建任务…'
    : commands.busy
      ? '正在处理原操作…'
      : reason;
  const registerReason = !selectedRepository
    ? '请先选择并核对仓库'
    : !selectedProfile
      ? '登记前请选择执行配置版本'
      : !validCommit
        ? '请输入完整的 Git 提交标识'
        : null;

  async function submit() {
    if (
      reason ||
      locked ||
      preflight.current ||
      draft.design_revision_id === null ||
      !selectedRepository ||
      !selectedSnapshot ||
      !selectedProfile ||
      !selectedGrant ||
      !draft.target_branch
    )
      return;
    const request = new AbortController();
    preflight.current = request;
    setSubmitting(true);
    setActiveError(null);
    try {
      const active = (
        await api.documentCodeTasks(
          documentId,
          1,
          { statuses: ACTIVE_TASK_STATUSES },
          request.signal,
        )
      ).data.items[0];
      if (request.signal.aborted) return;
      if (active) {
        props.conflict(active.id);
        setActiveError('当前文档已有活动任务。');
        return;
      }
      await commands.submit(
        createTaskPath(documentId),
        snapshotObject({
          design_revision_id: draft.design_revision_id,
          material_refs: draft.material_refs,
          repository_id: selectedRepository.id,
          base_snapshot_id: selectedSnapshot.id,
          target_branch: draft.target_branch,
          execution_profile_version_id: selectedProfile.id,
          authorization_id: selectedGrant.id,
          budget_limit_cny: '0.000000',
        }),
      );
    } catch {
      if (!request.signal.aborted) setActiveError('暂时无法重新核对活动任务名额。');
    } finally {
      if (preflight.current === request) preflight.current = null;
      if (!request.signal.aborted) setSubmitting(false);
    }
  }

  const readErrors = [
    directory.error,
    design.error,
    repository.error,
    profile.error,
    grant.error,
    observation.error,
    snapshot.error,
  ].filter((value) => value !== null);
  return createPortal(
    <dialog
      ref={dialog}
      className="create-drawer code-task-drawer is-coding"
      aria-labelledby={heading}
      onKeyDown={trapModalTab}
      onCancel={(event) => {
        event.preventDefault();
        if (!closeLocked) props.close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header>
          <div className="code-drawer-identity">
            <h2 id={heading} tabIndex={-1}>
              创建代码任务
            </h2>
            <p className="read-status">{props.documentTitle}</p>
          </div>
          <button
            type="button"
            className="ui-button icon-button"
            aria-label="关闭创建代码任务"
            title="关闭"
            disabled={closeLocked}
            onClick={props.close}
          >
            <Icon name="close" />
          </button>
        </header>
        <div className="code-task-drawer-fields">
          {warning && <p role="status">{warning}</p>}
          {readErrors.length > 0 && (
            <div role="alert">
              {readErrors.map((error, index) => (
                <p key={index}>{error}</p>
              ))}
              <button
                type="button"
                className="ui-button"
                onClick={() => retry((value) => value + 1)}
              >
                重新核对选择
              </button>
            </div>
          )}
          <section className="code-drawer-section" aria-labelledby={heading + '-design-title'}>
            <h3 id={heading + '-design-title'}>固定设计</h3>
            <RevisionSelect
              api={api}
              requirementId={requirementId}
              documentId={documentId}
              usage="MAIN"
              value={draft.design_revision_id}
              change={(id) => {
                update({ design_revision_id: id });
                setPreview(false);
              }}
              disabled={locked}
              visible={visible}
            />
            {draft.design_revision_id !== null && (
              <button
                type="button"
                className="ui-button"
                aria-expanded={preview}
                onClick={() => setPreview(!preview)}
              >
                阅读固定设计
              </button>
            )}
            {preview && draft.design_revision_id !== null && (
              <RevisionPreview
                key={draft.design_revision_id}
                api={api}
                id={draft.design_revision_id}
                documentId={documentId}
                requirementId={requirementId}
                visible={visible}
              />
            )}
            <MaterialChoices
              api={api}
              documents={directory.value ?? []}
              draft={draft}
              update={update}
              disabled={locked || directory.loading || !!directory.error}
              visible={visible}
            />
          </section>
          <section className="code-drawer-section" aria-labelledby={heading + '-source-title'}>
            <h3 id={heading + '-source-title'}>固定代码起点</h3>
            <PagedTaskSelect
              label="仓库"
              emptyMessage="尚未登记代码仓库"
              value={draft.repository_id}
              visible={visible}
              load={loadRepositoryOptions}
              disabled={locked}
              change={(id) => {
                update({
                  repository_id: id,
                  observation_id: null,
                  base_snapshot_id: null,
                  target_branch: null,
                  commit_oid: '',
                });
                setOpenFiles(false);
              }}
            />
            <div className="code-task-toolbar">
              <button
                type="button"
                className="ui-button"
                disabled={locked}
                onClick={props.settings}
              >
                打开代码设置
              </button>
              <button
                type="button"
                className="ui-button"
                disabled={locked || !selectedRepository}
                title={!selectedRepository ? '请先选择并核对仓库' : undefined}
                onClick={() =>
                  selectedRepository &&
                  void commands.submit(
                    '/api/v1/code-repositories/' + selectedRepository.id + '/refresh',
                    {},
                  )
                }
              >
                读取仓库信息
              </button>
            </div>
            {selectedObservation && (
              <p>
                本次仓库观察 {new Date(selectedObservation.observed_at).toLocaleString('zh-CN')}
              </p>
            )}
            <div className="code-drawer-field">
              <label htmlFor={heading + '-commit'}>来源提交</label>
              <input
                id={heading + '-commit'}
                className="ui-input code-commit-input"
                value={draft.commit_oid}
                spellCheck={false}
                autoComplete="off"
                disabled={locked || !selectedRepository}
                aria-describedby={heading + '-commit-help'}
                onChange={(event) =>
                  update({ commit_oid: event.target.value, base_snapshot_id: null })
                }
              />
              <p className="read-status" id={heading + '-commit-help'}>
                仅使用所选 Git 提交。未提交的修改不纳入。登记后原仓库需保持可读。
              </p>
            </div>
            {selectedObservation?.status === 'READABLE' && (
              <div className="code-drawer-field">
                <label htmlFor={heading + '-branch-source'}>从本次观察填入提交</label>
                <SingleSelect
                  id={heading + '-branch-source'}
                  label="从本次观察填入提交"
                  value=""
                  disabled={locked}
                  placeholder="选择分支提交"
                  options={selectedObservation.local_branches.map((row) => ({
                    value: row.full_ref,
                    label: row.full_ref,
                  }))}
                  change={(ref) => {
                    const branch = selectedObservation.local_branches.find(
                      (row) => row.full_ref === ref,
                    );
                    if (branch) update({ commit_oid: branch.commit_oid, base_snapshot_id: null });
                  }}
                />
              </div>
            )}
            <div className="code-task-toolbar">
              <button
                type="button"
                className="ui-button code-drawer-secondary"
                disabled={locked || registerReason !== null}
                aria-describedby={registerReason ? heading + '-register-help' : undefined}
                onClick={() =>
                  selectedRepository &&
                  selectedProfile &&
                  void commands.submit(
                    '/api/v1/code-repositories/' + selectedRepository.id + '/snapshots',
                    { commit_oid: commit, execution_profile_version_id: selectedProfile.id },
                  )
                }
              >
                登记代码起点
              </button>
              {selectedRepository && !selectedProfile && !locked && (
                <button
                  type="button"
                  className="ui-button"
                  onClick={() => configurationHeading.current?.focus()}
                >
                  选择执行配置
                </button>
              )}
            </div>
            {registerReason && (
              <p className="read-status" id={heading + '-register-help'}>
                {registerReason}
              </p>
            )}
            {commands.operation && commands.operation.idempotency_key === draft.original_key && (
              <ol aria-label="原仓库操作步骤">
                {commands.operation.steps.map((step) => (
                  <li key={step.step_no}>
                    {step.step_type} · {step.status}
                  </li>
                ))}
              </ol>
            )}
            {selectedSnapshot && (
              <>
                <p>
                  已登记起点 #{selectedSnapshot.id} · {selectedSnapshot.ready ? '可用' : '不可用'}
                </p>
                <p>
                  <code>{selectedSnapshot.commit_oid}</code>
                </p>
                <button
                  type="button"
                  className="ui-button"
                  aria-expanded={openFiles}
                  onClick={() => {
                    setFilePage(1);
                    setOpenFiles(!openFiles);
                  }}
                >
                  查看固定文件
                </button>
                {openFiles && (
                  <section aria-label="固定起点文件">
                    {files.loading && <p role="status">正在读取固定文件…</p>}
                    {files.error && <p role="alert">{files.error}</p>}
                    {files.value?.data.items.length ? (
                      <ul>
                        {files.value.data.items.map((file) => (
                          <li key={file.path}>
                            <code>{file.path}</code> · {file.byte_count} 字节
                          </li>
                        ))}
                      </ul>
                    ) : !files.loading && !files.error && files.value ? (
                      <EmptyState icon="outline" message="当前页没有固定文件" compact />
                    ) : null}
                    {files.value?.meta.pagination && 'page' in files.value.meta.pagination && (
                      <Pagination
                        value={files.value.meta.pagination}
                        loading={files.loading}
                        change={setFilePage}
                        compactSingle
                        showLoadingStatus={false}
                      />
                    )}
                  </section>
                )}
              </>
            )}
          </section>
          <section
            className="code-drawer-section"
            aria-labelledby={heading + '-configuration-title'}
          >
            <h3 id={heading + '-configuration-title'} tabIndex={-1} ref={configurationHeading}>
              目标与配置
            </h3>
            <div className="code-drawer-field">
              <label htmlFor={heading + '-target-branch'}>目标分支</label>
              <SingleSelect
                id={heading + '-target-branch'}
                label="目标分支"
                value={draft.target_branch ?? ''}
                disabled={locked || selectedObservation?.status !== 'READABLE'}
                placeholder={
                  selectedObservation?.status === 'READABLE' ? '请选择' : '请先读取仓库信息'
                }
                options={[
                  {
                    value: '',
                    label:
                      selectedObservation?.status === 'READABLE' ? '请选择' : '请先读取仓库信息',
                  },
                  ...(draft.target_branch &&
                  !selectedObservation?.local_branches.some(
                    (row) => row.full_ref === draft.target_branch,
                  )
                    ? [
                        {
                          value: draft.target_branch,
                          label: draft.target_branch + ' · 待核对',
                          disabled: true,
                        },
                      ]
                    : []),
                  ...(selectedObservation?.local_branches.map((row) => ({
                    value: row.full_ref,
                    label: row.full_ref + (checkedOut.has(row.full_ref) ? ' · 已检出' : ''),
                    disabled: checkedOut.has(row.full_ref),
                  })) ?? []),
                ]}
                change={(value) => update({ target_branch: value || null })}
              />
            </div>
            <PagedTaskSelect
              label="执行配置"
              value={draft.execution_profile_id}
              load={loadProfileOptions}
              disabled={locked}
              visible={visible}
              change={(id) =>
                update({
                  execution_profile_id: id,
                  execution_profile_version_id: null,
                  authorization_id: null,
                  base_snapshot_id: null,
                })
              }
            />
            {draft.execution_profile_id !== null && (
              <PagedTaskSelect
                key={draft.execution_profile_id}
                label="执行配置版本"
                value={draft.execution_profile_version_id}
                load={loadProfileVersions}
                disabled={locked}
                visible={visible}
                change={(id) =>
                  update({
                    execution_profile_version_id: id,
                    authorization_id: null,
                    base_snapshot_id: null,
                  })
                }
              />
            )}
            {selectedProfile && (
              <p>
                检查配置 #{selectedProfile.check_set_version_id} ·{' '}
                {selectedProfile.ready ? '可开始' : '执行条件未就绪'}
              </p>
            )}
          </section>
          <section
            className="code-drawer-section"
            aria-labelledby={heading + '-authorization-title'}
          >
            <h3 id={heading + '-authorization-title'}>执行授权</h3>
            {selectedProfile && (
              <>
                <PagedTaskSelect
                  key={selectedProfile.id}
                  label="未绑定授权"
                  value={draft.authorization_id}
                  load={loadGrants}
                  disabled={locked}
                  visible={visible}
                  change={(id) => update({ authorization_id: id })}
                />
                <Approval
                  key={'approve-' + selectedProfile.id}
                  profile={selectedProfile}
                  disabled={locked}
                  approve={(scope) =>
                    void commands.submit(
                      '/api/v1/code-authorizations',
                      snapshotObject({ profile_version_id: selectedProfile.id, scope }),
                    )
                  }
                />
              </>
            )}
          </section>
          <section className="code-drawer-section" aria-labelledby={heading + '-review-title'}>
            <h3 id={heading + '-review-title'}>创建摘要</h3>
            <dl className="code-task-facts">
              <dt>设计版本</dt>
              <dd>
                {draft.design_revision_id === null ? '未选择' : '#' + draft.design_revision_id}
              </dd>
              <dt>固定材料</dt>
              <dd>{draft.material_refs.length} 份</dd>
              <dt>代码起点</dt>
              <dd>{selectedSnapshot === null ? '未核实' : '#' + selectedSnapshot.id}</dd>
              <dt>目标分支</dt>
              <dd>{draft.target_branch ?? '未选择'}</dd>
              <dt>授权</dt>
              <dd>{selectedGrant === null ? '未核实' : '#' + selectedGrant.id}</dd>
            </dl>
            <p className="read-status">创建后任务保持未开始。</p>
          </section>
          {commands.message && <p role="status">{commands.message}</p>}
          {activeError && <p role="alert">{activeError}</p>}
          {draft.original_key && (
            <div className="code-task-toolbar">
              <button
                type="button"
                className="ui-button"
                disabled={commands.busy}
                onClick={() => void commands.check()}
              >
                核对原请求
              </button>
              {commands.canObserveBaseline && (
                <button
                  type="button"
                  className="ui-button"
                  disabled={commands.busy}
                  onClick={() => void commands.observeBaseline()}
                >
                  继续核对原登记
                </button>
              )}
              {commands.record && (
                <RecoveryActions
                  record={commands.record}
                  recovery={commands.recovery}
                  replayEnabled={!commands.busy}
                  settled={commands.settled}
                />
              )}
            </div>
          )}
        </div>
        <footer>
          {submitStatus && (
            <span id={heading + '-reason'} className="read-status" role="status">
              {submitStatus}
            </span>
          )}
          <div className="code-drawer-footer-actions">
            <button
              type="button"
              className="ui-button"
              disabled={closeLocked}
              onClick={props.close}
            >
              取消
            </button>
            <button
              type="submit"
              className="ui-button primary"
              disabled={submitStatus !== null}
              aria-describedby={submitStatus ? heading + '-reason' : undefined}
            >
              创建任务
            </button>
          </div>
        </footer>
      </form>
    </dialog>,
    document.body,
  );
}
