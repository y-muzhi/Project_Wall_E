import { FormationInlineBranches } from './inline-branches.tsx';
import { FormationProposals } from './proposals-view.tsx';
import { FormationPathEditorView } from './editor-view.tsx';
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import type { RequirementDetailOwner } from '../requirements/detail-owner.ts';
import { DiscussionProgress } from '../requirements/discussion-view.tsx';
import type { FormationWorkspace } from './workspace.ts';
import { FormationStepView } from './detail-view.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Icon } from '../shared/icon.tsx';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import { stepLabels } from './labels.ts';
import './progress-view.css';
function RecoveryPanel({ owner }: Readonly<{ owner: FormationWorkspace }>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  if (state.pending.length === 0)
    return state.recovery_error === null ? null : <p role="alert">{state.recovery_error}</p>;
  return (
    <section className="formation-recovery" aria-label="待核实操作">
      <h3>待核实操作</h3>
      <p>核实会使用原请求及原标识；不会按当前输入重新准备操作。</p>
      <ul>
        {state.pending.map((row) => (
          <li key={row.key}>
            <span>
              {row.status === 'PREPARED' ? '尚未发送' : '结果待核实'} ·{' '}
              {row.method === 'PATCH' ? '主线调整' : '对话操作'}
            </span>
            <div className="formation-toolbar">
              <button
                type="button"
                className="ui-button"
                disabled={state.phase === 'SENDING'}
                onClick={() => void owner.replay(row.key)}
              >
                按原请求核实
              </button>
              {row.status === 'PREPARED' && row.dispatch_count === 0 && (
                <button
                  type="button"
                  className="ui-button"
                  disabled={state.phase === 'SENDING'}
                  onClick={() => void owner.cancelUnsent(row.key)}
                >
                  取消未发送操作
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
function FormationPanel({
  owner,
  expanded,
  toggle,
  discuss,
}: Readonly<{
  owner: FormationWorkspace;
  expanded: boolean;
  toggle: () => void;
  discuss: () => void;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    read = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot);
  const summary = read.summary.data,
    page = read.page.data;
  const routeList = useRef<HTMLOListElement>(null);
  const scrollSave = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (scrollSave.current !== null) clearTimeout(scrollSave.current);
    },
    [],
  );
  useLayoutEffect(() => {
    const route = routeList.current,
      anchor = owner.scrollAnchor;
    if (route === null || anchor === null) return;
    const node = Array.from(route.children).find(
      (item) => item.getAttribute('data-step-ref') === anchor,
    );
    if (node !== undefined)
      route.scrollTop += node.getBoundingClientRect().top - route.getBoundingClientRect().top;
  }, [owner, page]);
  const rememberScroll = () => {
    if (scrollSave.current !== null) clearTimeout(scrollSave.current);
    scrollSave.current = setTimeout(() => {
      const route = routeList.current;
      if (route === null) return;
      const top = route.getBoundingClientRect().top;
      const node = Array.from(route.children).find(
        (item) => item.getBoundingClientRect().bottom > top + 1,
      );
      const anchor = node?.getAttribute('data-step-ref');
      if (anchor !== null && anchor !== undefined) owner.rememberScrollAnchor(anchor);
    }, 250);
  };

  const chooseDocument = () =>
    void owner.chooseStep(null).then((ok) => {
      if (ok) discuss();
    });
  return (
    <section
      className={'formation-progress' + (expanded ? ' is-expanded' : '')}
      aria-label="文档主线"
    >
      <header className="formation-heading">
        <h2>文档主线</h2>
        <div className="formation-toolbar">
          <button type="button" className="ui-button" onClick={discuss}>
            返回 AI 对话
          </button>
          <button
            type="button"
            className="ui-button icon-button"
            data-formation-expand={owner.documentId}
            aria-label={expanded ? '收起主线' : '展开主线'}
            title={expanded ? '收起主线' : '展开主线'}
            onClick={toggle}
          >
            <Icon name={expanded ? 'close' : 'panel'} />
          </button>
        </div>
      </header>
      <div className="formation-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={state.loading || state.phase === 'SENDING'}
          onClick={() => void (state.phase === 'CONFIRMED' ? owner.finish() : owner.refresh())}
        >
          {state.phase === 'CONFIRMED' ? '刷新已确认结果' : '刷新主线'}
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={owner.targetReason !== null}
          title={owner.targetReason ?? undefined}
          onClick={chooseDocument}
        >
          {owner.busy ? '下一轮讨论整篇' : '讨论整篇文档'}
        </button>
      </div>
      {summary?.exists === true && (
        <button
          type="button"
          className="ui-button formation-edit-entry"
          disabled={owner.targetReason !== null}
          title={owner.targetReason ?? undefined}
          onClick={() => owner.openPathEditor()}
        >
          调整路线
        </button>
      )}
      {state.editor_open && owner.pathEditor !== null && (
        <FormationPathEditorView owner={owner} editor={owner.pathEditor} />
      )}
      {state.notice && (
        <p role="status" className="formation-notice">
          {state.notice}
        </p>
      )}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
        </p>
      )}
      {state.draft_warning && <p role="status">{state.draft_warning}</p>}
      {state.preference_warning && <p role="status">{state.preference_warning}</p>}
      {state.target_error && <p role="alert">{state.target_error}</p>}
      {owner.targetReason !== null && <p className="field-help">{owner.targetReason}</p>}
      {state.loading && summary === null && <p role="status">正在读取文档主线…</p>}
      <RecoveryPanel owner={owner} />
      {summary !== null && (
        <p className="formation-target">
          下一轮目标：{owner.targetLabel}
          {state.next_target !== null && (
            <button type="button" className="ui-button" onClick={() => owner.followServerFocus()}>
              跟随当前讨论
            </button>
          )}
        </p>
      )}
      {summary?.goal && (
        <section className="formation-goal">
          <h3>文档目标</h3>
          <p>{summary.goal.text}</p>
        </section>
      )}
      {summary?.exists === true && <FormationProposals owner={owner} />}
      {summary?.exists === false ? (
        <EmptyState icon="outline" message="文档主线尚未建立，请先在 AI 对话中讨论文档目标" fill />
      ) : (
        summary?.exists === true && (
          <div className="formation-body">
            <section className="formation-route" aria-label="主线步骤">
              <div className="formation-route-heading">
                <h3>
                  步骤{' '}
                  <span>
                    (
                    {summary.counts.steps.PLANNED +
                      summary.counts.steps.IN_PROGRESS +
                      summary.counts.steps.PAUSED +
                      summary.counts.steps.COMPLETED +
                      summary.counts.steps.CANCELLED}
                    )
                  </span>
                </h3>
                <label>
                  <input
                    type="checkbox"
                    checked={read.show_cancelled}
                    disabled={state.loading}
                    onChange={(event) => void owner.setShowCancelled(event.target.checked)}
                  />
                  显示已取消
                </label>
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={state.show_branches}
                  onChange={(event) => owner.setShowBranches(event.target.checked)}
                />{' '}
                支线
              </label>
              {summary.current_step_ref !== null && (
                <button
                  type="button"
                  className="ui-button formation-current"
                  onClick={() => void owner.selectView(summary.current_step_ref)}
                >
                  查看当前讨论步骤
                </button>
              )}
              {read.page.error && (
                <p role="alert" className="inline-error">
                  {read.page.error}
                </p>
              )}
              {read.page.phase === 'LOADING' && <p role="status">正在读取步骤…</p>}
              {page !== null && page.data.items.length === 0 && read.page.phase === 'READY' && (
                <EmptyState
                  icon="outline"
                  message={
                    read.page_cursor === null
                      ? read.show_cancelled
                        ? '暂无主线步骤'
                        : '暂无符合筛选的步骤'
                      : '此页已无步骤，请返回首页'
                  }
                  compact
                />
              )}
              {page !== null && page.data.items.length > 0 && (
                <ol className="formation-route-list" ref={routeList} onScroll={rememberScroll}>
                  {page.data.items.map((step) => (
                    <li
                      key={step.step_ref}
                      data-step-ref={step.step_ref}
                      data-selected={step.step_ref === read.selected_step_ref}
                      data-current={step.step_ref === summary.current_step_ref}
                    >
                      <button
                        type="button"
                        className="formation-node"
                        aria-pressed={step.step_ref === read.selected_step_ref}
                        onClick={() => void owner.selectView(step.step_ref)}
                      >
                        <span className="formation-node-marker" aria-hidden="true">
                          {step.position}
                        </span>
                        <span>
                          <strong>{step.title}</strong>
                          <small>
                            {stepLabels[step.status]}
                            {step.status === 'CANCELLED' ? ' · 原第' + step.position + '步' : ''}
                            {step.step_ref === summary.current_step_ref ? ' · 当前讨论' : ''}
                          </small>
                        </span>
                      </button>
                      <div className="formation-node-footer">
                        <p>
                          成果 {step.expected_results.length} · 问题 {step.relation_counts.issues} ·
                          支线 {step.relation_counts.branches}
                        </p>
                        <button
                          type="button"
                          className="ui-button"
                          aria-label={(owner.busy ? '下一轮讨论 ' : '讨论 ') + step.title}
                          disabled={owner.targetReason !== null}
                          title={owner.targetReason ?? undefined}
                          onClick={() =>
                            void owner.chooseStep(step.step_ref).then((ok) => {
                              if (ok) discuss();
                            })
                          }
                        >
                          {owner.busy ? '下一轮讨论' : '讨论'}
                        </button>
                      </div>
                      {state.show_branches &&
                        step.relation_counts.branches > 0 &&
                        summary.formation_version !== null && (
                          <FormationInlineBranches
                            owner={owner}
                            stepRef={step.step_ref}
                            formationVersion={summary.formation_version}
                            discuss={discuss}
                          />
                        )}
                    </li>
                  ))}
                </ol>
              )}
              <nav className="formation-pagination" aria-label="主线步骤分页">
                <button
                  type="button"
                  className="ui-button"
                  disabled={
                    state.loading || read.page.phase === 'LOADING' || read.page_cursor === null
                  }
                  onClick={() => void owner.read.loadPage(null)}
                >
                  首页
                </button>
                <button
                  type="button"
                  className="ui-button"
                  disabled={
                    state.loading ||
                    read.page.phase === 'LOADING' ||
                    page?.meta.pagination.has_more !== true
                  }
                  onClick={() =>
                    void owner.read.loadPage(page?.meta.pagination.next_cursor ?? null)
                  }
                >
                  下一页
                </button>
              </nav>
            </section>
            <FormationStepView owner={owner} discuss={discuss} />
          </div>
        )
      )}
    </section>
  );
}
function ExpandedFormation({
  owner,
  close,
  discuss,
}: Readonly<{ owner: FormationWorkspace; close: () => void; discuss: () => void }>) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    const release = registerModal(dialog);
    return () => {
      dialog.close();
      release();
      queueMicrotask(() => {
        const entry = document.querySelector<HTMLElement>(
          '[data-formation-expand="' + owner.documentId + '"]',
        );
        if (
          entry?.isConnected &&
          !entry.closest('[hidden],[inert]') &&
          entry.getClientRects().length > 0
        )
          entry.focus({ preventScroll: true });
      });
    };
  }, [owner]);
  return createPortal(
    <dialog
      ref={ref}
      className="formation-dialog"
      aria-label="展开文档主线"
      tabIndex={-1}
      onKeyDown={trapModalTab}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <FormationPanel
        owner={owner}
        expanded
        toggle={close}
        discuss={() => {
          close();
          discuss();
        }}
      />
    </dialog>,
    document.body,
  );
}
export function FormationProgress({
  owner,
  active,
  blocked,
  discuss,
}: Readonly<{
  owner: RequirementDetailOwner;
  active: boolean;
  blocked: boolean;
  discuss: () => void;
}>) {
  const workspace = owner.regions?.formation;
  if (workspace === null || workspace === undefined)
    return <DiscussionProgress owner={owner} active={active} blocked={blocked} discuss={discuss} />;
  return (
    <OwnedFormationProgress
      key={workspace.documentId}
      workspace={workspace}
      owner={owner}
      active={active}
      blocked={blocked}
      discuss={discuss}
    />
  );
}
function OwnedFormationProgress({
  workspace,
  owner,
  active,
  blocked,
  discuss,
}: Readonly<{
  workspace: FormationWorkspace;
  owner: RequirementDetailOwner;
  active: boolean;
  blocked: boolean;
  discuss: () => void;
}>) {
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (active) void workspace.refresh();
  }, [workspace, active]);
  useEffect(() => {
    if (!active) setExpanded(false);
  }, [active]);
  if (state.mode === 'LEGACY')
    return <DiscussionProgress owner={owner} active={active} blocked={blocked} discuss={discuss} />;
  if (state.mode === 'UNKNOWN')
    return (
      <section aria-label="文档主线">
        <p role="status">正在读取文档主线…</p>
        {state.error && <p role="alert">{state.error}</p>}
        <button
          type="button"
          className="ui-button"
          disabled={state.loading}
          onClick={() => void workspace.refresh()}
        >
          重新读取
        </button>
      </section>
    );
  return expanded ? (
    <ExpandedFormation owner={workspace} close={() => setExpanded(false)} discuss={discuss} />
  ) : (
    <FormationPanel
      owner={workspace}
      expanded={false}
      toggle={() => setExpanded(true)}
      discuss={discuss}
    />
  );
}
