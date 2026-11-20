import { Ctx, Container, Clock } from '@milkdown/kit/ctx';
import { ApiClient } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { prepareCodeCommand } from '../../src/api/code-command-snapshot.ts';
import { registeredCommand } from '../../src/api/code-command-registry.ts';
import { CommandRecoveryStore } from '../../src/code-tasks/command-recovery-store.ts';
import { FormationCommandStore } from '../../src/formation/command-store.ts';
import { FormationCommandRecovery } from '../../src/formation/command-recovery.ts';
import { freezeFormation } from '../../src/formation/command-model.ts';
import { CommandStorageError } from '../../src/shared/command-ledger.ts';
function check(value: unknown, message: string): asserts value {
  if (!value) throw Error(message);
}
async function open(name: string, version: number): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(name, version);
    r.onupgradeneeded = () => {
      if (r.transaction?.db.objectStoreNames.length === 0) {
        const p = r.result.createObjectStore('pending_commands');
        p.createIndex('by_origin_intent', ['origin', 'intent_key'], { unique: true });
        r.result.createObjectStore('command_receipts');
      }
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
async function put(
  database: IDBDatabase,
  store: string,
  value: unknown,
  key: IDBValidKey,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = database.transaction(store, 'readwrite');
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error);
    tx.objectStore(store).put(value, key);
  });
}
async function codeRow(index: number) {
  const key = crypto.randomUUID(),
    path = '/api/v1/code-tasks/' + index + '/start',
    scope = registeredCommand('POST', path, key);
  const action = await prepareCodeCommand(
    new ApiClient(
      () => {
        throw Error('No network');
      },
      () => key,
    ),
    path,
    {},
    {
      decoder_kind: scope.decoder_kind,
      success_status: [202],
      errors: [],
      validate_input: () => {},
      decode: (v) => v,
    },
    location.origin,
  );
  const now = new Date().toISOString();
  return {
    ...action.frozen,
    schema_version: 4,
    recovery_mode: 'REPLAY_SAME_KEY',
    intent_key: 'POST ' + path,
    close_state: 'NONE',
    close_requested_at: null,
    status: 'PREPARED',
    task_id: null,
    testing_task_id: null,
    operation_id: null,
    created_at: now,
    updated_at: now,
    submitted_at: null,
    dispatch_count: 0,
    dispatch_owner_id: null,
    record_revision: 1,
    lookup_status: null,
  };
}
async function runLedgerProbe() {
  const checks: string[] = [],
    names: string[] = [],
    owners: { close: () => void }[] = [];
  const name = () => {
    const value = 'walle-v21-ledger-probe-' + crypto.randomUUID();
    names.push(value);
    return value;
  };
  const keep = <T extends { close: () => void }>(value: T) => {
    owners.push(value);
    return value;
  };
  try {
    const originalName = name(),
      old = keep(await open(originalName, 1)),
      row = await codeRow(1);
    await put(old, 'pending_commands', row, [location.origin, row.key]);
    const bytes = JSON.stringify(row);
    let closed = false;
    old.onversionchange = () => {
      closed = true;
      old.close();
    };
    const codes = keep(new CommandRecoveryStore({ name: originalName }));
    const list = await codes.list();
    check(list.length === 1 && closed, 'v1 connection barrier or schema4 row lost');
    const upgraded = keep(await open(originalName, 2));
    const preserved = await new Promise<unknown>((resolve, reject) => {
      const r = upgraded
        .transaction('pending_commands')
        .objectStore('pending_commands')
        .get([location.origin, row.key]);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    check(JSON.stringify(preserved) === bytes, 'upgrade rewrote schema4 bytes');
    let downgraded = false;
    try {
      await open(originalName, 1);
    } catch (e) {
      downgraded = e instanceof DOMException && e.name === 'VersionError';
    }
    check(downgraded, 'old bundle can scan DB2');
    checks.push('DB1→DB2 barrier preserves schema4 bytes and refuses old bundle');

    const formation = keep(new FormationCommandStore({ name: originalName }));
    const request = new ApiClient(() => {
      throw Error('No network');
    });
    const prepared = request.prepare(
      'PATCH',
      '/api/v1/requirements/1',
      {
        document_id: 2,
        expected_discussion_version: 1,
        discussion_command: { type: 'FORMATION', action: 'SWITCH_STEP', step_ref: null },
      },
      { idempotent: true, success_status: 200 },
    );
    const frozen = await freezeFormation(
      request.exportPrepared(prepared),
      1,
      2,
      crypto.randomUUID(),
      location.origin,
    );
    const staged = await formation.reserve(frozen);
    check(staged.kind === 'PREPARED', 'fresh record not prepared');
    check(
      (await codes.list()).length === 1 && (await formation.list(1, 2)).length === 1,
      'business owner read the other row',
    );
    const race = await Promise.all([
      formation.dispatch(staged.record, crypto.randomUUID()),
      formation.dispatch(staged.record, crypto.randomUUID()),
    ]);
    check(race.filter(Boolean).length === 1, 'two tabs obtained initial dispatch');
    const sent = race.find((v) => v !== null)!;
    check(
      (await formation.resolve(sent, {
        final_state: 'CANCELLED_UNSENT',
        http_status: null,
        result_code: null,
        guide_run_id: null,
        user_message_id: null,
        event_ids: [],
      })) === null,
      'sent record cancelled as unsent',
    );
    const unknown = await formation.markUnknown(sent);
    check(unknown?.status === 'UNKNOWN', 'unknown record missing');
    check(
      (await formation.list(1, 2)).every((v) => !Object.hasOwn(v, 'body_text')),
      'list leaked body',
    );
    checks.push('mixed owners, CAS send claim, UNKNOWN retention and no unsent cancellation');

    const blockedName = name(),
      held = keep(await open(blockedName, 1));
    const blocked = keep(new FormationCommandStore({ name: blockedName }));
    let blockedReason = false;
    try {
      await blocked.list(1, 2);
    } catch (e) {
      blockedReason = e instanceof CommandStorageError && e.reason === 'BLOCKED';
    }
    check(blockedReason, 'blocked upgrade did not refuse new writes');
    blocked.close();
    held.close();
    await new Promise((resolve) => setTimeout(resolve, 30));
    const unchanged = keep(await open(blockedName, 1));
    check(unchanged.version === 1, 'refused upgrade continued');
    checks.push('blocked upgrade preserves original DB1 and grants no send gate');

    const replayName = name();
    let requests: { body: unknown; key: string | null }[] = [],
      lose = true;
    const receipt = {
      processing: 'MODEL',
      guide_run_id: 9,
      user_message_id: 10,
      accepted_target: {
        discussion_step_ref: 's1',
        discussion_branch_ref: null,
        branch_intent: null,
        branch_resume_basis: null,
      },
    };
    const client = new ApiClient(async (_path, init) => {
      requests.push({ body: init?.body, key: new Headers(init?.headers).get('Idempotency-Key') });
      if (lose) {
        lose = false;
        throw Error('lost result');
      }
      return new Response(
        JSON.stringify({
          success: true,
          data: receipt,
          error: null,
          meta: { request_id: crypto.randomUUID() },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      );
    });
    const api = new WalleApi(client, new Ctx(new Container(), new Clock())).forDocumentAssistant(2),
      store = keep(new FormationCommandStore({ name: replayName }));
    const recovery = new FormationCommandRecovery(1, 2, api, store);
    const body = {
      expected_discussion_version: 1,
      operation: 'DISCUSS' as const,
      instruction: '精确保留原请求',
      target: receipt.accepted_target,
      scope: null,
      source_refs: [],
      proposal_ref: null,
      proposal_intent: null,
      acknowledge_source_changes: false,
    };
    const action = recovery.wrap(api.prepareFormationDiscuss(1, body));
    try {
      await action.submit();
    } catch {
      /* Expected unknown. */
    }
    const queued = await recovery.list();
    check(queued.length === 1 && queued[0]?.status === 'UNKNOWN', 'unknown not durable');
    const fresh = new FormationCommandRecovery(
      1,
      2,
      api,
      keep(new FormationCommandStore({ name: replayName })),
    );
    check(requests.length === 1, 'read recovery sent a request');
    await fresh.replay(queued[0]!.key);
    check(
      Number(requests.length) === 2 && JSON.stringify(requests[0]) === JSON.stringify(requests[1]),
      'reload changed original bytes/key',
    );
    check((await fresh.list()).length === 0, 'confirmed pending retained');
    const terminal = await fresh.store.receipt(queued[0]!.key);
    check(
      terminal?.http_status === 202 && terminal.guide_run_id === 9,
      '202 treated as unknown operation',
    );
    checks.push(
      'cold replay exact original bytes/key; confirmed 202 resolves pending and keeps receipt',
    );

    const fullName = name(),
      full = keep(await open(fullName, 2));
    for (let index = 1; index <= 100; index++) {
      const item = await codeRow(index);
      await put(full, 'pending_commands', item, [location.origin, item.key]);
    }
    const fullStore = keep(new FormationCommandStore({ name: fullName }));
    let capacity = false;
    try {
      await fullStore.reserve(frozen);
    } catch (e) {
      capacity = e instanceof CommandStorageError && e.reason === 'CAPACITY';
    }
    check(capacity, 'formation got a separate capacity quota');
    check(
      (await keep(new CommandRecoveryStore({ name: fullName })).list()).length === 100,
      'capacity refusal deleted old commands',
    );
    checks.push('global 100-row capacity shared with Coding; no eviction');
    return { checks };
  } finally {
    for (const owner of owners) owner.close();
    for (const value of names)
      await new Promise<void>((resolve, reject) => {
        const r = indexedDB.deleteDatabase(value);
        r.onsuccess = () => resolve();
        r.onerror = () => reject(r.error);
        r.onblocked = () => reject(Error('Owned database connection leaked'));
      });
  }
}
Object.assign(window, { runLedgerProbe });
