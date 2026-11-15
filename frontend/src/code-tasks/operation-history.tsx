import { useCallback, useEffect, useRef, useState } from 'react';
import type { WalleApi } from '../api/walle.ts';
import type { CodeTaskOperation } from '../api/code-task-operations.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { useSettingsRead } from './settings/read.ts';

const names = {
  START: '开始任务',
  RESUME: '继续任务',
  TERMINATE: '停止任务',
  ANSWER_QUESTION: '答复原问题',
  DECIDE_PERMISSION: '处理原生权限',
  PREPARE_HANDOFF: '准备文档移交',
  APPLY_CONFIGURATION: '应用配置与授权',
  CAPTURE_AND_CHECK: '固定代码并自检',
  VERIFY_CANDIDATE: '重新自检',
  HANDOFF_ROLE: '角色交接',
  SUBMIT_FOR_TESTING: '发布独立测试候选',
  LINK_TEST_REPORT: '关联独立测试报告',
  REPAIR: '按缺陷发起修复',
  PREPARE_DELIVERY: '准备完整目标预览',
  DELIVER: '接收代码并登记交付',
  RECONCILE: '核对原操作',
};
const statuses = {
  PENDING: '等待处理',
  RUNNING: '正在处理',
  SUCCEEDED: '已确认',
  FAILED: '失败',
  UNKNOWN: '结果待核对',
  CANCELLED: '已取消',
};
const stepNames = {
  RESTORE_WORKSPACE: '准备工作区',
  PREPARE_BASIS: '核对固定依据',
  CHECK_CONDITIONS: '检查执行条件',
  START_INSTANCE: '启动执行实例',
  CREATE_SESSION: '建立原会话',
  SEND_INITIAL: '核对首条执行消息',
  RECONCILE: '核对原操作',
  CONTINUE_OR_OBSERVE: '核对继续消息',
  READ_NATIVE: '核对原生请求',
  SEND_RESPONSE: '发送原答复',
  VALIDATE: '核对原问题与目标文档',
  SAVE_FACT: '保存移交记录',
  CONFIRM_NATIVE: '确认原生处理',
  BLOCK_NEW: '封闭新执行',
  QUIESCE_IF_REQUIRED: '核对旧执行范围',
  APPLY_PAIR: '准备配置与授权',
  VERIFY_EFFECTIVE: '核对实际生效',
  REVOKE_GATEWAY: '关闭模型入口',
  ABORT_IF_APPLICABLE: '请求取消原会话',
  STOP_OWNED_ACTIVITY: '核对原活动停止',
  RECONCILE_WRITES: '核对原写入',
  CLEANUP: '回收执行资源',
  QUIESCE: '核对写入已停止',
  REVOKE: '退役原会话并封闭写入',
  SEND_HANDOFF: '核对下一角色已接收',
  QUERY: '读取原投递事实',
  COMPARE: '核对原会话和消息',
  RECORD: '记录实际核对结果',
  CAPTURE: '固定代码内容',
  PUBLISH: '保存固定代码',
  RESTORE_CHECK_COPY: '准备固定检查副本',
  RESTORE_SOURCE: '核对原候选代码',
  SEND_REPAIR: '核对修复消息',
  OBSERVE: '观察修复执行',
  CAPTURE_RESULT: '固定修复候选',
  VALIDATE_REPORT: '复核原独立报告',
  READ_TARGET: '读取原目标分支',
  SEAL_TARGET: '固定原目标完整树',
  SAVE_PLAN: '保存交付预览',
  FIX_COMMIT_INPUT: '固定提交内容',
  BUILD_OBJECTS: '构造提交对象',
  SAVE_PLANNED_COMMIT: '保存计划提交',
  PREPARE_REF: '准备目标引用',
  VERIFY_LOCKED_TARGET: '核对持锁目标',
  DISPATCH_COMMIT_ONCE: '派发原引用更新',
  FINALIZE_OWNED_RUNTIME: '收尾原活动',
  CHECK: '执行开发自检',
} as const;

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  visible: boolean;
  selected: number | null;
  selectOperation(id: number | null): void;
  restoreSourceFocus(): boolean;
}>;

