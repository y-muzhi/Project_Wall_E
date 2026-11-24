import { FormationReadSources } from './source-list.tsx';
import { ProgressGroup, ViewedProgress } from './progress-group.tsx';
import { FormationInlineBranches } from './inline-branches.tsx';
import { FormationProposals } from './proposals-view.tsx';
import { FormationPathEditorView } from './editor-view.tsx';
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { RequirementDetailOwner } from '../requirements/detail-owner.ts';
import { DiscussionProgress } from '../requirements/discussion-view.tsx';
import type { FormationWorkspace } from './workspace.ts';
import { FormationStepView } from './detail-view.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Icon } from '../shared/icon.tsx';
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
  discuss,
}: Readonly<{
  owner: FormationWorkspace;
  discuss: () => void;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    read = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot);
  const summary = read.summary.data,
    page = read.page.data;

  const routeList = useRef<HTMLOListElement>(null);
  const panel = useRef<HTMLElement>(null);
  const restoreAnchor = useRef(owner.scrollAnchor);
  const scrollSave = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [openStep, setOpenStep] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [goalOpen, setGoalOpen] = useState(false);
  const detailId = useId();

  const scrollHost = () => panel.current?.closest<HTMLElement>('.detail-panel-content');
  const nodeFor = (ref: string) =>
    Array.from(routeList.current?.children ?? []).find(
      (item) => item.getAttribute('data-step-ref') === ref,
    );
  useLayoutEffect(() => {
    const anchor = restoreAnchor.current;
    const route = routeList.current;
    const host = scrollHost();
    if (anchor === null || route === null || host == null) return;
    const node = Array.from(route.children).find(
      (item) => item.getAttribute('data-step-ref') === anchor,
    );
    if (node !== undefined) {
      restoreAnchor.current = null;
      host.scrollTop += node.getBoundingClientRect().top - host.getBoundingClientRect().top - 8;
    }
  }, [page]);
  useEffect(() => {
    const host = panel.current?.closest<HTMLElement>('.detail-panel-content');
    if (host == null) return;
    const rememberScroll = () => {
      if (scrollSave.current !== null) clearTimeout(scrollSave.current);
      scrollSave.current = setTimeout(() => {
        const route = routeList.current;
        if (route === null) return;
        const top = host.getBoundingClientRect().top;
        const node = Array.from(route.children).find(
          (item) => item.getBoundingClientRect().bottom > top + 1,
        );
        const ref = node?.getAttribute('data-step-ref');
        if (ref != null) owner.rememberScrollAnchor(ref);
      }, 250);
    };
    host.addEventListener('scroll', rememberScroll, { passive: true });
    return () => {
      host.removeEventListener('scroll', rememberScroll);
      if (scrollSave.current !== null) clearTimeout(scrollSave.current);
    };
  }, [owner]);

  const locateStep = async (ref: string, requireCurrent = false) => {
    setLocating(true);
    restoreAnchor.current = null;
    try {
      if (!(await owner.read.revealStep(ref)) || panel.current === null) return;
      if (requireCurrent && owner.read.getSnapshot().summary.data?.current_step_ref !== ref) return;
      // Select and scroll within the route without dispatching a discussion action.
      if (state.brief) setOpenStep(ref);
      else void owner.selectView(ref);
      requestAnimationFrame(() => {
        const node = nodeFor(ref);
        const host = scrollHost();
        if (node === undefined || host == null) return;
        host.scrollTop += node.getBoundingClientRect().top - host.getBoundingClientRect().top - 8;
        node.querySelector('button')?.focus({ preventScroll: true });
        owner.rememberScrollAnchor(ref);
      });
    } finally {
      setLocating(false);
    }
  };
  const setShowCancelled = (value: boolean) => {
    if (
      !value &&
      (read.detail.data?.status === 'CANCELLED' ||
        page?.data.items.some(
          (step) => step.step_ref === read.selected_step_ref && step.status === 'CANCELLED',
        ))
    )
      void owner.selectView(null);
    void owner.setShowCancelled(value);
  };
  const hasPendingProposals = (summary?.counts.proposals.PENDING ?? 0) > 0;
  const hasRoute = summary?.exists === true;
  const currentStep = summary?.current_step_ref ?? null;
  const stepTitles = new Map(page?.data.items.map((step) => [step.step_ref, step.title]));
  const nodeDetail = (
    <div id={detailId} className="formation-node-detail">
      <FormationStepView owner={owner} />
    </div>
  );
  return (
    <section ref={panel} className="formation-progress" aria-label="文档主线">
      <header className="formation-heading">
        <h2>文档主线</h2>
        <div className="formation-heading-actions">
          {hasRoute && (
            <button type="button" className="ui-button" onClick={discuss}>
              继续讨论
            </button>
          )}
          {(!state.brief || owner.hasPathDraft) && (
            <details className="formation-options">
              <summary className="ui-button icon-button" aria-label="主线操作" title="主线操作">
                <Icon name="more" />
              </summary>
              <div className="formation-options-menu">
                <button
                  type="button"
                  className="ui-button"
                  disabled={state.loading || state.phase === 'SENDING'}
                  onClick={() =>
                    void (state.phase === 'CONFIRMED' ? owner.finish() : owner.refresh())
                  }
                >
                  {state.phase === 'CONFIRMED' ? '刷新已确认结果' : '刷新主线'}
                </button>
                {hasRoute && owner.hasPathDraft && (
                  <button
                    type="button"
                    className="ui-button"
                    disabled={owner.targetReason !== null}
                    title={owner.targetReason ?? undefined}
                    onClick={(event) => {
                      const options = event.currentTarget.closest('details');
                      if (options !== null) options.open = false;
                      owner.openPathEditor();
                    }}
                  >
                    查看旧路线草稿
                  </button>
                )}
              </div>
            </details>
          )}
        </div>
      </header>
      {summary?.goal && (
        <section className="formation-document-goal" aria-label="文档目标">
          <h3>文档目标</h3>
          <p>{summary.goal.text}</p>
          {state.brief?.focus && (
            <details onToggle={(event) => setGoalOpen(event.currentTarget.open)}>
              <summary>文档级讨论记录</summary>
              {goalOpen && <ViewedProgress owner={owner} stepRef={null} />}
            </details>
          )}
        </section>
      )}
      {state.editor_open && owner.pathEditor !== null && (
        <FormationPathEditorView owner={owner} editor={owner.pathEditor} />
      )}
      {state.notice && (
        <p role="status" className={state.notice === '操作已确认' ? 'sr-only' : 'formation-notice'}>
          {state.notice}
        </p>
      )}
      {state.error && (
        <div className="formation-toolbar">
          <p role="alert" className="inline-error">
            {state.error}
          </p>
          <button
            className="ui-button"
            type="button"
            disabled={state.loading}
            onClick={() => void owner.refresh()}
          >
            重新读取主线
          </button>
        </div>
      )}
      {state.draft_warning && <p role="status">{state.draft_warning}</p>}
      {state.preference_warning && <p role="status">{state.preference_warning}</p>}
      {state.target_error && <p role="alert">{state.target_error}</p>}
      {owner.targetReason !== null && <p className="field-help">{owner.targetReason}</p>}
      {state.loading && summary === null && <p role="status">正在读取文档主线…</p>}
      <RecoveryPanel owner={owner} />
      {state.next_target !== null && (
        <p className="formation-target">
          下一轮目标 · {owner.targetLabel}
          <button type="button" className="ui-button" onClick={() => owner.followServerFocus()}>
            跟随当前讨论
          </button>
        </p>
      )}
      {hasRoute && hasPendingProposals && <FormationProposals owner={owner} />}
      {summary?.exists === false && (
        <>
          {state.previousTopics.length > 0 ||
          (state.brief?.decision_total ?? 0) > 0 ||
          (state.brief?.issue_total ?? 0) > 0 ? (
            <section aria-label="已有讨论">
              <h3>已有讨论</h3>
              <p>本文档尚未建立主线</p>
              {state.brief && <ProgressGroup owner={owner} brief={state.brief} group="decisions" />}
              {state.brief && <ProgressGroup owner={owner} brief={state.brief} group="issues" />}
              <ul>
                {state.previousTopics.map((topic) => (
                  <li key={topic.topic_ref}>
                    {topic.title}
                    <FormationReadSources
                      owner={owner}
                      label="讨论来源"
                      sources={[{ kind: 'MESSAGE', message_id: topic.updated_by_message_id }]}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <EmptyState icon="outline" message="文档主线尚未建立" fill />
          )}
          <button className="ui-button" type="button" onClick={discuss}>
            讨论文档目标
          </button>
        </>
      )}
      {state.brief &&
        hasRoute &&
        (state.brief.decision_total > 0 ||
          state.brief.issue_total > 0 ||
          state.brief.next?.kind === 'RECOMMENDATION') && (
          <section className="formation-discussion" aria-label="当前讨论进展">
            {(['decisions', 'issues'] as const).map((group) => (
              <ProgressGroup
                key={[
                  owner.documentId,
                  state.brief!.formation_version,
                  state.brief!.discussion_version,
                  state.brief!.revision_id,
                  group,
                ].join('/')}
                owner={owner}
                brief={state.brief!}
                group={group}
              />
            ))}
            {state.brief.next?.kind === 'RECOMMENDATION' && (
              <div>
                <h3>建议下一步</h3>
                <p>{state.brief.next.reason}</p>
                {state.brief.next.source_refs.length > 0 && (
                  <FormationReadSources
                    owner={owner}
                    sources={state.brief.next.source_refs}
                    label="建议依据"
                  />
                )}
              </div>
            )}
          </section>
        )}
      {hasRoute && (
        <div className="formation-body">
          <section className="formation-route" aria-label="主线步骤">
            <h3>主线步骤</h3>
            {state.brief && (
              <p className="formation-focus-caption">
                {state.brief.focus ? '当前讨论 · ' + state.brief.focus.title : '当前讨论整份文档'}
              </p>
            )}
            <div className="formation-route-heading">
              {(summary.counts.steps.CANCELLED > 0 || read.show_cancelled) && (
                <label>
                  <input
                    type="checkbox"
                    checked={read.show_cancelled}
                    disabled={state.loading || locating}
                    onChange={(event) => setShowCancelled(event.target.checked)}
                  />
                  已放弃节点 {summary.counts.steps.CANCELLED > 0 && summary.counts.steps.CANCELLED}
                </label>
              )}
              {!state.brief && (
                <label>
                  <input
                    type="checkbox"
                    checked={state.show_branches}
                    onChange={(event) => owner.setShowBranches(event.target.checked)}
                  />
                  支线
                </label>
              )}
              {currentStep !== null && page !== null && !stepTitles.has(currentStep) && (
                <button
                  type="button"
                  className="ui-button formation-current"
                  disabled={currentStep === null || state.loading || locating}
                  title={currentStep === null ? '当前没有聚焦在单个步骤上' : undefined}
                  onClick={() => {
                    if (currentStep !== null) void locateStep(currentStep, true);
                  }}
                >
                  <Icon name="locate" />
                  定位当前步骤
                </button>
              )}
            </div>
            {read.page.error && (
              <div className="formation-toolbar">
                <p role="alert" className="inline-error">
                  {read.page.error}
                </p>
                <button
                  type="button"
                  className="ui-button"
                  onClick={() => void owner.read.loadPage(read.page_cursor)}
                >
                  重新读取步骤
                </button>
              </div>
            )}
            {read.page.phase === 'LOADING' && (
              <p role="status">{locating ? '正在定位当前步骤…' : '正在读取步骤…'}</p>
            )}
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
              <ol className="formation-route-list" ref={routeList}>
                {page.data.items.map((step) => {
                  const selected =
                    step.step_ref === (state.brief ? openStep : read.selected_step_ref);
                  const current = step.step_ref === summary.current_step_ref;
                  return (
                    <li
                      key={step.step_ref}
                      data-step-ref={step.step_ref}
                      data-selected={selected}
                      data-current={current}
                      data-status={step.status}
                    >
                      <button
                        type="button"
                        className="formation-node"
                        aria-current={current ? 'step' : undefined}
                        aria-expanded={selected}
                        aria-controls={selected ? detailId : undefined}
                        onClick={() => {
                          const next = selected ? null : step.step_ref;
                          if (state.brief) setOpenStep(next);
                          else void owner.selectView(next);
                        }}
                      >
                        <span className="formation-node-marker" aria-hidden="true">
                          {step.status === 'COMPLETED' ? <Icon name="check" /> : step.position}
                        </span>
                        <span className="formation-node-content">
                          <span className="formation-node-heading">
                            <strong>{step.title}</strong>
                            <span className="formation-node-status">{stepLabels[step.status]}</span>
                          </span>
                          <small>预期成果 · {step.expected_results[0]?.description}</small>
                        </span>
                      </button>
                      {selected &&
                        (state.brief ? (
                          <section
                            id={detailId}
                            className="formation-node-detail"
                            aria-label="步骤详情"
                          >
                            {step.expected_results.length > 1 && (
                              <>
                                <h4>其他预期成果</h4>
                                <ul>
                                  {step.expected_results.slice(1).map((result) => (
                                    <li key={result.result_ref}>{result.description}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                            <ViewedProgress owner={owner} stepRef={step.step_ref} />
                            {step.last_event && <p>最近活动 · {step.last_event.reason}</p>}
                          </section>
                        ) : (
                          nodeDetail
                        ))}
                      {!state.brief &&
                        state.show_branches &&
                        step.relation_counts.branches > 0 &&
                        summary.formation_version !== null && (
                          <FormationInlineBranches
                            owner={owner}
                            stepRef={step.step_ref}
                            stepTitle={step.title}
                            stepTitles={stepTitles}
                            locating={locating}
                            locate={(ref) => void locateStep(ref)}
                            formationVersion={summary.formation_version}
                          />
                        )}
                    </li>
                  );
                })}
              </ol>
            )}
            {(read.page_cursor !== null || page?.meta.pagination.has_more === true) && (
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
            )}
          </section>
        </div>
      )}
      {hasRoute && !hasPendingProposals && !state.brief && <FormationProposals owner={owner} />}
    </section>
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
  const read = useSyncExternalStore(workspace.read.subscribe, workspace.read.getSnapshot);
  const initialized = useRef(false);
  useEffect(() => {
    if (!active || state.brief || initialized.current || read.page.phase !== 'READY') return;
    initialized.current = true;
    const current = read.summary.data?.current_step_ref;
    if (
      read.selected_step_ref === null &&
      current != null &&
      read.page.data?.data.items.some((step) => step.step_ref === current)
    )
      void workspace.selectView(current);
  }, [active, state.brief, read.page, read.selected_step_ref, read.summary.data, workspace]);
  useEffect(() => {
    if (active) void workspace.refresh(false);
  }, [workspace, active]);
  useEffect(() => {
    if (active && !state.loading && read.summary.data?.exists && read.page.phase === 'IDLE') {
      void workspace.read.loadPage(null);
    }
  }, [workspace, active, state.loading, read.summary.data, read.page.phase]);
  if (state.mode === 'LEGACY')
    return <DiscussionProgress owner={owner} active={active} blocked={blocked} discuss={discuss} />;
  if (state.mode === 'UNKNOWN')
    return (
      <section aria-label="文档主线">
        {(state.loading || !state.error) && <p role="status">正在读取文档主线…</p>}
        {state.error && <p role="alert">{state.error}</p>}
        <button
          type="button"
          className="ui-button"
          disabled={state.loading}
          onClick={() => void workspace.refresh()}
        >
          重新读取
        </button>
        <button type="button" className="ui-button" onClick={discuss}>
          返回 AI 对话
        </button>
      </section>
    );
  return <FormationPanel owner={workspace} discuss={discuss} />;
}
