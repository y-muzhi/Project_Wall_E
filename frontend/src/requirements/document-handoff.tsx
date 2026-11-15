import { useCallback, useState, useSyncExternalStore } from 'react';
import { linkHandoffPath } from '../api/code-task-handoff.ts';
import type { HandoffView } from '../api/code-task-handoff.ts';
import type { WalleApi } from '../api/walle.ts';
import type { DocumentHandoffLink } from '../application/router.ts';
import { evidenceLabel } from '../code-tasks/evidence-picker.tsx';
import { useCodeTaskCommand } from '../code-tasks/handoff-command.ts';
import { RecoveryActions } from '../code-tasks/settings/recovery-actions.tsx';
import { useSettingsRead } from '../code-tasks/settings/read.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import type { RequirementDetailOwner } from './detail-owner.ts';

const eventNames = {
  PREPARED: '已准备移交',
  DISCUSSION_LINKED: '已关联讨论',
  REVISION_LINKED: '已关联版本',
  ABANDONED: '已明确放弃',
};
const fieldNames = {
  guide_run_id: '已保存讨论运行编号',
  message_id: '已保存消息编号',
  revision_id: '已保存版本编号',
};
const inputIds = ['guide_run_id', 'message_id', 'revision_id'] as const;
const blankRefs = { guide_run_id: '', message_id: '', revision_id: '' };

type Props = Readonly<{
  api: WalleApi;
  owner: RequirementDetailOwner;
  link: DocumentHandoffLink;
  active: boolean;
  blocked: boolean;
}>;

function draftMarker(link: DocumentHandoffLink, requirement: number) {
  return [
    'walle:v2:handoff-insert',
    location.origin,
    requirement,
    link.documentId,
    link.taskId,
    link.handoffId,
  ].join(':');
}

function wasInserted(marker: string) {
  try {
    return sessionStorage.getItem(marker) === '1';
  } catch {
    return false;
  }
}

function plainText(data: HandoffView) {
  const title = '代码任务 #' + data.task_id + ' · 文档移交 #' + data.id;
  return {
    title,
    text: [
      title,
      '来源问题 #' + data.question_id,
      ...data.source_question.questions.map((item) => item.header + '\n' + item.text),
      ...(data.evidence_refs.length
        ? ['相关代码证据 ' + data.evidence_refs.map(evidenceLabel).join('、')]
        : []),
    ].join('\n'),
  };
}