export function TaskOperationHistory({
  api,
  taskId,
  visible,
  selected,
  selectOperation,
  restoreSourceFocus,
}: Props) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const opener = useRef<HTMLButtonElement>(null);
  const detailButton = useRef<HTMLButtonElement>(null);
  const detailTitle = useRef<HTMLHeadingElement>(null);
  const list = useCallback(
    (signal: AbortSignal) => {
      void retry;
      return api.codeTaskOperations(taskId, page, signal);
    },
    [api, taskId, page, retry],
  );
  const detail = useCallback(
    (signal: AbortSignal) => {
      void detailRetry;
      if (selected === null) throw Error('No original Coding operation selected');
      return api.codeTaskOperation(taskId, selected, signal);
    },
    [api, taskId, selected, detailRetry],
  );
  const history = useSettingsRead(list, visible && open, '暂时无法读取任务操作历史');
  const original = useSettingsRead(detail, visible && selected !== null, '暂时无法读取原操作详情');
  const pagination = history.value?.meta.pagination;
  const currentPage =
    pagination && 'page' in pagination && pagination.page === page ? pagination : null;
  const rows = currentPage ? history.value?.data.items : undefined;
  const record = original.value?.data.id === selected ? original.value.data : null;

  useEffect(() => {
    if (selected !== null) detailTitle.current?.focus();
  }, [selected]);

  function closeDetail() {
    selectOperation(null);
    if (restoreSourceFocus()) return;
    if (detailButton.current?.isConnected) detailButton.current.focus();
    else opener.current?.focus();
  }

  function changePage(next: number) {
    selectOperation(null);
    setPage(next);
  }

  function toggleHistory() {
    setOpen(!open);
  }

  return (
    <section className="code-task-controls" aria-label="任务操作历史">
      <div className="code-task-toolbar">
        <button
          ref={opener}
          type="button"
          className="ui-button"
          aria-expanded={open}
          onClick={toggleHistory}
        >
          操作历史
        </button>
        {open && (
          <button
            type="button"
            className="ui-button"
            disabled={history.loading}
            onClick={() => setRetry((value) => value + 1)}
          >
            刷新操作历史
          </button>
        )}
      </div>
      {open && (
        <>
          {history.loading && <p role="status">正在读取操作历史…</p>}
          {history.error && (
            <p role="alert" className="inline-error">
              {history.error}
            </p>
          )}
          {rows && !history.loading && !history.error && rows.length === 0 && (
            <EmptyState
              icon="outline"
              message={currentPage?.total ? '该页没有操作记录' : '任务尚无操作记录'}
            />
          )}
          {rows && rows.length > 0 && (
            <ul aria-label="操作记录">
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="ui-button"
                    aria-expanded={selected === row.id}
                    onClick={(event) => {
                      detailButton.current = event.currentTarget;
                      selectOperation(row.id);
                    }}
                  >
                    查看{names[row.operation_type]}操作 #{row.id}
                  </button>{' '}
                  {statuses[row.status]}
                </li>
              ))}
            </ul>
          )}
          {currentPage && (
            <Pagination
              value={currentPage}
              loading={history.loading}
              change={changePage}
              compactSingle
              showLoadingStatus={false}
            />
          )}
        </>
      )}
      {selected !== null && (
        <section aria-label={'原操作 #' + selected} aria-busy={original.loading}>
          <div className="code-task-toolbar">
            <h3 ref={detailTitle} tabIndex={-1}>
              原操作 #{selected}
            </h3>
            <button type="button" className="ui-button" onClick={closeDetail}>
              关闭操作详情
            </button>
          </div>
          {original.loading && <p role="status">正在读取原操作…</p>}
          {original.error && (
            <p role="alert" className="inline-error">
              {original.error}{' '}
              <button
                type="button"
                className="ui-button"
                onClick={() => setDetailRetry((value) => value + 1)}
              >
                重试操作详情
              </button>
            </p>
          )}
          {record && <OperationDetails record={record} />}
        </section>
      )}
    </section>
  );
}

function OperationDetails({ record }: Readonly<{ record: CodeTaskOperation }>) {
  return (
    <>
      <p>
        {names[record.operation_type]} · {statuses[record.status]}
      </p>
      <ol>
        {record.steps.map((step) => (
          <li key={step.step_no}>
            {record.operation_type === 'SUBMIT_FOR_TESTING'
              ? step.step_type === 'VALIDATE'
                ? '核对发布资格'
                : '保存候选发布'
              : stepNames[step.step_type]}{' '}
            · {statuses[step.status]}
          </li>
        ))}
      </ol>
    </>
  );
}
