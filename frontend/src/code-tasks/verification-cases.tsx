import { useCallback, useId, useState } from 'react';
import type { CodeCheckItem } from '../api/code-task-checks.ts';
import type { WalleApi } from '../api/walle.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { useSettingsRead } from './settings/read.ts';

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  item: CodeCheckItem;
  visible: boolean;
  testing?: boolean;
}>;

export function VerificationCases(props: Props) {
  const { item } = props;
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div>
      {item.executed_case_count !== null && (
        <p>
          已记录 {item.executed_case_count}／{item.expected_case_count} 例，
          {item.passed_case_count} 例通过，{item.failed_case_count} 例失败
        </p>
      )}
      <button
        className="ui-button"
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? '收起用例详情' : '查看用例详情'}
      </button>
      {open && <CasePage {...props} id={id} />}
    </div>
  );
}

function CasePage({ api, taskId, item, visible, testing, id }: Props & { id: string }) {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => {
      void retry;
      void item.executed_case_count;
      return testing
        ? api.testingCases(taskId, item.verification_id, item.id, page, signal)
        : api.codeTaskVerificationCases(taskId, item.verification_id, item.id, page, signal);
    },
    [api, testing, taskId, item.verification_id, item.id, item.executed_case_count, page, retry],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取原用例记录');
  const pagination = result.value?.meta.pagination;
  const current =
    pagination && 'page' in pagination && pagination.page === page ? pagination : null;
  const rows = current ? result.value?.data.items : undefined;
  return (
    <section id={id} aria-label={item.check_id + ' 的用例详情'} aria-busy={result.loading}>
      {result.loading && <p role="status">正在读取原用例记录…</p>}
      {result.error && (
        <p role="alert" className="inline-error">
          {result.error}{' '}
          <button className="ui-button" type="button" onClick={() => setRetry((n) => n + 1)}>
            重试读取用例
          </button>
        </p>
      )}
      {!result.loading && !result.error && rows?.length === 0 && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页超出用例记录范围' : '当前没有已记录的用例'}
        />
      )}
      {!!rows?.length && (
        <ul aria-label="已记录的受控用例">
          {rows.map((row) => (
            <li key={row.case_id}>
              <strong>{row.name}</strong> · {row.result === 'PASSED' ? '通过' : '失败'}
              <div>
                {row.passed_assertion_count} 项断言通过，{row.failed_assertion_count} 项失败， 预期{' '}
                {row.expected_assertion_count} 项
              </div>
              {row.summary && <div>{row.summary}</div>}
            </li>
          ))}
        </ul>
      )}
      {current && <Pagination value={current} loading={result.loading} change={setPage} />}
    </section>
  );
}
