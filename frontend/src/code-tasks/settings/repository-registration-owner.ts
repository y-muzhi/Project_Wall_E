import { ApiRejected, ApiUnknown, exact, positiveInteger } from '../../api/client.ts';
import { text } from '../../api/decoding.ts';
import type { RepositoryOperation } from '../../api/code-repository-operations.ts';
import type { WalleApi } from '../../api/walle.ts';
import { normalizeOrdinary } from '../../shared/text.ts';
import { CommandStorageError } from '../command-recovery-store.ts';
import { uuid } from '../command-recovery-model.ts';
import type { PendingSummary } from '../command-recovery-model.ts';
import type { CommandRecovery, RecoveryLookup } from '../command-recovery.ts';

const PATH = '/api/v1/code-repositories';
type Field = 'name' | 'root_path';
type Fields = Readonly<Record<Field, string>>;
type Original = Readonly<{ key: string; operationId: number; repositoryId: number }>;
type Recovery = Pick<CommandRecovery, 'stageIntent' | 'send' | 'reconcileOperation'> & {
  store: Pick<CommandRecovery['store'], 'origin' | 'receipt'>;
};
type State = Readonly<{
  fields: Fields;
  commandKey: string | null;
  busy: boolean;
  fieldErrors: Readonly<Partial<Fields>>;
  submitError: string | null;
  draftWarning: string | null;
  original: Original | null;
  operation: RepositoryOperation | null;
  operationLoading: boolean;
  operationError: string | null;
}>;

function message(error: unknown, fallback: string): string {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : fallback;
}

function fieldErrors(error: ApiRejected): Readonly<Partial<Fields>> {
  const fields = error.details?.field_errors;
  if (error.code !== 'INVALID_INPUT' || !Array.isArray(fields)) return {};
  const result: Partial<Record<Field, string>> = {};
  for (const entry of fields) {
    if (entry === null || typeof entry !== 'object' || !('field' in entry)) continue;
    if (entry.field === 'name') result.name = '请填写有效的仓库名称';
    if (entry.field === 'root_path') result.root_path = '请核对本机绝对目录路径';
  }
  return result;
}

function originalReference(key: string, result: RecoveryLookup): Original | null {
  const receipt = result.original_receipt;
  if (receipt?.original_http_status !== 202 || !receipt.original_outcome?.success) return null;
  const data = exact(receipt.original_outcome.data, [
    'resource_kind',
    'resource_id',
    'operation_id',
    'operation_status',
  ]);
  const operationId = positiveInteger(data.operation_id);
  if (
    data.resource_kind !== 'REPOSITORY' ||
    data.operation_status !== 'PENDING' ||
    receipt.operation_id !== operationId ||
    receipt.task_id !== null ||
    receipt.testing_task_id !== null
  )
    throw TypeError('Original repository receipt differs');
  return { key, operationId, repositoryId: positiveInteger(data.resource_id) };
}

const emptyFields: Fields = Object.freeze({ name: '', root_path: '' });

export class RepositoryRegistrationOwner {
  private readonly listeners = new Set<() => void>();
  private readonly draftKey: string;
  private readonly api: Pick<WalleApi, 'repositoryOperation'>;
  private readonly recovery: Recovery;
  private readonly storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  private visible = false;
  private closed = false;
  private readRequest: AbortController | null = null;
  private restoring: Readonly<{ key: string }> | null = null;
  private value: State = {
    fields: emptyFields,
    commandKey: null,
    busy: false,
    fieldErrors: {},
    submitError: null,
    draftWarning: null,
    original: null,
    operation: null,
    operationLoading: false,
    operationError: null,
  };

