import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { NativeQuestion } from '../api/code-task-issues.ts';
import {
  answerActions,
  decodeQuestionResponseInput,
  factKinds,
  questionResponsePath,
} from '../api/code-task-question-response.ts';
import type {
  NativeQuestionAnswer,
  QuestionBasisRef,
  QuestionOperation,
} from '../api/code-task-question-response.ts';
import type { WalleApi } from '../api/walle.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import { originalFrozen, verifiedFrozen } from './command-recovery-model.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { EvidencePicker } from './evidence-picker.tsx';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { useSettingsRead } from './settings/read.ts';

const actions = {
  USE_FIXED_BASIS: '按原设计处理',
  CITE_FIXED_BASIS: '引用固定依据',
  CLARIFY_FACTS: '补充事实',
};
const facts = { OBSERVATION: '现象', REPRODUCTION: '复现结果', EXISTING_BEHAVIOR: '既有行为' };
type Fact = NonNullable<NativeQuestionAnswer['clarification']>;
type Draft = Readonly<{
  action: NativeQuestionAnswer['action'] | '';
  cite: QuestionBasisRef[];
  factBasis: QuestionBasisRef[];
  fact: Fact;
}>;
type FixedRevision = Readonly<{ document_id: number; revision_id: number }>;

function newDraft(): Draft {
  return {
    action: '',
    cite: [],
    factBasis: [],
    fact: { kind: 'OBSERVATION', text: '', option_indices: [], evidence_refs: [] },
  };
}
function restoredDraft(answer: NativeQuestionAnswer): Draft {
  const draft = newDraft();
  return {
    action: answer.action,
    cite: answer.action === 'CITE_FIXED_BASIS' ? [...answer.basis_refs] : [],
    factBasis: answer.action === 'CLARIFY_FACTS' ? [...answer.basis_refs] : [],
    fact: answer.clarification ?? draft.fact,
  };
}

function answerProblems(details: JsonObject | null, code: string) {
  const fields = details?.field_errors;
  const problems = new Map<number, string>();
  if (!Array.isArray(fields)) return problems;
  for (const entry of fields) {
    if (
      !entry ||
      typeof entry !== 'object' ||
      Array.isArray(entry) ||
      typeof entry.field !== 'string'
    )
      continue;
    const match = /^answers\[(\d+)\]/.exec(entry.field);
    if (match) {
      problems.set(
        Number(match[1]),
        code === 'BASIS_REF_INVALID'
          ? '请核对本题引用的固定原文。'
          : '请核对本题答复、相关选项或证据。',
      );
    }
  }
  return problems;
}

function answer(draft: Draft, index: number): NativeQuestionAnswer | null {
  if (!draft.action) return null;
  if (draft.action === 'USE_FIXED_BASIS')
    return { index, action: draft.action, basis_refs: [], clarification: null };
  if (draft.action === 'CITE_FIXED_BASIS')
    return draft.cite.length
      ? { index, action: draft.action, basis_refs: draft.cite, clarification: null }
      : null;
  const fact = draft.fact;
  const content = fact.text.replace(/\r\n?/g, '\n');
  if (
    !/[^\p{White_Space}]/u.test(content) ||
    [...content].length > 2000 ||
    (fact.kind === 'EXISTING_BEHAVIOR' && !draft.factBasis.length)
  )
    return null;
  return {
    index,
    action: draft.action,
    basis_refs: draft.factBasis,
    clarification: {
      ...fact,
      text: content,
      option_indices: [...fact.option_indices].sort((a, b) => a - b),
    },
  };
}
function errorText(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '暂时无法核对原答复。';
}
function terminal(status: QuestionOperation['status']) {
  return status === 'FAILED' || status === 'SUCCEEDED' || status === 'CANCELLED';
}
function operationDelay(value: QuestionOperation) {
  return terminal(value.status) ? null : value.status === 'UNKNOWN' ? 5000 : 1500;
}
function progress(operation: QuestionOperation) {
  switch (operation.status) {
    case 'PENDING':
      return '答复请求已接收，等待原生确认。';
    case 'RUNNING':
      return '正在发送并核对原答复。';
    case 'UNKNOWN':
      return '原答复的处理结果待核对。';
    case 'SUCCEEDED':
      return '原答复已由执行器确认。';
    case 'CANCELLED':
      return '任务停止时取消了尚未发送的答复。';
    case 'FAILED':
      return operation.failure_code === 'QUESTION_NOT_OPEN'
        ? '执行器已无法核实原问题，答复未发送。'
        : '原会话暂时无法核对，答复未发送。';
  }
}

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  row: NativeQuestion;
  visible: boolean;
  ready: boolean;
  disabledReason: string | null;
  listUnavailable: boolean;
  changed(): void;
}>;

