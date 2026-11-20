import { Ctx, Container, Clock } from '@milkdown/kit/ctx';
import { WalleApi } from '../../src/api/walle.ts';
import { snapshotObject } from '../../src/api/client.ts';
import { authorizationScope } from '../../src/api/code-authorizations.ts';
/** Owned browser IndexedDB diagnostics only; no business API or model. */
import { ApiClient, exact, positiveInteger, object } from '../../src/api/client.ts';
import { prepareCodeCommand } from '../../src/api/code-command-snapshot.ts';
import { registeredCommand } from '../../src/api/code-command-registry.ts';
import {
  CommandRecoveryStore,
  CommandStorageError,
} from '../../src/code-tasks/command-recovery-store.ts';
import { originalFrozen } from '../../src/code-tasks/command-recovery-model.ts';
import type { JsonObject } from '../../src/api/client.ts';
import { CommandRecovery } from '../../src/code-tasks/command-recovery.ts';
import type { OperationReader } from '../../src/code-tasks/command-recovery.ts';
import type { CommandIdentity } from '../../src/api/code-command-registry.ts';
import { pendingSummary } from '../../src/code-tasks/command-recovery-model.ts';
import type { PendingSummary } from '../../src/code-tasks/command-recovery-model.ts';
import type { CommandReceipt } from '../../src/api/code-command-receipts.ts';
import type { FrozenCodeAction } from '../../src/api/code-command-snapshot.ts';
import { ERROR_MESSAGES } from '../../src/api/code-errors.ts';
import {
  CONFIGURATION_IDENTITY_BINDINGS,
  configurationCollection,
} from '../../src/api/code-configuration-identities.ts';
import type { ConfigurationIdentityKind } from '../../src/api/code-configuration-identities.ts';

