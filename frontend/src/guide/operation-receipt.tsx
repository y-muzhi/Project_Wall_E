import { useState } from 'react';
import type { ReactNode } from 'react';
import type { GuideOperationReceipt } from '../api/models.ts';
import { RequestCallRecord } from './model-call-view.tsx';
import type { OperationDetailKind } from './saved-operation.ts';

const states = {
  RUNNING: '处理中',
  FAILED: '失败',
  CANCELLED: '已取消',
  SAVED: '已保存',
  PENDING_REVIEW: '待审阅',
  OUTDATED: '基准版本已更新',
  APPLIED: '已应用',
  DISCARDED: '已放弃',
  NO_CHANGE: '正文无变化',
  NOT_APPLIED: '未写入',
  PROGRESS_UPDATED: '已更新',
};
const scopes = { DOCUMENT: '整篇文档', SECTION: '章节', BLOCK: '区块', SELECTION: '选区' };

export function GuideOperationCard({
  receipt,
  commands,
  review,
  showDetail,
}: Readonly<{
  receipt: GuideOperationReceipt;
  commands?: ReactNode;
  review?: (id: number) => void;
  showDetail: (kind: OperationDetailKind) => void;
}>) {
  const [expanded, setExpanded] = useState(false);
  const savedVersion = receipt.state === 'SAVED' ? receipt.saved_content_version : null;
  const label =
    receipt.operation === 'PROPOSE_CHANGES'
      ? '文档修改建议'
      : receipt.operation === 'DISCUSS'
        ? '讨论进展'
        : receipt.operation === 'REVISE' && (receipt.base_content_version ?? 0) > 1
          ? '文档修订'
          : '首次出稿';
  const status =
    states[receipt.state] +
    (receipt.saved_content_version === null ? '' : ` V${receipt.saved_content_version}`);
  return (
    <section className="guide-operation-card" aria-label={label}>
      <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>
          <strong>{label}</strong>
          <span data-state={receipt.state}>{status}</span>
        </summary>
        <div className="guide-operation-detail">
          {(receipt.document_name || receipt.scope_type) && (
            <p>
              {[
                receipt.document_name,
                receipt.scope_label ?? (receipt.scope_type && scopes[receipt.scope_type]),
                receipt.base_content_version !== null && `基于 V${receipt.base_content_version}`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          )}
          {receipt.reason && <p role="status">{receipt.reason}</p>}
          {expanded && <RequestCallRecord runId={receipt.run_id} />}
          {commands}
        </div>
      </details>
      {review && receipt.batch_id !== null && (
        <button className="ui-button" type="button" onClick={() => review(receipt.batch_id!)}>
          查看修改建议
        </button>
      )}
      {savedVersion !== null && (
        <div className="guide-operation-version-actions">
          <button className="ui-button" type="button" onClick={() => showDetail('VERSION')}>
            查看 V{savedVersion}
          </button>
          {receipt.base_content_version !== null && (
            <button className="ui-button" type="button" onClick={() => showDetail('COMPARE')}>
              比对 V{receipt.base_content_version} 与 V{savedVersion}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
