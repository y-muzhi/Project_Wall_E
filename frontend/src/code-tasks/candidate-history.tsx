import { useCallback, useState } from 'react';
import { ApiRejected } from '../api/client.ts';
import type { CodeCandidate } from '../api/code-task-candidates.ts';
import type { WalleApi } from '../api/walle.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { CandidateDiff } from './candidate-diff.tsx';
import { TASK_PHASE } from './list-model.ts';
import { useSettingsRead } from './settings/read.ts';
import { VerificationHistory } from './verification-history.tsx';

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  currentId: number | null;
  selection: number | null;
  select(id: number | null): void;
  filePath: string | null;
  page: number;
  selectPage(page: number): void;
  selectFile(candidateId: number, path: string | null): void;
  visible: boolean;
}>;

async function readFixedContent<T>(load: Promise<T>): Promise<T> {
  try {
    return await load;
  } catch (error) {
    if (error instanceof ApiRejected && error.code === 'CONTENT_NOT_READY') {
      throw new ApiRejected(
        error.code,
        '固定代码暂不可用，请核对原操作',
        error.details,
        error.request_id,
        error.status,
      );
    }
    throw error;
  }
}

export function CandidateHistory({
  api,
  taskId,
  currentId,
  selection,
  select,
  filePath,
  page,
  selectPage,
  selectFile,
  visible,
}: Props) {
  const [localHistoryPage, setLocalHistoryPage] = useState(1);
  const selected = selection ?? currentId;
  const historyPage = selected === null ? page : localHistoryPage;
  const selectHistoryPage = selected === null ? selectPage : setLocalHistoryPage;
  const [retry, setRetry] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => {
      void retry;
      void currentId;
      return readFixedContent(api.codeTaskCandidates(taskId, historyPage, signal));
    },
    [api, taskId, currentId, historyPage, retry],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取固定代码');
  const pagination = result.value?.meta.pagination;
  const currentPage =
    pagination && 'page' in pagination && pagination.page === historyPage ? pagination : null;
  const candidates = currentPage ? result.value?.data.items : undefined;

  return (
    <section className="code-task-result" aria-label="待验收代码" aria-busy={result.loading}>
      <h2>待验收代码</h2>
      {result.loading && <p role="status">正在读取固定代码…</p>}
      {result.error && (
        <p role="alert">
          {result.error}{' '}
          <button
            type="button"
            className="ui-button"
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取
          </button>
        </p>
      )}
      {!result.loading && !result.error && candidates?.length === 0 && (
        <EmptyState
          icon="outline"
          message={historyPage > 1 ? '当前页超出固定代码范围' : '尚未形成待验收代码'}
        />
      )}
      {!!candidates?.length && (
        <ul aria-label="固定代码列表">
          {candidates.map((item) => (
            <li key={item.id}>
              <button
                className="ui-button"
                type="button"
                aria-current={selected === item.id ? 'true' : undefined}
                onClick={() => select(item.id)}
              >
                代码 #{item.id} · {item.id === currentId ? '当前' : '历史'}
              </button>{' '}
              {TASK_PHASE[item.role]} · {item.file_count} 个文件
            </li>
          ))}
        </ul>
      )}
      {currentPage && (
        <Pagination value={currentPage} loading={result.loading} change={selectHistoryPage} />
      )}
      {selected !== null && (
        <CandidateDetail
          key={selected}
          api={api}
          taskId={taskId}
          id={selected}
          current={currentId}
          openCurrent={() => select(null)}
          filePath={filePath}
          page={page}
          selectPage={selectPage}
          selectFile={(path) => selectFile(selected, path)}
          visible={visible}
        />
      )}
    </section>
  );
}

function CandidateDetail({
  api,
  taskId,
  id,
  current,
  openCurrent,
  filePath,
  page,
  selectPage,
  selectFile,
  visible,
}: Readonly<{
  api: WalleApi;
  taskId: number;
  id: number;
  current: number | null;
  openCurrent(): void;
  filePath: string | null;
  page: number;
  selectPage(page: number): void;
  selectFile(path: string | null): void;
  visible: boolean;
}>) {
  const [retry, setRetry] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => {
      void retry;
      return readFixedContent(api.codeTaskCandidate(taskId, id, signal));
    },
    [api, taskId, id, retry],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取所选固定代码');
  return (
    <section aria-label={'代码 #' + id + ' 详情'} aria-busy={result.loading}>
      <h3>代码 #{id} 详情</h3>
      {result.loading && <p role="status">正在读取代码详情…</p>}
      {result.error && (
        <p role="alert">
          {result.error}{' '}
          <button
            type="button"
            className="ui-button"
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取详情
          </button>
        </p>
      )}
      {result.value && (
        <>
          {id !== current && (
            <div className="code-task-toolbar">
              <p className="read-status">历史代码，仅供查看</p>
              {current !== null && (
                <button type="button" className="ui-button" onClick={openCurrent}>
                  查看当前代码 #{current}
                </button>
              )}
            </div>
          )}
          <CandidateFacts candidate={result.value.data} />
          <CandidateDiff
            api={api}
            taskId={taskId}
            candidateId={id}
            filePath={filePath}
            page={page}
            selectPage={selectPage}
            selectFile={selectFile}
            visible={visible}
          />
          <VerificationHistory
            api={api}
            taskId={taskId}
            candidateId={id}
            currentVerificationId={null}
            visible={visible}
          />
        </>
      )}
    </section>
  );
}

function CandidateFacts({ candidate }: Readonly<{ candidate: CodeCandidate }>) {
  return (
    <dl className="code-task-facts">
      <dt>固定时间</dt>
      <dd>
        <time dateTime={candidate.captured_at}>
          {new Date(candidate.captured_at).toLocaleString()}
        </time>
      </dd>
      <dt>阶段</dt>
      <dd>{TASK_PHASE[candidate.role]}</dd>
      <dt>来源代码</dt>
      <dd>
        {candidate.parent_candidate_id === null
          ? '起点 Git 版本 #' + candidate.base_snapshot_id
          : '代码 #' + candidate.parent_candidate_id}
      </dd>
      <dt>内容</dt>
      <dd>
        {candidate.file_count} 个文件 · {candidate.byte_count} 字节
      </dd>
      {candidate.published_for_testing_at !== null && (
        <>
          <dt>独立测试</dt>
          <dd>候选已发布</dd>
        </>
      )}
    </dl>
  );
}