function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
function safeName(name: string): void {
  check(/^walle-v20-idb-probe-[a-z0-9-]+$/.test(name), 'owned probe database required');
}
const pathFor = (id: number) => '/api/v1/code-tasks/' + id + '/start';
async function make(path = pathFor(7)): Promise<FrozenCodeAction<unknown>> {
  const scope = registeredCommand('POST', path, crypto.randomUUID());
  return prepareCodeCommand(
    new ApiClient(() => {
      throw Error('No real HTTP in storage probe');
    }),
    path,
    { expected_state_version: 1 },
    {
      decoder_kind: scope.decoder_kind,
      success_status: [202],
      errors: ['INVALID_STATE'],
      validate_input(value) {
        positiveInteger(exact(value, ['expected_state_version']).expected_state_version);
      },
      decode(value) {
        return value;
      },
    },
    location.origin,
  );
}
function emptyReceipt(): CommandReceipt<unknown> {
  return {
    lookup_status: 'NOT_FOUND',
    record_status: null,
    original_http_status: null,
    original_outcome: null,
    task_id: null,
    testing_task_id: null,
    operation_id: null,
  };
}
function closedReceipt(path: string): CommandReceipt<unknown> {
  return {
    ...emptyReceipt(),
    lookup_status: 'FOUND',
    record_status: 'CLOSED',
    original_http_status: 409,
    original_outcome: {
      success: false,
      data: null,
      error: {
        code: 'COMMAND_CLOSED',
        message: ERROR_MESSAGES.COMMAND_CLOSED,
        details: { method: 'POST', path, closed_at: new Date().toISOString() },
      },
    },
  };
}
async function rawDatabase(name: string): Promise<IDBDatabase> {
  safeName(name);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 2);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function rawChange(name: string, change: (store: IDBObjectStore) => void): Promise<void> {
  const database = await rawDatabase(name);
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = database.transaction('pending_commands', 'readwrite');
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
      change(tx.objectStore('pending_commands'));
    });
  } finally {
    database.close();
  }
}
async function remove(name: string): Promise<void> {
  safeName(name);
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase(name);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(Error('Owned probe connection was not closed'));
  });
}
async function failure(
  task: Promise<unknown>,
  reason?: CommandStorageError['reason'],
): Promise<void> {
  try {
    await task;
  } catch (error) {
    if (reason !== undefined)
      check(
        error instanceof CommandStorageError && error.reason === reason,
        'unexpected storage error ' + String(error),
      );
    return;
  }
  throw Error('Expected refusal');
}
export async function storageProbe(): Promise<{ checks: readonly string[] }> {
  const checks: string[] = [];
  const stores: CommandRecoveryStore[] = [];
  const names: string[] = [];
  const owned = () => {
    const name = 'walle-v20-idb-probe-' + crypto.randomUUID();
    names.push(name);
    const store = new CommandRecoveryStore({ name });
    stores.push(store);
    return { name, store };
  };
  try {
    const { name, store } = owned(),
      other = new CommandRecoveryStore({ name });
    stores.push(other);
    const first = await make(),
      second = await make();
    const reserved = await Promise.all([store.reserve(first.frozen), other.reserve(second.frozen)]);
    check(
      reserved.filter((row) => row.kind === 'PREPARED').length === 1,
      'unique intent must have one winner',
    );
    check(
      reserved.filter((row) => row.kind === 'EXISTING').length === 1,
      'other original retained',
    );
    check(
      reserved.every((row) => row.kind !== 'RESOLVED'),
      'new intent is not resolved',
    );
    const initial = (await store.list())[0]!;
    check(
      !Object.hasOwn(initial, 'body_json') && !Object.hasOwn(initial, 'body_sha256'),
      'list leaked body',
    );
    const detail = await store.detail(initial.key);
    check(detail !== null, 'actual detail missing');
    const frozen = originalFrozen(detail);
    const gates = await Promise.all([
      store.dispatch(initial, frozen, crypto.randomUUID()),
      other.dispatch(initial, frozen, crypto.randomUUID()),
    ]);
    check(gates.filter(Boolean).length === 1, 'two gates passed same revision');
    const dispatched = gates.find(Boolean)!;
    check(
      dispatched.dispatch_count === 1 && dispatched.status === 'DISPATCHING',
      'dispatch count not committed',
    );
    check((await other.cancelUnsent(initial)) === null, 'old cancel erased dispatched record');
    check(
      (await store.dispatch(dispatched, frozen, crypto.randomUUID())) === null,
      'first gate reused',
    );
    const replayed = await other.dispatch(dispatched, frozen, crypto.randomUUID(), true);
    check(replayed?.dispatch_count === 2, 'explicit original replay not counted');
    const requested = await store.requestClose(replayed);
    check(requested?.close_state === 'REQUESTED', 'close not saved');
    check(
      (await other.dispatch(requested, frozen, crypto.randomUUID(), true)) === null,
      'closed intent replayed',
    );
    check((await store.cancelUnsent(requested)) === null, 'requested close cancelled locally');
    const cancelled = await other.observe(requested, closedReceipt(requested.path));
    check(
      cancelled && 'final_state' in cancelled && cancelled.final_state === 'CLOSED_UNEXECUTED',
      'closed terminal missing',
    );
    check((await store.detail(initial.key)) === null, 'pending not atomically removed');
    check((await store.reserve(frozen)).kind === 'RESOLVED', 'old key revived through reserve');
    const replacement = await store.reserve((await make()).frozen);
    check(replacement.kind === 'PREPARED', 'terminal did not release original intent');
    check(
      (await other.observe(requested, closedReceipt(requested.path))) === null,
      'late result revived old key',
    );
    check((await store.list()).length === 1, 'late old result cleared replacement');
    store.close();
    other.close();
    const reopened = new CommandRecoveryStore({ name });
    stores.push(reopened);
    check((await reopened.list()).length === 1, 'connection reopen lost pending');
    const unchanged = (await reopened.list())[0]!;
    const looked = await reopened.observe(unchanged, emptyReceipt());
    check(looked && !('final_state' in looked), 'NOT_FOUND cleared pending');
    check(
      (await reopened.cancelUnsent(looked)) === null,
      'lookup observation treated as never sent proof',
    );
    check(
      (await reopened.pruneResolved(new Date(Date.now() + 31 * 86400000).toISOString())) === 1,
      'old tombstone missing',
    );
    check((await reopened.list()).length === 1, 'prune removed pending');
    checks.push(
      'unique intent / two-connection CAS / dispatch count / close gate / atomic tombstone / late result / reopen / pending never expires',
    );

    const unsent = owned(),
      unsentAction = await make(pathFor(20));
    const draft = await unsent.store.reserve(unsentAction.frozen);
    check(draft.kind === 'PREPARED', 'unsent fixture missing');
    const local = await unsent.store.cancelUnsent(draft.record);
    check(local?.final_state === 'CANCELLED_UNSENT', 'pure unsent cancel not recorded');
    check(
      (await unsent.store
        .dispatch(draft.record, unsentAction.frozen, crypto.randomUUID())
        .catch(() => null)) === null,
      'old sender passed cancel',
    );
    checks.push(
      'explicit never-dispatched cancellation is atomic and cannot create a new send gate',
    );

    const damaged = owned(),
      damagedAction = await make(pathFor(30));
    const dr = await damaged.store.reserve(damagedAction.frozen);
    check(dr.kind === 'PREPARED', 'damaged fixture');
    await rawChange(damaged.name, (raw) =>
      raw.put(
        { ...objectFrom(damagedAction.frozen, dr.record), body_json: null, body_sha256: 'damaged' },
        [location.origin, dr.record.key],
      ),
    );
    const damagedSummary = (await damaged.store.list())[0]!;
    const close = await damaged.store.requestClose(damagedSummary);
    check(close, 'damaged identity could not close');
    const damagedTerminal = await damaged.store.observe(close, closedReceipt(close.path));
    check(
      damagedTerminal && 'final_state' in damagedTerminal && damagedTerminal.body_sha256 === null,
      'closed damage did not keep nullable body digest',
    );
    checks.push(
      'damaged body cannot replay but safe original identity can close and retain body digest null',
    );

    const accepted = owned(),
      acceptedAction = await make(pathFor(40));
    const ar = await accepted.store.reserve(acceptedAction.frozen);
    check(ar.kind === 'PREPARED', 'accepted fixture');
    const ag = await accepted.store.dispatch(ar.record, acceptedAction.frozen, crypto.randomUUID());
    check(ag, 'accepted gate');
    const receipt: CommandReceipt<unknown> = {
      lookup_status: 'FOUND',
      record_status: 'SUCCEEDED',
      original_http_status: 202,
      original_outcome: { success: true, data: { task_id: 40, operation_id: 42 }, error: null },
      task_id: 40,
      testing_task_id: null,
      operation_id: 42,
    };
    const observed = await accepted.store.observe(ag, receipt);
    check(
      observed && !('final_state' in observed) && observed.status === 'ACCEPTED',
      '202 resolved prematurely',
    );
    const uncertain = await accepted.store.markUnknown(observed);
    check(uncertain?.status === 'ACCEPTED', 'known acceptance degraded');
    check(
      (await accepted.store.completeOperation(uncertain, 43, 'SUCCEEDED')) === null,
      'foreign operation completed',
    );
    const actual = await accepted.store.completeOperation(uncertain, 42, 'FAILED');
    check(
      actual?.final_state === 'CONFIRMED' && actual.operation_id === 42,
      'original failed operation not resolved',
    );
    checks.push(
      '202 persists original associations until exact terminal operation; transport loss does not erase acceptance',
    );

    const aborted = owned(),
      abortAction = await make(pathFor(50));
    const before = await aborted.store.reserve(abortAction.frozen);
    check(before.kind === 'PREPARED', 'abort fixture');
    const nativePut = IDBObjectStore.prototype.put;
    let sent = 0,
      successSeen = false;
    IDBObjectStore.prototype.put = function (...args: Parameters<IDBObjectStore['put']>) {
      const request = nativePut.apply(this, args);
      if (this.name === 'pending_commands' && this.transaction.db.name === aborted.name) {
        request.addEventListener(
          'success',
          () => {
            successSeen = true;
            this.transaction.abort();
          },
          { once: true },
        );
      }
      return request;
    };
    try {
      await failure(
        aborted.store
          .dispatch(before.record, abortAction.frozen, crypto.randomUUID())
          .then((gate) => {
            if (gate) sent++;
          }),
        'UNAVAILABLE',
      );
    } finally {
      IDBObjectStore.prototype.put = nativePut;
    }
    check(successSeen && sent === 0, 'put success incorrectly authorized sending');
    const afterAbort = new CommandRecoveryStore({ name: aborted.name });
    stores.push(afterAbort);
    check(
      (await afterAbort.list())[0]!.dispatch_count === 0,
      'abort did not restore original counter',
    );
    checks.push(
      'real request success followed by transaction abort never grants dispatch; previous record preserved',
    );

    const capacity = owned();
    for (let index = 1; index <= 100; index++)
      check(
        (await capacity.store.reserve((await make(pathFor(1000 + index))).frozen)).kind ===
          'PREPARED',
        'capacity setup',
      );
    await failure(capacity.store.reserve((await make(pathFor(2000))).frozen), 'CAPACITY');
    check((await capacity.store.list()).length === 100, 'capacity evicted pending');
    checks.push('100 real pending records / 101st refused / no pending eviction');

    const quota = owned(),
      qa = await make(pathFor(60)),
      nativeAdd = IDBObjectStore.prototype.add;
    IDBObjectStore.prototype.add = function (...args: Parameters<IDBObjectStore['add']>) {
      if (this.transaction.db.name === quota.name)
        throw new DOMException('Injected quota', 'QuotaExceededError');
      return nativeAdd.apply(this, args);
    };
    try {
      await failure(quota.store.reserve(qa.frozen), 'CAPACITY');
    } finally {
      IDBObjectStore.prototype.add = nativeAdd;
    }
    check((await quota.store.list()).length === 0, 'quota created ghost pending');
    checks.push('injected quota refusal saves nothing and provides no ordinary send gate');

    const upgrade = owned();
    await upgrade.store.reserve((await make(pathFor(70))).frozen);
    const upgraded = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(upgrade.name, 3);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    upgraded.close();
    await failure(upgrade.store.list(), 'UNAVAILABLE');
    checks.push('real versionchange closes this owner and prevents another dispatch');

    return { checks: Object.freeze(checks) };
  } catch (error) {
    throw new Error('After ' + checks.join(' | ') + ': ' + String(error), { cause: error });
  } finally {
    for (const store of stores) store.close();
    await Promise.all(stores.map((store) => store.settle()));
    for (const name of names) await remove(name);
  }
}
function objectFrom(frozen: FrozenCodeAction<unknown>['frozen'], metadata: PendingSummary) {
  return { ...metadata, ...frozen, recovery_mode: 'REPLAY_SAME_KEY' };
}

