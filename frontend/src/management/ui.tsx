import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ManagementReadError } from './api.ts';
import { ManagementStorageError } from './command-store.ts';

type Query<T> = { key: string; value: T | null; error: string | null; waiting: boolean };
export function useRead<T>(key: string, load: (signal: AbortSignal) => Promise<T>, enabled = true) {
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<Query<T>>({ key, value: null, error: null, waiting: enabled });
  useEffect(() => {
    if (!enabled) return;
    const task = new AbortController();
    const timeout = window.setTimeout(() => {
      task.abort();
      setState((previous) => ({
        key,
        value: previous.key === key ? previous.value : null,
        error: '读取超时，请重试。',
        waiting: false,
      }));
    }, 15000);
    setState((previous) => ({
      key,
      value: previous.key === key ? previous.value : null,
      error: null,
      waiting: true,
    }));
    void load(task.signal)
      .then((value) => {
        if (!task.signal.aborted) setState({ key, value, error: null, waiting: false });
      })
      .catch((error: unknown) => {
        if (task.signal.aborted) return;
        const message =
          error instanceof ManagementReadError || error instanceof ManagementStorageError
            ? error.message
            : '暂时无法读取管理资料，请重试。';
        setState((previous) => ({
          key,
          value: previous.key === key ? previous.value : null,
          error: message,
          waiting: false,
        }));
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      window.clearTimeout(timeout);
      task.abort();
    };
  }, [key, load, refresh, enabled]);
  const current = state.key === key ? state : { key, value: null, error: null, waiting: enabled };
  return { ...current, retry: () => setRefresh((previous) => previous + 1) };
}

export function ReadStatus({
  state,
}: {
  state: { waiting: boolean; error: string | null; retry: () => void; value?: unknown };
}) {
  return (
    <>
      {state.waiting && (
        <p role="status" className="feedback">
          正在读取…
        </p>
      )}
      {state.error && (
        <div role="alert" className="feedback error">
          <span>
            {state.error}
            {Boolean(state.value) && ' 暂显示上次读取结果。'}
          </span>
          <button type="button" onClick={state.retry}>
            重新读取
          </button>
        </div>
      )}
    </>
  );
}

export function Panel({
  title,
  back,
  backLabel = '返回列表',
  children,
}: {
  title: string;
  back?: () => void;
  backLabel?: string;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [title]);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h1 ref={heading} tabIndex={-1}>
          {title}
        </h1>
        {back && (
          <button type="button" onClick={back}>
            {backLabel}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}
