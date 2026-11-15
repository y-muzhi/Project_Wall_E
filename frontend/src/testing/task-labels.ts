export const testingStatus = {
  DRAFT: '待准备',
  PLANNING: '正在起草计划',
  READY: '就绪',
  RUNNING: '测试进行中',
  WAITING: '等待处理',
  STOPPING: '正在终止',
  COMPLETED: '测试已结束',
  TERMINATED: '已终止',
} as const;
export const testingPurpose = {
  DIAGNOSTIC: '诊断',
  ACCEPTANCE: '验收',
  PACK_VALIDATION: '测试包有效性',
} as const;
export const testingPhase = {
  PLAN: '计划',
  PREPARE: '准备',
  EXECUTE: '执行',
  REPORT: '报告',
  FINISHED: '结束',
} as const;
export const testingReason = {
  TASK_STATE: '当前任务状态不允许此操作',
  ASSET_NOT_READY: '尚未绑定可用的测试计划与测试包',
  MODEL_NOT_READY: '计划起草模型尚未就绪',
  EXECUTION_NOT_READY: '独立测试执行环境尚未就绪',
  BUDGET_NOT_READY: '当前预算不足',
  OPERATION_UNKNOWN: '尚无可继续的原操作或原结果待核实',
  AUTHORIZATION_NOT_READY: '独立授权尚未就绪',
  REFERENCE_SET_NOT_REGISTERED: '固定设计尚无预登记参考集',
} as const;
