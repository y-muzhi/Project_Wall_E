import { exact, positiveInteger } from './client.ts';
import type { JsonObject } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { array, checked, choices, nullable, require, shape, text, time } from './decoding.ts';
import { QUESTION_RESPONSE_BINDING } from './code-task-question-response.ts';

export const permissionDecisions = ['ALLOW_ONCE', 'DENY'] as const;
export type PermissionDecision = (typeof permissionDecisions)[number];

export const permissionResponsePath = (task: number, permission: number) =>
  '/api/v1/code-tasks/' +
  positiveInteger(task) +
  '/permissions/' +
  positiveInteger(permission) +
  '/responses';

const inputFields = {
  expected_state_version: positiveInteger,
  session_id: positiveInteger,
  decision: choices(permissionDecisions),
};
const fixed = shape({ task_id: positiveInteger, permission_id: positiveInteger, ...inputFields });
const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['WAITING']),
  state_version: positiveInteger,
});

function input(value: JsonObject, original: CommandIdentity) {
  require(original.decoder_kind === 'APP-CODE-CMD-C47' && original.owner_module === 'CODING');
  return shape(inputFields)(value);
}

export const PERMISSION_RESPONSE_BINDING: CodeCommandBinding<ReturnType<typeof receipt>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C47',
    success_status: Object.freeze([202] as const),
    errors: Object.freeze(
      QUESTION_RESPONSE_BINDING.errors.filter((error) => error !== 'BASIS_REF_INVALID'),
    ),
    validate_input: input,
    decode(value: unknown, original: CommandIdentity, request: JsonObject) {
      const prepared = input(request, original);
      const accepted = receipt(value);
      require(
        accepted.task_id === original.parameters.task_id &&
          accepted.state_version === prepared.expected_state_version + 1,
      );
      return accepted;
    },
  });

function nil(value: unknown): null {
  require(value === null);
  return null;
}
const steps = ['READ_NATIVE', 'SEND_RESPONSE', 'CONFIRM_NATIVE'] as const;
const statuses = ['PENDING', 'RUNNING', 'UNKNOWN', 'FAILED', 'CANCELLED', 'SUCCEEDED'] as const;
const phases = {
  PENDING: ['PENDING/PENDING/PENDING'],
  RUNNING: ['SUCCEEDED/PENDING/PENDING', 'SUCCEEDED/RUNNING/PENDING'],
  UNKNOWN: ['SUCCEEDED/UNKNOWN/PENDING'],
  FAILED: ['FAILED/PENDING/PENDING', 'SUCCEEDED/FAILED/PENDING'],
  CANCELLED: ['PENDING/PENDING/PENDING'],
  SUCCEEDED: ['SUCCEEDED/SUCCEEDED/SUCCEEDED'],
};
const ids = checked(array(positiveInteger, 65536), (values) =>
  require(values.every((value, i) => i === 0 || values[i - 1]! < value)),
);
const seen = shape({ permission_ids: ids });
const processed = shape({ confirmed_permission_ids: ids, pending_permission_ids: ids });
const failures = [
  'QUESTION_NOT_OPEN',
  'CONFIG_NOT_READY',
  'PERMISSION_NOT_GRANTED',
  'TASK_ENDED',
] as const;
const failure = choices([...failures, 'EXTERNAL_RESULT_UNKNOWN']);
const terminal = (status: string) => ['FAILED', 'SUCCEEDED', 'CANCELLED'].includes(status);

export const decodePermissionOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['DECIDE_PERMISSION']),
    idempotency_key: text,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(statuses),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(failure),
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(statuses),
        external_identity: nullable((value: unknown) => exact(value, [])),
        fixed_input: fixed,
        result_ref: (value: unknown) => value,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      3,
      3,
    ),
  }),
  (row) => {
    const {
      fixed_input: base,
      status,
      created_at: created,
      started_at: started,
      ended_at: ended,
    } = row;
    registeredCommand(
      'POST',
      permissionResponsePath(row.task_id, base.permission_id),
      row.idempotency_key,
    );
    require(
      row.resource_id === row.task_id &&
        row.task_id === base.task_id &&
        row.session_id === base.session_id &&
        row.expected_state_version === base.expected_state_version,
    );
    require(
      (started === null) === (status === 'PENDING' || status === 'CANCELLED') &&
        (ended !== null) === terminal(status) &&
        created <= (started ?? created) &&
        (started ?? created) <= (ended ?? started ?? created),
    );
    require(
      status === 'FAILED'
        ? failures.some((reason) => reason === row.failure_code)
        : row.failure_code ===
            (status === 'UNKNOWN'
              ? 'EXTERNAL_RESULT_UNKNOWN'
              : status === 'CANCELLED'
                ? 'TASK_ENDED'
                : null),
    );
    require(phases[status].includes(row.steps.map((step) => step.status).join('/')));
    for (const [i, step] of row.steps.entries()) {
      const phase = step.status;
      const dispatched = i === 1 && ['RUNNING', 'UNKNOWN', 'SUCCEEDED'].includes(phase);
      const start = step.started_at ?? created;
      const observed = step.last_observed_at ?? created;
      require(
        step.operation_id === row.id &&
          step.step_no === i + 1 &&
          step.step_type === steps[i] &&
          JSON.stringify(step.fixed_input) === JSON.stringify(base) &&
          (step.external_identity !== null) === dispatched &&
          (step.started_at === null) === (phase === 'PENDING') &&
          (step.last_observed_at === null) === (phase === 'PENDING') &&
          (step.ended_at !== null) === (phase === 'SUCCEEDED' || phase === 'FAILED') &&
          created <= start &&
          start <= (step.ended_at ?? observed) &&
          (step.ended_at ?? observed) <= observed,
      );
    }
    const [read, send, confirm] = row.steps;
    require(read !== undefined && send !== undefined && confirm !== undefined);
    const observed = read.status === 'SUCCEEDED' ? seen(read.result_ref).permission_ids : [];
    if (read.status === 'SUCCEEDED') {
      require(
        observed.includes(base.permission_id) &&
          (base.decision === 'DENY' || observed.length === 1),
      );
    } else require(read.result_ref === null);
    if (send.status === 'UNKNOWN' || send.status === 'SUCCEEDED') {
      const result = processed(send.result_ref);
      const ids = [...result.confirmed_permission_ids, ...result.pending_permission_ids].sort(
        (a, b) => a - b,
      );
      require(
        JSON.stringify(ids) === JSON.stringify(observed) &&
          result.pending_permission_ids.length > 0 === (send.status === 'UNKNOWN'),
      );
      if (status === 'SUCCEEDED')
        require(JSON.stringify(processed(confirm.result_ref)) === JSON.stringify(result));
      else require(confirm.result_ref === null);
    } else require(send.result_ref === null && confirm.result_ref === null);
  },
);
export type PermissionOperation = ReturnType<typeof decodePermissionOperation>;
