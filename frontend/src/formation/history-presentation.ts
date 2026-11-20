import type { entityChange } from '../api/formation-history.ts';
import { branchLabels, issueLabels, stepLabels } from './labels.ts';
export type HistoricalChange = ReturnType<typeof entityChange>;
export const changeNames: Readonly<Record<HistoricalChange['entity_kind'], string>> = {
  STEP: '步骤',
  GOAL: '文档目标',
  RESULT: '成果要求',
  ISSUE: '问题',
  BRANCH: '支线',
  ARTIFACT: '正文关联',
  ORDER: '步骤顺序',
  RESULT_ROUTE: '原成果去向',
  ASSESSMENT: 'AI评估',
  RECOMMENDATION: 'AI建议',
  PROPOSAL: '提案处置',
  PROPOSAL_CHECK: '撤回调整核验',
  ARTIFACT_REVIEW: '关联复核',
};
const reviewNames = {
  MATCHED: '原关联已核实',
  REASSOCIATED: '形成替代关联',
  UNVERIFIED: '暂无法核实',
  REMOVED: '内容已移除',
} as const;
const verdicts = {
  SUFFICIENT: '基本充分',
  GAPS_REMAIN: '仍有缺口',
  UNCERTAIN: '暂无法判断',
} as const;
const proposalNames = {
  PENDING: '待确认',
  DEFERRED: '已暂缓',
  APPLIED: '已采用',
  SUPERSEDED: '已有新提案',
} as const;
/** Text comes only from the immutable event snapshot, never a current entity lookup. */
export function historicalDescription(row: HistoricalChange, side: 'before' | 'after'): string {
  switch (row.entity_kind) {
    case 'STEP': {
      const v = row[side];
      return v === null
        ? '无'
        : v.title +
            ' · ' +
            stepLabels[v.status] +
            ' · 第' +
            v.position +
            '步 · 定义V' +
            v.definition_version;
    }
    case 'GOAL': {
      const v = row[side];
      return v === null ? '无' : v.text + ' · 目标V' + v.version;
    }
    case 'RESULT': {
      const v = row[side];
      return v === null
        ? '无'
        : v.description + ' · ' + (v.kind === 'CONTENT' ? '文档内容' : '分析结论');
    }
    case 'ISSUE': {
      const v = row[side];
      return v === null
        ? '无'
        : v.description +
            ' · 归属' +
            v.step_ref +
            ' · ' +
            issueLabels[v.disposition] +
            (v.disposition_reason ? ' · ' + v.disposition_reason : '');
    }
    case 'BRANCH': {
      const v = row[side];
      return v === null
        ? '无'
        : v.question +
            ' · 来源' +
            v.origin_step_ref +
            '，返回' +
            v.return_step_ref +
            ' · ' +
            branchLabels[v.status] +
            (v.result_summary ? ' · 原结论：' + v.result_summary : '');
    }
    case 'ARTIFACT': {
      const v = row[side];
      return v === null
        ? '无'
        : v.summary +
            ' · 归属' +
            v.step_ref +
            ' · 核对版本#' +
            v.checked_against_revision_id +
            ' · ' +
            (v.freshness === 'CURRENT'
              ? '当时有效'
              : v.freshness === 'NEEDS_REVIEW'
                ? '当时待复核'
                : '当时已移除');
    }
    case 'ORDER': {
      const v = row[side];
      return v === null ? '无' : v.step_ref + '：第' + v.position + '步';
    }
    case 'RESULT_ROUTE': {
      const v = row[side];
      return v === null
        ? '无'
        : v.from_result_ref +
            ' → ' +
            (v.disposition === 'NOT_REQUIRED' ? '不再需要' : v.target_result_refs.join('、')) +
            ' · ' +
            v.reason;
    }
    case 'ASSESSMENT': {
      const v = row[side];
      return v === null
        ? '无'
        : verdicts[v.verdict] + ' · ' + v.reason + ' · 依据版本#' + v.evaluated_revision_id;
    }
    case 'RECOMMENDATION': {
      const v = row[side];
      return v === null ? '无' : v.reason + (v.step_ref ? ' · 目标' + v.step_ref : '');
    }
    case 'PROPOSAL': {
      const v = row[side];
      return v === null
        ? '无'
        : proposalNames[v.disposition] +
            (v.needs_revision ? ' · 调整中／待重新核对' : '') +
            ' · 原卡' +
            v.proposal.card_key;
    }
    case 'PROPOSAL_CHECK': {
      const v = row[side];
      return v === null
        ? '无'
        : '原提案核验一致 · 正式命令消息#' +
            v.command_message_id +
            ' · 核对正文V' +
            v.checked_versions.content_version;
    }
    case 'ARTIFACT_REVIEW': {
      const v = row[side];
      return v === null
        ? '无'
        : reviewNames[v.result] +
            '：' +
            v.reviewed_artifact_ref +
            ' → ' +
            (v.replacement_artifact_ref ?? '保留原关联身份') +
            ' · 核对版本#' +
            v.checked_against_revision_id +
            ' · 触发回复#' +
            v.assistant_message_id;
    }
  }
}
