import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { array, checked, choices, id, nullable, require, shape, text, time } from './decoding.ts';
import { readPage } from './pagination.ts';
import { testingTaskPath } from './testing-tasks.ts';

const controls = {
  TERMINATE: ['FENCE', 'STOP_OWN_ACTIVITIES', 'VERIFY_STOP', 'CLEANUP', 'SAVE_TERMINATED'],
  ATTACH_ASSETS: ['VALIDATE', 'SAVE_FACT'],
  INCREASE_TEST_BUDGET: ['VALIDATE', 'SAVE_FACT'],
  DRAFT_PLAN: ['BUILD_CONTEXT', 'RESERVE', 'CALL_MODEL', 'SAVE_DRAFT'],
  RUN_TEST: [
    'FIX_INPUT',
    'MATERIALIZE',
    'PREPARE',
    'EXECUTE',
    'STOP',
    'VERIFY_INPUT',
    'CLEANUP',
    'SAVE_REPORT',
  ],
  RESUME: ['RECONCILE', 'CHECK_CONDITIONS', 'CONTINUE_OR_OBSERVE'],
  RECONCILE: ['QUERY', 'COMPARE', 'RECORD'],
} as const;
const status = choices(['PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED']);
const fingerprint = checked(text, (value) => require(/^[a-f0-9]{64}$/.test(value)));
const versionInput = { expected_state_version: id };
const runInput = shape({ ...versionInput, input_fingerprint: fingerprint });
const recoveryInput = shape({ ...versionInput, operation_id: id });
const observed = shape({ operation_id: id, observed_status: status });
const terminal = (state: ReturnType<typeof status>) =>
  state === 'SUCCEEDED' || state === 'FAILED' || state === 'CANCELLED';