/** Two real browser tabs use these only with the same explicit owned name. */
const tabOwners = new Map<string, CommandRecoveryStore>();
export async function stageInTab(
  name: string,
): Promise<{ kind: string; key: string; revision: number }> {
  safeName(name);
  const store = new CommandRecoveryStore({ name });
  tabOwners.set(name, store);
  const staged = await store.reserve((await make(pathFor(3000))).frozen);
  check(staged.kind !== 'RESOLVED', 'unexpected resolved fixture');
  return { kind: staged.kind, key: staged.record.key, revision: staged.record.record_revision };
}
export async function dispatchInTab(
  name: string,
): Promise<{ passed: boolean; count: number | null }> {
  safeName(name);
  const store = tabOwners.get(name);
  check(store, 'stage this actual tab first');
  const current = (await store.list())[0]!;
  const detail = await store.detail(current.key);
  check(detail, 'tab detail');
  const gate = await store.dispatch(current, originalFrozen(detail), crypto.randomUUID());
  return { passed: gate !== null, count: gate?.dispatch_count ?? null };
}
export async function closeTabOwner(name: string, cleanup = false): Promise<void> {
  safeName(name);
  const store = tabOwners.get(name);
  check(store, 'original tab owner required');
  store.close();
  await store.settle();
  tabOwners.delete(name);
  if (cleanup) await remove(name);
}

