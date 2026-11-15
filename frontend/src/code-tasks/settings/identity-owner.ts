import { ApiRejected, ApiUnknown, exact, positiveInteger } from '../../api/client.ts';
import type { PagePagination } from '../../api/client.ts';
import { text, time } from '../../api/decoding.ts';
import { commandSha256 } from '../../api/code-command-snapshot.ts';
import type { CheckSetVersion } from '../../api/code-check-sets.ts';
import type { ExecutionProfileVersion } from '../../api/code-execution-profiles.ts';
import type { WalleApi } from '../../api/walle.ts';
import { configurationCollection } from '../../api/code-configuration-identities.ts';
import type {
  ConfigurationIdentityKind,
  ConfigurationIdentityRow,
} from '../../api/code-configuration-identities.ts';
import { normalizeOrdinary } from '../../shared/text.ts';
import { CommandStorageError } from '../command-recovery-store.ts';
import type { CommandRecovery, RecoveryLookup } from '../command-recovery.ts';
import { uuid } from '../command-recovery-model.ts';
import type { PendingSummary } from '../command-recovery-model.ts';

type Api = Pick<
  WalleApi,
  | 'codeExecutionProfiles'
  | 'codeCheckSets'
  | 'codeExecutionProfileVersions'
  | 'codeCheckSetVersions'
