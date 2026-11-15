import { ApiUnknown, exact, object, positiveInteger } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { array, checked, choices, nullable, require, shape, text, time } from './decoding.ts';

export const taskStartPath = (taskId: number) => '/api/v1/code-tasks/' + taskId + '/start';

const startReceipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['PENDING']),
  state_version: positiveInteger,
});

function version(input: JsonObject, original: CommandIdentity) {
  require(original.owner_module === 'CODING' && original.decoder_kind === 'APP-CODE-CMD-C35');
  return positiveInteger(exact(input, ['expected_state_version']).expected_state_version);
}

export const START_CODE_TASK_BINDING: CodeCommandBinding<ReturnType<typeof startReceipt>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C35',
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
      'PRECONDITION_FAILED',
    ] as const),
    validate_input: version,
    decode(value: unknown, original: CommandIdentity, input: JsonObject) {
      const receipt = startReceipt(value);
      require(
        receipt.task_id === positiveInteger(original.parameters.task_id) &&
          receipt.state_version === version(input, original) + 1,
      );
      return receipt;
    },
  });

const stages = [
  'RESTORE_WORKSPACE',
  'PREPARE_BASIS',
  'CHECK_CONDITIONS',
  'START_INSTANCE',
  'CREATE_SESSION',
  'SEND_INITIAL',
] as const;
const states = ['PENDING', 'RUNNING', 'UNKNOWN', 'CANCELLED', 'FAILED'] as const;
const fixedInput = shape({ task_id: positiveInteger, expected_state_version: positiveInteger });
const failures = choices(['CONTENT_NOT_READY', 'CONFIG_NOT_READY', 'EXTERNAL_RESULT_UNKNOWN']);
function nil(value: unknown): null {
  require(value === null);
  return null;
}
const startOperation = shape({
  id: positiveInteger,
  task_id: positiveInteger,
  testing_task_id: nil,
  resource_kind: choices(['TASK']),
  resource_id: positiveInteger,
  session_id: nullable(positiveInteger),
  operation_type: choices(['START']),
  idempotency_key: text,
  expected_state_version: positiveInteger,
  fixed_input: fixedInput,
  control_generation: positiveInteger,
  status: choices([...states, 'SUCCEEDED']),
  created_at: time,
  started_at: nullable(time),
  ended_at: nullable(time),
  failure_code: nullable(failures),
  steps: array(
    shape({
      operation_id: positiveInteger,
      step_no: positiveInteger,
      step_type: choices(stages),
      status: choices([...states, 'SUCCEEDED']),
      external_identity: nullable((value) => exact(value, [])),
      fixed_input: fixedInput,
      result_ref: (value) => value,
      started_at: nullable(time),
      ended_at: nullable(time),
      last_observed_at: nullable(time),
    }),
    stages.length,
    stages.length,
  ),
  content_capture: nil,
});

export function taskStartOperationDecoder(id: number, taskId: number, key?: string) {
  positiveInteger(id);
  positiveInteger(taskId);
  return checked(startOperation, (row) => {
    registeredCommand('POST', taskStartPath(taskId), row.idempotency_key);
    require(
      row.id === id &&
        row.task_id === taskId &&
        row.resource_id === taskId &&
        (key === undefined || row.idempotency_key === key) &&
        row.fixed_input.task_id === taskId &&
        row.fixed_input.expected_state_version === row.expected_state_version,
    );
    const terminal = ['FAILED', 'CANCELLED', 'SUCCEEDED'].includes(row.status);
    require((row.ended_at !== null) === terminal);
    if (row.status === 'FAILED')
      require(row.failure_code === 'CONFIG_NOT_READY' || row.failure_code === 'CONTENT_NOT_READY');
    else
      require(row.failure_code === (row.status === 'UNKNOWN' ? 'EXTERNAL_RESULT_UNKNOWN' : null));
    const [workspace, basis, check, launch, session, initial] = row.steps;
    require(
      workspace !== undefined &&
        basis !== undefined &&
        check !== undefined &&
        launch !== undefined &&
        session !== undefined &&
        initial !== undefined,
    );
    const tail = [launch.status, session.status, initial.status];
    if (check.status === 'SUCCEEDED') {
      require(workspace.status === 'SUCCEEDED' && basis.status === 'SUCCEEDED');
      const completed = tail.filter((step) => step === 'SUCCEEDED').length;
      require(tail.slice(0, completed).every((step) => step === 'SUCCEEDED'));
      if (row.status === 'SUCCEEDED') {
        require(completed === 3 && initial.ended_at === row.ended_at);
      } else {
        const current = tail[completed];
        require(tail.slice(completed + 1).every((step) => step === 'PENDING'));
        require(
          row.status === 'UNKNOWN'
            ? current === 'UNKNOWN'
            : row.status === 'RUNNING' && (current === 'PENDING' || current === 'RUNNING'),
        );
      }
    } else {
      require(
        tail.every((step) => step === (row.status === 'CANCELLED' ? 'CANCELLED' : 'PENDING')),
      );
    }
    if (session.status === 'PENDING' || session.status === 'CANCELLED')
      require(row.session_id === null);
    else positiveInteger(row.session_id);
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === id &&
          step.step_no === index + 1 &&
          step.step_type === stages[index] &&
          step.fixed_input.task_id === taskId &&
          step.fixed_input.expected_state_version === row.expected_state_version,
      );
      if (step.status === 'SUCCEEDED' && index !== 2) {
        const fields = [
          'workspace_id',
          'document_count',
          null,
          'instance_id',
          'session_id',
          'session_id',
        ];
        const field = fields[index];
        require(typeof field === 'string');
        const resultId = positiveInteger(exact(step.result_ref, [field])[field]);
        if (field === 'session_id') require(resultId === row.session_id);
      } else if (index === 2 && (step.status === 'FAILED' || step.status === 'SUCCEEDED')) {
        const report = object(step.result_ref);
        require(typeof report.fixed_content_verified === 'boolean');
        if (step.status === 'SUCCEEDED') {
          require(
            report.fixed_content_verified === true &&
              Array.isArray(report.capability_codes) &&
              report.capability_codes.length === 0,
          );
        }
      } else require(step.result_ref === null);
    }
  });
}

export async function readTaskStartOperation(
  client: ApiClient,
  id: number,
  taskId: number,
  signal?: AbortSignal,
  key?: string,
) {
  const decoder = taskStartOperationDecoder(id, taskId, key);
  const result = await client.read(
    '/api/v1/code-operations/' + id,
    decoder,
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
  const { id: operationId, task_id, status } = result.data;
  return { ...result, data: { id: operationId, task_id, status } };
}
