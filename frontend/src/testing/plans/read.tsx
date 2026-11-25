import { useCallback, useEffect, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../../api/client.ts';
import { CommandStorageError } from '../../code-tasks/command-recovery-store.ts';
import { useSettingsVisibility } from '../../code-tasks/settings/read.ts';

type PageMeta = { page: number; total_pages: number };

export function errorText(error: unknown, fallback: string) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : fallback;
}

export function useTestingRead<T>(
  key: string,
  load: ((signal: AbortSignal) => Promise<T>) | null,
  keepPrevious = false,
) {
  const [snapshot, setSnapshot] = useState<Readonly<{ key: string; value: T }> | null>(null);
  const [status, setStatus] = useState<Readonly<{
    key: string;
    busy: boolean;
    error: string | null;
  }> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const visible = useSettingsVisibility();
  const reload = useCallback(() => setAttempt((current) => current + 1), []);
  useEffect(() => {
    if (load === null || !visible) return;
    const request = new AbortController();
    setStatus({ key, busy: true, error: null });
    void load(request.signal).then(
      (value) => {
        if (request.signal.aborted) return;
        setSnapshot({ key, value });
        setStatus({ key, busy: false, error: null });
      },
      (error: unknown) => {
        if (!request.signal.aborted)
          setStatus({ key, busy: false, error: errorText(error, '暂时无法读取测试记录') });
      },
    );
    return () => request.abort();
  }, [key, load, attempt, visible]);
  return {
    data:
      snapshot !== null && load !== null && (keepPrevious || snapshot.key === key)
        ? snapshot.value
        : null,
    stale: keepPrevious && snapshot !== null && load !== null && snapshot.key !== key,
    loading: load !== null && (status?.key !== key || status.busy),
    error: load !== null && status?.key === key ? status.error : null,
    reload,
  };
}

export function ReadState({
  loading,
  error,
  stale,
  retry,
}: Readonly<{
  loading: boolean;
  error: string | null;
  stale: boolean;
  retry(): void;
}>) {
  return (
    <>
      {loading && <p role="status">正在读取…</p>}
      {error && (
        <div className="code-settings-form-actions">
          <p className="inline-error" role="alert">
            {error}
          </p>
          <button type="button" className="ui-button" onClick={retry}>
            重试读取
          </button>
        </div>
      )}
      {error && stale && <p className="read-status">显示上次读取的记录</p>}
    </>
  );
}

export function Pager({
  meta,
  page,
  busy,
  select,
}: Readonly<{ meta: PageMeta | null; page: number; busy: boolean; select(page: number): void }>) {
  if (meta === null) return null;
  return (
    <div className="code-settings-form-actions">
      <button
        type="button"
        className="ui-button"
        disabled={busy || page === 1}
        title={busy ? '正在读取' : page === 1 ? '已是首页' : undefined}
        onClick={() => select(page - 1)}
      >
        上一页
      </button>
      <span>第 {page} 页</span>
      <button
        type="button"
        className="ui-button"
        disabled={busy || page >= meta.total_pages}
        title={busy ? '正在读取' : page >= meta.total_pages ? '没有下一页' : undefined}
        onClick={() => select(page + 1)}
      >
        下一页
      </button>
    </div>
  );
}
export function meta(value: unknown): PageMeta | null {
  return typeof value === 'object' &&
    value !== null &&
    'page' in value &&
    'total_pages' in value &&
    typeof value.page === 'number' &&
    typeof value.total_pages === 'number'
    ? { page: value.page, total_pages: value.total_pages }
    : null;
}