export function QuestionResponseControl({
  api,
  task,
  row,
  visible,
  ready,
  disabledReason,
  listUnavailable,
  changed,
}: Props) {
  const taskId = task.id,
    questionId = row.id,
    sessionId = row.session_id;
  const path = questionResponsePath(taskId, questionId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async (original, link, signal) => {
          if (original.path !== path || link.task_id !== taskId)
            throw Error('Original answer owner differs');
          const { data } = await api.codeTaskOperation(taskId, link.operation_id, signal);
          if (
            data.operation_type !== 'ANSWER_QUESTION' ||
            data.fixed_input.question_id !== questionId ||
            data.session_id !== sessionId ||
            data.idempotency_key !== original.key
          )
            throw Error('Original answer operation differs');
          return {
            operation_id: data.id,
            task_id: taskId,
            testing_task_id: null,
            status: data.status,
          };
        },
      ),
    [api, path, taskId, questionId, sessionId],
  );
  const [drafts, setDrafts] = useState(() => row.questions.map(newDraft));
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [accepted, setAccepted] = useState<number | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [canStopWaiting, setCanStopWaiting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState(() => answerProblems(null, ''));
  const [retry, setRetry] = useState(0);
  const opener = useRef<HTMLButtonElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const alive = useRef(true);
  const working = useRef(false);
  const sending = useRef<AbortController | null>(null);
  const finished = useRef<number | null>(null);

  const readPending = useCallback(async () => {
    const rows = await recovery.store.list();
    if (!alive.current) return;
    const original = rows.find((item) => item.path === path) ?? null;
    setPending(original);
    if (original?.operation_id != null) setAccepted(original.operation_id);
    setLedgerReady(true);
  }, [recovery, path]);

  useEffect(() => {
    alive.current = true;
    void readPending().catch((failure) => {
      if (alive.current) setError(errorText(failure));
    });
    return () => {
      alive.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [readPending, recovery]);
  useEffect(() => {
    if (open) title.current?.focus();
  }, [open]);
  const operationId = pending?.operation_id ?? accepted;
  const loadOperation = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      if (operationId === null) throw Error('Original answer not selected');
      const { data } = await api.codeTaskOperation(taskId, operationId, signal);
      if (
        data.operation_type !== 'ANSWER_QUESTION' ||
        data.fixed_input.question_id !== questionId ||
        data.session_id !== sessionId
      )
        throw Error('Original answer operation differs');
      return data;
    },
    [api, operationId, questionId, sessionId, taskId, retry],
  );
  const operationRead = useSettingsRead(
    loadOperation,
    visible && operationId !== null,
    '暂时无法读取原答复操作',
    operationDelay,
  );
  const operation = operationRead.value?.id === operationId ? operationRead.value : null;

  useEffect(() => {
    if (!operation || !terminal(operation.status) || finished.current === operation.id) return;
    const controller = new AbortController();
    async function finish() {
      if (!operation) return;
      try {
        if (pending?.operation_id === operation.id && pending.status === 'ACCEPTED') {
          await recovery.reconcileOperation(pending.key, controller.signal);
          if (!controller.signal.aborted) await readPending();
        }
        if (controller.signal.aborted) return;
        finished.current = operation.id;
        changed();
      } catch (failure) {
        if (!controller.signal.aborted) setError(errorText(failure));
      }
    }
    void finish();
    return () => controller.abort();
  }, [operation, pending, recovery, readPending, changed, retry]);

  async function apply(result: RecoveryLookup) {
    if (!alive.current) return;
    const id = result.original_receipt?.operation_id ?? result.local?.operation_id;
    const outcome = result.original_receipt?.original_outcome;
    if (id != null) {
      setAccepted(id);
      setNotice('答复请求已接收，等待原生确认。');
      changed();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
      setProblems(answerProblems(outcome.error.details, outcome.error.code));
      if (outcome.error.code === 'VERSION_CONFLICT') changed();
    } else setNotice('原答复请求结果待核对。');
    await readPending();
  }

  async function run(action: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError(null);
    setProblems(new Map());
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      if (alive.current) {
        setError(errorText(failure));
        if (failure instanceof ApiRejected)
          setProblems(answerProblems(failure.details, failure.code));
        await readPending().catch(() => undefined);
        if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
      }
    } finally {
      working.current = false;
      if (alive.current) setBusy(false);
    }
  }

  const available =
    row.available_actions.find((item) => item.action === 'ANSWER_QUESTION')?.enabled === true;
  const matchesTaskWait =
    task.active_session_id === sessionId &&
    task.waiting_items.some((item) => item.kind === 'QUESTION' && item.source_id === questionId);
  const reason = pending
    ? '请先核对原答复请求'
    : !ledgerReady
      ? '正在核对本地原请求'
      : !ready
        ? '当前任务状态正在核对'
        : !available
          ? (disabledReason ?? '当前原问题暂不可答复')
          : !matchesTaskWait
            ? '正在核对任务与原问题的等待状态'
            : null;
  const values = drafts.map(answer);
  const complete = values.length === row.questions.length && values.every((item) => item !== null);
  const bases: FixedRevision[] = [
    { document_id: task.document_id, revision_id: task.design_revision_id },
    ...task.material_refs,
  ];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason || !complete || working.current) return;
    void run(async () => {
      const staged = await recovery.stageIntent(path, {
        expected_state_version: task.state_version,
        session_id: sessionId,
        answers: values.map(({ index, action, basis_refs, clarification }) => ({
          index,
          action,
          basis_refs: [...basis_refs],
          clarification:
            clarification === null
              ? null
              : {
                  ...clarification,
                  option_indices: [...clarification.option_indices],
                  evidence_refs: [...clarification.evidence_refs],
                },
        })),
      });
      if (!alive.current) return;
      if (staged.kind !== 'PREPARED') {
        setNotice('已有原答复请求，请先核对。');
        await readPending();
        return;
      }
      setPending(staged.record);
      const controller = new AbortController();
      sending.current = controller;
      setCanStopWaiting(true);
      try {
        await apply(
          await recovery.send(staged.record.key, staged.record.record_revision, controller.signal),
        );
      } finally {
        sending.current = null;
        if (alive.current) setCanStopWaiting(false);
      }
    });
  }

  async function openOriginal(original: PendingSummary) {
    const value = await recovery.store.detail(original.key);
    const { frozen } = await verifiedFrozen(
      originalFrozen(value),
      recovery.store.origin,
      recovery.store.scope,
    );
    const input = decodeQuestionResponseInput(JSON.parse(frozen.body_json));
    if (
      frozen.path !== path ||
      frozen.key !== original.key ||
      input.session_id !== sessionId ||
      input.answers.length !== row.questions.length
    )
      throw Error('Original question response input differs');
    if (!alive.current) return;
    setDrafts(input.answers.map(restoredDraft));
    setOpen(true);
  }

  function changeDraft(index: number, next: Draft) {
    setDrafts((previous) => previous.map((draft, number) => (index === number ? next : draft)));
    if (problems.has(index)) {
      const remaining = new Map(problems);
      remaining.delete(index);
      setProblems(remaining);
    }
  }
  const reasonId = 'answer-reason-' + questionId;
  return (
    <section aria-label={'答复原生问题 #' + questionId}>
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          ref={opener}
          aria-expanded={open}
          aria-describedby={reason ? reasonId : undefined}
          disabled={busy || reason !== null}
          onClick={() => setOpen(true)}
        >
          答复原问题
        </button>
        {pending && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原答复请求
          </button>
        )}
        {pending && !open && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(() => openOriginal(pending))}
          >
            查看原答复内容
          </button>
        )}
        {canStopWaiting && (
          <button type="button" className="ui-button" onClick={() => sending.current?.abort()}>
            停止等待答复结果
          </button>
        )}
        {operationId !== null && (
          <button
            type="button"
            className="ui-button"
            disabled={operationRead.loading}
            onClick={() => setRetry((value) => value + 1)}
          >
            核对答复操作 #{operationId}
          </button>
        )}
        {!ledgerReady && error && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(readPending)}
          >
            重新读取答复请求记录
          </button>
        )}
      </div>
      {reason && (
        <p id={reasonId} className="field-help">
          {reason}
        </p>
      )}
      {open && (
        <form
          className="code-question-response"
          aria-label="逐题答复"
          onSubmit={submit}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && event.nativeEvent.isComposing) event.preventDefault();
          }}
        >
          <h4 tabIndex={-1} ref={title}>
            {pending ? '原答复内容' : '逐题答复'}
          </h4>
          {row.questions.map((question, index) => (
            <AnswerFields
              key={question.index}
              api={api}
              bases={bases}
              visible={visible}
              question={question}
              draft={drafts[index]!}
              problem={problems.get(index)}
              disabled={busy || reason !== null}
              changed={(next) => changeDraft(index, next)}
            />
          ))}
          {!complete && <p className="field-help">请按原题顺序完成所有答复。</p>}
          <div className="code-task-toolbar">
            <button
              type="submit"
              className="ui-button primary"
              disabled={busy || reason !== null || !complete}
            >
              提交答复
            </button>
            <button
              type="button"
              className="ui-button"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                if (!opener.current?.disabled) opener.current?.focus();
              }}
            >
              关闭答复
            </button>
          </div>
        </form>
      )}
      {operation ? (
        <p role="status">
          {operation.status === 'SUCCEEDED' && listUnavailable
            ? '答复结果已确认，列表暂不可读。'
            : progress(operation)}
        </p>
      ) : (
        notice && <p role="status">{notice}</p>
      )}
      {(error || operationRead.error) && (
        <p role="alert" className="inline-error">
          {error ?? operationRead.error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={false}
          settled={(_, result, detail) => {
            if (result) void run(() => apply(result));
            else
              void run(async () => {
                await readPending();
                setNotice(detail);
              });
          }}
        />
      )}
    </section>
  );
}

