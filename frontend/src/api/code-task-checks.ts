/** Original Coding self-check commands and read-only verification projections. */
import type { ApiClient, JsonObject } from './client.ts';
import { ApiUnknown, exact, positiveInteger } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  distinct,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

const taskPath = (taskId: number) => '/api/v1/code-tasks/' + positiveInteger(taskId);
export const captureCheckPath = (taskId: number) => taskPath(taskId) + '/candidates';
export const candidateCheckPath = (taskId: number, candidateId: number) =>
  captureCheckPath(taskId) + '/' + positiveInteger(candidateId) + '/verifications';

const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['RUNNING', 'VERIFYING']),
  state_version: positiveInteger,
});

function input(value: JsonObject, original: CommandIdentity) {
  require(original.owner_module === 'CODING');
  const fixed = exact(value, ['expected_state_version', 'purpose']);
  require(fixed.purpose === 'HANDOFF');
  return positiveInteger(fixed.expected_state_version);
}

export const CANDIDATE_CHECK_BINDINGS = (['APP-CODE-CMD-C50', 'APP-CODE-CMD-C51'] as const).map(
  (decoder_kind): CodeCommandBinding<ReturnType<typeof receipt>> =>
    Object.freeze({
      decoder_kind,
      success_status: [202] as const,
      errors: [
        'INVALID_INPUT',
        'NOT_FOUND',
        'INVALID_STATE',
        'TASK_ENDED',
        'VERSION_CONFLICT',
        'OPERATION_CONFLICT',
        'WRITER_ACTIVE',
        'VERIFICATION_STAGE_NOT_READY',
        'CHECK_CONFIGURATION_INVALID',
        'CONTENT_NOT_READY',
        'CONFIG_NOT_READY',
        'STORAGE_UNAVAILABLE',
        'INTERNAL_ERROR',
        'COMMAND_CLOSED',
        'EXTERNAL_RESULT_UNKNOWN',
      ] as const,
      validate_input(value: JsonObject, original: CommandIdentity) {
        require(original.decoder_kind === decoder_kind);
        input(value, original);
      },
      decode(value: unknown, original: CommandIdentity, request: JsonObject) {
        require(original.decoder_kind === decoder_kind);
        const version = input(request, original);
        const row = receipt(value);
        require(
          row.task_id === original.parameters.task_id &&
            row.state_version === version + 1 &&
            (decoder_kind === 'APP-CODE-CMD-C50' || row.task_status === 'VERIFYING'),
        );
        return row;
      },
    }),
);

function nil(value: unknown): null {
  require(value === null);
  return null;
}
const sha256 = checked(nonempty, (value) => require(/^[0-9a-f]{64}$/.test(value)));
const labels = checked(array(nonempty, 16384), distinct);
const itemReason = choices([
  'COMMAND_FAILED',
  'ASSERTION_FAILED',
  'NO_CONTROLLED_CASES',
  'RESOURCE_MISSING',
  'DEPENDENCY_MISMATCH',
  'ISOLATION_UNAVAILABLE',
  'TARGET_UNVERIFIED',
  'APPLICATION_START_FAILED',
  'TIMEOUT',
  'OUTPUT_LIMIT',
  'INPUT_CHANGED',
  'EVIDENCE_INCOMPLETE',
  'PROCESS_STATE_UNKNOWN',
  'CLEANUP_UNVERIFIED',
]);
const stream = shape({ byte_count: count, sha256 });
const processEvidence = shape({
  exit_code: nullable(checked(count, (code) => require(code <= 0xffffffff))),
  stdout: nullable(stream),
  stderr: nullable(stream),
});