/** Real storage with scripted native API responses; no business server effects. */
export async function ownerProbe(): Promise<{ checks: readonly string[] }> {
  const name = 'walle-v20-idb-probe-' + crypto.randomUUID();
  const checks: string[] = [];
  const stores: CommandRecoveryStore[] = [],
    owners: CommandRecovery[] = [];
  const calls: { path: string; method: string; key: string | null; body: string | null }[] = [];
  const store = new CommandRecoveryStore({ name });
  stores.push(store);
  let server: CommandReceipt<unknown> = emptyReceipt(),
    mode: 'DROP' | 'ACK' = 'DROP',
    keys = 0;
  let operationStatus = 'RUNNING';
  function success(data: unknown, status = 200): Response {
    return new Response(
      JSON.stringify({
        success: true,
        data,
        error: null,
        meta: { request_id: crypto.randomUUID() },
      }),
      { status, headers: { 'Content-Type': 'application/json' } },
    );
  }
  const send: typeof fetch = async (input, options) => {
    check(typeof input === 'string', 'same-origin registered string request required');
    const method = options?.method ?? 'GET';
    const key = new Headers(options?.headers).get('Idempotency-Key');
    const body = typeof options?.body === 'string' ? options.body : null;
    calls.push({ path: input, method, key, body });
    if (method === 'GET') {
      const url = new URL(input, location.origin);
      check(url.pathname === '/api/v1/code-command-receipts', 'wrong original module GET');
      check(!key && body === null, 'lookup acquired mutation key/body');
      return success(server);
    }
    check(key, 'original key required');
    if (input === '/api/v1/command-intents/close') {
      const pending = summaryFor(await store.detail(key));
      check(pending.close_state === 'REQUESTED', 'close POST before committed REQUESTED');
      const parsed = exact(JSON.parse(body!), ['method', 'path']);
      check(parsed.method === 'POST', 'close original method');
      server = closedReceipt(parsed.path as string);
      return success({ close_status: 'CLOSED', original_receipt: server });
    }
    const pending = summaryFor(await store.detail(key));
    check(
      pending.status === 'DISPATCHING' && pending.dispatch_count > 0,
      'HTTP before durable send gate',
    );
    if (mode === 'DROP') throw new TypeError('Scripted lost HTTP result');
    const original = registeredCommand('POST', input, key);
    const data = { task_id: original.parameters.task_id!, operation_id: 91 };
    server = {
      lookup_status: 'FOUND',
      record_status: 'SUCCEEDED',
      original_http_status: 202,
      original_outcome: { success: true, data, error: null },
      task_id: data.task_id,
      testing_task_id: null,
      operation_id: 91,
    };
    return success(data, 202);
  };
  const client = new ApiClient(send, () => {
    keys++;
    return crypto.randomUUID();
  });
  function native(path: string) {
    return {
      decoder_kind: registeredCommand('POST', path, crypto.randomUUID()).decoder_kind,
      success_status: [202] as const,
      errors: ['INVALID_STATE'] as const,
      validate_input(value: JsonObject) {
        positiveInteger(exact(value, ['expected_state_version']).expected_state_version);
      },
      decode(value: unknown, original: CommandIdentity) {
        const row = exact(value, ['task_id', 'operation_id']);
        check(row.task_id === original.parameters.task_id, 'wrong original response task');
        return {
          task_id: positiveInteger(row.task_id),
          operation_id: positiveInteger(row.operation_id),
        };
      },
    };
  }
  const reader: OperationReader = async (_original, association) => ({
    ...association,
    status: operationStatus,
  });
  const owner = new CommandRecovery(client, store, [native(pathFor(21))], reader);
  owners.push(owner);
  try {
    const staged = await owner.stage(pathFor(21), { expected_state_version: 1 });
    check(!('final_state' in staged), 'stage terminal');
    check(keys === 1 && calls.length === 0, 'stage dispatched or rekeyed');
    await failure(owner.send(staged.key, staged.record_revision));
    let pending = (await store.list())[0]!;
    check(pending.status === 'UNKNOWN' && pending.dispatch_count === 1, 'lost send not retained');
    const existing = await owner.stageIntent(pathFor(21), { expected_state_version: 2 });
    check(
      existing.kind === 'EXISTING' && existing.record.key === staged.key && keys === 1,
      'pending intent minted second original key or changed identity',
    );
    const beforeRead = calls.filter((row) => row.method === 'POST').length;
    await owner.lookup(staged.key);
    check(
      calls.filter((row) => row.method === 'POST').length === beforeRead,
      'GET replayed original',
    );
    pending = (await store.list())[0]!;
    check(pending.lookup_status === 'NOT_FOUND', 'missing receipt not saved');
    const replayOptions = await owner.inspectOriginal(staged.key, pending.record_revision, true);
    check(
      replayOptions.replay && replayOptions.close,
      'verified original not available for replay/close',
    );
    await failure(owner.replayOriginal(staged.key, pending.record_revision));
    pending = (await store.list())[0]!;
    check(
      pending.dispatch_count === 2 && pending.lookup_status === null,
      'new dispatch reused the prior lookup observation',
    );
    const nextOptions = await owner.inspectOriginal(staged.key, pending.record_revision, true);
    check(!nextOptions.replay && nextOptions.close, 'replay allowed before a new original lookup');
    const closed = await owner.closeOriginal(staged.key, pending.record_revision);
    check(
      closed.local &&
        'final_state' in closed.local &&
        closed.local.final_state === 'CLOSED_UNEXECUTED',
      'owner did not resolve closed',
    );
    check(keys === 1, 'close minted another action key');
    const actualClose = calls.find((row) => row.path === '/api/v1/command-intents/close')!;
    check(
      actualClose.key === staged.key && Object.keys(JSON.parse(actualClose.body!)).length === 2,
      'close included original body or wrong key',
    );
    const replacement = await owner.stage(pathFor(21), { expected_state_version: 1 });
    check(
      !('final_state' in replacement) && replacement.key !== staged.key,
      'new explicit intent did not get new key',
    );
    const count = calls.length;
    await owner.lookup(staged.key);
    check(
      calls.length === count && (await store.list())[0]!.key === replacement.key,
      'old tombstone lookup fetched/revived old request or cleared new draft',
    );
    checks.push(
      'actual owner stages before HTTP, lost send stays pending, lookup never replays, durable REQUESTED closes original key, late old lookup preserves replacement',
    );

    mode = 'ACK';
    server = emptyReceipt();
    const accepted = await owner.send(replacement.key, replacement.record_revision);
    check(
      accepted.local && !('final_state' in accepted.local) && accepted.local.status === 'ACCEPTED',
      'owner resolved 202 early',
    );
    pending = (await store.list())[0]!;
    const closeCalls = calls.filter((row) => row.path === '/api/v1/command-intents/close').length;
    const received = await owner.closeOriginal(pending.key, pending.record_revision);
    check(
      received.local &&
        !('final_state' in received.local) &&
        received.local.close_state === 'ALREADY_RECEIVED',
      'received command not retained',
    );
    check(
      calls.filter((row) => row.path === '/api/v1/command-intents/close').length === closeCalls,
      'known received fact sent redundant close',
    );
    const noReplay = calls.length;
    await failure(owner.send(received.local.key, received.local.record_revision));
    check(calls.length === noReplay, 'already received closing reopened replay');
    const running = await owner.reconcileOperation(replacement.key);
    check(running && !('final_state' in running), 'RUNNING released pending');
    operationStatus = 'FAILED';
    const terminal = await owner.reconcileOperation(replacement.key);
    check(
      terminal && 'final_state' in terminal && terminal.operation_id === 91,
      'original terminal operation not settled',
    );
    checks.push(
      'strict 202 saves associations, known received close blocks replay, exact operation RUNNING retains and FAILED settles command without declaring task success',
    );

    mode = 'DROP';
    server = emptyReceipt();
    const damaged = await owner.stage(pathFor(22), { expected_state_version: 1 });
    check(!('final_state' in damaged), 'damaged stage');
    const actual = await store.detail(damaged.key);
    await rawChange(name, (raw) =>
      raw.put({ ...object(actual), body_json: null, body_sha256: 'bad' }, [
        location.origin,
        damaged.key,
      ]),
    );
    await owner.lookup(damaged.key);
    const damagedPending = (await store.list())[0]!;
    const damagedOptions = await owner.inspectOriginal(
      damaged.key,
      damagedPending.record_revision,
      true,
    );
    check(
      damagedOptions.close && !damagedOptions.replay,
      'damaged body offered replay or blocked safe close',
    );
    const damagedCalls = calls.length;
    await failure(owner.replayOriginal(damaged.key, damagedPending.record_revision));
    check(calls.length === damagedCalls, 'damaged body replay sent HTTP');
    const closedDamage = await owner.closeOriginal(damaged.key, damagedPending.record_revision);
    check(
      closedDamage.local &&
        'final_state' in closedDamage.local &&
        closedDamage.local.body_sha256 === null,
      'owner could not safely close damaged body',
    );
    checks.push(
      'body damage prohibits restore while native original-identity close remains available',
    );

    let identityKind: ConfigurationIdentityKind = 'EXECUTION_PROFILE';
    let identitySends = 0;
    const identityClient = new ApiClient(async (input, options) => {
      const key = new Headers(options?.headers).get('Idempotency-Key');
      check(
        key && input === configurationCollection(identityKind).path,
        'identity wrong original route/key',
      );
      const committed = summaryFor(await store.detail(key));
      check(
        committed.status === 'DISPATCHING' && committed.dispatch_count === 1,
        'native configuration HTTP before IDB oncomplete',
      );
      check(options?.body === '{"name":"目录契约"}', 'native configuration bytes changed');
      identitySends++;
      return success(
        {
          resource_kind: identityKind,
          resource_id: identityKind === 'EXECUTION_PROFILE' ? 101 : 202,
        },
        201,
      );
    });
    const identityOwner = new CommandRecovery(
      identityClient,
      store,
      CONFIGURATION_IDENTITY_BINDINGS,
      async () => {
        throw Error('Identity command cannot accept an async operation');
      },
    );
    owners.push(identityOwner);
    for (const kind of ['EXECUTION_PROFILE', 'CHECK_SET'] as const) {
      identityKind = kind;
      const staged = await identityOwner.stage(configurationCollection(kind).path, {
        name: '目录契约',
      });
      check(!('final_state' in staged), 'native identity unexpectedly resolved before send');
      const sent = await identityOwner.send(staged.key, staged.record_revision);
      check(
        sent.local && 'final_state' in sent.local && sent.local.final_state === 'CONFIRMED',
        'native 201 identity did not confirm',
      );
      check(
        (await store.detail(staged.key)) === null,
        'native identity pending/body retained after confirmation',
      );
      check(
        (await store.receipt(staged.key))?.http_status === 201,
        'native identity terminal receipt absent',
      );
    }
    check(identitySends === 2, 'native identity dispatch duplicated');
    checks.push(
      'registered configuration identity DTOs send only after real IDB commit and preserve 201 terminal receipts',
    );

    const queryName = 'walle-v20-idb-probe-' + crypto.randomUUID();
    const queryStore = new CommandRecoveryStore({ name: queryName });
    stores.push(queryStore);
    const queryPath = '/api/v1/code-tasks/23/accept';
    const queryNative = {
      ...native(pathFor(23)),
      decoder_kind: registeredCommand('POST', queryPath, crypto.randomUUID()).decoder_kind,
    };
    const firstOwner = new CommandRecovery(client, queryStore, [queryNative], reader);
    owners.push(firstOwner);
    try {
      const query = await firstOwner.stage(queryPath, { expected_state_version: 1 });
      check(!('final_state' in query), 'query fixture');
      firstOwner.dispose();
      const coldStore = new CommandRecoveryStore({ name: queryName });
      stores.push(coldStore);
      const cold = new CommandRecovery(client, coldStore, [queryNative], reader);
      owners.push(cold);
      const before = calls.length;
      await failure(cold.send(query.key, query.record_revision));
      check(
        calls.length === before && (await coldStore.list())[0]!.dispatch_count === 0,
        'cold PREPARED cooperation window sent',
      );
      server = emptyReceipt();
      await cold.lookup(query.key);
      const looked = (await coldStore.list())[0]!;
      const options = await cold.inspectOriginal(query.key, looked.record_revision, true);
      check(!options.replay && options.close, 'QUERY_ONLY mode offered original business replay');
      const beforeReplay = calls.length;
      await failure(cold.replayOriginal(query.key, looked.record_revision));
      check(
        calls.length === beforeReplay && (await coldStore.list())[0]!.dispatch_count === 0,
        'explicit QUERY_ONLY consumed a send gate',
      );
      checks.push('cold QUERY_ONLY cannot submit or consume a send gate after NOT_FOUND');
    } finally {
      for (const active of owners) active.dispose();
      await Promise.all(stores.map((item) => item.settle()));
      await remove(queryName);
    }
    return { checks: Object.freeze(checks) };
  } finally {
    for (const active of owners) active.dispose();
    for (const active of stores) active.close();
    await Promise.all(stores.map((item) => item.settle()));
    await remove(name);
  }
}
function summaryFor(value: unknown): PendingSummary {
  return pendingSummary(value, location.origin);
}