function AnswerFields({
  api,
  bases,
  visible,
  question,
  draft,
  problem,
  disabled,
  changed,
}: Readonly<{
  api: WalleApi;
  bases: FixedRevision[];
  visible: boolean;
  question: NativeQuestion['questions'][number];
  draft: Draft;
  problem: string | undefined;
  disabled: boolean;
  changed(next: Draft): void;
}>) {
  const fact = draft.fact;
  const changeFact = (next: Partial<Fact>) => changed({ ...draft, fact: { ...fact, ...next } });
  return (
    <fieldset disabled={disabled}>
      <legend>
        第 {question.index + 1} 题 · {question.header}
      </legend>
      {problem && <p className="inline-error">{problem}</p>}
      <label>
        答复方式{' '}
        <select
          value={draft.action}
          onChange={(event) =>
            changed({
              ...draft,
              action: answerActions.find((value) => value === event.target.value) ?? '',
            })
          }
        >
          <option value="">请选择</option>
          {answerActions.map((value) => (
            <option
              key={value}
              value={value}
              disabled={value === 'CITE_FIXED_BASIS' && !bases.length}
            >
              {actions[value]}
            </option>
          ))}
        </select>
      </label>
      {draft.action === 'CITE_FIXED_BASIS' && (
        <BasisPicker
          api={api}
          bases={bases}
          visible={visible}
          value={draft.cite}
          changed={(cite) => changed({ ...draft, cite })}
        />
      )}
      {draft.action === 'CLARIFY_FACTS' && (
        <>
          <p>仅补充事实，新规则请转文档讨论。程序不会据此更改设计或授权。</p>
          <label>
            事实类型{' '}
            <select
              value={fact.kind}
              onChange={(event) => {
                const kind = factKinds.find((value) => value === event.target.value);
                if (kind) changeFact({ kind });
              }}
            >
              {factKinds.map((kind) => (
                <option key={kind} value={kind}>
                  {facts[kind]}
                </option>
              ))}
            </select>
          </label>
          <label>
            事实说明
            <textarea
              rows={3}
              value={fact.text}
              onChange={(event) => changeFact({ text: event.target.value })}
            />
          </label>
          <p className="field-help">{[...fact.text.replace(/\r\n?/g, '\n')].length} / 2000</p>
          {question.options.length > 0 && (
            <fieldset>
              <legend>相关原题选项</legend>
              {question.options.map((option, index) => (
                <label key={index}>
                  <input
                    type="checkbox"
                    checked={fact.option_indices.includes(index)}
                    onChange={(event) => {
                      const selected = fact.option_indices.filter((item) => item !== index);
                      changeFact({
                        option_indices: event.target.checked
                          ? question.multiple
                            ? [...selected, index]
                            : [index]
                          : selected,
                      });
                    }}
                  />
                  {option.label}
                </label>
              ))}
            </fieldset>
          )}
          <EvidencePicker
            value={fact.evidence_refs}
            changed={(evidence_refs) => changeFact({ evidence_refs })}
          />
          <BasisPicker
            api={api}
            bases={bases}
            visible={visible}
            value={draft.factBasis}
            changed={(factBasis) => changed({ ...draft, factBasis })}
          />
        </>
      )}
    </fieldset>
  );
}