  constructor(
    api: Pick<WalleApi, 'repositoryOperation'>,
    recovery: Recovery,
    storage: Pick<Storage, 'getItem' | 'setItem'> | null,
  ) {
    this.api = api;
    this.recovery = recovery;
    this.storage = storage;
    this.draftKey = 'walle:v2.0:code:settings:' + recovery.store.origin + ':REGISTER_REPOSITORY';
    try {
      if (storage === null) throw Error('Draft unavailable');
      const raw = storage.getItem(this.draftKey);
      if (raw === null) return;
      const draft = exact(JSON.parse(raw), ['schema_version', 'fields', 'command_key', 'original']);
      if (draft.schema_version !== 1) throw TypeError('Draft version differs');
      const fields = exact(draft.fields, ['name', 'root_path']);
      const original =
        draft.original === null
          ? null
          : exact(draft.original, ['key', 'operationId', 'repositoryId']);
      this.value = {
        ...this.value,
        fields: { name: text(fields.name), root_path: text(fields.root_path) },
        commandKey: draft.command_key === null ? null : uuid(draft.command_key),
        original:
          original === null
            ? null
            : {
                key: uuid(original.key),
                operationId: positiveInteger(original.operationId),
                repositoryId: positiveInteger(original.repositoryId),
              },
      };
    } catch {
      this.value = { ...this.value, draftWarning: '草稿暂存不可用，离开后可能无法恢复' };
    }
  }

  getSnapshot = (): State => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private publish(changes: Partial<State>) {
    if (this.closed) return;
    this.value = { ...this.value, ...changes };
    for (const listener of this.listeners) listener();
  }

  private saveDraft() {
    try {
      if (this.storage === null) throw Error('Draft unavailable');
      this.storage.setItem(
        this.draftKey,
        JSON.stringify({
          schema_version: 1,
          fields: this.value.fields,
          command_key: this.value.commandKey,
          original: this.value.original,
        }),
      );
      if (this.value.draftWarning) this.publish({ draftWarning: null });
    } catch {
      this.publish({ draftWarning: '草稿暂存不可用，离开后可能无法恢复' });
    }
  }

  edit(field: Field, value: string) {
    if (this.closed || this.value.busy || this.value.commandKey !== null) return;
    this.publish({
      fields: { ...this.value.fields, [field]: value },
      fieldErrors: { ...this.value.fieldErrors, [field]: undefined },
      submitError: null,
    });
    this.saveDraft();
  }

  async submit() {
    if (this.closed || !this.visible || this.value.busy || this.value.commandKey !== null) return;
    const name = normalizeOrdinary(this.value.fields.name);
    const root_path = this.value.fields.root_path;
    const errors: Partial<Record<Field, string>> = {};
    if (!name || name.includes('\0')) errors.name = '请填写有效的仓库名称';
    if (!/^[A-Za-z]:[\\/]/.test(root_path) || root_path.includes('\0'))
      errors.root_path = '请输入本机绝对目录路径';
    this.publish({ fieldErrors: errors, submitError: null });
    if (Object.keys(errors).length > 0) return;
    this.publish({ busy: true });
    try {
      const staged = await this.recovery.stageIntent(PATH, { name, root_path });
      if (this.closed) return;
      if (staged.kind !== 'PREPARED') {
        this.publish({ submitError: '已有原请求，请先核对原结果' });
        return;
      }
      const key = staged.record.key;
      this.publish({ commandKey: key });
      this.saveDraft();
      const result = await this.recovery.send(key, staged.record.record_revision);
      if (this.closed) return;
      const original = originalReference(key, result);
      if (original === null) throw new ApiUnknown(true);
      this.accept(original);
    } catch (error) {
      if (this.closed) return;
      this.publish({
        fieldErrors: error instanceof ApiRejected ? fieldErrors(error) : {},
        submitError: message(error, '暂时无法确认登记请求，请核对原结果'),
      });
    } finally {
      this.publish({ busy: false });
    }
  }

  reconcileReceipt(record: PendingSummary, result: RecoveryLookup) {
    if (this.closed || record.path !== PATH) return;
    const original = originalReference(record.key, result);
    if (original !== null) {
      this.accept(original);
      return;
    }
    const local = result.local;
    if (
      this.value.commandKey === record.key &&
      local &&
      'final_state' in local &&
      local.http_status !== 202
    ) {
      this.publish({ commandKey: null });
      this.saveDraft();
    }
  }

