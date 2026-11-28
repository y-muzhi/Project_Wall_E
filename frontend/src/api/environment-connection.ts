import {
  EnvironmentEntryError,
  loadBoundEnvironment,
  sameEnvironmentScope,
  type BoundEnvironment,
} from './environment-binding.ts';
import { RECOVERY_READ_ONLY } from './environment-actions.ts';

type Failure = EnvironmentEntryError['code'];
type Phase = 'READY' | 'CHECKING' | Failure;
export type EnvironmentConnectionState = Readonly<{
  phase: Phase;
  environment: BoundEnvironment;
}>;

export const environmentMessages: Readonly<Record<Failure, string>> = {
  ACCESS: '需要完成当前环境的登录认证。',
  PERMISSION: '当前身份或访问来源未获此环境许可。',
  SCOPE_CHANGED: '入口所属环境或数据代次已变化，当前页面仍保留原内容。',
  PROTOCOL: '入口协议与当前页面版本不一致，请使用与环境匹配的页面。',
  NOT_READY: '当前环境尚未就绪。请稍后重新核对。',
  UNREACHABLE: '暂时无法读取当前环境。请检查连接后重新核对。',
};

/** One mounted business tree owns this immutable scope and its current observation. */
export class EnvironmentConnection {
  private state: EnvironmentConnectionState;
  private readonly listeners = new Set<() => void>();
  private readonly oldRuns = new Set<string>();
  private revision = 0;
  private checkController: AbortController | null = null;
  private pending: Promise<void> | null = null;
  private closed = false;
  private readonly load: typeof loadBoundEnvironment;

  constructor(
    environment: BoundEnvironment,
    load: typeof loadBoundEnvironment = loadBoundEnvironment,
  ) {
    this.load = load;
    this.state = Object.freeze({ environment, phase: 'READY' });
  }

  getSnapshot = (): EnvironmentConnectionState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private publish(phase: Phase, environment = this.state.environment): void {
    this.state = Object.freeze({ environment, phase });
    for (const listener of this.listeners) {
      try {
        listener();
      } catch (error) {
        console.error('WALL-E environment observer failed', error);
      }
    }
  }

  get requestRevision(): number {
    return this.revision;
  }

  blockReason(mutation: boolean): string | null {
    if (this.closed) return '当前页面已关闭。';
    if (this.state.phase === 'CHECKING') return '正在核对连接，请稍后再操作。';
    if (this.state.phase !== 'READY') return environmentMessages[this.state.phase];
    if (mutation && this.state.environment.recovery !== undefined) return RECOVERY_READ_ONLY;
    if (mutation && this.state.environment.userPermission === 'READ_ONLY')
      return '当前访问身份仅可查看。';
    return null;
  }

  private invalidateCheck(): void {
    this.revision += 1;
    this.checkController?.abort();
    this.checkController = null;
    this.pending = null;
  }

  disconnected = (): void => {
    this.reportFailure(this.revision, 'UNREACHABLE');
  };

  reportFailure(revision: number, failure: Failure): void {
    if (
      this.closed ||
      revision !== this.revision ||
      this.state.phase === 'SCOPE_CHANGED' ||
      this.state.phase === failure
    )
      return;
    this.invalidateCheck();
    this.publish(failure);
  }

  /** Old reads do not populate a rechecked page. Identified mutation receipts can
   * still settle their original owner while the same scope is temporarily paused. */
  acceptResponse(revision: number, run: string, mutation: boolean): boolean {
    if (this.closed || this.state.phase === 'SCOPE_CHANGED') return false;
    const current = revision === this.revision && this.state.phase === 'READY';
    if (!mutation && (!current || this.oldRuns.has(run))) return false;
    if (current && run !== this.state.environment.runId && !this.oldRuns.has(run))
      void this.recheck();
    return true;
  }

  recheck = (): Promise<void> => {
    if (this.closed || this.state.phase === 'SCOPE_CHANGED') return Promise.resolve();
    if (this.pending) return this.pending;

    const original = this.state.environment;
    const controller = new AbortController();
    const revision = ++this.revision;
    this.checkController = controller;
    const current = () =>
      !this.closed && this.revision === revision && this.checkController === controller;
    const pending = Promise.resolve()
      .then(() => this.load(original.scope.origin, controller.signal))
      .then((environment) => {
        if (!current()) return;
        if (!sameEnvironmentScope(environment.scope, original.scope)) {
          this.reportFailure(revision, 'SCOPE_CHANGED');
          return;
        }
        if (environment.runId !== original.runId) this.oldRuns.add(original.runId);
        this.oldRuns.delete(environment.runId);
        this.publish('READY', environment);
      })
      .catch((error: unknown) => {
        if (current()) {
          const failure = error instanceof EnvironmentEntryError ? error.code : 'UNREACHABLE';
          this.reportFailure(revision, failure);
        }
      })
      .finally(() => {
        if (this.checkController === controller) {
          this.checkController = null;
          this.pending = null;
        }
      });
    this.pending = pending;
    this.publish('CHECKING');
    return pending;
  };

  dispose(): void {
    if (this.closed) return;
    this.closed = true;
    this.invalidateCheck();
    this.listeners.clear();
  }
}
