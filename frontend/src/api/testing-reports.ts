import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { checkItem, verificationCase } from './code-task-checks.ts';
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  id,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';
import { testingBasisFields } from './testing-plans.ts';
import { testingTaskPath, testingTaskPurposes } from './testing-tasks.ts';

const policy = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
const stages = ['BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'] as const;
const results = [
  'PASSED',
  'FAILED',
  'UNAVAILABLE',
  'UNKNOWN',
  'CANCELLED',
  'INCONCLUSIVE',
] as const;
const eligibility = [
  'RESULT_NOT_PASSED',
  'TEST_ASSET_REVOKED',
  'SCOPE_INCOMPLETE',
  'DESIGN_MISMATCH',
  'TARGET_NOT_CURRENT',
  'NOT_CODING_CANDIDATE',
  'NOT_ACCEPTANCE',
  'CODING_CHAIN_INCOMPLETE',
  'UNCOVERED_BEHAVIOR',
  'ACTIVITY_NOT_STOPPED',
  'EVIDENCE_INCOMPLETE',
] as const;
const verificationReasons = [
  'REQUIRED_NOT_PASSED',
  'NO_CONTROLLED_CASES',
  'RESOURCE_NOT_READY',
  'COVERAGE_NOT_READY',
  'ACTIVITY_NOT_STOPPED',
  'EVIDENCE_INCOMPLETE',
  'TEST_ASSET_REVOKED',
] as const;
const sha256 = checked(nonempty, (value) => require(/^[a-f0-9]{64}$/.test(value)));
const ref = checked(nonempty, (value) =>
  require(/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/.test(value)),
);
const refs = checked(array(ref, 16384), distinct);
const scope = checked(array(choices(stages), 4), (values) =>
  require(values.join(',') === stages.filter((stage) => values.includes(stage)).join(',')),
);
const absent = (value: unknown): null => {
  require(value === null);
  return null;
};

const provenance = checked(
  shape({
    ...testingBasisFields,
    target_kind: choices(['CANDIDATE', 'SNAPSHOT']),
    candidate_id: nullable(id),
    snapshot_id: nullable(id),
    profile_version_id: id,
    purpose: choices(testingTaskPurposes),
    source_code_task_id: nullable(id),
  }),
  (row) => {
    require((row.candidate_id !== null) === (row.target_kind === 'CANDIDATE'));
    require((row.source_code_task_id !== null) === (row.target_kind === 'CANDIDATE'));
    require((row.snapshot_id !== null) === (row.target_kind === 'SNAPSHOT'));
    distinct(row.material_refs.map((item) => item.document_id));
    require(row.material_refs.every((item) => item.document_id !== row.document_id));
  },
);
const reasons = checked(array(choices(eligibility), eligibility.length), distinct);
const report = checked(
  shape({
    id,
    testing_task_id: id,
    verification_id: id,
    plan_version_id: id,
    test_pack_version_id: id,
    input_fingerprint: sha256,
    result: choices(results),
    scope_stages: scope,
    manual_coverage_ids: refs,
    uncovered_behavior_ids: refs,
    created_at: time,
    provenance,
    eligible: bool,
    delivery_eligible: bool,
    ineligibility_reason_codes: reasons,
    delivery_ineligibility_reason_codes: reasons,
  }),
  (row) => {
    require(row.eligible === (row.ineligibility_reason_codes.length === 0));
    require(row.delivery_eligible === (row.delivery_ineligibility_reason_codes.length === 0));
    require(
      row.ineligibility_reason_codes.every((code) =>
        row.delivery_ineligibility_reason_codes.includes(code),
      ),
    );
    require(row.manual_coverage_ids.every((value) => !row.uncovered_behavior_ids.includes(value)));
    if (row.eligible) require(row.result === 'PASSED');
    if (row.delivery_eligible)
      require(
        row.provenance.purpose === 'ACCEPTANCE' &&
          row.provenance.target_kind === 'CANDIDATE' &&
          row.scope_stages.length === stages.length &&
          row.uncovered_behavior_ids.length === 0,
      );
  },
);
export type TestingReport = ReturnType<typeof report>;
const reportPath = (identity: number) => '/api/v1/test-reports/' + id(identity);
export function readTestingReport(client: ApiClient, identity: number, signal?: AbortSignal) {
  return client.read(
    reportPath(identity),
    checked(report, (row) => require(row.id === identity)),
    [],
    signal,
    policy,
  );
}
export function readTestingTaskReport(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    testingTaskPath(task) + '/report',
    checked(report, (row) => require(row.testing_task_id === task && row.id === identity)),
    [],
    signal,
    policy,
  );
}

export const findingClassifications = [
  'PRODUCT',
  'TEST_DESIGN',
  'REQUIREMENT',
  'ENVIRONMENT',
  'UNKNOWN',
] as const;
const classification = choices(findingClassifications);
const length = (maximum: number) =>
  checked(nonempty, (value) => require([...value].length <= maximum));