/** Explicit bounded capacity/blocked diagnostics, no normal storage. */
export async function boundsProbe(): Promise<{ checks: readonly string[] }> {
  const checks: string[] = [];
  const name = 'walle-v20-idb-probe-' + crypto.randomUUID(),
    blockedName = 'walle-v20-idb-probe-' + crypto.randomUUID();
  const store = new CommandRecoveryStore({ name });
  let held: IDBDatabase | undefined, blockedStore: CommandRecoveryStore | undefined;
  try {
    const text = 'x'.repeat(7.5 * 1024 * 1024);
    const client = new ApiClient(() => {
      throw Error('capacity fixture cannot dispatch');
    });
    const binding = {
      decoder_kind: registeredCommand('POST', pathFor(5001), crypto.randomUUID()).decoder_kind,
      success_status: [202] as const,
      errors: [] as const,
      validate_input(value: JsonObject) {
        check(typeof exact(value, ['payload']).payload === 'string', 'capacity payload fixture');
      },
      decode(value: unknown) {
        return value;
      },
    };
    await failure(
      prepareCodeCommand(
        client,
        pathFor(5000),
        { payload: 'x'.repeat(8 * 1024 * 1024) },
        binding,
        location.origin,
      ),
    );
    for (let i = 1; i <= 17; i++) {
      const action = await prepareCodeCommand(
        client,
        pathFor(5000 + i),
        { payload: text },
        binding,
        location.origin,
      );
      check(
        (await store.reserve(action.frozen)).kind === 'PREPARED',
        '128MiB fixture refused too soon',
      );
    }
    const over = await prepareCodeCommand(
      client,
      pathFor(6000),
      { payload: text },
      binding,
      location.origin,
    );
    await failure(store.reserve(over.frozen), 'CAPACITY');
    check((await store.list()).length === 17, '128MiB capacity evicted or added pending');
    checks.push(
      'actual UTF8 body over 8MiB refused; seventeen 7.5MiB bodies persist, eighteenth crosses 128MiB and is refused without eviction',
    );

    const initial = new CommandRecoveryStore({ name: blockedName });
    await initial.list();
    initial.close();
    await initial.settle();
    held = await rawDatabase(blockedName);
    let wasBlocked = false,
      wasAborted = false;
    let settled: Promise<void> | undefined;
    const factory = new Proxy(indexedDB, {
      get(target, property) {
        if (property === 'open')
          return (databaseName: string) => {
            check(databaseName === blockedName, 'wrong owned blocked target');
            const request = target.open(databaseName, 3);
            settled = new Promise<void>((resolve) => {
              request.addEventListener('blocked', () => {
                wasBlocked = true;
              });
              request.addEventListener('error', () => {
                wasAborted = true;
                resolve();
              });
              request.addEventListener('success', () => {
                request.result.close();
                resolve();
              });
            });
            return request;
          };
        const value = Reflect.get(target, property, target);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
    blockedStore = new CommandRecoveryStore({ name: blockedName, factory: () => factory });
    await failure(blockedStore.list(), 'BLOCKED');
    check(wasBlocked, 'native blocked event not observed');
    blockedStore.close();
    held.close();
    held = undefined;
    await settled;
    check(wasAborted, 'refused blocked open continued into an upgrade');
    const unchanged = await rawDatabase(blockedName);
    check(
      unchanged.version === 2 && unchanged.objectStoreNames.length === 2,
      'blocked open modified stores/version',
    );
    unchanged.close();
    checks.push(
      'real blocked open refuses owner, later release aborts the refused upgrade and retains original database version/stores',
    );
    return { checks: Object.freeze(checks) };
  } finally {
    held?.close();
    blockedStore?.close();
    store.close();
    await store.settle();
    await blockedStore?.settle();
    await remove(name);
    await remove(blockedName);
  }
}
function configurationContent() {
  const binding = {
    native_model_id: 'walle-code',
    purpose: 'CODE',
    model_profile_ref: 'deepseek-v2',
    model_snapshot_ref: 'test-only-snapshot',
    price_version_id: 1,
    input_cap_tokens: 1000,
    context_cap_tokens: 2000,
    output_cap_tokens: 100,
    admission_ref: 'test-only',
  };
  const names = [
    'max_model_requests',
    'max_output_tokens',
    'max_consecutive_failures',
    'max_active_seconds',
    'max_file_bytes',
    'max_snapshot_bytes',
    'max_snapshot_files',
    'max_capture_entries',
    'max_capture_seconds',
    'max_manifest_bytes',
    'max_git_seconds',
    'max_git_output_bytes',
    'max_delivery_window_seconds',
    'max_check_output_bytes',
    'max_check_cases',
    'max_case_steps',
    'max_case_payload_bytes',
    'query_timeout_seconds',
    'send_timeout_seconds',
    'queue_wait_seconds',
    'graceful_stop_seconds',
    'force_stop_wait_seconds',
  ];
  return {
    executor: {
      version: '1.19.5',
      binary_ref: 'test-only-executor',
      adapter_contract_version: 'test-adapter',
      runtime_bundle_ref: 'test-runtime',
      configuration_policy_version: 'OC20-CONFIG-1',
      runtime_policy_version: 'WIN20-ISOLATION-1',
    },
    git: {
      version: '2.56.0.windows.4',
      binary_ref: 'test-only-git',
      runtime_bundle_ref: 'test-runtime',
      source_commit: '581291682ad5a238c08c93d1f5bd4518382a3230',
      protocol_version: 'GIT20-LOCAL-1',
    },
    models: {
      primary_profile_ref: 'deepseek-v2',
      auxiliary_profile_refs: [],
      protocol_version: 'OC20-MODEL-1',
      bindings: [
        binding,
        { ...binding, native_model_id: 'walle-compaction', purpose: 'COMPACTION' },
      ],
    },
    environment: { python_ref: null, node_ref: null, package_manager_refs: [], secret_refs: [] },
    commands: [],
    capture_rules: {
      content_policy_version: 'CONTENT20-STORE-1',
      product_include_paths: ['.'],
      nonproduct_exclude_paths: [],
      new_file_mode: '100644',
      secret_policy_ref: 'test-policy',
    },
    delivery: null,
    check_set_version_id: 1,
    limits: Object.fromEntries(names.map((name) => [name, 100])),
    capability_evidence_refs: [],
  };
}

/** Real IndexedDB cold owners with native C07/C08/C15 bindings and scripted transport. */
export async function configurationProbe(): Promise<{ checks: readonly string[] }> {
  const name = 'walle-v20-idb-probe-' + crypto.randomUUID();
  const stores: CommandRecoveryStore[] = [];
  const owners: CommandRecovery[] = [];
  const checks: string[] = [];
  const profile = configurationContent();
  const scope = authorizationScope({
    read_roots: [],
    write_workspace_only: true,
    allowed_command_ids: [],
    network_targets: [],
    model_profile_refs: ['deepseek-v2'],
    allow_local_delivery: false,
    limits: profile.limits,
  });
  const cases = [
    {
      path: '/api/v1/code-execution-profiles/7/versions',
      body: snapshotObject(profile),
      kind: 'EXECUTION_PROFILE_VERSION',
    },
    {
      path: '/api/v1/code-check-sets/7/versions',
      body: { protocol_version: 'CHECK20-CONTROL-1', items: [], coverage_plan: [] },
      kind: 'CHECK_SET_VERSION',
    },
    {
      path: '/api/v1/code-authorizations',
      body: snapshotObject({ profile_version_id: 9, scope }),
      kind: 'AUTHORIZATION',
    },
  ];
  try {
    for (const item of cases) {
      let store = new CommandRecoveryStore({ name });
      stores.push(store);
      let drop = true,
        keys = 0;
      const calls: { key: string; body: string }[] = [];
      const transport: typeof fetch = async (input, options) => {
        const key = new Headers(options?.headers).get('Idempotency-Key');
        check(
          input === item.path && key !== null && typeof options?.body === 'string',
          'configuration original path/key/body changed',
        );
        const saved = summaryFor(await store.detail(key));
        check(
          saved.status === 'DISPATCHING' && saved.dispatch_count === calls.length + 1,
          'HTTP before durable IDB gate',
        );
        calls.push({ key, body: options.body });
        if (drop) {
          drop = false;
          throw Error('Injected response loss');
        }
        return new Response(
          JSON.stringify({
            success: true,
            data: { resource_kind: item.kind, resource_id: 9 },
            error: null,
            meta: { request_id: crypto.randomUUID() },
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        );
      };
      const context = new Ctx(new Container(), new Clock());
      const api = new WalleApi(
        new ApiClient(transport, () => {
          keys++;
          return crypto.randomUUID();
        }),
        context,
      );
      const owner = api.configurationRecovery(store, async () => {
        throw Error('Created configuration has no async operation');
      });
      owners.push(owner);
      const staged = await owner.stage(item.path, item.body);
      check(!('final_state' in staged), 'configuration already resolved');
      await failure(owner.send(staged.key, staged.record_revision));
      const unknown = summaryFor(await store.detail(staged.key));
      check(
        unknown.status === 'UNKNOWN' && unknown.dispatch_count === 1,
        'lost response discarded original request',
      );
      const original = originalFrozen(await store.detail(staged.key));
      owner.dispose();
      await store.settle();
      store = new CommandRecoveryStore({ name });
      stores.push(store);
      const coldApi = new WalleApi(
        new ApiClient(transport, () => {
          throw Error('Cold original cannot allocate key');
        }),
        context,
      );
      const cold = coldApi.configurationRecovery(store, async () => {
        throw Error('No operation');
      });
      owners.push(cold);
      const restored = summaryFor(await store.detail(staged.key));
      check(
        originalFrozen(await store.detail(staged.key)).body_json === original.body_json,
        'cold persisted bytes changed',
      );
      const result = await cold.send(restored.key, restored.record_revision);
      check(
        result.local !== null &&
          'final_state' in result.local &&
          result.local.final_state === 'CONFIRMED',
        'cold native created result not confirmed',
      );
      check(
        keys === 1 &&
          calls.length === 2 &&
          calls[0]!.key === calls[1]!.key &&
          calls[0]!.body === calls[1]!.body,
        'cold replay changed key/body or duplicated intent',
      );
      check((await store.detail(staged.key)) === null, 'terminal retained pending body');
      check((await store.receipt(staged.key))?.http_status === 201, 'terminal 201 receipt missing');
      checks.push(
        item.kind +
          ': durable dispatch, lost reply, real IDB reopen, same original bytes/key, typed 201 confirmation and pending cleanup',
      );
      cold.dispose();
      await store.settle();
    }
    return { checks: Object.freeze(checks) };
  } finally {
    for (const owner of owners) owner.dispose();
    for (const store of stores) store.close();
    await Promise.all(stores.map((store) => store.settle()));
    await remove(name);
  }
}
