import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { RequirementDetailOwner } from './detail-owner.ts';
import { SourceReference } from './source-reference.tsx';
import type { DiscussionState } from '../api/models.ts';
import { Icon } from '../shared/icon.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { activeModal } from '../shared/modal.ts';
import {
  progressPresentation,
  topicRecords,
  assessments,
  evidenceOrigins,
  evidenceStates,
  dispositionLabels,
} from './discussion-presentation.ts';
import type { ProgressTopic } from './discussion-presentation.ts';
import type { DiscussionCommand } from '../api/walle.ts';
import brief from '../../../backend/resources/v17/guides/collaboration.brief.v2.json' with { type: 'json' };
import design from '../../../backend/resources/v17/guides/collaboration.design.v2.json' with { type: 'json' };
import specification from '../../../backend/resources/v17/guides/collaboration.specification.v2.json' with { type: 'json' };
const guides = {
  REQUIREMENT_BRIEF: brief,
  FRONTEND_DESIGN: design,
  BACKEND_DESIGN: specification,
  DESIGN: design,
  SPECIFICATION: specification,
};
const natures = { FACT: '事实', CONSTRAINT: '约束', PROPOSAL: '建议' };
type Evidence = DiscussionState['evidence'][number];
function EvidenceRecords({
  items,
  owner,
}: {
  items: readonly Evidence[];
  owner: RequirementDetailOwner;
}) {
  const documents = owner.getSnapshot().detail!.documents;
  return (
    <ul className="progress-records">
      {items.map((item) => (
        <li key={item.evidence_ref} data-state={item.state}>
          <div className="progress-record-meta">
            <span data-origin={item.origin}>{evidenceOrigins[item.origin]}</span>
            {!(item.origin === 'AI_PROPOSAL' && item.nature === 'PROPOSAL') && (
              <span>{natures[item.nature]}</span>
            )}
            <span>{evidenceStates[item.state]}</span>
          </div>
          <p>{item.assertion}</p>
          <details className="progress-sources">
            <summary>查看来源 · {item.source_refs.length}</summary>
            <ul>
              {item.source_refs.map((source) => (
                <li key={JSON.stringify(source)}>
                  <SourceReference
                    read={(signal) => owner.readSource(source, signal)}
                    label={
                      source.kind === 'REVISION'
                        ? `${documents.find((document) => document.id === source.document_id)?.name ?? '文档 #' + source.document_id} · 版本记录 #${source.revision_id}`
                        : source.kind === 'MESSAGE'
                          ? `消息 #${source.message_id}`
                          : source.kind === 'CARD_ANSWER'
                            ? `正式回答 #${source.message_id} · ${source.card_key}`
                            : source.kind === 'RUN_RESULT'
                              ? `运行 #${source.guide_run_id} · 分析结果`
                              : `运行 #${source.guide_run_id} · 已保存材料`
                    }
                  />
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}
function Dispositions({ items }: { items: DiscussionState['dispositions'] }) {
  return (
    <ul className="progress-decisions">
      {items.map((item, index) => (
        <li key={`${item.message_id}:${index}`}>
          <span>{dispositionLabels[item.kind]}</span>
          <p>{item.summary}</p>
        </li>
      ))}
    </ul>
  );
}
function TopicDetails({
  topic,
  discussion,
  owner,
  locked,
  focus,
}: {
  topic: ProgressTopic;
  discussion: DiscussionState;
  owner: RequirementDetailOwner;
  locked: boolean;
  focus(): void;
}) {
  const current = topic.topic_ref === discussion.focus_topic_ref,
    records = topicRecords(discussion, topic);
  return (
    <details className="progress-topic" open={current} data-current={current}>
      <summary>
        <span className="progress-chevron">
          <Icon name="right" />
        </span>
        <span className="progress-topic-heading">
          <span className="progress-topic-title">
            {current && <span className="progress-current-label">当前</span>}
            {topic.title}
          </span>
          <span className="progress-topic-meta">
            {topic.unresolved_impacts.length > 0 && (
              <span>{topic.unresolved_impacts.length} 项待明确</span>
            )}
            {records.current.length > 0 && <span>{records.current.length} 条记录</span>}
          </span>
        </span>
        <span className="progress-assessment" data-assessment={topic.assessment}>
          {assessments[topic.assessment]}
        </span>
      </summary>
      <div className="progress-topic-body">
        {!current && <p className="progress-topic-purpose">{topic.purpose}</p>}
        {topic.unresolved_impacts.length > 0 && (
          <section className="progress-unresolved">
            <h4>待明确的问题</h4>
            <ul>
              {topic.unresolved_impacts.map((impact, index) => (
                <li key={index}>{impact}</li>
              ))}
            </ul>
          </section>
        )}
        <section className="progress-record-section">
          <h4>
            已记录内容 <small>AI整理</small>
          </h4>
          {records.current.length ? (
            <EvidenceRecords items={records.current} owner={owner} />
          ) : (
            <EmptyState icon="info" message="暂无内容依据" compact />
          )}
        </section>
        <section className="progress-outcomes">
          <h4>需要形成的成果</h4>
          <ul>
            {topic.expected_outcomes.map((outcome) => (
              <li key={outcome.outcome_ref}>
                <strong>{outcome.text}</strong>
                <p>{outcome.criterion}</p>
              </li>
            ))}
          </ul>
        </section>
        {records.dispositions.length > 0 && (
          <section>
            <h4>讨论记录</h4>
            <Dispositions items={records.dispositions} />
          </section>
        )}
        {topic.dependencies.length > 0 && (
          <section className="progress-dependencies">
            <h4>关联主题</h4>
            <ul>
              {topic.dependencies.map((ref) => (
                <li key={ref}>
                  {discussion.topics.find((item) => item.topic_ref === ref)?.title ??
                    '暂不可读取的主题'}
                </li>
              ))}
            </ul>
          </section>
        )}
        {records.history.length > 0 && (
          <details className="progress-history">
            <summary>已更新的记录 · {records.history.length}</summary>
            <EvidenceRecords items={records.history} owner={owner} />
          </details>
        )}
        {!current && (
          <button type="button" className="ui-button" disabled={locked} onClick={focus}>
            讨论此主题
          </button>
        )}
      </div>
    </details>
  );
}
export function DiscussionProgress({
  owner,
  blocked,
  active,
  discuss,
}: {
  owner: RequirementDetailOwner;
  blocked: boolean;
  active: boolean;
  discuss(): void;
}) {
  const flow = owner.regions!.discussion,
    state = useSyncExternalStore(flow.subscribe, flow.getSnapshot),
    actual = state.detail,
    discussion = state.discussion;
  const panel = useRef<HTMLElement>(null),
    focusCard = useRef<HTMLElement>(null);
  const [error, setError] = useState<string | null>(null);
  const currentDocumentId = owner.getSnapshot().detail?.selected_document_id ?? null;
  const currentDocument = actual.documents.find((item) => item.id === currentDocumentId);
  const locked = blocked || !flow.allowed || currentDocumentId === null;
  const send = async (command: DiscussionCommand) => {
    setError(null);
    try {
      if (!(await flow.submit(command))) return;
      owner.toasts.push('success', '当前讨论主题已更新');
      requestAnimationFrame(() => {
        if (!panel.current || panel.current.closest('[hidden],[inert]') || activeModal()) return;
        focusCard.current?.focus({ preventScroll: true });
        panel.current.scrollTop = 0;
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '讨论调整失败');
    }
  };
  const view =
    discussion && currentDocument && currentDocument.document_kind !== 'DRAWING'
      ? progressPresentation(discussion, guides[currentDocument.document_kind].mainlines)
      : null;
  const stale = discussion !== null && state.version !== actual.requirement.discussion_version;
  // Observe acknowledged versions only in the visible progress tab; this is not a poller or
  // model request. A failed read stays visible until the user explicitly retries.
  useEffect(() => {
    if (!active) return;
    const current = flow.getSnapshot();
    if (!current.discussion || (current.version ?? -1) < actual.requirement.discussion_version)
      void flow.load();
  }, [active, actual.requirement.discussion_version, flow]);
  useEffect(() => {
    if (active) return () => flow.pauseRead();
  }, [active, flow]);
  const reread = () =>
    void owner
      .refresh()
      .then(() => {
        if (
          panel.current &&
          !panel.current.closest('[hidden],[inert]') &&
          !flow.getSnapshot().loading
        )
          return flow.load();
      })
      .catch(() => undefined);
  return (
    <section ref={panel} className="discussion-progress" aria-label="大纲与进展">
      <header className="progress-panel-heading">
        <div>
          <h2>大纲与进展</h2>
        </div>
        <button type="button" className="ui-button" onClick={discuss}>
          返回对话
        </button>
      </header>
      <div className="progress-body">
        {state.loading && (
          <p className="progress-notice" role="status">
            正在读取讨论进展…
          </p>
        )}
        {discussion && view && (
          <>
            {stale && (
              <p className="progress-notice" role="status">
                讨论已变化，以下为保留的进展。
                <button
                  type="button"
                  className="ui-button"
                  disabled={state.loading}
                  onClick={reread}
                >
                  重新读取
                </button>
              </p>
            )}
            {view.focus ? (
              <section
                ref={focusCard}
                tabIndex={-1}
                className="progress-focus-card"
                aria-label="当前重点"
              >
                <div>
                  <span className="progress-eyebrow">当前重点</span>
                  <span className="progress-assessment" data-assessment={view.focus.assessment}>
                    {assessments[view.focus.assessment]}
                  </span>
                </div>
                <h3>{view.focus.title}</h3>
                <p>{view.focus.purpose}</p>
              </section>
            ) : view.topics.length ? (
              <p className="progress-notice">
                尚未选定当前主题。可展开下方主题，选择“讨论此主题”。
              </p>
            ) : !state.loading && !state.error ? (
              <EmptyState icon="progress" message="暂无讨论主题" />
            ) : null}
            {view.next && (
              <section className="progress-next-step" aria-label="下一步建议">
                <span className="progress-eyebrow">下一步建议</span>
                <strong>{view.next.label}</strong>
                <p>{view.next.reason}</p>
                {view.next.topic && view.next.topic.topic_ref !== discussion.focus_topic_ref && (
                  <p className="field-help">关联主题：{view.next.topic.title}</p>
                )}
                {view.next.impacts.length > 0 && (
                  <ul>
                    {view.next.impacts.map((impact, index) => (
                      <li key={index}>{impact}</li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            {view.groups.length > 0 && (
              <>
                <div className="progress-route-heading">
                  <h3>讨论主线</h3>
                  <span>
                    {view.topics.length} 个主题
                    {view.reviewCount > 0 && ` · ${view.reviewCount} 个需复核`}
                  </span>
                </div>
                <ol className="progress-mainlines">
                  {view.groups.map((mainline, index) => (
                    <li key={mainline.ref}>
                      <details
                        className="progress-mainline"
                        open={mainline.topics.some(
                          (topic) => topic.topic_ref === discussion.focus_topic_ref,
                        )}
                      >
                        <summary>
                          <span className="progress-mainline-number">
                            {String(index + 1).padStart(2, '0')}
                          </span>
                          <strong>{mainline.title}</strong>
                          <span className="progress-mainline-count">
                            {mainline.topics.length} 个主题
                          </span>
                          <span className="progress-chevron">
                            <Icon name="right" />
                          </span>
                        </summary>
                        <div className="progress-mainline-body">
                          <p className="progress-mainline-purpose">{mainline.purpose}</p>
                          {mainline.topics.map((topic) => (
                            <TopicDetails
                              key={topic.topic_ref}
                              topic={topic}
                              discussion={discussion}
                              owner={owner}
                              locked={locked}
                              focus={() =>
                                void send({ type: 'SET_FOCUS', topic_ref: topic.topic_ref })
                              }
                            />
                          ))}
                        </div>
                      </details>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </>
        )}
        {(state.error || error) && (
          <p className="inline-error progress-notice" role="alert">
            {error ?? state.error}
            <button
              type="button"
              className="ui-button"
              disabled={state.loading || state.phase === 'SUBMITTING'}
              onClick={reread}
            >
              重新读取进展
            </button>
          </p>
        )}
        {state.phase === 'UNKNOWN' && (
          <button
            type="button"
            className="ui-button"
            disabled={blocked}
            onClick={() => void flow.retryUnknown()}
          >
            核实原请求
          </button>
        )}
        {state.phase === 'CONFIRMED' && (
          <button
            type="button"
            className="ui-button"
            disabled={blocked || state.loading}
            onClick={() => void flow.finish()}
          >
            读取保存结果
          </button>
        )}
        {!discussion && !state.loading && (
          <button type="button" className="ui-button" onClick={() => void flow.load()}>
            读取讨论进展
          </button>
        )}
      </div>
    </section>
  );
}