>;
type Recovery = Pick<CommandRecovery, 'stageIntent' | 'send'> & {
  store: Pick<CommandRecovery['store'], 'origin' | 'list'>;
};
export type IdentitySettingsState = Readonly<{
  name: string;
  busy: boolean;
  blockedKey: string | null;
  submitError: string | null;
  draftWarning: string | null;
  identities: Readonly<{
    items: readonly ConfigurationIdentityRow[];
    pagination: PagePagination;
  }> | null;
  loading: boolean;
  requestedPage: number;
  readError: string | null;
  selectedId: number | null;
  versions: Readonly<{
    items: readonly (ExecutionProfileVersion | CheckSetVersion)[];
    pagination: PagePagination;
  }> | null;
  versionsLoading: boolean;
  requestedVersionPage: number;
  versionsError: string | null;
}>;
function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : fallback;
}
export class IdentitySettingsOwner {
  readonly kind: ConfigurationIdentityKind;
  private readonly api: Api;
  private readonly recovery: Recovery;
  private readonly storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  private readonly draftKey: string;
  private draftCommandKey: string | null = null;
  private readonly listeners = new Set<() => void>();
  private readRequest: AbortController | null = null;
  private versionRequest: AbortController | null = null;
  private readEpoch = 0;
  private versionEpoch = 0;
  private pendingEpoch = 0;
  private visible = false;
  private closed = false;
  private value: IdentitySettingsState = Object.freeze({
    name: '',
    busy: false,
    blockedKey: null,
    submitError: null,
    draftWarning: null,
    identities: null,
    loading: false,
    requestedPage: 1,
    readError: null,
    selectedId: null,
    versions: null,
    versionsLoading: false,
    requestedVersionPage: 1,
    versionsError: null,
  });
  constructor(
    api: Api,
    recovery: Recovery,
    kind: ConfigurationIdentityKind,
    storage: Pick<Storage, 'getItem' | 'setItem'> | null,
  ) {
    this.api = api;
    this.recovery = recovery;
    this.kind = kind;
    this.storage = storage;
    this.draftKey = 'walle:v2.0:code:settings:' + recovery.store.origin + ':' + kind;
    try {
      if (storage === null) throw Error('Draft storage unavailable');
      const raw = storage.getItem(this.draftKey);
      if (raw !== null) {
        const draft = exact(JSON.parse(raw), [
          'schema_version',
          'name',
          'updated_at',
          'command_key',
        ]);
        if (draft.schema_version !== 1) throw Error('Draft invalid');
        time(draft.updated_at);
        const name = text(draft.name);
        this.draftCommandKey = draft.command_key === null ? null : uuid(draft.command_key);
        this.value = Object.freeze({ ...this.value, name });
      }
    } catch {
      this.value = Object.freeze({
        ...this.value,
        draftWarning: '草稿暂存不可用，离开后可能无法恢复',
      });
    }
  }
  getSnapshot = (): IdentitySettingsState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(changes: Partial<IdentitySettingsState>) {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) listener();
  }
  private saveDraft() {
    try {
      if (this.storage === null) throw Error('Draft storage unavailable');
      this.storage.setItem(
        this.draftKey,
        JSON.stringify({
          schema_version: 1,
          name: this.value.name,
          updated_at: new Date().toISOString(),
          command_key: this.draftCommandKey,
        }),
      );
      this.publish({ draftWarning: null });
    } catch {
      this.publish({ draftWarning: '草稿暂存不可用，离开后可能无法恢复' });
    }
  }
  edit(name: string) {
    if (this.closed || this.value.busy || this.value.blockedKey !== null) return;
    this.draftCommandKey = null;
    this.publish({ name, submitError: null });
    this.saveDraft();
  }
  async syncPending() {
    if (this.closed) return;
    const epoch = ++this.pendingEpoch;
    try {
      const records = await this.recovery.store.list();
      if (this.closed || epoch !== this.pendingEpoch) return;
      const pending = records.find(
        (record) => record.path === configurationCollection(this.kind).path,
      );
      this.publish({ blockedKey: pending?.key ?? null });
    } catch (error) {
      if (!this.closed && epoch === this.pendingEpoch)
        this.publish({ submitError: errorMessage(error, '暂时无法核对原请求') });
    }
  }
  async read(page = 1) {
    if (this.closed || !this.visible || this.readRequest !== null) return;
    const request = new AbortController(),
      epoch = ++this.readEpoch;
    this.readRequest = request;
    this.publish({ loading: true, readError: null, requestedPage: page });
    try {
      const response = await (this.kind === 'EXECUTION_PROFILE'
        ? this.api.codeExecutionProfiles(page, request.signal)
        : this.api.codeCheckSets(page, request.signal));
      const pagination = response.meta.pagination;
      if (pagination === undefined || !('page' in pagination))
        throw new TypeError('Actual page required');
      if (!this.closed && epoch === this.readEpoch)
        this.publish({
          identities: Object.freeze({ items: response.data.items, pagination }),
          readError: null,
        });
    } catch (error) {
      if (!this.closed && epoch === this.readEpoch)
        this.publish({ readError: errorMessage(error, '暂时无法读取配置列表') });
    } finally {
      if (!this.closed && epoch === this.readEpoch) this.publish({ loading: false });
      if (this.readRequest === request) this.readRequest = null;
    }
  }
  select(id: number) {
    positiveInteger(id);
    if (
      this.closed ||
      this.value.busy ||
      !this.value.identities?.items.some((row) => row.id === id)
    )
      return;
    this.versionRequest?.abort();
    this.versionRequest = null;
    ++this.versionEpoch;
    this.publish({ selectedId: id, versions: null, versionsError: null, versionsLoading: false });
    void this.readVersions();
  }
  async readVersions(page = 1) {
    const id = this.value.selectedId;
    if (this.closed || !this.visible || id === null || this.versionRequest !== null) return;
    const request = new AbortController(),
      epoch = ++this.versionEpoch;
    this.versionRequest = request;
    this.publish({ versionsLoading: true, versionsError: null, requestedVersionPage: page });
    try {
      const response = await (this.kind === 'EXECUTION_PROFILE'
        ? this.api.codeExecutionProfileVersions(id, page, request.signal)
        : this.api.codeCheckSetVersions(id, page, request.signal));
      const pagination = response.meta.pagination;
      if (pagination === undefined || !('page' in pagination))
        throw TypeError('Actual version page required');
      if (!this.closed && epoch === this.versionEpoch && this.value.selectedId === id)
        this.publish({
          versions: Object.freeze({ items: response.data.items, pagination }),
          versionsError: null,
        });
    } catch (error) {
      if (!this.closed && epoch === this.versionEpoch)
        this.publish({ versionsError: errorMessage(error, '暂时无法读取配置版本') });
    } finally {
      if (!this.closed && epoch === this.versionEpoch) this.publish({ versionsLoading: false });
      if (this.versionRequest === request) this.versionRequest = null;
    }
  }
  private createdId(data: unknown): number {
    const result = exact(data, ['resource_kind', 'resource_id']);
    if (result.resource_kind !== this.kind) throw TypeError('Created identity differs');
    return positiveInteger(result.resource_id);
  }
  private showCreated(id: number) {
    ++this.pendingEpoch;
    this.retireReads();
    this.publish({
      name: '',
      selectedId: id,
      requestedPage: 1,
      versions: null,
      versionsError: null,
      versionsLoading: false,
      requestedVersionPage: 1,
      blockedKey: null,
      submitError: null,
    });
    this.draftCommandKey = null;
    this.saveDraft();
    void this.read(1);
    void this.readVersions(1);
  }
  async reconcileCreated(record: PendingSummary, result: RecoveryLookup, signal?: AbortSignal) {
    const local = result.local;
    const receipt = result.original_receipt;
    if (
      this.closed ||
      this.value.busy ||
      record.path !== configurationCollection(this.kind).path ||
      local === null ||
      !('final_state' in local) ||
      local.final_state !== 'CONFIRMED' ||
      local.key !== record.key ||
      local.http_status !== 201 ||
      receipt?.original_outcome?.success !== true
    )
      return;
    const name = this.value.name;
    const id = this.createdId(receipt.original_outcome.data);
    const draftKey = this.draftCommandKey;
    const digest =
      draftKey === record.key
        ? await commandSha256(JSON.stringify({ name: normalizeOrdinary(name) }))
        : null;
    if (signal?.aborted || this.closed || this.value.busy) return;
    const sameDraft =
      draftKey === record.key &&
      this.draftCommandKey === draftKey &&
      this.value.name === name &&
      digest !== null &&
      digest === local.body_sha256;
    if (sameDraft) this.showCreated(id);
    else void this.read(this.value.requestedPage);
  }
  async submit() {
    if (this.closed || this.value.busy || this.value.blockedKey !== null) return;
    let name: string;
    try {
      name = normalizeOrdinary(this.value.name);
      if (!name || name.includes('\0')) throw TypeError('Invalid name');
    } catch {
      this.publish({ submitError: '请填写有效的配置名称' });
      return;
    }
    this.publish({ busy: true, submitError: null });
    let stagedKey: string | null = null;
    try {
      const staged = await this.recovery.stageIntent(configurationCollection(this.kind).path, {
        name,
      });
      if (this.closed) return;
      if (staged.kind !== 'PREPARED') {
        ++this.pendingEpoch;
        this.publish({
          blockedKey: staged.kind === 'EXISTING' ? staged.record.key : null,
          submitError: '此配置操作已有原请求，请先核对原结果',
        });
        return;
      }
      stagedKey = staged.record.key;
      this.draftCommandKey = stagedKey;
      this.saveDraft();
      const response = await this.recovery.send(staged.record.key, staged.record.record_revision);
      if (this.closed) return;
      this.showCreated(this.createdId(response.response.data));
    } catch (error) {
      if (this.closed) return;
      this.publish({ submitError: errorMessage(error, '命令恢复暂不可用，尚未确认提交') });
      if (stagedKey !== null) {
        ++this.pendingEpoch;
        this.publish({ blockedKey: stagedKey });
      }
      await this.syncPending();
    } finally {
      if (!this.closed) this.publish({ busy: false });
    }
  }
  resume() {
    if (this.closed) return;
    this.visible = true;
    void this.syncPending();
    void this.read(this.value.requestedPage);
    void this.readVersions(this.value.requestedVersionPage);
  }
  private retireReads() {
    ++this.readEpoch;
    ++this.versionEpoch;
    this.readRequest?.abort();
    this.versionRequest?.abort();
    this.readRequest = null;
    this.versionRequest = null;
    this.publish({ loading: false, versionsLoading: false });
  }
  pause() {
    this.visible = false;
    this.retireReads();
  }
  dispose() {
    this.pause();
    this.closed = true;
    this.listeners.clear();
  }
}
