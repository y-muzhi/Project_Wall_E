import type { ComposerState } from './composer.ts';

const effects = {
  DISCUSS: '仅讨论，不修改文档。',
  REVISE: '成功后保存为新版本，原版本保留。',
};

/** Presentation only. The owner and server remain the send permission gates. */
export function composerFeedback(
  state: ComposerState,
  available: boolean,
  allowed: boolean,
): Readonly<{ effect: string; blocked: string | null }> {
  const effect = effects[state.action],
    result = (blocked: string | null) => ({ effect, blocked });
  if (state.phase === 'UNKNOWN') return result('发送结果待核实，请先核实原请求。');
  if (['SUBMITTING', 'READING', 'CONFIRMED'].includes(state.phase))
    return result('正在处理本次请求，请稍候。');
  if (state.needs_refresh) return result('当前状态已变化，请先重新读取状态。');
  const occupancy = state.detail.requirement.document_work_state;
  if (occupancy === 'MANUAL_EDITING') return result('请先完成或取消人工编辑，再发送 AI 请求。');
  if (occupancy === 'SUGGESTION_REVIEWING')
    return result('请先完成或放弃当前修改建议，再发送 AI 请求。');
  if (occupancy === 'GUIDE_ACTIVE') return result('AI 正在处理上一轮请求，请等待结束。');
  if (!available) return result('当前操作暂不可用，请等待状态同步完成。');
  if (state.action === 'REVISE' && state.detail.current?.archived_at != null)
    return result('当前文档已归档，无法写入。');
  if (state.action === 'REVISE' && state.target === null) return result('请先选择写入范围。');
  if (!allowed) return result('目标或来源已变化，请核对当前文档及范围后再发送。');
  return result(null);
}
