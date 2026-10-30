import type { DiscussionState } from '../api/models.ts';

export const phaseLabels = {
  DISCOVERY: '需求探索',
  SOLUTION: '方案设计',
  SPECIFICATION: '规格整理',
  REVIEW: '检查与完善',
} as const;
export const assessments = {
  NOT_STARTED: '尚未开始',
  DISCUSSING: '讨论中',
  SUPPORTED: '已有依据',
  REVIEW_REQUIRED: '需要复核',
} as const;
export const evidenceOrigins = {
  USER_STATEMENT: '用户陈述',
  USER_DECISION: '用户决定',
  AI_PROPOSAL: 'AI建议',
} as const;
export const evidenceStates = {
  ACTIVE: '当前有效',
  SUPERSEDED: '已被更新',
  DISPUTED: '存在争议',
} as const;
export const dispositionLabels = {
  DEFER: '暂缓',
  NOT_APPLICABLE: '不适用',
  REJECT_DRAFT: '暂不出稿',
  REDIRECT: '调整方向',
} as const;
const stepLabels = {
  PRESENT_DESIGN: '梳理设计方案',
  ASK_DECISION: '明确关键决定',
  SUMMARIZE_TOPIC: '整理当前主题',
  RECOMMEND_DRAFT: '建议形成文档',
  NEED_EVIDENCE: '补充必要依据',
  PROPOSE_PHASE_CHANGE: '评估下一阶段',
} as const;
type Mainline = Readonly<{ ref: string; title: string; purpose: string }>;
export type ProgressTopic = DiscussionState['topics'][number];

/** Read-only presentation: never infer confirmation, completeness or authority
 * from an assessment, disposition, count or the last model recommendation. */
export function progressPresentation(discussion: DiscussionState, mainlines: readonly Mainline[]) {
  const topics = discussion.topics.filter(
    (topic) => topic.phase_ref === discussion.phase.phase_ref,
  );
  const groups = mainlines.map((mainline) => ({
    ...mainline,
    topics: topics.filter((topic) => topic.mainline_ref === mainline.ref),
  }));
  const unmatched = topics.filter(
    (topic) => !mainlines.some((mainline) => mainline.ref === topic.mainline_ref),
  );
  if (unmatched.length)
    groups.push({
      ref: 'other',
      title: '其他主题',
      purpose: '尚未对应到当前主线的已保存主题。',
      topics: unmatched,
    });
  const focus = topics.find((topic) => topic.topic_ref === discussion.focus_topic_ref) ?? null;
  const step = discussion.last_step?.value,
    action = step?.action;
  const next =
    typeof action === 'string' &&
    Object.hasOwn(stepLabels, action) &&
    typeof step?.reason === 'string'
      ? {
          label: stepLabels[action as keyof typeof stepLabels],
          reason: step.reason,
          topic: topics.find((topic) => topic.topic_ref === step.topic_ref) ?? null,
          impacts: Array.isArray(step.unresolved_impacts)
            ? step.unresolved_impacts.filter((item): item is string => typeof item === 'string')
            : [],
        }
      : null;
  return {
    topics,
    groups,
    focus,
    next,
    reviewCount: topics.filter((topic) => topic.assessment === 'REVIEW_REQUIRED').length,
    phaseDispositions: discussion.dispositions.filter((item) =>
      item.scope_refs.includes(discussion.phase.phase_ref),
    ),
  };
}
export function topicRecords(discussion: DiscussionState, topic: ProgressTopic) {
  const evidence = discussion.evidence.filter((item) =>
    topic.evidence_refs.includes(item.evidence_ref),
  );
  return {
    current: evidence.filter((item) => item.state !== 'SUPERSEDED'),
    history: evidence.filter((item) => item.state === 'SUPERSEDED'),
    dispositions: discussion.dispositions.filter((item) =>
      item.scope_refs.includes(topic.topic_ref),
    ),
  };
}
