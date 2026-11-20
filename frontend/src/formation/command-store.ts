/** Formation semantics over the same DB2 transaction/capacity gates as Coding/Testing. */
import { object, snapshotObject } from '../api/client.ts';
import { CommandLedger, CommandStorageError, checked, corrupt } from '../shared/command-ledger.ts';
import {
  isFormationRecord,
  ledgerPendingSize,
  validateLedgerPending,
  validateLedgerReceipt,
} from '../shared/command-ledger-model.ts';
import {
  COMMAND_PENDING_BYTES,
  COMMAND_PENDING_LIMIT,
  uuid,
} from '../code-tasks/command-recovery-model.ts';
import {
  formationPending,
  formationReceipt,
  frozenFormation,
  verifyFormationFrozen,
  verifyFormationIdentity,
} from './command-model.ts';
import type { FormationFrozen, FormationPending, FormationReceipt } from './command-model.ts';
export type FormationPendingSummary = Omit<FormationPending, 'body_text'>;
export type FormationStage =
  | Readonly<{ kind: 'PREPARED' | 'EXISTING'; record: FormationPending }>
  | Readonly<{ kind: 'RESOLVED'; receipt: FormationReceipt }>;
export type FormationResult = Readonly<
  Pick<
    FormationReceipt,
    'final_state' | 'http_status' | 'result_code' | 'guide_run_id' | 'user_message_id' | 'event_ids'
  >