const absent = (value: unknown): null => {
  require(value === null);
  return null;
};
const operation = checked(
  shape({
    id,
    task_id: absent,
    testing_task_id: id,
    resource_kind: choices(['TESTING_TASK']),
    resource_id: id,
    session_id: absent,
    content_capture: absent,
    operation_type: choices([
      'TERMINATE',
      'ATTACH_ASSETS',
      'INCREASE_TEST_BUDGET',
      'RUN_TEST',
      'DRAFT_PLAN',
      'RESUME',
      'RECONCILE',
    ]),
    idempotency_key: checked(text, (value) =>
      require(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value)),
    ),
    expected_state_version: id,
    fixed_input: (value: unknown) => value,
    control_generation: id,
    status,
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(text),
    steps: array(
      shape({
        operation_id: id,
        step_no: id,
        step_type: text,
        status,
        external_identity: absent,
        fixed_input: (value: unknown) => value,
        result_ref: (value: unknown) => value,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      8,
      2,
    ),
  }),
  (row) => {
    require(row.resource_id === row.testing_task_id);
    if (row.operation_type === 'DRAFT_PLAN') {
      checkDraft(row);
      return;
    }
    if (
      row.operation_type === 'RUN_TEST' ||
      row.operation_type === 'RESUME' ||
      row.operation_type === 'RECONCILE'
    ) {
      checkExecution(row);
      return;
    }
    require(row.started_at !== null);
    const started = row.started_at;
    require((row.status === 'SUCCEEDED') === (row.ended_at !== null));
    require(row.failure_code === (row.status === 'UNKNOWN' ? 'EXECUTION_NOT_STOPPED' : null));
    require(row.status === 'RUNNING' || row.status === 'UNKNOWN' || row.status === 'SUCCEEDED');
    require(row.operation_type === 'TERMINATE' || row.status === 'SUCCEEDED');
    require(row.created_at <= started && (row.ended_at === null || started <= row.ended_at));
    const base = { expected_state_version: id };
    const decode =
      row.operation_type === 'TERMINATE'
        ? shape(base)
        : row.operation_type === 'ATTACH_ASSETS'
          ? shape({ ...base, plan_version_id: id, test_pack_version_id: id })
          : shape({ ...base, new_budget_limit_cny: text, authorization_id: id });
    const input = decode(row.fixed_input);
    require(input.expected_state_version === row.expected_state_version);
    const sequence = controls[row.operation_type];
    require(row.steps.length === sequence.length);
    row.steps.forEach((step, index) => {
      require(
        step.step_no === index + 1 &&
          step.operation_id === row.id &&
          step.step_type === sequence[index],
      );
      require(JSON.stringify(decode(step.fixed_input)) === JSON.stringify(input));
      const expected =
        row.status === 'SUCCEEDED' || index === 0
          ? 'SUCCEEDED'
          : row.status === 'UNKNOWN' && index === 1
            ? 'UNKNOWN'
            : 'PENDING';
      require(step.status === expected);
      if (expected === 'SUCCEEDED') {
        require(
          step.started_at !== null && step.ended_at !== null && step.last_observed_at !== null,
        );
        require(
          step.started_at >= started &&
            step.started_at <= step.ended_at &&
            step.ended_at <= step.last_observed_at,
        );
        if (row.operation_type === 'TERMINATE' && index === 1) {
          const refs = shape({ stop_observation_id: id, cleanup_observation_id: id })(
            step.result_ref,
          );
          require(refs.stop_observation_id !== refs.cleanup_observation_id);
        } else require(step.result_ref === null);
      } else if (expected === 'PENDING') {
        require(
          step.started_at === null &&
            step.ended_at === null &&
            step.last_observed_at === null &&
            step.result_ref === null,
        );
      } else {
        require(
          step.started_at !== null &&
            step.last_observed_at !== null &&
            step.ended_at === null &&
            step.result_ref === null,
        );
        require(step.started_at <= step.last_observed_at);
      }
    });
  },
);
function checkDraft(row: ReturnType<typeof operation>) {
  require(row.status !== 'PENDING' && row.started_at !== null);
  require(row.created_at <= row.started_at);
  require((row.ended_at !== null) === terminal(row.status));
  if (row.ended_at !== null) require(row.ended_at >= row.started_at);
  require(
    row.status === 'UNKNOWN'
      ? row.failure_code === 'EXTERNAL_RESULT_UNKNOWN'
      : row.status === 'FAILED'
        ? row.failure_code === 'CONFIG_NOT_READY' || row.failure_code === 'EVIDENCE_INCOMPLETE'
        : row.failure_code === null,
  );
  const decode = shape(versionInput);
  require(decode(row.fixed_input).expected_state_version === row.expected_state_version);
  require(row.steps.length === controls.DRAFT_PLAN.length);
  row.steps.forEach((step, index) => {
    require(
      step.step_no === index + 1 &&
        step.operation_id === row.id &&
        step.step_type === controls.DRAFT_PLAN[index] &&
        decode(step.fixed_input).expected_state_version === row.expected_state_version,
    );
    const pending = step.status === 'PENDING';
    require((step.started_at === null) === pending && (step.last_observed_at === null) === pending);
    require((step.ended_at !== null) === terminal(step.status));
    if (index < 2 || row.status === 'SUCCEEDED') require(step.status === 'SUCCEEDED');
    else if (row.status === 'RUNNING')
      require(pending || (index === 2 && step.status === 'RUNNING'));
    else if (row.status === 'UNKNOWN')
      require(step.status === (index === 2 ? 'UNKNOWN' : 'PENDING'));
    else if (row.status === 'CANCELLED') require(step.status === 'CANCELLED');
    else
      require(
        index === 2
          ? step.status === 'SUCCEEDED' || step.status === 'FAILED'
          : step.status === 'FAILED' || step.status === 'CANCELLED',
      );
    if (step.step_type === 'SAVE_DRAFT' && step.status === 'SUCCEEDED')
      shape({ plan_id: id, plan_version_id: id })(step.result_ref);
    else require(step.result_ref === null);
  });
}

function checkExecution(row: TestingTaskOperation) {
  const run = row.operation_type === 'RUN_TEST';
  const pending = row.status === 'PENDING';
  require(
    run
      ? !pending
      : row.status === 'PENDING' || row.status === 'SUCCEEDED' || row.status === 'FAILED',
  );
  require((row.started_at === null) === pending);
  require((row.ended_at !== null) === terminal(row.status));
  require(
    row.started_at === null ||
      (row.created_at <= row.started_at &&
        (row.ended_at === null || row.started_at <= row.ended_at)),
  );
  if (run) {
    require(
      row.failure_code ===
        (row.status === 'UNKNOWN'
          ? 'EXECUTION_NOT_STOPPED'
          : row.status === 'FAILED'
            ? 'EVIDENCE_INCOMPLETE'
            : null),
    );
  } else require((row.failure_code !== null) === (row.status === 'FAILED'));
  const decode = run ? runInput : recoveryInput;
  const input = decode(row.fixed_input);
  require(input.expected_state_version === row.expected_state_version);
  const sequence = controls[row.operation_type];
  require(row.steps.length === sequence.length);
  let result: ReturnType<typeof observed> | null = null;
  row.steps.forEach((step, index) => {
    require(
      step.step_no === index + 1 &&
        step.operation_id === row.id &&
        step.step_type === sequence[index],
    );
    require(JSON.stringify(decode(step.fixed_input)) === JSON.stringify(input));
    const waiting = step.status === 'PENDING';
    require((step.started_at === null) === waiting && (step.last_observed_at === null) === waiting);
    require((step.ended_at !== null) === terminal(step.status));
    require(row.ended_at === null || terminal(step.status));
    if (step.started_at !== null && step.last_observed_at !== null) {
      require(
        row.started_at !== null &&
          row.started_at <= step.started_at &&
          step.started_at <= step.last_observed_at,
      );
      if (step.ended_at !== null)
        require(step.started_at <= step.ended_at && step.ended_at <= step.last_observed_at);
      if (row.ended_at !== null) require(step.last_observed_at <= row.ended_at);
    }
    if (run) {
      if (step.step_type === 'SAVE_REPORT' && step.status === 'SUCCEEDED') {
        shape({ report_id: id })(step.result_ref);
      } else require(step.result_ref === null);
    } else if (pending) {
      require(waiting && step.result_ref === null);
    } else {
      const expected =
        row.status === 'FAILED' && index === sequence.length - 1 ? 'FAILED' : 'SUCCEEDED';
      require(step.status === expected);
      const outcome = observed(step.result_ref);
      require(
        outcome.operation_id === recoveryInput(input).operation_id &&
          outcome.operation_id !== row.id,
      );
      require(result === null || result.observed_status === outcome.observed_status);
      result = outcome;
    }
  });
}

export type TestingTaskOperation = ReturnType<typeof operation>;
const policy = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
export function readTestingTaskOperation(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    testingTaskPath(task) + '/operations/' + id(identity),
    checked(operation, (row) => require(row.testing_task_id === task && row.id === identity)),
    [],
    signal,
    policy,
  );
}
export function readTestingTaskOperations(
  client: ApiClient,
  task: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    testingTaskPath(task) + '/operations',
    checked(operation, (row) => require(row.testing_task_id === task)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
}
