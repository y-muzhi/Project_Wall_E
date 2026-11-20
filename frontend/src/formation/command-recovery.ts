/** Only an explicit send/replay dispatches. Native bindings reconstruct decoders, never bytes. */
import { ApiRejected, ApiUnknown, exact, positiveInteger, snapshotObject } from '../api/client.ts';
import type { ApiSuccess, FrozenRequest } from '../api/client.ts';
import type { ApiAction, CreateFormationDiscuss, WalleApi } from '../api/walle.ts';
import { responses } from '../api/models.ts';
import { CommandStorageError } from '../shared/command-ledger.ts';
import { freezeFormation, frozenFormation, verifyFormationFrozen } from './command-model.ts';
import type { FormationPending, FormationReceipt } from './command-model.ts';
import { FormationCommandStore } from './command-store.ts';

export class FormationUnsentError extends Error {
  constructor(message: string) {
    super(message);
  }
}
type Port = Pick<
  WalleApi,
  'prepareFormationCommand' | 'prepareFormationDiscuss' | 'prepareCardResponses'
>;
export class FormationCommandRecovery {
  private readonly ownerId = crypto.randomUUID();
  private closed = false;
  readonly requirementId: number;
  readonly documentId: number;
  private readonly api: Port;
  readonly store: FormationCommandStore;
  constructor(
    requirementId: number,
    documentId: number,
    api: Port,
    store = new FormationCommandStore(),
  ) {
    this.requirementId = requirementId;
    this.documentId = documentId;
    this.api = api;
    this.store = store;
    positiveInteger(requirementId);
    positiveInteger(documentId);
  }
  private owned(row: FormationPending): void {
    if (
      this.closed ||
      row.requirement_id !== this.requirementId ||
      row.document_id !== this.documentId
    )
      throw TypeError('Owned formation request required');
  }
  wrap<T>(action: ApiAction<T>, intentKey: string = crypto.randomUUID()): ApiAction<T> {
    const intent = intentKey;
    let row: FormationPending | null = null;
    let confirmed: ApiSuccess<T> | null = null;
    let pending: Promise<ApiSuccess<T>> | null = null;
    const submit = (): Promise<ApiSuccess<T>> => {
      if (pending !== null) return pending;
      if (confirmed !== null) return Promise.resolve(confirmed);
      pending = (async () => {
        if (this.closed) throw new FormationUnsentError('文档已关闭，原输入和恢复记录保留');
        if (row === null) {
          try {
            if (action.request === undefined) throw TypeError('Frozen native request required');
            const frozen = await freezeFormation(
              action.request,
              this.requirementId,
              this.documentId,
              intent,
              this.store.origin,
            );
            const staged = await this.store.reserve(frozen);
            if (staged.kind === 'RESOLVED')
              throw TypeError('Resolved action requires read reconciliation');
            row = staged.record;
          } catch (error) {
            throw new FormationUnsentError(
              error instanceof Error ? error.message : '操作暂存失败，尚未发送',
            );
          }
        }
        this.owned(row);
        const response = await this.send(row, action);
        row = null;
        confirmed = response;
        return response;
      })().finally(() => {
        pending = null;
      });
      return pending;
    };
    return Object.freeze({ request: action.request, submit });
  }
  private async send<T>(row: FormationPending, action: ApiAction<T>): Promise<ApiSuccess<T>> {
    this.owned(row);
    const latest = await this.store.detail(row.key);
    if (latest === null) throw new FormationUnsentError('该操作已有确认结果，请重新读取文档');
    if (latest.identity_sha256 !== row.identity_sha256 || latest.body_sha256 !== row.body_sha256)
      throw TypeError('Original formation request differs');
    row = latest;
    let dispatched: FormationPending | null;
    try {
      dispatched = await this.store.dispatch(row, this.ownerId, row.dispatch_count !== 0);
    } catch (error) {
      throw new FormationUnsentError(
        error instanceof Error ? error.message : '暂存不可用，尚未发送',
      );
    }
    if (dispatched === null)
      throw new FormationUnsentError('此操作已被其他页面接续，请重新读取恢复记录');
    try {
      const response = await action.submit();
      const data = snapshotObject(response.data);
      const guide = data.guide_run_id === undefined ? null : positiveInteger(data.guide_run_id);
      const user =
        data.user_message_id === null || data.user_message_id === undefined
          ? null
          : positiveInteger(data.user_message_id);
      const events = data.event_ids === undefined ? [] : data.event_ids;
      if (!Array.isArray(events)) throw new ApiUnknown(true);
      const receipt = await this.store.resolve(dispatched, {
        final_state: 'CONFIRMED',
        http_status: response.status,
        result_code: null,
        guide_run_id: guide,
        user_message_id: user,
        event_ids: events.map(positiveInteger),
      });
      if (receipt === null) throw new ApiUnknown(true);
      return response;
    } catch (error) {
      if (error instanceof ApiRejected && error.code !== 'REQUEST_IN_PROGRESS') {
        const receipt = await this.store.resolve(dispatched, {
          final_state: 'KNOWN_REJECTED',
          http_status: error.status,
          result_code: error.code,
          guide_run_id: null,
          user_message_id: null,
          event_ids: [],
        });
        if (receipt === null) throw new ApiUnknown(true);
        throw error;
      }
      try {
        await this.store.markUnknown(dispatched);
      } catch {
        /* Original dispatch record remains. */
      }
      if (error instanceof CommandStorageError) throw new ApiUnknown(true);
      throw error;
    }
  }
  private async restore(row: FormationPending): Promise<ApiAction<unknown>> {
    this.owned(row);
    await verifyFormationFrozen(frozenFormation(row), this.store.origin);
    const request: FrozenRequest = {
      method: row.method,
      path: row.path,
      key: row.key,
      body: row.body_text,
    };
    const original = snapshotObject(JSON.parse(row.body_text));
    if (row.method === 'PATCH') {
      const body = exact(original, [
        'document_id',
        'expected_discussion_version',
        'discussion_command',
      ]);
      return this.api.prepareFormationCommand(
        this.requirementId,
        {
          expected_discussion_version: positiveInteger(body.expected_discussion_version),
          discussion_command: snapshotObject(body.discussion_command),
        },
        request,
      );
    }
    if (row.path.endsWith('/guide-runs')) {
      const { document_id: _owner, ...body } = original;
      // The native method validates every input field before restoring the opaque transport.
      return this.api.prepareFormationDiscuss(
        this.requirementId,
        body as unknown as CreateFormationDiscuss,
        request,
      );
    }
    const matched = /^\/api\/v1\/conversation-messages\/([1-9][0-9]*)\/responses$/.exec(row.path);
    if (matched === null) throw TypeError('Unregistered formation request');
    const { expected_discussion_version: version, ...body } = original;
    return this.api.prepareCardResponses(
      Number(matched[1]),
      responses(body),
      positiveInteger(version),
      request,
    );
  }
  async replay(key: string): Promise<ApiSuccess<unknown>> {
    const row = await this.store.detail(key);
    if (row === null) throw new FormationUnsentError('该操作已有确认结果，请重新读取文档');
    return this.send(row, await this.restore(row));
  }
  list() {
    return this.store.list(this.requirementId, this.documentId);
  }
  async cancelUnsent(key: string): Promise<FormationReceipt | null> {
    const row = await this.store.detail(key);
    if (row === null) return null;
    this.owned(row);
    return this.store.resolve(row, {
      final_state: 'CANCELLED_UNSENT',
      http_status: null,
      result_code: null,
      guide_run_id: null,
      user_message_id: null,
      event_ids: [],
    });
  }
  dispose(): void {
    this.closed = true;
    this.store.close();
  }
}
