import { useCallback, useState } from 'react';
import { createdDefect, defectPath } from '../../api/code-task-defects.ts';
import type { TestingFinding, TestingReport } from '../../api/testing-reports.ts';
import type { WalleApi } from '../../api/walle.ts';
import { useCodeTaskCommand } from '../../code-tasks/handoff-command.ts';
import { RecoveryActions } from '../../code-tasks/settings/recovery-actions.tsx';
import { Confirmation } from '../../shared/confirmation.tsx';
import { ReadState, useTestingRead } from '../plans/read.tsx';

export function FindingHandoff({
  api,
  source,
  task,
  candidate,
  finding,
  stale,
  close,
}: Readonly<{
  api: WalleApi;
  source: TestingReport['provenance'];
  task: number;
  candidate: number;
  finding: TestingFinding | null;
  stale: boolean;
  close(): void;
}>) {
  const [saved, setSaved] = useState<number | null>(null);
  const [confirmation, setConfirmation] = useState<Readonly<{
    finding: number;
    findingVersion: number;
    taskVersion: number;
  }> | null>(null);
  const load = useCallback((signal: AbortSignal) => api.codeTask(task, signal), [api, task]);
  const read = useTestingRead('finding-coding:' + task + ':' + finding?.id, finding ? load : null);
  const current = read.data?.data;
  const command = useCodeTaskCommand(
    api,
    defectPath(task),
    (data) => {
      setSaved(createdDefect(data).defect_id);
      close();
    },
    read.reload,
    '缺陷登记',
    '缺陷报告已保存。',
  );
  const version = current?.state_version;
  const block = command.pending
    ? '请先核对原缺陷请求'
    : !command.ready || command.busy
      ? '正在核对原缺陷请求'
      : stale || read.loading || read.error || !current
        ? '请先核对当前 Coding 任务'
        : current.current_candidate_id !== candidate ||
            current.document_id !== source.document_id ||
            current.design_revision_id !== source.design_revision_id ||
            current.requirement_id !== source.requirement_id
          ? '该报告的候选或固定设计已非当前来源'
          : !current.available_actions.some(
                (action) => action.action === 'REGISTER_DEFECT' && action.enabled,
              )
            ? '当前 Coding 任务状态不允许登记缺陷'
            : null;
  const ready = block === null && finding !== null && version !== undefined;
  const sameFinding =
    confirmation !== null &&
    confirmation.finding === finding?.id &&
    confirmation.findingVersion === finding.state_version;
  function prepare() {
    if (ready)
      setConfirmation({
        finding: finding.id,
        findingVersion: finding.state_version,
        taskVersion: version,
      });
  }
  function confirm() {
    if (!ready || !sameFinding || version !== confirmation.taskVersion) return;
    command.submit({
      candidate_id: candidate,
      expected_state_version: version,
      testing_finding_id: finding.id,
    });
    setConfirmation(null);
  }
  return (
    <>
      {finding && (
        <section className="testing-editor-panel" aria-label="交给 Coding">
          <h4>
            发现项 #{finding.id} · 候选 #{candidate}
          </h4>
          <ReadState
            loading={read.loading}
            error={read.error}
            stale={current !== undefined}
            retry={read.reload}
          />
          <div className="code-task-toolbar">
            <button
              className="ui-button"
              type="button"
              disabled={!ready}
              title={block ?? undefined}
              onClick={prepare}
            >
              保存到 Coding 缺陷报告
            </button>
            <button className="ui-button" type="button" onClick={close}>
              取消
            </button>
          </div>
          {block && !read.loading && !read.error && <p className="read-status">{block}</p>}
        </section>
      )}
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            className="ui-button"
            type="button"
            disabled={command.busy}
            title={command.busy ? '正在核对原缺陷请求' : undefined}
            onClick={command.lookup}
          >
            核对原缺陷请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={false}
            settled={command.settled}
          />
        </div>
      )}
      {saved !== null && (
        <div className="code-task-toolbar">
          <span>缺陷 #{saved}</span>
          <a className="ui-button" href={'/code-tasks/' + task + '?tab=testing'}>
            打开 Coding 任务
          </a>
        </div>
      )}
      <Confirmation
        open={sameFinding}
        busy={command.busy}
        title="交给 Coding"
        description={
          '将发现项 #' + finding?.id + ' 按原归因保存到候选 #' + candidate + ' 的缺陷报告。'
        }
        confirmLabel="确认登记"
        confirmDisabled={!ready || version !== confirmation?.taskVersion}
        confirm={confirm}
        cancel={() => setConfirmation(null)}
      />
    </>
  );
}