export const checkItem = checked(
  shape({
    id: positiveInteger,
    verification_id: positiveInteger,
    check_id: nonempty,
    required: bool,
    check_kind: choices(['PROJECT_COMMAND', 'CONTROLLED_ASSERTION']),
    evidence_kind: choices(['PROCESS_EXIT', 'CONTENT_INTEGRITY', 'CONTROLLED_CASES']),
    command_execution_id: nullable(positiveInteger),
    result: choices([
      'NOT_RUN',
      'RUNNING',
      'PASSED',
      'FAILED',
      'UNAVAILABLE',
      'UNKNOWN',
      'CANCELLED',
    ]),
    reason_code: nullable(itemReason),
    expected_case_count: nullable(count),
    executed_case_count: nullable(count),
    passed_case_count: nullable(count),
    failed_case_count: nullable(count),
    reused_from_item_id: nullable(positiveInteger),
    evidence_summary: nullable(nonempty),
    started_at: nullable(time),
    ended_at: nullable(time),
  }),
  (row) => {
    require((row.check_kind === 'PROJECT_COMMAND') === (row.evidence_kind === 'PROCESS_EXIT'));
    require(row.reused_from_item_id !== row.id);
    if (row.evidence_summary !== null) {
      require(row.evidence_summary.length <= 8192);
      if (row.evidence_kind === 'PROCESS_EXIT') processEvidence(JSON.parse(row.evidence_summary));
    }
    const cases = [
      row.expected_case_count,
      row.executed_case_count,
      row.passed_case_count,
      row.failed_case_count,
    ];
    if (row.evidence_kind === 'CONTROLLED_CASES') {
      const expected = count(row.expected_case_count);
      const executed = count(row.executed_case_count);
      const passed = count(row.passed_case_count);
      const failed = count(row.failed_case_count);
      require(executed === passed + failed && executed <= expected);
      if (row.result === 'PASSED') require(expected > 0 && expected === executed && failed === 0);
    } else require(cases.every((value) => value === null));
    if (row.started_at !== null && row.ended_at !== null) require(row.started_at <= row.ended_at);
  },
);
export type CodeCheckItem = ReturnType<typeof checkItem>;

export function projectCommandEvidence(item: CodeCheckItem) {
  if (item.evidence_kind !== 'PROCESS_EXIT' || item.evidence_summary === null) return null;
  return processEvidence(JSON.parse(item.evidence_summary));
}

const stages = ['BACKEND', 'FRONTEND', 'INTEGRATION'] as const;
const eligibilityReason = choices([
  'REQUIRED_NOT_PASSED',
  'VERIFICATION_STAGE_NOT_READY',
  'RESOURCE_NOT_READY',
  'COVERAGE_NOT_READY',
  'NO_CONTROLLED_CASES',
  'CANDIDATE_MISMATCH',
  'CONFIGURATION_MISMATCH',
  'ENVIRONMENT_MISMATCH',
  'RESULT_INCOMPLETE',
  'ACTIVITY_NOT_STOPPED',
  'CLEANUP_NOT_VERIFIED',
  'INPUT_CHANGED',
]);
const verification = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    owner_kind: choices(['CODING']),
    testing_task_id: nil,
    candidate_id: positiveInteger,
    snapshot_id: nil,
    purpose: choices(['HANDOFF']),
    role: choices(stages),
    check_set_version_id: positiveInteger,
    profile_version_id: positiveInteger,
    testing_profile_version_id: nil,
    environment_record_id: positiveInteger,
    operation_id: positiveInteger,
    scope_stages: array(choices(stages), 3, 1),
    selected_check_ids: labels,
    status: choices(['PENDING', 'RUNNING', 'FINISHED', 'UNKNOWN', 'CANCELLED']),
    stop_status: choices(['NOT_STARTED', 'ACTIVE', 'VERIFIED', 'UNKNOWN']),
    cleanup_status: choices(['NOT_STARTED', 'CLEANING', 'VERIFIED', 'FAILED', 'UNKNOWN']),
    source_integrity_status: choices(['NOT_CHECKED', 'VERIFIED', 'CHANGED', 'UNKNOWN']),
    created_at: time,
    ended_at: nullable(time),
    backend_handoff_operation_id: nullable(positiveInteger),
    frontend_handoff_operation_id: nullable(positiveInteger),
    items: array(checkItem, 16384, 1),
    environment_record: shape({
      id: positiveInteger,
      task_id: positiveInteger,
      testing_task_id: nil,
      runtime_refs: labels,
      dependency_refs: labels,
      runner_refs: labels,
      effective_config_application_id: nullable(positiveInteger),
      testing_profile_version_id: nil,
      check_resource_refs: labels,
      scope_key: sha256,
      observed_at: time,
    }),
    eligible: bool,
    ineligibility_reason_codes: checked(array(eligibilityReason, 12), distinct),
  }),
  (row) => {
    const index = stages.indexOf(row.role);
    require(
      row.environment_record.id === row.environment_record_id &&
        row.environment_record.task_id === row.task_id &&
        row.scope_stages.length === index + 1 &&
        row.scope_stages.every((stage, i) => stage === stages[i]) &&
        (index === 0) === (row.backend_handoff_operation_id === null) &&
        (index !== 2) === (row.frontend_handoff_operation_id === null) &&
        row.items.length === row.selected_check_ids.length &&
        row.items.every(
          (item, i) =>
            item.verification_id === row.id && item.check_id === row.selected_check_ids[i],
        ) &&
        row.eligible === (row.ineligibility_reason_codes.length === 0) &&
        (row.ended_at === null || row.ended_at >= row.created_at),
    );
    distinct(row.items.map((item) => item.id));
    if (row.eligible)
      require(
        row.status === 'FINISHED' &&
          row.stop_status === 'VERIFIED' &&
          row.cleanup_status === 'VERIFIED' &&
          row.source_integrity_status === 'VERIFIED' &&
          row.items.every((item) => !item.required || item.result === 'PASSED'),
      );
  },
);

