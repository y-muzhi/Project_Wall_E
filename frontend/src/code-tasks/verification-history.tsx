import { useCallback, useState } from 'react';
import type { CodeCheckItem, CodeVerification } from '../api/code-task-checks.ts';
import { projectCommandEvidence } from '../api/code-task-checks.ts';
import type { WalleApi } from '../api/walle.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { TASK_PHASE } from './list-model.ts';
import { useSettingsRead } from './settings/read.ts';
import { VerificationCases } from './verification-cases.tsx';

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  candidateId: number;
  currentVerificationId: number | null;
  visible: boolean;
  onSelect?(id: number): void;
  selectedPage?: number;
  selectPage?(page: number): void;
}>;

const states = {
  PENDING: '等待执行',
  RUNNING: '正在自检',
  FINISHED: '检查已结束',
  UNKNOWN: '结果待核对',
  CANCELLED: '已取消',
} as const;

const eligibility = {
  REQUIRED_NOT_PASSED: '必检项尚未通过',
  VERIFICATION_STAGE_NOT_READY: '当前阶段或角色交接条件不满足',
  RESOURCE_NOT_READY: '原检查资源尚未就绪',
  COVERAGE_NOT_READY: '固定检查覆盖尚未就绪',
  NO_CONTROLLED_CASES: '未取得所需受控用例',
  CANDIDATE_MISMATCH: '该记录属于其他固定代码',
  CONFIGURATION_MISMATCH: '当前采用的配置已变化',
  ENVIRONMENT_MISMATCH: '当前执行环境与原记录不一致',
  RESULT_INCOMPLETE: '检查证据不完整',
  ACTIVITY_NOT_STOPPED: '原活动尚未确认停止',
  CLEANUP_NOT_VERIFIED: '原资源清理尚未确认',
  INPUT_CHANGED: '检查输入发生变化',
} as const;

const itemStates = {
  NOT_RUN: '未运行',
  RUNNING: '进行中',
  PASSED: '通过',
  FAILED: '失败',
  UNAVAILABLE: '不可用',
  UNKNOWN: '待核对',
  CANCELLED: '已取消',
} as const;

const itemReasons = {
  COMMAND_FAILED: '原命令以非零状态退出',
  ASSERTION_FAILED: '受控断言未通过',
  NO_CONTROLLED_CASES: '未取得所需受控用例',
  RESOURCE_MISSING: '缺少固定检查资源',
  DEPENDENCY_MISMATCH: '依赖与原配置不一致',
  ISOLATION_UNAVAILABLE: '隔离环境不可用',
  TARGET_UNVERIFIED: '原目标归属未核实',
  APPLICATION_START_FAILED: '被测应用启动失败',
  TIMEOUT: '运行超时',
  OUTPUT_LIMIT: '输出超过允许范围',
  INPUT_CHANGED: '检查输入发生变化',
  EVIDENCE_INCOMPLETE: '检查证据不完整',
  PROCESS_STATE_UNKNOWN: '原进程状态待核对',
  CLEANUP_UNVERIFIED: '清理状态待核对',
} as const;

const stop = {
  NOT_STARTED: '尚未开始',
  ACTIVE: '原活动仍在执行',
  VERIFIED: '已确认',
  UNKNOWN: '待核对',
};
const cleanup = {
  NOT_STARTED: '尚未开始',
  CLEANING: '回收中',
  VERIFIED: '已确认',
  FAILED: '清理失败',
  UNKNOWN: '待核对',
};
const integrity = {
  NOT_CHECKED: '尚未核对',
  VERIFIED: '已确认',
  CHANGED: '输入已变化',
  UNKNOWN: '待核对',
};

function checkDelay(result: { data: CodeVerification }) {
  const verification = result.data;
  if (verification.ended_at !== null) return null;
  return verification.status === 'UNKNOWN' ? 3000 : 1000;
}

function historyDelay(result: { data: { items: readonly CodeVerification[] } }) {
  const active = result.data.items.filter((item) => item.ended_at === null);
  if (!active.length) return null;
  return active.some((item) => item.status !== 'UNKNOWN') ? 1000 : 3000;
}

