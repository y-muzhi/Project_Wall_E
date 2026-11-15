import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { balanceMicro, cnyBalance, formatCnyBalance, money, moneyMicro } from './code-values.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
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

export const testingTasksPath = '/api/v1/testing-tasks';
export const testingTaskPath = (task: number) => testingTasksPath + '/' + id(task);
export const testingTaskControlPath = (
  task: number,
  action: 'terminate' | 'assets' | 'budget' | 'run' | 'resume' | 'reconcile' | 'draft-plan',
) => testingTaskPath(task) + '/' + action;
export const testingTaskStatuses = [
  'DRAFT',
  'PLANNING',
  'READY',
  'RUNNING',
  'WAITING',
  'STOPPING',
  'COMPLETED',
  'TERMINATED',
] as const;
export const testingTaskPurposes = ['DIAGNOSTIC', 'ACCEPTANCE', 'PACK_VALIDATION'] as const;
const actions = [
  'DRAFT_PLAN',
  'ATTACH_ASSETS',
  'RUN_TEST',
  'INCREASE_TEST_BUDGET',
  'RESUME',
  'RECONCILE',
  'TERMINATE',
] as const;
const reasons = [
  'TASK_STATE',
  'ASSET_NOT_READY',
  'MODEL_NOT_READY',
  'EXECUTION_NOT_READY',
  'BUDGET_NOT_READY',
  'OPERATION_UNKNOWN',
  'AUTHORIZATION_NOT_READY',
  'REFERENCE_SET_NOT_REGISTERED',
] as const;
const fields = {
  target_kind: choices(['SNAPSHOT', 'CANDIDATE']),
  candidate_id: nullable(id),
  snapshot_id: nullable(id),
  purpose: choices(testingTaskPurposes),
};
const selectable = {
  plan_version_id: nullable(id),
  test_pack_version_id: nullable(id),
};
const budgetInput = money;
const fixed = {
  ...testingBasisFields,
  ...fields,
  profile_version_id: id,
  authorization_id: id,
  budget_limit_cny: budgetInput,
  ...selectable,
  previous_testing_task_id: nullable(id),
};
function checkTarget(row: {
  target_kind: 'SNAPSHOT' | 'CANDIDATE';
  candidate_id: number | null;
  snapshot_id: number | null;
}) {
  require((row.candidate_id !== null) === (row.target_kind === 'CANDIDATE'));
  require((row.snapshot_id !== null) === (row.target_kind === 'SNAPSHOT'));
}
function checkBasis(row: {
  document_id: number;
  material_refs: readonly { document_id: number }[];
}) {
  distinct(row.material_refs.map((item) => item.document_id));
  require(row.material_refs.every((item) => item.document_id !== row.document_id));
}
export const createTestingTaskInput = checked(shape(fixed), (row) => {
  checkTarget(row);
  checkBasis(row);
  require(row.purpose !== 'PACK_VALIDATION');
  require((row.plan_version_id === null) === (row.test_pack_version_id === null));
});
export type CreateTestingTaskInput = ReturnType<typeof createTestingTaskInput>;

