import { exact, positiveInteger } from '../api/wire-shape.ts';
import { hash, items, one, uuid } from './model.ts';

export function priorResultScopes(value: unknown, environment: string) {
  const row = exact(value, ['format_version', 'environment_id', 'source_data_generations']);
  if (row.format_version !== 1 || uuid(row.environment_id) !== environment)
    throw new TypeError('Invalid archived scope');
  const generations = items(row.source_data_generations, uuid, 256);
  if (new Set(generations).size !== generations.length)
    throw new TypeError('Duplicate archived scope');
  return generations;
}

export function priorResultInput(
  generation: string,
  capability: string,
  target: string,
  key: string,
) {
  if (
    capability.length > 64 ||
    !/^APP-[A-Z]+-CMD-C[0-9]{2}$/.test(capability) ||
    !/^[\x20-\x7E]{1,512}$/.test(target)
  )
    throw new TypeError('Invalid original command scope');
  return {
    source_data_generation: uuid(generation),
    original_capability: capability,
    original_target: target,
    request_key: uuid(key),
  };
}

export type PriorResultInput = ReturnType<typeof priorResultInput>;

export function priorResult(value: unknown, environment: string, generation: string) {
  const row = exact(value, [
    'format_version',
    'environment_id',
    'source_data_generation',
    'status',
    'result_summary',
    'evidence',
  ]);
  if (
    row.format_version !== 1 ||
    uuid(row.environment_id) !== environment ||
    uuid(row.source_data_generation) !== generation
  )
    throw new TypeError('Invalid archived command identity');
  const evidence =
    row.evidence === null
      ? null
      : exact(row.evidence, [
          'kind',
          'backup_manifest_sha256',
          'index_sha256',
          'capture_receipt_sha256',
        ]);
  const source = evidence && {
    kind: one(evidence.kind, ['SEALED_IDEMPOTENCY_RECEIPTS'] as const),
    backup: hash(evidence.backup_manifest_sha256),
    index: hash(evidence.index_sha256),
    capture: hash(evidence.capture_receipt_sha256),
  };
  const status = one(row.status, ['KNOWN', 'UNVERIFIABLE'] as const);
  if (status === 'UNVERIFIABLE') {
    if (row.result_summary !== null)
      throw new TypeError('Unverified command has a terminal result');
    return { status, evidence: source, result: null };
  }
  if (!source) throw new TypeError('Missing archived evidence');
  const summary = exact(row.result_summary, ['record_status', 'original_http_status']);
  const state = one(summary.record_status, ['SUCCEEDED', 'REJECTED', 'CLOSED'] as const);
  const code = positiveInteger(summary.original_http_status);
  const minimum = state === 'SUCCEEDED' ? 200 : 400;
  if (code < minimum || code >= minimum + 100)
    throw new TypeError('Invalid archived command result');
  return { status, evidence: source, result: { state, code } };
}
