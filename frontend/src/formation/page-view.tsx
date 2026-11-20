import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiRejected, stableJson } from '../api/client.ts';
import type { FormationCursorPagination } from '../api/client.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import type { IconName } from '../shared/icon.tsx';
type Result<T> = Readonly<{
  data: Readonly<{ items: readonly T[]; total: number }>;
  meta: Readonly<{ pagination: FormationCursorPagination }>;
}>;
/** One expanded list, one cursor page. Its old good page survives a failed refresh. */
export function FormationPage<T>({
  scope,
  load,
  empty,
  icon,
  render,
  onPathChanged,
  identity,
  showTotal = true,
}: Readonly<{
  scope: string;
  load: (cursor: string | null, signal: AbortSignal) => Promise<Result<T>>;
  empty: string;
  icon: IconName;
  render: (row: T, index: number) => ReactNode;
  onPathChanged?: () => void;
  identity?: (row: T) => string | number;
  showTotal?: boolean;
}>) {
  const [cursor, setCursor] = useState<string | null>(null),
    [previous, setPrevious] = useState<(string | null)[]>([]);
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<{
    scope: string;
    result: Result<T> | null;
    loading: boolean;
    error: string | null;
  }>({
    scope,
    result: null,
    loading: true,
    error: null,
  });
  const latest = useRef(load);
  latest.current = load;
  useEffect(() => {
    const controller = new AbortController();
    setState((old) => ({
      scope,
      result: old.scope === scope ? old.result : null,
      loading: true,
      error: null,
    }));
    void latest.current(cursor, controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) setState({ scope, result, loading: false, error: null });
      },
      (error) => {
        if (controller.signal.aborted) return;
        if (
          error instanceof ApiRejected &&
          error.code === 'STATE_CONFLICT' &&
          error.details?.reason === 'PATH_CHANGED'
        )
          onPathChanged?.();
        setState((old) => ({
          ...old,
          loading: false,
          error: error instanceof ApiRejected ? error.message : '暂时无法读取，请重试',
        }));
      },
    );
    return () => controller.abort();
  }, [scope, cursor, reload]);
  const result = state.scope === scope ? state.result : null,
    loading = state.scope !== scope || state.loading;
  return (
    <div className="formation-page" aria-busy={loading}>
      <div className="formation-page-heading">
        {showTotal && result !== null && <span>共 {result.data.total} 项</span>}
        <button
          type="button"
          className="ui-button"
          disabled={loading}
          onClick={() => setReload((value) => value + 1)}
        >
          刷新
        </button>
      </div>
      {loading && <p role="status">正在读取…</p>}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
          {result !== null && result.data.items.length > 0 && '；下方保留上次成功读取的记录。'}
        </p>
      )}
      {!loading && state.error === null && result !== null && result.data.items.length === 0 && (
        <EmptyState
          compact
          icon={icon}
          message={cursor === null ? empty : '此页已无记录，请返回前页或刷新'}
        />
      )}
      {result !== null && result.data.items.length > 0 && (
        <ul className="formation-records">
          {result.data.items.map((row, index) => (
            <li key={identity?.(row) ?? stableJson(row)!}>{render(row, index)}</li>
          ))}
        </ul>
      )}
      <nav className="formation-pagination" aria-label="列表分页">
        <button
          type="button"
          className="ui-button"
          disabled={loading || previous.length === 0}
          onClick={() => {
            const last = previous.at(-1) ?? null;
            setPrevious((values) => values.slice(0, -1));
            setCursor(last);
          }}
        >
          上一页
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={loading || state.error !== null || result?.meta.pagination.has_more !== true}
          onClick={() => {
            const next = result?.meta.pagination.next_cursor;
            if (next === null || next === undefined) return;
            setPrevious((values) => [...values, cursor]);
            setCursor(next);
          }}
        >
          下一页
        </button>
      </nav>
    </div>
  );
}