export function VerificationHistory({
  api,
  taskId,
  candidateId,
  currentVerificationId,
  visible,
  onSelect,
  selectedPage,
  selectPage,
}: Props) {
  const [localPage, setLocalPage] = useState(1);
  const page = selectedPage ?? localPage;
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const identity = selected ?? currentVerificationId;
  function selectRecord(id: number) {
    if (onSelect) onSelect(id);
    else setSelected(id);
  }
  const list = useCallback(
    (signal: AbortSignal) => {
      void retry;
      void currentVerificationId;
      return api.codeTaskVerifications(taskId, candidateId, page, signal);
    },
    [api, taskId, candidateId, page, currentVerificationId, retry],
  );
  const result = useSettingsRead(list, visible, '暂时无法读取开发自检历史', historyDelay);
  const pagination = result.value?.meta.pagination;
  const currentPage =
    pagination && 'page' in pagination && pagination.page === page ? pagination : null;
  const rows = currentPage ? result.value?.data.items : undefined;
  return (
    <section aria-label={'代码 #' + candidateId + ' 的开发自检'} aria-busy={result.loading}>
      <h3>开发自检记录 · 代码 #{candidateId}</h3>
      {result.loading && <p role="status">正在读取开发自检记录…</p>}
      {result.error && (
        <p role="alert" className="inline-error">
          {result.error}{' '}
          <button className="ui-button" type="button" onClick={() => setRetry((n) => n + 1)}>
            重试读取记录
          </button>
        </p>
      )}
      {!result.loading && !result.error && rows?.length === 0 && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页超出开发自检记录范围' : '当前没有开发自检记录'}
        />
      )}
      {!!rows?.length && (
        <ul aria-label="开发自检记录列表">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                className="ui-button"
                type="button"
                aria-pressed={identity === row.id}
                onClick={() => selectRecord(row.id)}
              >
                自检 #{row.id} · {states[row.status]}
              </button>{' '}
              {row.id === currentVerificationId ? '当前记录' : '历史记录'}
            </li>
          ))}
        </ul>
      )}
      {currentPage && (
        <Pagination
          value={currentPage}
          loading={result.loading}
          change={selectPage ?? setLocalPage}
        />
      )}
      {identity !== null && (
        <VerificationDetail
          key={identity}
          api={api}
          taskId={taskId}
          candidateId={candidateId}
          verificationId={identity}
          visible={visible}
        />
      )}
    </section>
  );
}

export function VerificationDetail({
  api,
  taskId,
  candidateId,
  verificationId,
  visible,
  readOnly = false,
}: Readonly<{
  api: WalleApi;
  taskId: number;
  candidateId: number | null;
  verificationId: number;
  visible: boolean;
  readOnly?: boolean;
}>) {
  const [retry, setRetry] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      const result = await api.codeTaskVerification(taskId, verificationId, signal);
      if (candidateId !== null && result.data.candidate_id !== candidateId)
        throw Error('原自检与所选代码不一致');
      return result;
    },
    [api, taskId, candidateId, verificationId, retry],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取自检详情', checkDelay);
  const verification = result.value?.data;
  return (
    <section aria-label={'自检 #' + verificationId + ' 详情'} aria-busy={result.loading}>
      <h4>自检 #{verificationId} 详情</h4>
      {result.loading && <p role="status">正在读取自检详情…</p>}
      {result.error && (
        <p role="alert" className="inline-error">
          {result.error}{' '}
          <button className="ui-button" type="button" onClick={() => setRetry((n) => n + 1)}>
            重试读取自检详情
          </button>
        </p>
      )}
      {verification && (
        <>
          {readOnly && <p className="read-status">指定自检记录，仅供查看</p>}
          <dl className="code-task-facts">
            {readOnly && (
              <>
                <dt>固定代码</dt>
                <dd>#{verification.candidate_id}</dd>
              </>
            )}
            <dt>阶段范围</dt>
            <dd>{verification.scope_stages.map((stage) => TASK_PHASE[stage]).join('、')}</dd>
            <dt>检查状态</dt>
            <dd>{states[verification.status]}</dd>
            <dt>开发交接资格</dt>
            <dd>{verification.eligible ? '当前开发自检合格' : '当前不满足开发交接条件'}</dd>
            <dt>原活动停止</dt>
            <dd>{stop[verification.stop_status]}</dd>
            <dt>原资源清理</dt>
            <dd>{cleanup[verification.cleanup_status]}</dd>
            <dt>输入完整性</dt>
            <dd>{integrity[verification.source_integrity_status]}</dd>
          </dl>
          {!!verification.ineligibility_reason_codes.length && (
            <ul aria-label="当前不合格原因">
              {verification.ineligibility_reason_codes.map((reason) => (
                <li key={reason}>{eligibility[reason]}</li>
              ))}
            </ul>
          )}
          <ul aria-label="开发自检项">
            {verification.items.map((item) => (
              <CheckItem key={item.id} item={item} api={api} taskId={taskId} visible={visible} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function CheckItem({
  item,
  api,
  taskId,
  visible,
}: Readonly<{
  item: CodeCheckItem;
  api: WalleApi;
  taskId: number;
  visible: boolean;
}>) {
  const evidence = projectCommandEvidence(item);
  const labels = {
    PROCESS_EXIT: '项目命令',
    CONTENT_INTEGRITY: '内容完整性',
    CONTROLLED_CASES: '受控用例',
  };
  return (
    <li>
      <strong>{item.check_id}</strong> {labels[item.evidence_kind]} ·{' '}
      {item.required ? '必检' : '选检'} · {itemStates[item.result]}
      {item.reason_code && ' · ' + itemReasons[item.reason_code]}
      {evidence && (
        <div>
          {evidence.exit_code === null ? '未取得退出码' : '实际退出码 ' + evidence.exit_code}
          {evidence.stdout && ' · 标准输出 ' + evidence.stdout.byte_count + ' 字节'}
          {evidence.stderr && ' · 标准错误 ' + evidence.stderr.byte_count + ' 字节'}
        </div>
      )}
      {item.evidence_kind === 'CONTROLLED_CASES' && (
        <VerificationCases api={api} taskId={taskId} item={item} visible={visible} />
      )}
      {item.reused_from_item_id !== null && <div>引用原检查项 #{item.reused_from_item_id}</div>}
    </li>
  );
}
