import type { ApiClient } from './client.ts';
import { ApiUnknown } from './client.ts';
import { decodeCandidateDiff } from './code-task-candidates.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
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

const states = ['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'] as const;
const previewSteps = ['VALIDATE_REPORT', 'READ_TARGET', 'SEAL_TARGET', 'SAVE_PLAN'] as const;
const deliverSteps = [
  'FIX_COMMIT_INPUT',
  'BUILD_OBJECTS',
  'SAVE_PLANNED_COMMIT',
  'PREPARE_REF',
  'VERIFY_LOCKED_TARGET',
  'DISPATCH_COMMIT_ONCE',
  'RECONCILE',
  'FINALIZE_OWNED_RUNTIME',
] as const;
const oid = checked(nonempty, (value) => require(/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value)));
const sha256 = checked(nonempty, (value) => require(/^[a-f0-9]{64}$/.test(value)));
const nil = (value: unknown) => {
  require(value === null);
  return null;
};
const yes = (value: unknown) => {
  require(value === true);
  return true;
};
const fields = { expected_state_version: id, candidate_id: id, test_report_id: id };
const previewInput = shape(fields);
const acceptInput = shape({
  ...fields,
  delivery_plan_id: id,
  expected_target_commit: oid,
  repository_quiescent_confirmed: yes,
  manual_risk_accepted: bool,
});
const receiptFields = {
  task_id: id,
  operation_id: id,
  operation_status: choices(['PENDING']),
  task_status: choices(['AWAITING_ACCEPTANCE']),
  state_version: id,
};
const previewReceipt = shape(receiptFields);
const acceptedReceipt = shape({ ...receiptFields, acceptance_id: id, delivery_id: id });
const base = (task: number) => '/api/v1/code-tasks/' + id(task);
export const planPath = (task: number) => base(task) + '/delivery-plans';
export const acceptPath = (task: number) => base(task) + '/accept';
const deliveryPath = (task: number) => base(task) + '/deliveries';
const readErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const;
const commandErrors = [
  ...readErrors,
  'TASK_ENDED',
  'INVALID_STATE',
  'VERSION_CONFLICT',
  'OPERATION_CONFLICT',
  'COMMAND_CLOSED',
  'TEST_REPORT_NOT_ELIGIBLE',
  'TEST_SOURCE_MISMATCH',
  'TEST_ASSET_REVOKED',
  'CHECKS_NOT_PASSED',
  'VERIFICATION_STAGE_NOT_READY',
  'CANDIDATE_NOT_CURRENT',
  'DELIVERY_PLAN_STALE',
  'TARGET_CHANGED',
  'TARGET_CHECKED_OUT',
  'DELIVERY_NOT_AUTHORIZED',
  'DELIVERY_WINDOW_REQUIRED',
  'REPOSITORY_UNSUPPORTED',
] as const;
export const PREPARE_DELIVERY: CodeCommandBinding<ReturnType<typeof previewReceipt>> = {
  decoder_kind: 'APP-CODE-CMD-C62',
  success_status: [202],
  errors: commandErrors,
  validate_input: previewInput,
  decode(value, original, input) {
    const row = previewReceipt(value);
    require(
      row.task_id === original.parameters.task_id &&
        row.state_version === previewInput(input).expected_state_version + 1,
    );
    return row;
  },
};
export const ACCEPT_DELIVERY: CodeCommandBinding<ReturnType<typeof acceptedReceipt>> = {
  decoder_kind: 'APP-CODE-CMD-C64',
  success_status: [202],
  errors: commandErrors,
  validate_input: acceptInput,
  decode(value, original, input) {
    const row = acceptedReceipt(value);
    require(
      row.task_id === original.parameters.task_id &&
        row.state_version === acceptInput(input).expected_state_version + 1,
    );
    return row;
  },
};
const plan = shape({
  id,
  task_id: id,
  candidate_id: id,
  test_report_id: id,
  repository_id: id,
  target_branch: nonempty,
  expected_target_commit: oid,
  target_tree_oid: oid,
  target_manifest_sha256: sha256,
  result_tree_oid: oid,
  operation_id: id,
  created_at: time,
  target_observed_at: time,
  target_diff_items: array(decodeCandidateDiff, 20),
});
export type DeliveryPlanView = ReturnType<typeof plan>;
export async function readDeliveryPlan(
  client: ApiClient,
  task: number,
  identity: number,
  page: number,
  signal?: AbortSignal,
) {
  require(id(page) <= 100000);
  const response = await client.read(
    planPath(task) + '/' + id(identity),
    checked(plan, (row) => {
      require(
        row.id === identity && row.task_id === task && row.target_observed_at <= row.created_at,
      );
      distinct(row.target_diff_items.map((item) => item.path));
    }),
    [['page', String(page)]],
    signal,
    codeErrorPolicy(readErrors),
  );
  const pagination = response.meta.pagination;
  if (
    !pagination ||
    !('page' in pagination) ||
    pagination.page !== page ||
    response.data.target_diff_items.length !==
      Math.min(20, Math.max(0, pagination.total - (page - 1) * 20))
  )
    throw new ApiUnknown(false);
  return response;
}
const delivery = checked(
  shape({
    id,
    task_id: id,
    acceptance_id: id,
    delivery_plan_id: id,
    operation_id: id,
    status: choices([
      'PENDING',
      'PREPARING',
      'WRITING',
      'UNKNOWN',
      'SUCCEEDED',
      'BLOCKED',
      'CANCELLED',
    ]),
    git_write_status: choices([
      'NOT_DISPATCHED',
      'PREPARED',
      'MAY_HAVE_BEEN_SENT',
      'CONFIRMED',
      'ABORTED_UNSENT',
      'UNKNOWN',
    ]),
    postcheck_status: choices(['NOT_RUN', 'VERIFIED', 'CONFLICT', 'UNKNOWN']),
    created_at: time,
    current_window_id: nullable(id),
    commit_input_sha256: nullable(sha256),
    observed_target_commit: nullable(oid),
    delivered_at: nullable(time),
    last_reconciled_at: nullable(time),
    planned_commit_oid: nullable(oid),
    failure_code: nullable(nonempty),
    candidate_id: id,
    test_report_id: id,
    manual_risk_accepted: bool,
    delivery_window: shape({
      state: choices(['REQUIRED', 'ACTIVE', 'EXPIRED', 'CLOSED', 'UNKNOWN']),
      confirmed_at: nullable(time),
      expires_at: nullable(time),
    }),
  }),
  (row) => {
    require((row.status === 'SUCCEEDED') === (row.delivered_at !== null));
    require(
      (row.delivery_window.confirmed_at === null) === (row.delivery_window.expires_at === null),
    );
  },
);
export type DeliveryView = ReturnType<typeof delivery>;
export function readDeliveries(
  client: ApiClient,
  task: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    deliveryPath(task),
    checked(delivery, (row) => require(row.task_id === task)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    codeErrorPolicy(readErrors),
  );
}
export function readDelivery(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    deliveryPath(task) + '/' + id(identity),
    checked(delivery, (row) => require(row.task_id === task && row.id === identity)),
    [],
    signal,
    codeErrorPolicy(readErrors),
  );
}
function operation(kind: 'PREPARE_DELIVERY' | 'DELIVER') {
  const fixed = kind === 'PREPARE_DELIVERY' ? previewInput : acceptInput;
  const path = kind === 'PREPARE_DELIVERY' ? planPath : acceptPath;
  const steps = kind === 'PREPARE_DELIVERY' ? previewSteps : deliverSteps;
  return checked(
    shape({
      id,
      task_id: id,
      testing_task_id: nil,
      resource_kind: choices(['TASK']),
      resource_id: id,
      session_id: id,
      operation_type: choices([kind]),
      idempotency_key: nonempty,
      expected_state_version: id,
      fixed_input: fixed,
      control_generation: id,
      status: choices(states),
      created_at: time,
      started_at: nullable(time),
      ended_at: nullable(time),
      failure_code: nullable(nonempty),
      content_capture: nil,
      steps: array(
        shape({
          operation_id: id,
          step_no: id,
          step_type: choices([...previewSteps, ...deliverSteps]),
          status: choices(states),
          external_identity: nil,
          fixed_input: fixed,
          result_ref: nullable(shape({ delivery_plan_id: id })),
          started_at: nullable(time),
          ended_at: nullable(time),
          last_observed_at: nullable(time),
        }),
        steps.length,
        steps.length,
      ),
    }),
    (row) => {
      registeredCommand('POST', path(row.task_id), row.idempotency_key);
      require(
        row.resource_id === row.task_id &&
          row.expected_state_version === row.fixed_input.expected_state_version,
      );
      for (const [index, step] of row.steps.entries()) {
        require(
          step.operation_id === row.id &&
            step.step_no === index + 1 &&
            step.step_type === steps[index],
        );
        require(JSON.stringify(row.fixed_input) === JSON.stringify(step.fixed_input));
        if (step.result_ref !== null)
          require(step.step_type === 'SAVE_PLAN' && step.status === 'SUCCEEDED');
      }
    },
  );
}
export const decodePrepareDeliveryOperation = operation('PREPARE_DELIVERY');
export const decodeDeliverOperation = operation('DELIVER');