>;
function identityFields(row: FormationPending): Omit<FormationFrozen, 'body_text'> {
  const { body_text: _bytes, ...identity } = frozenFormation(row);
  return identity;
}
function instant(previous?: string): string {
  return new Date(
    Math.max(Date.now(), previous === undefined ? 0 : Date.parse(previous)),
  ).toISOString();
}
function sameIdentity(a: FormationPending | FormationReceipt, b: FormationFrozen): boolean {
  return (
    a.identity_sha256 === b.identity_sha256 &&
    a.body_sha256 === b.body_sha256 &&
    a.intent_key === b.intent_key &&
    a.requirement_id === b.requirement_id &&
    a.document_id === b.document_id
  );
}
export class FormationCommandStore extends CommandLedger {
  async list(
    requirementId: number,
    documentId: number,
  ): Promise<readonly FormationPendingSummary[]> {
    const rows = await this.transaction<unknown[]>('readonly', ({ pending }, done, fail) => {
      const values: unknown[] = [];
      const scan = pending.openCursor();
      scan.onsuccess = () =>
        checked(() => {
          const cursor = scan.result;
          if (!cursor) {
            done(values);
            return;
          }
          if (!Array.isArray(cursor.key) || cursor.key.length !== 2) return corrupt();
          const origin = cursor.key[0];
          if (origin === this.origin) {
            validateLedgerPending(cursor.value, this.origin);
            if (isFormationRecord(cursor.value)) {
              const row = formationPending(cursor.value, this.origin);
              if (row.key !== cursor.key[1]) return corrupt();
              if (row.requirement_id === requirementId && row.document_id === documentId)
                values.push(row);
            }
          }
          cursor.continue();
        }, fail);
    });
    const values = await Promise.all(
      rows.map(async (value) => {
        const row = formationPending(value, this.origin);
        await verifyFormationIdentity(row, this.origin);
        const { body_text: _bytes, ...summary } = row;
        return Object.freeze(summary);
      }),
    );
    return Object.freeze(
      values.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.key.localeCompare(b.key)),
    );
  }
  async detail(key: string): Promise<FormationPending | null> {
    uuid(key);
    const value = await this.transaction<unknown>('readonly', ({ pending }, done) => {
      const request = pending.get([this.origin, key]);
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    validateLedgerPending(value, this.origin);
    if (!isFormationRecord(value)) return null;
    const row = formationPending(value, this.origin);
    if (row.key !== key) return corrupt();
    await verifyFormationIdentity(row, this.origin);
    return row;
  }
  async receipt(key: string): Promise<FormationReceipt | null> {
    uuid(key);
    const value = await this.transaction<unknown>('readonly', ({ receipts }, done) => {
      const request = receipts.get([this.origin, key]);
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    validateLedgerReceipt(value, this.origin);
    if (!isFormationRecord(value)) return null;
    const row = formationReceipt(value, this.origin);
    if (row.key !== key) return corrupt();
    await verifyFormationIdentity(row, this.origin);
    return row;
  }
  async reserve(frozen: FormationFrozen): Promise<FormationStage> {
    await verifyFormationFrozen(frozen, this.origin);
    const now = instant();
    const row = formationPending(
      {
        ...frozen,
        schema_version: 5,
        recovery_mode: 'REPLAY_ORIGINAL',
        status: 'PREPARED',
        created_at: now,
        updated_at: now,
        submitted_at: null,
        dispatch_count: 0,
        dispatch_owner_id: null,
        record_revision: 1,
      },
      this.origin,
    );
    const size = ledgerPendingSize(row);
    const result = await this.transaction<{
      kind: 'PREPARED' | 'EXISTING' | 'RESOLVED';
      value: unknown;
    }>('readwrite', ({ pending, receipts }, done, fail) => {
      const terminal = receipts.get([this.origin, row.key]);
      terminal.onsuccess = () =>
        checked(() => {
          if (terminal.result !== undefined) {
            done({ kind: 'RESOLVED', value: terminal.result });
            return;
          }
          const existing = pending.index('by_origin_intent').get([this.origin, row.intent_key]);
          existing.onsuccess = () =>
            checked(() => {
              if (existing.result !== undefined) {
                done({ kind: 'EXISTING', value: existing.result });
                return;
              }
              let count = 0,
                total = 0;
              const scan = pending.openCursor();
              scan.onsuccess = () =>
                checked(() => {
                  const cursor = scan.result;
                  if (cursor) {
                    count++;
                    total += ledgerPendingSize(cursor.value);
                    cursor.continue();
                    return;
                  }
                  if (count >= COMMAND_PENDING_LIMIT || total + size > COMMAND_PENDING_BYTES)
                    throw new CommandStorageError('CAPACITY');
                  const save = pending.add(row, [this.origin, row.key]);
                  save.onsuccess = () => done({ kind: 'PREPARED', value: row });
                }, fail);
            }, fail);
        }, fail);
    });
    if (result.kind === 'RESOLVED') {
      const receipt = formationReceipt(result.value, this.origin);
      if (!sameIdentity(receipt, frozen)) return corrupt();
      await verifyFormationIdentity(receipt, this.origin);
      return Object.freeze({ kind: 'RESOLVED', receipt });
    }
    const record = formationPending(result.value, this.origin);
    if (
      record.intent_key !== frozen.intent_key ||
      record.requirement_id !== frozen.requirement_id ||
      record.document_id !== frozen.document_id
    )
      return corrupt();
    await verifyFormationIdentity(record, this.origin);
    return Object.freeze({ kind: result.kind, record });
  }
  private async change(
    expected: FormationPending,
    mutate: (row: FormationPending) => FormationPending | FormationReceipt | null,
  ): Promise<FormationPending | FormationReceipt | null> {
    await verifyFormationIdentity(expected, this.origin);
    const result = await this.transaction<unknown | null>(
      'readwrite',
      ({ pending, receipts }, done, fail) => {
        const terminal = receipts.get([this.origin, expected.key]);
        terminal.onsuccess = () =>
          checked(() => {
            if (terminal.result !== undefined) {
              const receipt = formationReceipt(terminal.result, this.origin);
              if (!sameIdentity(receipt, frozenFormation(expected))) return corrupt();
              done(receipt);
              return;
            }
            const request = pending.get([this.origin, expected.key]);
            request.onsuccess = () =>
              checked(() => {
                if (request.result === undefined) {
                  done(null);
                  return;
                }
                const row = formationPending(request.result, this.origin);
                if (
                  !sameIdentity(row, frozenFormation(expected)) ||
                  row.record_revision !== expected.record_revision
                ) {
                  done(null);
                  return;
                }
                const next = mutate(row);
                if (next === null) {
                  done(null);
                  return;
                }
                if ('final_state' in next) {
                  const receipt = formationReceipt(next, this.origin);
                  receipts.add(receipt, [this.origin, row.key]);
                  const remove = pending.delete([this.origin, row.key]);
                  remove.onsuccess = () => done(receipt);
                } else {
                  const changed = formationPending(
                    {
                      ...next,
                      record_revision: row.record_revision + 1,
                      updated_at: instant(row.updated_at),
                    },
                    this.origin,
                  );
                  for (const [field, value] of Object.entries(frozenFormation(row)))
                    if (object(changed)[field] !== value) return corrupt();
                  const save = pending.put(changed, [this.origin, row.key]);
                  save.onsuccess = () => done(changed);
                }
              }, fail);
          }, fail);
      },
    );
    if (result === null) return null;
    return 'final_state' in object(result)
      ? formationReceipt(result, this.origin)
      : formationPending(result, this.origin);
  }
  async dispatch(
    expected: FormationPending,
    ownerId: string,
    replay = false,
  ): Promise<FormationPending | null> {
    uuid(ownerId);
    await verifyFormationFrozen(frozenFormation(expected), this.origin);
    const result = await this.change(expected, (row) => {
      if ((row.dispatch_count === 0) !== !replay) return null;
      return {
        ...row,
        status: 'DISPATCHING',
        submitted_at: instant(row.updated_at),
        dispatch_count: row.dispatch_count + 1,
        dispatch_owner_id: ownerId,
      };
    });
    return result !== null && !('final_state' in result) ? result : null;
  }
  async markUnknown(expected: FormationPending): Promise<FormationPending | null> {
    const result = await this.change(expected, (row) =>
      row.dispatch_count === 0 ? null : { ...row, status: 'UNKNOWN' },
    );
    return result !== null && !('final_state' in result) ? result : null;
  }
  async resolve(
    expected: FormationPending,
    result: FormationResult,
  ): Promise<FormationReceipt | null> {
    const captured = snapshotObject(result);
    const changed = await this.change(expected, (row) => {
      if (captured.final_state === 'CANCELLED_UNSENT') {
        if (row.status !== 'PREPARED' || row.dispatch_count !== 0) return null;
      } else if (row.dispatch_count === 0) return null;
      return formationReceipt(
        {
          ...identityFields(row),
          schema_version: 5,
          ...captured,
          resolved_at: instant(row.updated_at),
        },
        this.origin,
      );
    });
    return changed !== null && 'final_state' in changed ? changed : null;
  }
}