  private accept(original: Original) {
    const selected = this.value.original;
    if (selected !== null && selected.operationId >= original.operationId) {
      if (
        selected.operationId === original.operationId &&
        (selected.key !== original.key || selected.repositoryId !== original.repositoryId)
      )
        throw TypeError('Original registration identity differs');
      return;
    }
    this.cancelRead();
    this.publish({ original, operation: null, operationError: null, submitError: null });
    this.saveDraft();
  }

  observeOperation(operation: RepositoryOperation) {
    if (this.closed || operation.operation_type !== 'REGISTER_REPOSITORY') return;
    const selected = this.value.original;
    if (selected !== null && selected.key === operation.idempotency_key) {
      if (selected.operationId !== operation.id || selected.repositoryId !== operation.resource_id)
        throw TypeError('Original registration resource differs');
      this.publish({ operation, operationError: null });
    }
    if (this.value.commandKey !== operation.idempotency_key) return;
    if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(operation.status)) return;
    this.publish({
      fields: operation.status === 'SUCCEEDED' ? emptyFields : this.value.fields,
      commandKey: null,
      submitError: null,
    });
    this.saveDraft();
  }

  async restoreCompletion(records: readonly PendingSummary[]) {
    const key = this.value.commandKey;
    if (
      !this.visible ||
      this.closed ||
      this.value.busy ||
      key === null ||
      this.restoring?.key === key ||
      records.some((record) => record.key === key)
    )
      return;
    const attempt = { key };
    this.restoring = attempt;
    try {
      const local = await this.recovery.store.receipt(key);
      if (this.restoring !== attempt || this.closed || this.value.commandKey !== key) return;
      if (local === null) {
        this.publish({ operationError: '暂未找到当前草稿关联的原请求记录' });
        return;
      }
      if (local.path !== PATH || local.key !== key)
        throw TypeError('Original local receipt differs');
      if (local.http_status !== 202) {
        this.publish({ commandKey: null });
        this.saveDraft();
        return;
      }
      const operationId = positiveInteger(local.operation_id);
      await this.readOperation(key, operationId);
    } catch (error) {
      if (this.restoring === attempt && this.value.commandKey === key)
        this.publish({ operationError: message(error, '暂时无法核对原登记结果') });
    } finally {
      if (this.restoring === attempt) this.restoring = null;
    }
  }

  async read(pending: PendingSummary | null) {
    const original = this.value.original;
    if (original === null) return;
    const useRecovery = pending?.key === original.key && pending.status === 'ACCEPTED';
    await this.readOperation(original.key, original.operationId, useRecovery);
  }

  private async readOperation(key: string, operationId: number, useRecovery = false) {
    if (!this.visible || this.closed || this.readRequest !== null) return;
    const request = new AbortController();
    this.readRequest = request;
    this.publish({ operationLoading: true, operationError: null });
    try {
      if (useRecovery) {
        const previous = this.value.operation;
        await this.recovery.reconcileOperation(key, request.signal);
        if (request.signal.aborted || this.closed || this.value.operation !== previous) return;
      }
      const { data: operation } = await this.api.repositoryOperation(operationId, request.signal);
      if (request.signal.aborted || this.closed) return;
      if (
        operation.id !== operationId ||
        operation.idempotency_key !== key ||
        operation.operation_type !== 'REGISTER_REPOSITORY'
      )
        throw TypeError('Original registration operation differs');
      const selected = this.value.original;
      if (selected === null || selected.operationId < operationId) {
        this.publish({ original: { key, operationId, repositoryId: operation.resource_id } });
        this.saveDraft();
      }
      this.observeOperation(operation);
    } catch (error) {
      if (!request.signal.aborted && !this.closed)
        this.publish({ operationError: message(error, '暂时无法读取原登记操作') });
    } finally {
      if (this.readRequest === request) {
        this.readRequest = null;
        this.publish({ operationLoading: false });
      }
    }
  }

  resume() {
    if (!this.closed) this.visible = true;
  }
  private cancelRead() {
    this.readRequest?.abort();
    this.readRequest = null;
    this.publish({ operationLoading: false });
  }
  pause() {
    this.visible = false;
    this.restoring = null;
    this.cancelRead();
  }
  dispose() {
    this.pause();
    this.closed = true;
    this.listeners.clear();
  }
}
