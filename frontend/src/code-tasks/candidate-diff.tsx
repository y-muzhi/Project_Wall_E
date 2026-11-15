import { useCallback, useState } from 'react';
import type { CodeCandidateDiff } from '../api/code-task-candidates.ts';
import type { WalleApi } from '../api/walle.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { CandidateFilePreview } from './candidate-file-preview.tsx';
import { useSettingsRead } from './settings/read.ts';

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  candidateId: number;
  filePath: string | null;
  page: number;
  selectPage(page: number): void;
  selectFile(path: string | null): void;
  visible: boolean;
}>;
const changes = { ADD: '新增', MODIFY: '修改', DELETE: '删除', MODE: '模式变更' };

export function CandidateDiff({
  api,
  taskId,
  candidateId,
  filePath,
  page,
  selectPage,
  selectFile,
  visible,
}: Props) {
  const [retry, setRetry] = useState(0);
  const [selectionHint, setSelectionHint] = useState<CodeCandidateDiff | null>(null);
  const [filesOpen, setFilesOpen] = useState(true);
  const load = useCallback(
    (signal: AbortSignal) => {
      void retry;
      return api.codeTaskCandidateDiff(taskId, candidateId, page, signal);
    },
    [api, taskId, candidateId, page, retry],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取固定差异');
  const pagination = result.value?.meta.pagination;
  const current =
    pagination && 'page' in pagination && pagination.page === page ? pagination : null;
  const rows = current ? result.value?.data.items : undefined;
  const selected = selectionHint?.path === filePath ? selectionHint : undefined;

  function openFile(row: CodeCandidateDiff) {
    setSelectionHint(row);
    selectFile(row.path);
  }

  return (
    <section className="code-candidate-diff" aria-label="固定代码差异" aria-busy={result.loading}>
      <h4>起点 Git 版本／待验收代码</h4>
      {result.loading && <p role="status">正在读取固定差异…</p>}
      {result.error && (
        <p role="alert" className="inline-error">
          {result.error}{' '}
          <button
            className="ui-button"
            type="button"
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取差异
          </button>
        </p>
      )}
      {!result.loading && !result.error && rows?.length === 0 && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页超出差异范围' : '这份代码与比较版本一致'}
        />
      )}
      <div className="code-candidate-diff__body">
        {!!rows?.length && (
          <div>
            <button
              type="button"
              className="ui-button code-candidate-diff__list-toggle"
              aria-expanded={filesOpen}
              onClick={() => setFilesOpen((open) => !open)}
            >
              {filesOpen ? '收起差异文件' : '展开差异文件'}
            </button>
            <div className={filesOpen ? undefined : 'code-candidate-diff__list-collapsed'}>
              <ul aria-label="差异文件列表">
                {rows.map((row) => (
                  <li key={row.path}>
                    <button
                      type="button"
                      className="ui-button"
                      aria-pressed={filePath === row.path}
                      onClick={() => openFile(row)}
                    >
                      {row.path}
                    </button>
                    <div>
                      {changes[row.change]} · {row.before_size ?? '—'} → {row.after_size ?? '—'}{' '}
                      字节
                      {row.binary ? ' · 二进制' : ''}
                    </div>
                    {row.before_mode !== row.after_mode && (
                      <div>
                        {row.before_mode ?? '—'} → {row.after_mode ?? '—'}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {current && (
                <Pagination value={current} loading={result.loading} change={selectPage} />
              )}
            </div>
          </div>
        )}
        {current && !rows?.length && current.total > 0 && (
          <Pagination value={current} loading={result.loading} change={selectPage} />
        )}
        {filePath !== null ? (
          <CandidateFilePreview
            key={filePath}
            api={api}
            taskId={taskId}
            candidateId={candidateId}
            filePath={filePath}
            item={selected}
            close={() => selectFile(null)}
            visible={visible}
          />
        ) : (
          !!rows?.length && <EmptyState icon="outline" message="请选择差异文件" />
        )}
      </div>
    </section>
  );
}
