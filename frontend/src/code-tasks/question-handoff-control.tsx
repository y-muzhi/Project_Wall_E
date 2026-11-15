import { useCallback, useEffect, useRef, useState } from 'react';
import { decodePreparedHandoff, prepareHandoffPath } from '../api/code-task-handoff.ts';
import type { NativeQuestion } from '../api/code-task-issues.ts';
import type { QuestionEvidenceRef } from '../api/code-task-question-response.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { WalleApi } from '../api/walle.ts';
import type { DocumentHandoffLink } from '../application/router.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { EvidencePicker } from './evidence-picker.tsx';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { useSettingsRead } from './settings/read.ts';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  row: NativeQuestion;
  ready: boolean;
  visible: boolean;
  disabledReason: string | null;
  openHandoff(requirementId: number, link: DocumentHandoffLink): void;
  changed(): void;
}>;

export function QuestionHandoffControl({
  api,
  task,
  row,
  ready,
  visible,
  disabledReason,
  changed,
  openHandoff,
}: Props) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState('');
  const [refs, setRefs] = useState<QuestionEvidenceRef[]>([]);
  const [retry, setRetry] = useState(0);
  const [prepared, setPrepared] = useState<{ id: number; target_document_id: number } | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const save = (value: unknown) => {
    const result = decodePreparedHandoff(value);
    if (result.task_id !== task.id || result.question_id !== row.id)
      throw Error('原移交归属不一致。');
    setPrepared({ id: result.handoff_id, target_document_id: result.target_document_id });
    setOpen(false);
  };
  const command = useCodeTaskCommand(api, prepareHandoffPath(task.id, row.id), save, changed);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      const { data } = await api.getRequirementDetail(
        task.requirement_id,
        signal,
        false,
        task.document_id,
      );
      return data.documents.filter((item) => item.archived_at === null);
    },
    [api, retry, task.document_id, task.requirement_id],
  );
  const documents = useSettingsRead(load, visible && open, '暂时无法读取可移交文档');
  useEffect(() => {
    if (open) title.current?.focus();
  }, [open]);
  const reason = command.pending
    ? '请先核对原移交请求。'
    : !command.ready
      ? '正在核对本地原请求。'
      : disabledReason
        ? disabledReason
        : !ready ||
            task.active_session_id !== row.session_id ||
            task.control_generation !== row.control_generation ||
            !task.waiting_items.some(
              (item) => item.kind === 'QUESTION' && item.source_id === row.id,
            )
          ? '当前任务与原问题状态正在核对。'
          : null;
  const selected = documents.value?.find((item) => String(item.id) === target);
  const links =
    prepared && !row.handoffs.some((item) => item.id === prepared.id)
      ? [...row.handoffs, prepared]
      : row.handoffs;
  function navigate(item: { id: number; target_document_id: number }) {
    openHandoff(task.requirement_id, {
      documentId: item.target_document_id,
      taskId: task.id,
      handoffId: item.id,
    });
  }

  return (
    <section aria-label={'文档移交 #' + row.id}>
      <button
        type="button"
        className="ui-button"
        ref={opener}
        aria-expanded={open}
        aria-describedby={reason ? 'handoff-reason-' + row.id : undefined}
        disabled={reason !== null || command.busy}
        onClick={() => setOpen(true)}
      >
        移交文档
      </button>
      {reason && (
        <p id={'handoff-reason-' + row.id} className="field-help">
          {reason}
        </p>
      )}
      {open && (
        <form
          aria-label="准备文档移交"
          className="code-question-response"
          onSubmit={(event) => {
            event.preventDefault();
            if (!reason && selected && !documents.error && !documents.loading)
              command.submit({
                expected_state_version: task.state_version,
                target_document_id: selected.id,
                evidence_refs: refs.map((ref) => ({ kind: ref.kind, id: ref.id })),
              });
          }}
        >
          <h4 tabIndex={-1} ref={title}>
            准备文档移交
          </h4>
          {documents.loading && <p role="status">正在读取可移交文档…</p>}
          {documents.error && (
            <p role="alert">
              {documents.error}{' '}
              <button
                type="button"
                className="ui-button"
                onClick={() => setRetry((value) => value + 1)}
              >
                重新读取文档
              </button>
            </p>
          )}
          {documents.value?.length === 0 && !documents.error && !documents.loading && (
            <EmptyState icon="document" message="本需求暂无可移交文档" />
          )}
          <fieldset disabled={reason !== null || command.busy}>
            <legend>选择目标和已有证据</legend>
            <label>
              目标文档{' '}
              <select value={target} onChange={(event) => setTarget(event.target.value)}>
                <option value="">选择同需求文档</option>
                {documents.value?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <EvidencePicker value={refs} changed={setRefs} />
          </fieldset>
          <div className="code-task-toolbar">
            <button
              type="submit"
              className="ui-button primary"
              disabled={
                !selected ||
                !!documents.error ||
                documents.loading ||
                reason !== null ||
                command.busy
              }
            >
              保存移交
            </button>
            <button
              type="button"
              className="ui-button"
              disabled={command.busy}
              onClick={() => {
                setOpen(false);
                opener.current?.focus();
              }}
            >
              关闭移交表单
            </button>
          </div>
        </form>
      )}
      {links.length > 0 && (
        <ul>
          {links.map((item) => (
            <li key={item.id}>
              移交 #{item.id} · 文档 #{item.target_document_id}{' '}
              <button type="button" className="ui-button" onClick={() => navigate(item)}>
                去文档讨论
              </button>
            </li>
          ))}
        </ul>
      )}
      {command.pending && (
        <>
          <button
            type="button"
            className="ui-button"
            disabled={command.busy}
            onClick={command.lookup}
          >
            核对原移交请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={ready && !command.busy}
            settled={command.settled}
          />
        </>
      )}
      {command.busy && (
        <button type="button" className="ui-button" onClick={command.stop}>
          停止等待移交结果
        </button>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {!command.ready && command.error && (
        <button type="button" className="ui-button" onClick={command.reload}>
          重新读取原移交请求
        </button>
      )}
    </section>
  );
}
