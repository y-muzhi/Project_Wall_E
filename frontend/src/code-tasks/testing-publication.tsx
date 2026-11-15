import { useState } from 'react';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { publicationPath } from '../api/code-task-publication.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { CreateTestingFromCandidate } from './create-testing.tsx';
import { TestingReportLink } from './testing-report-link.tsx';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Props = Readonly<{ api: WalleApi; task: CodeTaskView; ready: boolean; changed(): void }>;
type Intent = Readonly<{
  candidate_id: number;
  verification_id: number;
  expected_state_version: number;
}>;

const reasons: Partial<
  Record<NonNullable<CodeTaskView['available_actions'][number]['reason_code']>, string>
> = {
  INVALID_STATE: '当前状态不能发布测试候选',
  VERIFICATION_STAGE_NOT_READY: '须完成两次角色交接及联调自检',
  CHECK_CONFIGURATION_INVALID: '当前联调自检尚未满足发布条件',
  CONFIG_NOT_READY: '当前检查资源尚未就绪',
  TEST_SOURCE_MISMATCH: '候选或自检已发生变化',
  OPERATION_CONFLICT: '原活动仍需完成或核对',
};

export function TestingPublication({ api, task, ready, changed }: Props) {
  const [confirm, setConfirm] = useState<Intent | null>(null);
  const command = useCodeTaskCommand(
    api,
    publicationPath(task.id),
    () => undefined,
    changed,
    '原发布',
    '候选已发布供独立测试。',
  );
  const action = task.available_actions.find((item) => item.action === 'SUBMIT_FOR_TESTING');
  const published = task.status === 'AWAITING_TESTING' || task.status === 'AWAITING_ACCEPTANCE';
  const candidate = task.current_candidate_id;
  const verification = task.current_refs.verification_id;
  const allowed = ready && action?.enabled && candidate !== null && verification !== null;
  const confirmationCurrent = Boolean(
    allowed &&
    !command.pending &&
    confirm &&
    confirm.candidate_id === candidate &&
    confirm.verification_id === verification &&
    confirm.expected_state_version === task.state_version,
  );
  const reason = !ready
    ? '正在核对当前任务状态'
    : action?.reason_code
      ? (reasons[action.reason_code] ?? '当前不能发布测试候选')
      : !command.ready
        ? '正在读取原发布请求'
        : command.pending
          ? '请先核对原发布请求'
          : null;

  function choose() {
    if (!allowed || candidate === null || verification === null) return;
    setConfirm({
      candidate_id: candidate,
      verification_id: verification,
      expected_state_version: task.state_version,
    });
  }

  function submit() {
    if (confirmationCurrent && confirm) {
      setConfirm(null);
      command.submit(confirm);
    }
  }

  return (
    <section className="code-task-result" aria-label="独立测试">
      <h2>独立测试</h2>
      {published ? (
        <p>代码 #{candidate} 已发布供独立测试。</p>
      ) : (
        <div className="code-task-toolbar">
          <button
            className="ui-button"
            type="button"
            onClick={choose}
            disabled={!allowed || command.busy || !command.ready || command.pending !== null}
            title={reason ?? undefined}
          >
            {command.busy ? '正在核对原发布' : '发布供独立测试'}
          </button>
          {reason && <span>{reason}</span>}
        </div>
      )}
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.busy && (
        <button type="button" className="ui-button" onClick={command.stop}>
          停止等待
        </button>
      )}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            type="button"
            className="ui-button"
            onClick={command.lookup}
            disabled={command.busy}
          >
            核对原发布请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={Boolean(allowed)}
            settled={command.settled}
          />
        </div>
      )}
      {published && (
        <CreateTestingFromCandidate
          key={'create:' + candidate}
          api={api}
          task={task}
          ready={ready}
        />
      )}
      <TestingReportLink
        key={'report:' + candidate}
        api={api}
        task={task}
        ready={ready}
        changed={changed}
      />
      <Confirmation
        open={confirm !== null}
        busy={command.busy}
        title="发布供独立测试"
        description={
          confirm
            ? '发布代码 #' +
              confirm.candidate_id +
              ' 及联调自检 #' +
              confirm.verification_id +
              '。独立测试需另行创建任务。'
            : '发布当前固定联调候选。'
        }
        confirmLabel="确认发布"
        confirmDisabled={!confirmationCurrent}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