const reason = checked(length(2000), (value) => require(value.trim() === value));
const finding = checked(
  shape({
    id,
    test_report_id: id,
    item_id: nullable(id),
    case_id: nullable(ref),
    actual_behavior: length(4000),
    expected_behavior: nullable(length(4000)),
    basis_ref: nullable(shape({ document_id: id, revision_id: id, quote: length(4096) })),
    classification: choices(['UNCLASSIFIED', ...findingClassifications]),
    state_version: id,
    review_reason: nullable(reason),
    review_operation_id: nullable(id),
    created_at: time,
  }),
  (row) => {
    const reviewed = row.classification !== 'UNCLASSIFIED';
    require(
      reviewed === (row.review_reason !== null) && reviewed === (row.review_operation_id !== null),
    );
    require(row.case_id === null || row.item_id !== null);
    if (row.classification === 'PRODUCT')
      require(row.case_id !== null && row.basis_ref !== null && row.expected_behavior !== null);
  },
);
export type TestingFinding = ReturnType<typeof finding>;
export function readTestingFindings(
  client: ApiClient,
  reportId: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    reportPath(reportId) + '/findings',
    checked(finding, (row) => require(row.test_report_id === reportId)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
}
export const reviewTestingFindingPath = (identity: number) =>
  '/api/v1/testing-findings/' + id(identity) + '/review';
const reviewInput = shape({ expected_state_version: id, classification, reason });
export const REVIEW_TESTING_FINDING: CodeCommandBinding<TestingFinding> = {
  decoder_kind: 'APP-TEST-CMD-C40',
  success_status: [200],
  errors: [
    'INVALID_INPUT',
    'NOT_FOUND',
    'PERMISSION_NOT_GRANTED',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'COMMAND_CLOSED',
    'OPERATION_CONFLICT',
    'VERSION_CONFLICT',
    'INVALID_STATE',
    'BASIS_REF_INVALID',
    'TEST_SOURCE_MISMATCH',
  ],
  validate_input: reviewInput,
  decode(value, original, input) {
    const row = finding(value);
    const fixed = reviewInput(input);
    require(
      row.id === original.parameters.id &&
        row.classification === fixed.classification &&
        row.state_version === fixed.expected_state_version + 1 &&
        row.review_reason === fixed.reason,
    );
    return row;
  },
};

const verification = checked(
  shape({
    id,
    task_id: absent,
    owner_kind: choices(['TESTING']),
    testing_task_id: id,
    candidate_id: nullable(id),
    snapshot_id: nullable(id),
    purpose: choices(testingTaskPurposes),
    role: absent,
    check_set_version_id: id,
    profile_version_id: absent,
    testing_profile_version_id: id,
    environment_record_id: id,
    operation_id: id,
    scope_stages: scope,
    selected_check_ids: refs,
    status: choices(['PENDING', 'RUNNING', 'FINISHED', 'UNKNOWN', 'CANCELLED']),
    stop_status: choices(['NOT_STARTED', 'ACTIVE', 'VERIFIED', 'UNKNOWN']),
    cleanup_status: choices(['NOT_STARTED', 'CLEANING', 'VERIFIED', 'FAILED', 'UNKNOWN']),
    source_integrity_status: choices(['NOT_CHECKED', 'VERIFIED', 'CHANGED', 'UNKNOWN']),
    created_at: time,
    ended_at: nullable(time),
    backend_handoff_operation_id: absent,
    frontend_handoff_operation_id: absent,
    items: array(checkItem, 16384, 1),
    environment_record: shape({
      id,
      task_id: absent,
      testing_task_id: id,
      runtime_refs: refs,
      dependency_refs: refs,
      runner_refs: refs,
      effective_config_application_id: absent,
      testing_profile_version_id: id,
      check_resource_refs: refs,
      scope_key: sha256,
      observed_at: time,
    }),
    eligible: bool,
    ineligibility_reason_codes: checked(
      array(choices(verificationReasons), verificationReasons.length),
      distinct,
    ),
  }),
  (row) => {
    require((row.candidate_id === null) !== (row.snapshot_id === null));
    require(row.scope_stages.length > 0);
    require(row.ended_at === null || row.ended_at >= row.created_at);
    require(row.eligible === (row.ineligibility_reason_codes.length === 0));
    require(
      row.environment_record.id === row.environment_record_id &&
        row.environment_record.testing_task_id === row.testing_task_id &&
        row.environment_record.testing_profile_version_id === row.testing_profile_version_id,
    );
    distinct(row.items.map((item) => item.id));
    require(row.items.length === row.selected_check_ids.length);
    require(
      row.items.every(
        (item, index) =>
          item.verification_id === row.id &&
          item.check_id === row.selected_check_ids[index] &&
          item.check_kind === 'CONTROLLED_ASSERTION' &&
          item.reused_from_item_id === null &&
          item.evidence_summary === null,
      ),
    );
  },
);
export type TestingVerification = ReturnType<typeof verification>;
const verificationPath = (task: number, identity: number) =>
  testingTaskPath(task) + '/verifications/' + id(identity);
export function readTestingVerification(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    verificationPath(task, identity),
    checked(verification, (row) => require(row.id === identity && row.testing_task_id === task)),
    [],
    signal,
    policy,
  );
}
export function readTestingCases(
  client: ApiClient,
  task: number,
  identity: number,
  item: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    verificationPath(task, identity) + '/items/' + id(item) + '/cases',
    verificationCase,
    (row) => row.case_id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
}
