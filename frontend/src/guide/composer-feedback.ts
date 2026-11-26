import type { ComposerState } from './composer.ts';

const effects = {
  DISCUSS: '仅讨论，不修改文档。',
  REVISE: '请在运行回执查看本轮是否已保存或待审阅。',
  PROPOSE_CHANGES: '仅生成待审阅的修改建议，确认应用后才写入正文。',
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
  if (state.action !== 'DISCUSS' && state.detail.current?.archived_at != null)
    return result('当前文档已归档，无法写入。');
  if (state.action !== 'DISCUSS' && state.target === null) return result('请先选择写入范围。');
  if (state.action === 'DISCUSS' && state.parent === null && state.formation_blocked)
    return result(state.formation_blocked);
  if (!allowed) return result('目标或来源已变化，请核对当前文档及范围后再发送。');
  return result(null);
}

/** The footer swaps progress text in place as the original request advances. */
export function composerProgress(state: ComposerState, savingTopic: boolean): string | null {
  if (state.phase === 'SUBMITTING') return '正在发送';
  if (state.phase === 'READING') return '核实请求';
  if (state.phase === 'CONFIRMED') return '读取结果';
  if (state.detail.requirement.document_work_state === 'GUIDE_ACTIVE') return '等待回复';
  if (savingTopic) return '保存讨论主题';
  return state.refreshing ? '同步状态' : null;
}
