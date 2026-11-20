/** Formation errors are endpoint-scoped; unverified replies never prove rollback. */
import { documentFailureDetails, snapshotObject } from './client.ts';
import type { ApiErrorPolicy, JsonObject } from './client.ts';
import { choices, count, nullable, shape, text } from './decoding.ts';
import { boundedText, proposalRef, stateReasons, stepRef } from './formation-values.ts';

const readCodes = [
  'VALIDATION_FAILED',
  'NOT_FOUND',
  'STATE_CONFLICT',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const;
const extraCodes = [
  'FORMATION_INVALID',
  'FORMATION_LIMIT_EXCEEDED',
  'DISCUSSION_VERSION_CONFLICT',
  'CONTENT_VERSION_CONFLICT',
] as const;
const states = shape({
  reason: choices(stateReasons),
  step_ref: nullable(stepRef),
  proposal: nullable(proposalRef),
});
const limit = shape({
  resource_kind: choices([
    'CHANGE_COUNT',
    'CHANGE_BYTES',
    'PAGE_SIZE',
    'STEP_RESULTS',
    'MODEL_INPUT',
  ]),
  limit: count,
  actual: count,
});
const status: Readonly<Record<string, number>> = {
  VALIDATION_FAILED: 422,
  NOT_FOUND: 404,
  STATE_CONFLICT: 409,
  STORAGE_UNAVAILABLE: 503,
  INTERNAL_ERROR: 500,
  FORMATION_INVALID: 422,
  FORMATION_LIMIT_EXCEEDED: 422,
  DISCUSSION_VERSION_CONFLICT: 409,
  CONTENT_VERSION_CONFLICT: 409,
};
export function formationErrorPolicy(kind: 'READ' | 'PREVIEW'): ApiErrorPolicy {
  const allowed = new Set<string>(kind === 'READ' ? readCodes : [...readCodes, ...extraCodes]);
  return Object.freeze({
    decode(code: string, message: string, details: unknown, httpStatus: number): JsonObject | null {
      text(message);
      boundedText(1000)(message);
      if (!allowed.has(code) || status[code] !== httpStatus)
        throw new TypeError('Unregistered formation error');
      if (code === 'STATE_CONFLICT' && details !== null) return snapshotObject(states(details));
      if (code === 'FORMATION_LIMIT_EXCEEDED') return snapshotObject(limit(details));
      if (code === 'FORMATION_INVALID') {
        if (details !== null) throw new TypeError('Unexpected formation error details');
        return null;
      }
      return documentFailureDetails(code, details, httpStatus);
    },
    mutationUnknown(code: string, httpStatus: number) {
      return httpStatus >= 500 || code === 'REQUEST_IN_PROGRESS';
    },
  });
}
export const FORMATION_READ_ERRORS = formationErrorPolicy('READ');
export const FORMATION_PREVIEW_ERRORS = formationErrorPolicy('PREVIEW');

const workflowCodes = new Set([
  'FORMATION_INVALID',
  'FORMATION_LIMIT_EXCEEDED',
  'VALIDATION_FAILED',
  'NOT_FOUND',
  'STATE_CONFLICT',
  'SOURCE_INVALID',
  'SCOPE_INVALID',
  'SOURCE_VERSION_CONFLICT',
  'CARD_ALREADY_ANSWERED',
  'CARD_EXPIRED',
  'WORK_STATE_CONFLICT',
  'WORK_STATE_INCONSISTENT',
  'DISCUSSION_VERSION_CONFLICT',
  'CONTENT_VERSION_CONFLICT',
  'TARGET_STALE',
  'DOCUMENT_INVALID',
  'CONFIG_INVALID',
  'IDEMPOTENCY_CONFLICT',
  'REQUEST_IN_PROGRESS',
  'CAPACITY_EXHAUSTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
export const FORMATION_WORKFLOW_ERRORS: ApiErrorPolicy = Object.freeze({
  decode(code: string, message: string, details: unknown, httpStatus: number): JsonObject | null {
    boundedText(1000)(message);
    if (code === 'FORMATION_INVALID' || code === 'FORMATION_LIMIT_EXCEEDED')
      return FORMATION_PREVIEW_ERRORS.decode(code, message, details, httpStatus);
    if (!workflowCodes.has(code)) throw new TypeError('Unregistered formation workflow error');
    if (code === 'STATE_CONFLICT' && details !== null) {
      if (httpStatus !== 409) throw new TypeError('Formation conflict must use 409');
      return snapshotObject(states(details));
    }
    return documentFailureDetails(code, details, httpStatus);
  },
  mutationUnknown(code: string, httpStatus: number) {
    return httpStatus >= 500 || code === 'REQUEST_IN_PROGRESS';
  },
});
