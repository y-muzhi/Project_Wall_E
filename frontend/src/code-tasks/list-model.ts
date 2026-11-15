import type { CodeTaskStatus } from '../api/code-task-list.ts';

export const TASK_STATUS = {
  PENDING: '未开始',
  RUNNING: '执行中',
  WAITING: '待处理',
  VERIFYING: '自检中',
  AWAITING_TESTING: '待独立测试',
  AWAITING_ACCEPTANCE: '待接收',
  STOPPING: '停止中',
  COMPLETED: '已完成',
  TERMINATED: '已终止',
} satisfies Record<CodeTaskStatus, string>;

export const ACTIVE_TASK_STATUSES: readonly CodeTaskStatus[] = [
  'PENDING',
  'RUNNING',
  'WAITING',
  'VERIFYING',
  'AWAITING_TESTING',
  'AWAITING_ACCEPTANCE',
  'STOPPING',
];

export const TASK_PHASE = {
  PREPARING: '准备',
  BACKEND: '后端',
  FRONTEND: '前端',
  INTEGRATION: '联调',
  TESTING: '独立测试',
  ACCEPTANCE: '接收',
  DELIVERY: '交付',
  FINISHED: '结束',
} as const;

export type CodeTaskQuery = Readonly<{
  page: number;
  statuses: readonly CodeTaskStatus[];
  revisionId: number | null;
}>;

export const DEFAULT_TASK_QUERY: CodeTaskQuery = Object.freeze({
  page: 1,
  statuses: Object.freeze([]),
  revisionId: null,
});

export function safeId(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1;
}

export function readCodeTaskQuery(value: unknown): CodeTaskQuery {
  if (!value || typeof value !== 'object') return DEFAULT_TASK_QUERY;
  const row = value as Partial<CodeTaskQuery>;
  if (
    !safeId(row.page) ||
    row.page > 100000 ||
    !Array.isArray(row.statuses) ||
    new Set(row.statuses).size !== row.statuses.length ||
    !row.statuses.every(
      (status: unknown) => typeof status === 'string' && Object.hasOwn(TASK_STATUS, status),
    ) ||
    (row.revisionId !== null && !safeId(row.revisionId))
  )
    return DEFAULT_TASK_QUERY;
  return Object.freeze({
    page: row.page,
    statuses: Object.freeze([...row.statuses]),
    revisionId: row.revisionId,
  });
}