function positiveText(value: string) {
  if (!/^[1-9][0-9]*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

export function DocumentHandoff({ api, owner, link, active, blocked }: Props) {
  const composer = owner.regions!.conversation.composer;
  const state = useSyncExternalStore(composer.subscribe, composer.getSnapshot);
  const requirement = state.detail.requirement.id;
  const document = state.detail.selected_document_id;
  const marker = draftMarker(link, requirement);
  const [inserted, setInserted] = useState(() => wasInserted(marker));
  const [insertError, setInsertError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const refresh = useCallback(() => setRetry((value) => value + 1), []);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      const [handoff, task] = await Promise.all([
        api.codeHandoff(link.taskId, link.handoffId, page, signal),
        api.codeTask(link.taskId, signal),
      ]);
      if (
        handoff.data.target_document_id !== link.documentId ||
        task.data.requirement_id !== requirement
      )
        throw Error('Original document handoff owner differs');
      return { handoff, task: task.data, page };
    },
    [api, link.documentId, link.handoffId, link.taskId, page, requirement, retry],
  );
  const ownsDocument = document === link.documentId && state.detail.current?.id === link.documentId;
  const read = useSettingsRead(load, active && ownsDocument, '原移交无法在此文档核实。');
  const actual = read.value?.page === page ? read.value : null;
  const command = useCodeTaskCommand(
    api,
    linkHandoffPath(link.taskId, link.handoffId),
    () => setRefs(blankRefs),
    refresh,
  );
  const [kind, setKind] = useState<'DISCUSSION_LINKED' | 'REVISION_LINKED'>('DISCUSSION_LINKED');
  const [refs, setRefs] = useState(blankRefs);
  const status = actual?.task.status;
  const ended = status === 'TERMINATED';
  const linkBlocked =
    !actual ||
    read.loading ||
    !!read.error ||
    ended ||
    status === 'STOPPING' ||
    actual.task.active_operations.length !== 0 ||
    !command.ready ||
    command.busy ||
    command.pending !== null;
  const referenceValues = {
    guide_run_id: positiveText(refs.guide_run_id),
    message_id: positiveText(refs.message_id),
    revision_id: positiveText(refs.revision_id),
  };
  const valid =
    inputIds.every((id) => !refs[id] || referenceValues[id] !== null) &&
    (kind === 'REVISION_LINKED'
      ? referenceValues.revision_id !== null
      : referenceValues.guide_run_id !== null || referenceValues.message_id !== null);

  function insert() {
    if (!actual || !ownsDocument || blocked || read.error || read.loading || inserted) return;
    const current = composer.getSnapshot();
    if (
      !composer.editable ||
      current.action !== 'DISCUSS' ||
      !current.available ||
      current.detail.selected_document_id !== link.documentId
    )
      return;
    const source = plainText(actual.handoff.data);
    if (current.instruction.includes(source.title)) {
      setInserted(true);
      return;
    }
    const separator = current.instruction ? '\n\n' : '';
    const content = current.instruction + separator + source.text;
    if ([...content].length > 10000) {
      setInsertError('加入移交内容后超过讨论输入上限。请先整理当前草稿。');
      return;
    }
    setInsertError(null);
    composer.change(content);
    const draft = composer.getSnapshot();
    if (draft.instruction !== content) return;
    setInserted(true);
    if (!draft.draft_warning) {
      try {
        sessionStorage.setItem(marker, '1');
      } catch {
        // The same plain-text marker still prevents a duplicate in this draft.
      }
    }
  }

  const alreadyInserted =
    inserted || (!!actual && state.instruction.includes(plainText(actual.handoff.data).title));
  const canInsert =
    !!actual &&
    ownsDocument &&
    !blocked &&
    !read.loading &&
    !read.error &&
    !alreadyInserted &&
    composer.editable &&
    state.available &&
    state.action === 'DISCUSS';

  return (
    <section
      className="code-question-response"
      aria-label="来源代码任务移交"
      aria-busy={ownsDocument && read.loading}
    >
      <h3>来源代码任务移交</h3>
      {!ownsDocument && <p role="alert">当前文档与原移交目标不一致。</p>}
      {ownsDocument && read.loading && <p role="status">正在核对原移交…</p>}
      {read.error && (
        <p role="alert" className="inline-error">
          {read.error}{' '}
          <button className="ui-button" type="button" onClick={refresh}>
            重新读取移交
          </button>
        </p>
      )}
      {ownsDocument && actual && (
        <>
          <p>
            代码任务 #{link.taskId} · 移交 #{link.handoffId}
          </p>
          <ol>
            {actual.handoff.data.source_question.questions.map((item) => (
              <li key={item.index}>
                <strong>{item.header}</strong>
                <p>{item.text}</p>
              </li>
            ))}
          </ol>
          {actual.handoff.data.evidence_refs.length > 0 && (
            <p>相关代码证据 {actual.handoff.data.evidence_refs.map(evidenceLabel).join('、')}</p>
          )}
          <button className="ui-button" type="button" disabled={!canInsert} onClick={insert}>
            填入讨论输入
          </button>
          {alreadyInserted ? (
            <p role="status">原移交内容已填入讨论输入。</p>
          ) : (
            !canInsert && <p className="field-help">请在目标文档的可编辑讨论输入中填入移交。</p>
          )}
          {insertError && (
            <p role="alert" className="inline-error">
              {insertError}
            </p>
          )}
          <h4>已保存移交记录</h4>
          {actual.handoff.data.events.length === 0 && !read.error && !read.loading && (
            <EmptyState icon="history" message="此页暂无移交事件" />
          )}
          <ul>
            {actual.handoff.data.events.map((event) => (
              <li key={event.id}>
                {eventNames[event.kind]} · #{event.id}
                {event.guide_run_id !== null && ' · 讨论运行 #' + event.guide_run_id}
                {event.message_id !== null && ' · 消息 #' + event.message_id}
                {event.revision_id !== null && ' · 版本 #' + event.revision_id}
              </li>
            ))}
          </ul>
          <Pagination
            value={actual.handoff.pagination}
            change={setPage}
            loading={read.loading}
            compactSingle
            showLoadingStatus={false}
          />
          {ended ? (
            <p className="field-help">代码任务已结束，既有移交记录仍可查看。</p>
          ) : (
            <form
              aria-label="关联已有文档结果"
              onSubmit={(event) => {
                event.preventDefault();
                if (!valid || linkBlocked) return;
                command.submit({
                  expected_state_version: actual.task.state_version,
                  kind,
                  ...referenceValues,
                });
              }}
            >
              <fieldset disabled={linkBlocked}>
                <legend>关联已有文档结果</legend>
                <label>
                  关联类型{' '}
                  <select
                    value={kind}
                    onChange={(event) =>
                      setKind(
                        event.target.value === 'REVISION_LINKED'
                          ? 'REVISION_LINKED'
                          : 'DISCUSSION_LINKED',
                      )
                    }
                  >
                    <option value="DISCUSSION_LINKED">讨论</option>
                    <option value="REVISION_LINKED">版本</option>
                  </select>
                </label>
                {inputIds.map((field) => (
                  <label key={field}>
                    {fieldNames[field]}{' '}
                    <input
                      inputMode="numeric"
                      value={refs[field]}
                      onChange={(event) =>
                        setRefs((current) => ({ ...current, [field]: event.target.value }))
                      }
                    />
                  </label>
                ))}
                <button className="ui-button" type="submit" disabled={!valid || linkBlocked}>
                  保存已有结果关联
                </button>
              </fieldset>
              {linkBlocked && <p className="field-help">请先核对任务状态及原关联请求。</p>}
            </form>
          )}
        </>
      )}
      {ownsDocument && actual && command.pending && (
        <>
          <button
            type="button"
            className="ui-button"
            disabled={command.busy}
            onClick={command.lookup}
          >
            核对原关联请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={!!actual && !ended && status !== 'STOPPING' && !command.busy}
            settled={command.settled}
          />
        </>
      )}
      {ownsDocument && actual && command.busy && (
        <button type="button" className="ui-button" onClick={command.stop}>
          停止等待关联结果
        </button>
      )}
      {ownsDocument && actual && command.notice && <p role="status">{command.notice}</p>}
      {ownsDocument && actual && command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {ownsDocument && actual && !command.ready && command.error && (
        <button type="button" className="ui-button" onClick={command.reload}>
          重新读取原关联请求
        </button>
      )}
    </section>
  );
}
