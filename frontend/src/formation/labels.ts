import type { availability } from '../api/formation-values.ts';
export const stepLabels = {
  PLANNED: '未开始',
  IN_PROGRESS: '进行中',
  PAUSED: '已暂停',
  COMPLETED: '已结束',
  CANCELLED: '已放弃',
} as const;
export const branchLabels = {
  OPEN: '讨论中',
  RESOLVED: '已有结果',
  DEFERRED: '已暂缓',
  DROPPED: '已放弃',
} as const;
const reasons: Readonly<Record<string, string>> = {
  FORMATION_NOT_INITIALIZED: '尚未建立文档主线',
  ARTIFACT_SUPERSEDED: '此成果已被新关联替代',
  PATH_CHANGED: '路线已变化，请重新读取',
  GOAL_CHANGED: '目标已变化，请重新读取',
  STEP_DEFINITION_CHANGED: '步骤定义已变化，请重新读取',
  TARGET_CHANGED: '讨论目标已变化',
  BRANCH_STATE_CHANGED: '支线状态已变化',
  BRANCH_RETURN_MISMATCH: '支线返回步骤已变化',
  PROPOSAL_ADJUSTING: '提案正在调整',
  PROPOSAL_BASIS_CHANGED: '提案依据已变化',
  SOURCE_UNAVAILABLE: '所需来源暂不可用',
  INVALID_TRANSITION: '当前状态不支持此操作',
  WORK_STATE_CONFLICT: '当前正在处理文档操作',
  WORK_STATE_INCONSISTENT: '文档占用状态异常，请重新读取',
  CONTENT_CHANGED: '正文已变化',
  DEFINITION_CHANGED: '步骤定义已变化',
  PURPOSE_CHANGED: '提案用途已变化',
  BASIS_CHANGED: '提案依据已变化',
  ADJUSTING: '提案正在调整',
  ALREADY_ANSWERED: '此提案已有正式回答',
  DEFERRED: '此提案已暂缓',
  SUPERSEDED: '此提案已被替代',
};
export function availabilityText(reason: string | null | undefined): string {
  return reason === null
    ? ''
    : reason === undefined
      ? '当前状态不支持此操作'
      : (reasons[reason] ?? '当前操作暂不可用');
}
export function actionReason(
  rows: readonly ReturnType<typeof availability>[],
  action: string,
  blocked: string | null,
): string | null {
  if (blocked !== null) return blocked;
  const actual = rows.find((row) => row.action === action);
  return actual?.available ? null : availabilityText(actual?.reason);
}

export const issueLabels = {
  OPEN: '未解决',
  RESOLVED: '已解决',
  DEFERRED: '已暂缓',
  DROPPED: '已放弃',
} as const;

export const assessmentStaleLabels = {
  GOAL_CHANGED: '文档目标已变化',
  DEFINITION_CHANGED: '步骤定义已变化',
  COVERAGE_CHANGED: '相关正文范围已变化',
} as const;
export const recommendationStaleLabels = {
  GOAL_CHANGED: '文档目标已变化',
  OWNER_DEFINITION_CHANGED: '所属步骤定义已变化',
  OWNER_STATE_CHANGED: '所属步骤状态已变化',
  TARGET_CHANGED: '建议目标已变化',
  COVERAGE_CHANGED: '相关正文范围已变化',
  SOURCE_UNAVAILABLE: '原建议来源暂不可核实',
  RELATED_FACT_CHANGED: '相关成果、问题或支线已变化',
} as const;
export const recommendationActionLabels = {
  DISCUSS: '继续讨论',
  WRITE: '形成文档内容',
  RESOLVE_BRANCH: '核对支线结论',
  REVIEW_CONTENT: '复核文档内容',
  COMPLETE_STEP: '结束本步骤',
  SWITCH_STEP: '切换讨论步骤',
  NEED_MATERIAL: '补充材料',
} as const;
