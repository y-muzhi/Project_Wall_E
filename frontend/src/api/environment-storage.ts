import { parseEnvironmentJson, type EnvironmentScope } from './environment-binding.ts';
import { exact } from './wire-shape.ts';

export type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export type BrowserHistoryPort = Pick<History, 'state' | 'replaceState' | 'pushState' | 'go'> &
  Partial<Pick<History, 'scrollRestoration'>>;
const ENVELOPE = ['scope_version', 'origin', 'environment_id', 'data_generation', 'value'] as const;

export class EnvironmentStorageInvalid extends Error {
  constructor() {
    super('本机环境记录无法核对，旧记录已保留');
  }
}

function separateKey(scope: EnvironmentScope, key: string) {
  return (
    'walle:v2.01:' +
    scope.environment_id +
    ':' +
    scope.data_generation +
    ':' +
    encodeURIComponent(key)
  );
}

function envelope<T>(scope: EnvironmentScope, value: T) {
  return {
    scope_version: 1,
    origin: scope.origin,
    environment_id: scope.environment_id,
    data_generation: scope.data_generation,
    value,
  };
}

function valueOf(value: unknown, scope: EnvironmentScope): unknown {
  const record = exact(value, ENVELOPE);
  if (
    record.scope_version !== 1 ||
    record.origin !== scope.origin ||
    record.environment_id !== scope.environment_id ||
    record.data_generation !== scope.data_generation
  )
    throw new EnvironmentStorageInvalid();
  return record.value;
}

/** A restricted view of the existing store; callers cannot enumerate or clear other scopes. */
export class ScopedStoragePort implements StoragePort {
  private readonly storage: StoragePort;
  private readonly scope: EnvironmentScope;

  constructor(storage: StoragePort, scope: EnvironmentScope) {
    this.storage = storage;
    this.scope = Object.freeze({ ...scope });
  }

  getItem(key: string): string | null {
    const raw = this.storage.getItem(separateKey(this.scope, key));
    if (raw === null) return null;
    try {
      const value = valueOf(parseEnvironmentJson(raw), this.scope);
      if (typeof value !== 'string') throw new EnvironmentStorageInvalid();
      return value;
    } catch {
      throw new EnvironmentStorageInvalid();
    }
  }

  setItem(key: string, value: string) {
    // A corrupt record is a recoverable error, never a missing value to overwrite.
    this.getItem(key);
    this.storage.setItem(separateKey(this.scope, key), JSON.stringify(envelope(this.scope, value)));
  }

  removeItem(key: string) {
    this.getItem(key);
    this.storage.removeItem(separateKey(this.scope, key));
  }
}

export function environmentBrowserStorage(
  kind: 'sessionStorage' | 'localStorage',
  scope: EnvironmentScope | undefined,
): StoragePort {
  const storage = globalThis[kind];
  return scope ? new ScopedStoragePort(storage, scope) : storage;
}

export function bindBrowserHistory(
  history: BrowserHistoryPort,
  scope: EnvironmentScope,
): BrowserHistoryPort {
  const bound: BrowserHistoryPort = {
    get state() {
      return readScopedHistory(scope, history.state);
    },
    replaceState(value, title, url) {
      history.replaceState(scopedHistoryState(scope, value), title, url);
    },
    pushState(value, title, url) {
      history.pushState(scopedHistoryState(scope, value), title, url);
    },
    go(delta) {
      history.go(delta);
    },
  };
  if ('scrollRestoration' in history) {
    Object.defineProperty(bound, 'scrollRestoration', {
      get: () => history.scrollRestoration,
      set: (value: ScrollRestoration) => {
        history.scrollRestoration = value;
      },
    });
  }
  return bound;
}

export function scopedHistoryState(scope: EnvironmentScope, payload: unknown) {
  return envelope(scope, payload);
}

export function readScopedHistory(scope: EnvironmentScope, state: unknown): unknown {
  try {
    return valueOf(state, scope);
  } catch {
    // Reload the current URL normally; no old state or draft is deleted.
    return null;
  }
}
