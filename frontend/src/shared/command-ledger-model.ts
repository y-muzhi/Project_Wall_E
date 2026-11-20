/** The shared DB2 discriminant validates both branches; business owners see their own rows. */
import { object } from '../api/client.ts';
import { pendingSize, pendingSummary, receiptLocal } from '../code-tasks/command-recovery-model.ts';
import {
  formationPending,
  formationPendingSize,
  formationReceipt,
} from '../formation/command-model.ts';
export function isFormationRecord(value: unknown): boolean {
  const row = object(value);
  return row.schema_version === 5 && row.owner_module === 'FORMATION';
}
export function validateLedgerPending(value: unknown, origin: string): void {
  if (isFormationRecord(value)) formationPending(value, origin);
  else pendingSummary(value, origin);
}
export function validateLedgerReceipt(value: unknown, origin: string): void {
  if (isFormationRecord(value)) formationReceipt(value, origin);
  else receiptLocal(value, origin);
}
export function ledgerPendingSize(value: unknown): number {
  const row = object(value);
  validateLedgerPending(value, String(row.origin));
  return isFormationRecord(value) ? formationPendingSize(value) : pendingSize(value);
}
