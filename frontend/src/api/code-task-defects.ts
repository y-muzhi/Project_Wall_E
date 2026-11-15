import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { decodeQuestionEvidenceRef } from './code-task-question-response.ts';
import { array, checked, distinct, id, nullable, require, shape, text, time } from './decoding.ts';
import { readPage } from './pagination.ts';

export const defectPath = (task: number) => '/api/v1/code-tasks/' + id(task) + '/defects';
const nonblank = checked(text, (value) => require(/[^\\p{White_Space}]/u.test(value)));
export const decodeDefectBasis = shape({ document_id: id, revision_id: id, quote: nonblank });
export const decodeDefectEvidence = checked(array(decodeQuestionEvidenceRef, 65536), (rows) =>
  distinct(rows.map((row) => row.kind + ':' + row.id)),
);
const base = { candidate_id: id, expected_state_version: id };
const manual = shape({
  ...base,
  actual_behavior: nonblank,
  expected_behavior: nonblank,
  basis_ref: decodeDefectBasis,
  evidence_refs: decodeDefectEvidence,
});
const imported = shape({ ...base, testing_finding_id: id });
export function decodeCreateDefectInput(value: unknown) {
  return typeof value === 'object' && value !== null && 'testing_finding_id' in value
    ? imported(value)
    : manual(value);
}
const defect = checked(
  shape({
    id,
    task_id: id,
    candidate_id: id,
    actual_behavior: nonblank,
    expected_behavior: nonblank,
    basis_ref: decodeDefectBasis,
    evidence_refs: decodeDefectEvidence,
    testing_finding_id: nullable(id),
    created_at: time,
    actor_ref: nonblank,
  }),
  (row) => require(row.testing_finding_id === null || row.evidence_refs.length === 0),
);
export type CodeDefect = ReturnType<typeof defect>;
const errors = ['INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'] as const;
export const createdDefect = shape({ defect_id: id, task_id: id, candidate_id: id });
export const CREATE_CODE_DEFECT: CodeCommandBinding<ReturnType<typeof createdDefect>> = {
  decoder_kind: 'APP-CODE-CMD-C58',
  success_status: [201],
  errors: [
    ...errors,
    'PERMISSION_NOT_GRANTED',
    'COMMAND_CLOSED',
    'OPERATION_CONFLICT',
    'VERSION_CONFLICT',
    'INVALID_STATE',
    'TASK_ENDED',
    'CANDIDATE_NOT_CURRENT',
    'BASIS_REF_INVALID',
    'DEFECT_SOURCE_MISMATCH',
    'TEST_SOURCE_MISMATCH',
  ],
  validate_input: decodeCreateDefectInput,
  decode(value, original, input) {
    const row = createdDefect(value);
    require(row.task_id === original.parameters.task_id);
    require(row.candidate_id === decodeCreateDefectInput(input).candidate_id);
    return row;
  },
};
export function readCodeDefects(
  client: ApiClient,
  task: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    defectPath(task),
    checked(defect, (row) => require(row.task_id === task)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    codeErrorPolicy(errors),
  );
}
export function readCodeDefect(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    defectPath(task) + '/' + id(identity),
    checked(defect, (row) => require(row.task_id === task && row.id === identity)),
    [],
    signal,
    codeErrorPolicy(errors),
  );
}
