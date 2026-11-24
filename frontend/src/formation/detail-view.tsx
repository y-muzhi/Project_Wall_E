import { ViewedProgress } from './progress-group.tsx';
import { FormationReadSources } from './source-list.tsx';
import {
  assessmentStaleLabels,
  recommendationStaleLabels,
  recommendationActionLabels,
} from './labels.ts';
import { FormationAnalysisResults } from './analysis-results.tsx';
import { FormationStepRelations } from './step-relations.tsx';
import { FormationArtifactDetails } from './artifact-view.tsx';
import { FormationEventChanges } from './history-view.tsx';
import { FormationClosure } from './closure-view.tsx';
import type { eventView } from '../api/formation-history.ts';
import { useId, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationStepDetail } from '../api/formation-values.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import { localTime } from '../shared/time.ts';
import { FormationPage } from './page-view.tsx';
import { branchLabels, issueLabels, stepLabels } from './labels.ts';
const tabs = ['OVERVIEW', 'RESULTS', 'ISSUES', 'BRANCHES', 'HISTORY'] as const;
const tabNames = {
  OVERVIEW: '概览',
  RESULTS: '成果',
  ISSUES: '问题',
  BRANCHES: '支线',
  HISTORY: '事件记录',
} as const;
type Tab = (typeof tabs)[number];
function Overview({
  owner,
  step,
}: Readonly<{ owner: FormationWorkspace; step: FormationStepDetail }>) {
  return (
    <>
      {owner.getSnapshot().brief && <ViewedProgress owner={owner} stepRef={step.step_ref} />}
      <h4>预期成果</h4>
      <ul>
        {step.expected_results.map((result) => (
          <li key={result.result_ref}>
            <strong>{result.kind === 'CONTENT' ? '文档内容' : '分析结论'}</strong>：
            {result.description}
          </li>
        ))}
      </ul>
      <p className="field-help">
        依赖 {step.relation_counts.dependencies} · 问题 {step.relation_counts.issues} · 支线{' '}
        {step.relation_counts.branches} · 已关联成果 {step.relation_counts.artifacts}
      </p>
      <FormationStepRelations owner={owner} step={step} />
      {step.last_event && (
        <section className="formation-note">
          <h4>最近活动</h4>
          <p>
            {step.last_event.reason} · {localTime(step.last_event.created_at)}
          </p>
          <FormationEventChanges owner={owner} eventId={step.last_event.event_id} />
        </section>
      )}
      {step.assessment === null && <p>尚未评估</p>}
      {step.recommendation === null && <p>暂无建议</p>}
      {step.assessment && (
        <section className="formation-note" aria-label="AI步骤评估">
          <h4>AI 评估{step.assessment.validity === 'STALE' ? '（依据已变化）' : ''}</h4>
          <p>
            {
              {
                SUFFICIENT: '基本充分',
                GAPS_REMAIN: '仍有缺口',
                UNCERTAIN: '材料不足，暂无法判断',
              }[step.assessment.verdict]
            }
          </p>
          <p>{step.assessment.reason}</p>
          {step.assessment.stale_reason !== null && (
            <p>{assessmentStaleLabels[step.assessment.stale_reason]}</p>
          )}
          <FormationReadSources
            owner={owner}
            label="查看评估依据"
            sources={[
              ...step.assessment.source_refs,
              { kind: 'MESSAGE', message_id: step.assessment.assistant_message_id },
            ]}
          />
        </section>
      )}
      {step.recommendation && (
        <section className="formation-note" aria-label="AI步骤建议">
          <h4>{step.recommendation.validity === 'STALE' ? '历史建议，依据已变化' : '当前建议'}</h4>
          <p>建议：{recommendationActionLabels[step.recommendation.action]}</p>
          <p>{step.recommendation.reason}</p>
          {step.recommendation.stale_reason !== null && (
            <p>{recommendationStaleLabels[step.recommendation.stale_reason]}</p>
          )}
          {step.recommendation.step_ref !== null && <p>建议目标：{step.recommendation.step_ref}</p>}
          <FormationReadSources
            owner={owner}
            label="查看建议依据"
            sources={[
              ...step.recommendation.source_refs,
              { kind: 'MESSAGE', message_id: step.recommendation.assistant_message_id },
            ]}
          />
        </section>
      )}
      {step.closure && (
        <section className="formation-note">
          <h4>最近结束记录</h4>
          <FormationClosure owner={owner} eventId={step.closure.event_id} />
          <p>
            成果 {step.closure.result_count} · 遗留问题 {step.closure.issue_count} · 支线{' '}
            {step.closure.branch_count}
          </p>
          <p>
            基于步骤定义 V{step.closure.definition_version}、目标 V{step.closure.goal_version}
            ；结束不会禁止后续讨论。
          </p>
        </section>
      )}
      <details>
        <summary>步骤来源（{step.sources.length}）</summary>
        {step.sources.length === 0 ? (
          <EmptyState icon="history" message="暂无步骤来源" compact />
        ) : (
          step.sources.map((source, index) => (
            <SourceReference
              key={index}
              label={
                source.availability === 'AVAILABLE' ? '查看来源 ' + (index + 1) : '来源暂不可用'
              }
              read={(signal) =>
                readSource(owner.requirementId, source.source_ref, owner.api, signal)
              }
            />
          ))
        )}
      </details>
    </>
  );
}
function RelatedTab({
  owner,
  step,
  tab,
}: Readonly<{
  owner: FormationWorkspace;
  step: FormationStepDetail;
  tab: Tab;
}>) {
  const [showSuperseded, setShowSuperseded] = useState(false);
  const state = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot);
  const f = state.summary.data?.formation_version;
  if (f === null || f === undefined) return null;
  const req = owner.requirementId,
    doc = owner.documentId,
    ref = step.step_ref,
    scope = [doc, ref, f, tab].join(':');
  const recovery = () => void owner.refresh();
  if (tab === 'RESULTS')
    return (
      <section>
        <FormationAnalysisResults key={ref + ':' + f} owner={owner} step={step} />
        <h4>文档内容关联</h4>
        <label>
          <input
            type="checkbox"
            checked={showSuperseded}
            onChange={(event) => setShowSuperseded(event.target.checked)}
          />{' '}
          显示已替代关联
        </label>
        <FormationPage
          scope={scope + ':' + showSuperseded}
          key={scope + ':' + showSuperseded}
          icon="document"
          empty="此步骤尚无已关联成果"
          load={(cursor, signal) =>
            owner.api.getFormationArtifacts(
              req,
              doc,
              {
                limit: 20,
                known_f: f,
                step_ref: ref,
                include_superseded: showSuperseded,
                ...(cursor === null ? {} : { cursor }),
              },
              signal,
            )
          }
          onPathChanged={recovery}
          render={(row) => (
            <>
              <strong>{row.summary}</strong>
              <FormationArtifactDetails owner={owner} artifactRef={row.artifact_ref} />
              <p>
                {!row.is_active
                  ? '已被替代'
                  : row.freshness === 'CURRENT'
                    ? '关联有效'
                    : row.freshness === 'NEEDS_REVIEW'
                      ? '需要复核'
                      : '内容已移除'}
              </p>
              <p>
                覆盖成果 {row.result_refs.join('、')} · 原始区块 {row.origin_block_count} · 当前区块{' '}
                {row.current_block_count}
              </p>
              <SourceReference
                label="查看原始内容"
                read={(signal) =>
                  readSource(
                    req,
                    {
                      kind: 'REVISION',
                      document_id: doc,
                      revision_id: row.origin_revision_id,
                      block_ids: null,
                    },
                    owner.api,
                    signal,
                  )
                }
              />
            </>
          )}
        />
      </section>
    );
  if (tab === 'ISSUES')
    return (
      <FormationPage
        scope={scope}
        key={scope}
        icon="comment"
        empty="此步骤暂无问题"
        load={(cursor, signal) =>
          owner.api.getFormationIssues(
            req,
            doc,
            { limit: 20, known_f: f, step_ref: ref, ...(cursor === null ? {} : { cursor }) },
            signal,
          )
        }
        onPathChanged={recovery}
        render={(row) => (
          <>
            <strong>{row.description}</strong>
            <p>
              {issueLabels[row.disposition]}
              {row.blocking ? ' · 阻塞问题' : ''}
            </p>
            {row.disposition_reason && <p>{row.disposition_reason}</p>}
          </>
        )}
      />
    );
  if (tab === 'BRANCHES')
    return (
      <FormationPage
        scope={scope}
        key={scope}
        icon="outline"
        empty="此步骤暂无支线"
        load={(cursor, signal) =>
          owner.api.getFormationBranches(
            req,
            doc,
            { limit: 20, known_f: f, step_ref: ref, ...(cursor === null ? {} : { cursor }) },
            signal,
          )
        }
        onPathChanged={recovery}
        render={(row) => (
          <>
            <strong>{row.question}</strong>
            <p>
              {branchLabels[row.status]} · 来源 {row.origin_step_ref} · 返回 {row.return_step_ref}
            </p>
            <p>{row.relevance}</p>
            {row.result_summary && <p>已有结论：{row.result_summary}</p>}
          </>
        )}
      />
    );
  return (
    <FormationPage<ReturnType<typeof eventView>>
      scope={scope}
      key={scope}
      icon="history"
      empty="此步骤暂无历史记录"
      load={(cursor, signal) =>
        owner.api.getFormationEvents(
          req,
          doc,
          { limit: 20, step_ref: ref, ...(cursor === null ? {} : { cursor }) },
          signal,
        )
      }
      render={(row) => (
        <>
          <strong>{row.reason}</strong>
          <p>
            {localTime(row.created_at)} · 变更 {row.change_count} 项
          </p>
          <FormationEventChanges owner={owner} eventId={row.event_id} count={row.change_count} />
          {row.closure && (
            <section>
              <FormationClosure owner={owner} eventId={row.event_id} />
              <p>
                结束时：成果 {row.closure.result_count} · 问题 {row.closure.issue_count} · 支线{' '}
                {row.closure.branch_count}
              </p>
            </section>
          )}
        </>
      )}
    />
  );
}
export function FormationStepView({ owner }: Readonly<{ owner: FormationWorkspace }>) {
  const state = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot);
  const { tab } = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  const tabId = useId();
  const retained = useRef<Readonly<{
    owner: FormationWorkspace;
    detail: FormationStepDetail;
  }> | null>(null);
  if (retained.current?.owner !== owner) retained.current = null;
  if (state.detail.phase === 'READY' && state.detail.data !== null)
    retained.current = { owner, detail: state.detail.data };
  const detail = state.detail;
  const displayed =
    detail.data ??
    (retained.current?.detail.step_ref === state.selected_step_ref
      ? retained.current.detail
      : null);
  const readReason =
    detail.phase !== 'READY' || detail.data === null ? '请先读取当前步骤的最新详情' : null;
  let content: ReactNode;
  if (state.selected_step_ref === null)
    return <EmptyState icon="outline" message="选择步骤查看详情" fill />;
  if (displayed === null)
    return (
      <>
        {detail.phase === 'ERROR' ? (
          <p role="alert">{detail.error}</p>
        ) : (
          <p role="status">正在读取步骤…</p>
        )}
        <button
          type="button"
          className="ui-button"
          onClick={() => void owner.read.selectStep(state.selected_step_ref)}
        >
          重新读取
        </button>
      </>
    );
  content =
    tab === 'OVERVIEW' ? (
      <Overview key={displayed.step_ref} owner={owner} step={displayed} />
    ) : (
      <RelatedTab owner={owner} step={displayed} tab={tab} />
    );
  return (
    <section
      className="formation-step-detail"
      aria-label="步骤详情"
      aria-busy={detail.phase === 'LOADING'}
    >
      <header>
        <h3>{displayed.title}</h3>
        <span className="formation-status">{stepLabels[displayed.status]}</span>
      </header>
      {readReason !== null && (
        <p role="status">正在显示上次读取的步骤详情，请等待最新内容或重新读取。</p>
      )}
      {detail.error && (
        <p role="alert" className="inline-error">
          {detail.error}
        </p>
      )}
      <div role="tablist" aria-label="步骤详情分类" className="formation-tabs">
        {tabs.map((value, index) => (
          <button
            key={value}
            id={tabId + '-' + value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            aria-controls={tabId + '-content'}
            tabIndex={tab === value ? 0 : -1}
            onClick={() => owner.setTab(value)}
            onKeyDown={(event) => {
              const offsets = { ArrowLeft: -1, ArrowRight: 1 };
              let nextIndex = index;
              if (event.key === 'Home') nextIndex = 0;
              else if (event.key === 'End') nextIndex = tabs.length - 1;
              else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight')
                nextIndex = (index + offsets[event.key] + tabs.length) % tabs.length;
              else return;
              event.preventDefault();
              const next = tabs[nextIndex] ?? value;
              owner.setTab(next);
              document.getElementById(tabId + '-' + next)?.focus();
            }}
          >
            {tabNames[value]}
          </button>
        ))}
      </div>
      <div id={tabId + '-content'} role="tabpanel" aria-labelledby={tabId + '-' + tab}>
        {content}
      </div>
    </section>
  );
}