const summaryFields = {
  id,
  requirement_id: id,
  document_id: id,
  ...fields,
  status: choices(testingTaskStatuses),
  phase: choices(['PLAN', 'PREPARE', 'EXECUTE', 'REPORT', 'FINISHED']),
  created_at: time,
  report_id: nullable(id),
};
export const testingTaskSummary = checked(shape(summaryFields), (row) => {
  checkTarget(row);
  require((row.status === 'COMPLETED') === (row.report_id !== null));
});
export type TestingTaskSummary = ReturnType<typeof testingTaskSummary>;
const runtime = shape({
  environment_status: choices(['NOT_PREPARED', 'PREPARING', 'VERIFIED', 'UNAVAILABLE', 'UNKNOWN']),
  activity_status: choices(['NOT_STARTED', 'ACTIVE', 'QUIESCENT', 'UNKNOWN']),
  stop_status: choices([
    'NONE',
    'REQUESTED',
    'ABORTING',
    'TERMINATING',
    'VERIFYING',
    'VERIFIED',
    'UNKNOWN',
  ]),
  cleanup_status: choices(['NOT_STARTED', 'CLEANING', 'VERIFIED', 'FAILED', 'UNKNOWN']),
  reason_codes: array(nonempty, 64),
  active_process_count: nullable(count),
  observed_at: nullable(time),
});
const budget = checked(
  shape({
    budget_limit_cny: money,
    settled_cny: money,
    reserved_cny: money,
    available_cny: cnyBalance,
    model_request_count: count,
    request_limit: count,
  }),
  (row) => {
    require(
      balanceMicro(row.available_cny) ===
        moneyMicro(row.budget_limit_cny) -
          moneyMicro(row.settled_cny) -
          moneyMicro(row.reserved_cny),
    );
  },
);
const control = checked(
  shape({
    action: choices(actions),
    enabled: bool,
    reason_code: nullable(choices(reasons)),
  }),
  (row) => require(row.enabled === (row.reason_code === null)),
);
export const testingTaskView = checked(
  shape({
    ...fixed,
    ...summaryFields,
    kind: choices(['PRODUCT', 'PACK_VALIDATION']),
    state_version: id,
    control_generation: id,
    current_verification_id: nullable(id),
    draft_plan_operation_id: nullable(id),
    active_operation_id: nullable(id),
    validation_id: nullable(id),
    termination_operation_id: nullable(id),
    stop_requested_at: nullable(time),
    stopped_at: nullable(time),
    ended_at: nullable(time),
    available_actions: array(control, actions.length, actions.length),
    runtime,
    budget,
    draft_plan_result: nullable(shape({ operation_id: id, plan_id: id, plan_version_id: id })),
  }),
  (row) => {
    checkTarget(row);
    checkBasis(row);
    require((row.status === 'COMPLETED') === (row.report_id !== null));
    require((row.plan_version_id === null) === (row.test_pack_version_id === null));
    require((row.kind === 'PACK_VALIDATION') === (row.validation_id !== null));
    require((row.kind === 'PACK_VALIDATION') === (row.purpose === 'PACK_VALIDATION'));
    require(row.previous_testing_task_id !== row.id);
    require(row.budget.budget_limit_cny === row.budget_limit_cny);
    require(row.available_actions.every((item, index) => item.action === actions[index]));
    if (row.draft_plan_result !== null)
      require(row.draft_plan_result.operation_id === row.draft_plan_operation_id);
    if (row.status === 'TERMINATED')
      require(row.phase === 'FINISHED' && row.termination_operation_id !== null);
  },
);
export type TestingTaskView = ReturnType<typeof testingTaskView>;

const readErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const;
const policy = codeErrorPolicy(readErrors);
const baseErrors = [
  ...readErrors,
  'COMMAND_CLOSED',
  'OPERATION_CONFLICT',
  'VERSION_CONFLICT',
  'INVALID_STATE',
] as const;
const updateErrors = [
  ...baseErrors,
  'TASK_ENDED',
  'AUTHORIZATION_NOT_APPLICABLE',
  'TEST_SOURCE_MISMATCH',
  'TEST_ASSET_REVOKED',
  'CONTENT_NOT_READY',
  'BUDGET_NOT_INCREASED',
] as const;
const created = checked(shape({ testing_task_id: id, state_version: id }), (row) =>
  require(row.state_version === 1),
);
const expected = shape({ expected_state_version: id });
const attach = shape({ expected_state_version: id, plan_version_id: id, test_pack_version_id: id });
const increase = shape({
  expected_state_version: id,
  new_budget_limit_cny: budgetInput,
  authorization_id: id,
});
const accepted = shape({ testing_task_id: id, state_version: id, operation_id: id });
export const CREATE_TESTING_TASK: CodeCommandBinding<ReturnType<typeof created>> = {
  decoder_kind: 'APP-TEST-CMD-C23',
  success_status: [201],
  errors: [...updateErrors, 'BASIS_REF_INVALID'],
  validate_input: createTestingTaskInput,
  decode(value, original) {
    require(original.path === testingTasksPath && original.owner_module === 'TESTING');
    return created(value);
  },
};
export const ATTACH_TESTING_ASSETS: CodeCommandBinding<TestingTaskView> = {
  decoder_kind: 'APP-TEST-CMD-C27',
  success_status: [200],
  errors: updateErrors,
  validate_input: attach,
  decode(value, original, input) {
    const row = testingTaskView(value);
    const wanted = attach(input);
    require(row.id === original.parameters.testing_task_id);
    require(
      row.plan_version_id === wanted.plan_version_id &&
        row.test_pack_version_id === wanted.test_pack_version_id,
    );
    require(
      row.state_version === wanted.expected_state_version ||
        row.state_version === wanted.expected_state_version + 1,
    );
    return row;
  },
};
export const INCREASE_TESTING_BUDGET: CodeCommandBinding<TestingTaskView> = {
  decoder_kind: 'APP-TEST-CMD-C29',
  success_status: [200],
  errors: updateErrors,
  validate_input: increase,
  decode(value, original, input) {
    const row = testingTaskView(value);
    const wanted = increase(input);
    require(
      row.id === original.parameters.testing_task_id &&
        row.state_version === wanted.expected_state_version + 1,
    );
    require(
      row.authorization_id === wanted.authorization_id &&
        row.budget_limit_cny === formatCnyBalance(moneyMicro(wanted.new_budget_limit_cny)),
    );
    return row;
  },
};
const recover = shape({ expected_state_version: id, operation_id: id });
const executionErrors = [...updateErrors, 'CONFIG_NOT_READY', 'OPERATION_IN_PROGRESS'] as const;
function testingExecution(
  decoder_kind: 'APP-TEST-CMD-C26' | 'APP-TEST-CMD-C28' | 'APP-TEST-CMD-C30' | 'APP-TEST-CMD-C32',
): CodeCommandBinding<ReturnType<typeof accepted>> {
  const run = decoder_kind === 'APP-TEST-CMD-C28' || decoder_kind === 'APP-TEST-CMD-C26';
  const validate_input = run ? expected : recover;
  return {
    decoder_kind,
    success_status: [202],
    errors: executionErrors,
    validate_input,
    decode(value, original, input) {
      const row = accepted(value);
      const wanted = validate_input(input);
      require(row.testing_task_id === original.parameters.testing_task_id);
      require(row.state_version === wanted.expected_state_version + Number(run));
      return row;
    },
  };
}
export const DRAFT_TESTING_PLAN = testingExecution('APP-TEST-CMD-C26');
export const RUN_TESTING_TASK = testingExecution('APP-TEST-CMD-C28');
export const RESUME_TESTING_TASK = testingExecution('APP-TEST-CMD-C30');
export const RECONCILE_TESTING_TASK = testingExecution('APP-TEST-CMD-C32');
export const STOP_TESTING_TASK: CodeCommandBinding<TestingTaskView | ReturnType<typeof accepted>> =
  {
    decoder_kind: 'APP-TEST-CMD-C31',
    success_status: [200, 202],
    errors: baseErrors,
    validate_input: expected,
    decode(value, original) {
      if (typeof value === 'object' && value !== null && 'operation_id' in value) {
        const row = accepted(value);
        require(row.testing_task_id === original.parameters.testing_task_id);
        return row;
      }
      const row = testingTaskView(value);
      require(
        row.id === original.parameters.testing_task_id &&
          (row.status === 'TERMINATED' || row.status === 'COMPLETED'),
      );
      return row;
    },
  };

export type TestingTaskFilters = Readonly<
  Partial<
    Pick<TestingTaskSummary, 'requirement_id' | 'document_id' | 'status' | 'purpose'> & {
      candidate_id: number;
      snapshot_id: number;
    }
  >
>;
export async function readTestingTasks(
  client: ApiClient,
  filters: TestingTaskFilters,
  page: number,
  signal?: AbortSignal,
) {
  const query: [string, string][] = [['page', String(page)]];
  for (const [key, value] of Object.entries(filters)) query.push([key, String(value)]);
  const rows = await readPage(
    client,
    testingTasksPath,
    checked(testingTaskSummary, (row) => {
      for (const key of Object.keys(filters) as (keyof TestingTaskFilters)[])
        require(row[key] === filters[key]);
    }),
    (row) => row.id,
    query,
    page,
    signal,
    policy,
  );
  require(rows.data.items.every((row, index, all) => index === 0 || all[index - 1]!.id < row.id));
  return rows;
}
export function readTestingTask(client: ApiClient, task: number, signal?: AbortSignal) {
  return client.read(
    testingTaskPath(task),
    checked(testingTaskView, (row) => require(row.id === task)),
    [],
    signal,
    policy,
  );
}
