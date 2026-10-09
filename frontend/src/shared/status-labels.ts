import type {SaveStatus} from '../documents/autosave.ts';

export const REQUIREMENT_STATUS_LABELS = Object.freeze({
  INITIALIZING: '初始化中', ACTIVE: '进行中', COMPLETED: '已完成',
} as const);

export const SAVE_STATUS_LABELS = Object.freeze({
  SAVED: '已保存', DIRTY: '未保存', SAVING: '保存中', RETRYING: '保存失败，正在重试',
  UNKNOWN: '保存结果待核实', VALIDATION_ERROR: '草稿校验失败', CONFLICT: '草稿版本冲突', CLOSED: '编辑已结束',
} satisfies Record<SaveStatus, string>);

export function saveStatusLabel(status: SaveStatus, valid: boolean): string {
  return valid ? SAVE_STATUS_LABELS[status] : '未保存 · 当前输入尚未形成完整快照';
}
