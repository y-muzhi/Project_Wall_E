import { useEffect, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../../api/client.ts';

type ReadState<T> = Readonly<{ value: T | null; loading: boolean; error: string | null }>;
const READ_BACKOFF = [2000, 5000, 10000, 30000] as const;

export function useSettingsRead<T>(
  load: (signal: AbortSignal) => Promise<T>,
  visible: boolean,
  fallback: string,
  pollDelay?: (value: T) => number | null,
): ReadState<T> {
  const [state, setState] = useState<ReadState<T>>({ value: null, loading: true, error: null });
  useEffect(() => {
    if (!visible) return;
    const request = new AbortController();
    let reading = false;
    let failures = 0;
    let startedAt = Number.NEGATIVE_INFINITY;
    let timer: number | undefined;

    function schedule(delay: number | null) {
      if (delay !== null && !request.signal.aborted)
        timer = window.setTimeout(() => void read(false), delay);
    }

    async function read(showLoading: boolean) {
      if (request.signal.aborted || reading || (pollDelay && document.hidden)) return;
      if (timer !== undefined) window.clearTimeout(timer);
      reading = true;
      startedAt = performance.now();
      if (showLoading) setState((previous) => ({ ...previous, loading: true, error: null }));
      try {
        const value = await load(request.signal);
        if (!request.signal.aborted) {
          failures = 0;
          setState({ value, loading: false, error: null });
          schedule(pollDelay?.(value) ?? null);
        }
      } catch (error: unknown) {
        if (!request.signal.aborted) {
          setState((previous) => ({
            ...previous,
            loading: false,
            error:
              error instanceof ApiRejected || error instanceof ApiUnknown
                ? error.message
                : fallback,
          }));
          if (pollDelay) {
            const index = Math.min(failures, READ_BACKOFF.length - 1);
            failures += 1;
            schedule(READ_BACKOFF[index]!);
          }
        }
      } finally {
        reading = false;
      }
    }

    function focused() {
      if (performance.now() - startedAt >= 100) void read(false);
    }

    if (pollDelay) window.addEventListener('focus', focused);
    void read(true);
    return () => {
      request.abort();
      if (timer !== undefined) window.clearTimeout(timer);
      if (pollDelay) window.removeEventListener('focus', focused);
    };
  }, [load, visible, fallback, pollDelay]);
  return state;
}

export function useSettingsVisibility() {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    function visibilityChanged() {
      setVisible(!document.hidden);
    }
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => document.removeEventListener('visibilitychange', visibilityChanged);
  }, []);
  return visible;
}