export function BasisPicker({
  api,
  bases,
  visible,
  value,
  changed,
}: Readonly<{
  api: WalleApi;
  bases: FixedRevision[];
  visible: boolean;
  value: QuestionBasisRef[];
  changed(value: QuestionBasisRef[]): void;
}>) {
  const [revision, setRevision] = useState('');
  const [selection, setSelection] = useState('');
  const [retry, setRetry] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const selected = bases.find((item) => String(item.revision_id) === revision);
  const id = selected?.revision_id;
  const owner = selected?.document_id;
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      if (id === undefined || owner === undefined) throw Error('No fixed revision selected');
      const result = await api.getRevision(id, signal);
      if (result.data.document_id !== owner) throw Error('Fixed revision owner differs');
      return result.data;
    },
    [api, id, owner, retry],
  );
  const view = useSettingsRead(load, visible && id !== undefined, '暂时无法读取固定原文');
  const content = view.value?.id === id ? view.value?.markdown_content : null;

  function readSelection() {
    const source = area.current;
    if (source && content != null) {
      setSelection(content.slice(source.selectionStart, source.selectionEnd));
    }
  }

  return (
    <div>
      <div className="code-task-toolbar">
        <label>
          固定版本{' '}
          <select
            value={revision}
            onChange={(event) => {
              setRevision(event.target.value);
              setSelection('');
            }}
          >
            <option value="">选择固定版本</option>
            {bases.map((item) => (
              <option key={item.revision_id} value={item.revision_id}>
                文档 #{item.document_id} · 版本 #{item.revision_id}
              </option>
            ))}
          </select>
        </label>
      </div>
      {view.loading && selected && <p role="status">正在读取固定原文…</p>}
      {view.error && (
        <p role="alert">
          {view.error}{' '}
          <button
            type="button"
            className="ui-button"
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取原文
          </button>
        </p>
      )}
      {content != null && selected && (
        <div>
          <label>
            固定原文
            <textarea
              rows={4}
              readOnly
              ref={area}
              value={content}
              onSelect={readSelection}
              onKeyUp={readSelection}
              onPointerUp={readSelection}
            />
          </label>
          <button
            type="button"
            className="ui-button"
            disabled={!/[^\p{White_Space}]/u.test(selection)}
            onClick={() => {
              changed([...value, { ...selected, quote: selection }]);
              setSelection('');
              area.current?.focus();
            }}
          >
            引用选中原文
          </button>
        </div>
      )}
      {value.length > 0 && (
        <ul>
          {value.map((ref, index) => (
            <li key={index}>
              文档 #{ref.document_id} · 固定版本 #{ref.revision_id}
              <blockquote>{ref.quote}</blockquote>
              <button
                type="button"
                className="ui-button"
                onClick={() => changed(value.filter((_, i) => i !== index))}
              >
                移除引用
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
