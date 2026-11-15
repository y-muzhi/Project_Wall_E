/** C36 original model continuation and its non-secret background facts. */
import type { ApiClient, JsonObject } from './client.ts';
import { ApiUnknown, exact, positiveInteger } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import {
  array,
  checked,
  choices,
  distinct,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';

export const taskResumePath = (taskId: number) =>
  '/api/v1/code-tasks/' + positiveInteger(taskId) + '/resume';

const positiveIds = checked(array(positiveInteger, 64 * 1024), distinct);
const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['WAITING']),
  state_version: positiveInteger,
});

function input(value: JsonObject, original: CommandIdentity) {
  require(original.owner_module === 'CODING' && original.decoder_kind === 'APP-CODE-CMD-C36');
  const confirmation = Object.hasOwn(value, 'repository_quiescent_confirmed');
  const keys = ['expected_state_version', 'operation_id', 'waiting_item_ids'];
  if (confirmation) keys.push('repository_quiescent_confirmed');
  const fixed = exact(value, keys);
  require(!confirmation || fixed.repository_quiescent_confirmed === true);
  return {
    task: positiveInteger(original.parameters.task_id),
    version: positiveInteger(fixed.expected_state_version),
    operation: positiveInteger(fixed.operation_id),
    waits: positiveIds(fixed.waiting_item_ids),
  };
}

export const RESUME_CODE_TASK_BINDING: CodeCommandBinding<ReturnType<typeof receipt>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C36',
    success_status: Object.freeze([202] as const),
    errors: Object.freeze([
      'INVALID_INPUT',
      'NOT_FOUND',
      'INVALID_STATE',
      'TASK_ENDED',
      'VERSION_CONFLICT',
      'OPERATION_CONFLICT',
      'OPERATION_IN_PROGRESS',
      'EXTERNAL_RESULT_UNKNOWN',
      'EXECUTION_NOT_STOPPED',
      'CONFIG_NOT_READY',
      'STORAGE_UNAVAILABLE',
      'INTERNAL_ERROR',
      'COMMAND_CLOSED',
    ] as const),
    validate_input: input,
    decode(value: unknown, original: CommandIdentity, request: JsonObject) {
      const fixed = input(request, original);
      const accepted = receipt(value);
      require(
        accepted.task_id === fixed.task &&
          accepted.state_version === fixed.version + 1 &&
          accepted.operation_id !== fixed.operation,
      );
      return accepted;
    },
  });

const steps = ['RECONCILE', 'CHECK_CONDITIONS', 'CONTINUE_OR_OBSERVE'] as const;
const states = {
  PENDING: [['PENDING', 'PENDING', 'PENDING']],
  RUNNING: [['SUCCEEDED', 'SUCCEEDED', 'RUNNING']],
  UNKNOWN: [['SUCCEEDED', 'SUCCEEDED', 'UNKNOWN']],
  FAILED: [
    ['FAILED', 'PENDING', 'PENDING'],
    ['SUCCEEDED', 'FAILED', 'PENDING'],
  ],
  SUCCEEDED: [['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED']],
  CANCELLED: [['PENDING', 'PENDING', 'PENDING']],
} as const;
const fixedFields = {
  task_id: positiveInteger,
  expected_state_version: positiveInteger,
  operation_id: positiveInteger,
  waiting_item_ids: positiveIds,
};
const fixedModel = shape(fixedFields);
const fixedDelivery = shape({
  ...fixedFields,
  repository_quiescent_confirmed: (value: unknown) => {
    require(value === true);
    return true as const;
  },
});
function fixed(value: unknown) {
  return typeof value === 'object' &&
    value !== null &&
    Object.hasOwn(value, 'repository_quiescent_confirmed')
    ? fixedDelivery(value)
    : fixedModel(value);
}

function nil(value: unknown): null {
  require(value === null);
  return null;
}