export type CodeVerification = ReturnType<typeof verification>;
const readErrors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

export function readCodeVerifications(
  client: ApiClient,
  taskId: number,
  candidateId: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    candidateCheckPath(taskId, candidateId),
    checked(verification, (row) =>
      require(row.task_id === taskId && row.candidate_id === candidateId),
    ),
    (row) => row.id,
    [
      ['purpose', 'HANDOFF'],
      ['page', String(page)],
    ],
    page,
    signal,
    readErrors,
  );
}

export async function readCodeVerification(
  client: ApiClient,
  taskId: number,
  verificationId: number,
  signal?: AbortSignal,
) {
  const result = await client.read(
    taskPath(taskId) + '/verifications/' + positiveInteger(verificationId),
    checked(verification, (row) => require(row.task_id === taskId && row.id === verificationId)),
    [],
    signal,
    readErrors,
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}

export const verificationCase = checked(
  shape({
    case_id: checked(nonempty, (value) =>
      require(/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/.test(value)),
    ),
    name: checked(nonempty, (value) => require([...value].length <= 256)),
    result: choices(['PASSED', 'FAILED']),
    expected_assertion_count: positiveInteger,
    passed_assertion_count: count,
    failed_assertion_count: count,
    capture_status: choices(['FULL', 'REDACTED', 'INCOMPLETE']),
    summary: nullable(checked(nonempty, (value) => require([...value].length <= 256))),
    observed_at: time,
  }),
  (row) => {
    const observed = row.passed_assertion_count + row.failed_assertion_count;
    require(Number.isSafeInteger(observed) && observed <= row.expected_assertion_count);
    if (row.capture_status !== 'INCOMPLETE') require(observed === row.expected_assertion_count);
    if (row.result === 'PASSED')
      require(row.failed_assertion_count === 0 && row.capture_status !== 'INCOMPLETE');
    else require(row.failed_assertion_count > 0);
  },
);

export function readCodeVerificationCases(
  client: ApiClient,
  taskId: number,
  verificationId: number,
  itemId: number,
  page: number,
  signal?: AbortSignal,
) {
  const path = [
    taskPath(taskId),
    'verifications',
    positiveInteger(verificationId),
    'items',
    positiveInteger(itemId),
    'cases',
  ].join('/');
  return readPage(
    client,
    path,
    verificationCase,
    (row) => row.case_id,
    [['page', String(page)]],
    page,
    signal,
    readErrors,
  );
}
