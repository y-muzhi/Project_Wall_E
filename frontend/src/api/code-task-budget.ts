/** C40 total increase and the immutable saved task snapshot. */
import { exact, positiveInteger } from './client.ts';
import type { JsonObject } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { decodeTaskView } from './code-task-creation.ts';
import type { CodeTaskView } from './code-task-creation.ts';
import { formatCnyBalance, moneyMicro } from './code-values.ts';
import { require, text } from './decoding.ts';

export const taskBudgetPath = (taskId: number) =>
  '/api/v1/code-tasks/' + positiveInteger(taskId) + '/budget';

function check(input: JsonObject, original: CommandIdentity) {
  require(original.owner_module === 'CODING' && original.decoder_kind === 'APP-CODE-CMD-C40');
  const fixed = exact(input, ['expected_state_version', 'new_budget_limit_cny', 'reason']);
  require(text(fixed.reason).trim().length > 0);
  return {
    taskId: positiveInteger(original.parameters.task_id),
    version: positiveInteger(fixed.expected_state_version),
    amount: formatCnyBalance(moneyMicro(fixed.new_budget_limit_cny)),
  };
}

export const INCREASE_CODE_BUDGET_BINDING: CodeCommandBinding<CodeTaskView> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C40',
  success_status: Object.freeze([200] as const),
  errors: Object.freeze([
    'INVALID_INPUT',
    'NOT_FOUND',
    'INVALID_STATE',
    'TASK_ENDED',
    'VERSION_CONFLICT',
    'OPERATION_CONFLICT',
    'OPERATION_IN_PROGRESS',
    'BUDGET_NOT_INCREASED',
    'AUTHORIZATION_NOT_APPLICABLE',
    'CONFIG_NOT_READY',
    'PRECONDITION_FAILED',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'COMMAND_CLOSED',
  ] as const),
  validate_input: check,
  decode(value: unknown, original: CommandIdentity, input: JsonObject) {
    const fixed = check(input, original);
    const task = decodeTaskView(value);
    require(
      task.id === fixed.taskId &&
        task.state_version === fixed.version + 1 &&
        task.budget.limit_cny === fixed.amount &&
        task.status !== 'STOPPING' &&
        task.status !== 'TERMINATED',
    );
    return task;
  },
});