export const decodeTaskResumeOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['RESUME']),
    idempotency_key: text,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(['PENDING', 'RUNNING', 'UNKNOWN', 'FAILED', 'SUCCEEDED', 'CANCELLED']),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(
      choices([
        'EXECUTION_NOT_STOPPED',
        'CONFIG_NOT_READY',
        'EXTERNAL_RESULT_UNKNOWN',
        'TASK_ENDED',
      ]),
    ),
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(['PENDING', 'RUNNING', 'UNKNOWN', 'FAILED', 'SUCCEEDED']),
        external_identity: nullable((value: unknown) => exact(value, [])),
        fixed_input: fixed,
        result_ref: nullable((value: unknown) => {
          try {
            return shape({ operation_id: positiveInteger })(value);
          } catch {
            if (typeof value === 'object' && value !== null) {
              if (Object.hasOwn(value, 'delivery_window_id'))
                return shape({ delivery_window_id: positiveInteger })(value);
              if (Object.hasOwn(value, 'delivery_id'))
                return shape({ delivery_id: positiveInteger })(value);
            }
            return shape({ session_id: positiveInteger })(value);
          }
        }),
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      3,
      3,
    ),
  }),
  (row) => {
    registeredCommand('POST', taskResumePath(row.task_id), row.idempotency_key);
    require(
      row.resource_id === row.task_id &&
        row.fixed_input.task_id === row.task_id &&
        row.fixed_input.expected_state_version === row.expected_state_version &&
        row.fixed_input.operation_id !== row.id &&
        row.fixed_input.waiting_item_ids.length > 0,
    );
    const { status, started_at: started, ended_at: ended, created_at: created } = row;
    const terminal = status === 'FAILED' || status === 'SUCCEEDED' || status === 'CANCELLED';
    require(
      (ended !== null) === terminal &&
        (started === null) === (status === 'PENDING' || status === 'CANCELLED') &&
        created <= (started ?? created) &&
        (started ?? created) <= (ended ?? started ?? created),
    );
    const failure = row.failure_code;
    require(
      status === 'FAILED'
        ? failure === 'EXECUTION_NOT_STOPPED' || failure === 'CONFIG_NOT_READY'
        : status === 'UNKNOWN'
          ? failure === 'EXTERNAL_RESULT_UNKNOWN'
          : status === 'CANCELLED'
            ? failure === 'TASK_ENDED'
            : failure === null,
    );
    require(
      states[status].some((state) =>
        state.every((expected, index) => row.steps[index]?.status === expected),
      ),
    );
    const delivery = 'repository_quiescent_confirmed' in row.fixed_input;
    const result = row.steps[2]?.result_ref;
    const cleanup = !delivery && result != null && 'delivery_id' in result;
    for (const [index, step] of row.steps.entries()) {
      const empty = step.status === 'PENDING';
      const complete = step.status === 'SUCCEEDED' || step.status === 'FAILED';
      const stepStart = step.started_at ?? created;
      const observed = step.last_observed_at ?? created;
      const end = step.ended_at ?? observed;
      require(
        step.operation_id === row.id &&
          step.step_type === steps[index] &&
          step.step_no === index + 1 &&
          step.fixed_input.task_id === row.task_id &&
          step.fixed_input.expected_state_version === row.expected_state_version &&
          step.fixed_input.operation_id === row.fixed_input.operation_id &&
          step.fixed_input.waiting_item_ids.length === row.fixed_input.waiting_item_ids.length &&
          step.fixed_input.waiting_item_ids.every(
            (item, i) => item === row.fixed_input.waiting_item_ids[i],
          ) &&
          'repository_quiescent_confirmed' in step.fixed_input === delivery &&
          (step.external_identity !== null) === (!delivery && !cleanup && index === 2 && !empty) &&
          (step.started_at === null) === empty &&
          (step.last_observed_at === null) === empty &&
          (step.ended_at !== null) === complete &&
          created <= stepStart &&
          stepStart <= end &&
          end <= observed,
      );
      const ref = step.result_ref;
      if (index === 0 && step.status === 'SUCCEEDED')
        require(
          ref !== null &&
            'operation_id' in ref &&
            ref.operation_id === row.fixed_input.operation_id,
        );
      else if (index === 2 && step.status === 'SUCCEEDED')
        require(
          ref !== null &&
            (delivery
              ? 'delivery_window_id' in ref
              : cleanup
                ? 'delivery_id' in ref
                : 'session_id' in ref && ref.session_id === row.session_id),
        );
      else require(ref === null);
    }
  },
);

export type TaskResumeOperation = ReturnType<typeof decodeTaskResumeOperation>;

export async function readTaskResumeOperation(
  client: ApiClient,
  id: number,
  taskId: number,
  signal?: AbortSignal,
  key?: string,
) {
  positiveInteger(id);
  positiveInteger(taskId);
  const result = await client.read(
    '/api/v1/code-operations/' + id,
    checked(decodeTaskResumeOperation, (row) =>
      require(
        row.id === id &&
          row.task_id === taskId &&
          (key === undefined || row.idempotency_key === key),
      ),
    ),
    [],
    signal,
    codeErrorPolicy([
      'INVALID_INPUT',
      'NOT_FOUND',
      'CONFIG_NOT_READY',
      'STORAGE_UNAVAILABLE',
      'INTERNAL_ERROR',
    ]),
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
