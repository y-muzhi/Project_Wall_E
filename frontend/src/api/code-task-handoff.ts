/** Existing document links and the original source question remain separate. */
import { ApiUnknown, exact, positiveInteger } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { decodeNativeQuestion } from './code-task-issues.ts';
import {
  decodeQuestionEvidenceRef,
  QUESTION_RESPONSE_BINDING,
} from './code-task-question-response.ts';
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

const taskPath = (taskId: number) => '/api/v1/code-tasks/' + positiveInteger(taskId);
export const prepareHandoffPath = (taskId: number, questionId: number) =>
  taskPath(taskId) + '/questions/' + positiveInteger(questionId) + '/handoff';
const detailPath = (taskId: number, handoffId: number) =>
  taskPath(taskId) + '/handoffs/' + positiveInteger(handoffId);
export const linkHandoffPath = (taskId: number, handoffId: number) =>
  detailPath(taskId, handoffId) + '/links';

export const decodePreparedHandoff = shape({
  handoff_id: positiveInteger,
  task_id: positiveInteger,
  question_id: positiveInteger,
  target_document_id: positiveInteger,
});
const linked = shape({ handoff_event_id: positiveInteger, handoff_id: positiveInteger });
const evidence = array(decodeQuestionEvidenceRef, 65536);
const prepareFields = {
  expected_state_version: positiveInteger,
  target_document_id: positiveInteger,
  evidence_refs: evidence,
};
const prepare = shape(prepareFields);
const kinds = ['DISCUSSION_LINKED', 'REVISION_LINKED', 'ABANDONED'] as const;
const references = {
  guide_run_id: nullable(positiveInteger),
  message_id: nullable(positiveInteger),
  revision_id: nullable(positiveInteger),
};
const validReferences = (row: {
  kind: string;
  guide_run_id: number | null;
  message_id: number | null;
  revision_id: number | null;
}) =>
  require(
    row.kind === 'DISCUSSION_LINKED'
      ? row.guide_run_id !== null || row.message_id !== null
      : row.kind === 'REVISION_LINKED'
        ? row.revision_id !== null
        : row.guide_run_id === null && row.message_id === null && row.revision_id === null,
  );
const link = checked(
  shape({
    expected_state_version: positiveInteger,
    kind: choices(kinds),
    ...references,
  }),
  validReferences,
);
const errors = Object.freeze(
  QUESTION_RESPONSE_BINDING.errors.filter(
    (error) => error !== 'CONFIG_NOT_READY' && error !== 'BASIS_REF_INVALID',
  ),
);

export const PREPARE_HANDOFF_BINDING: CodeCommandBinding<ReturnType<typeof decodePreparedHandoff>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C48',
    success_status: Object.freeze([201] as const),
    errors,
    validate_input: prepare,
    decode(value: unknown, original: CommandIdentity, input: JsonObject) {
      const row = decodePreparedHandoff(value);
      require(
        row.task_id === original.parameters.task_id &&
          row.question_id === original.parameters.question_id &&
          row.target_document_id === prepare(input).target_document_id,
      );
      return row;
    },
  });

export const LINK_HANDOFF_BINDING: CodeCommandBinding<ReturnType<typeof linked>> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C49',
  success_status: Object.freeze([201] as const),
  errors,
  validate_input: link,
  decode(value: unknown, original: CommandIdentity) {
    const row = linked(value);
    require(row.handoff_id === original.parameters.handoff_id);
    return row;
  },
});

const event = checked(
  shape({
    id: positiveInteger,
    handoff_id: positiveInteger,
    kind: choices(['PREPARED', ...kinds]),
    ...references,
    created_at: time,
  }),
  validReferences,
);
const view = shape({
  id: positiveInteger,
  task_id: positiveInteger,
  question_id: positiveInteger,
  target_document_id: positiveInteger,
  operation_id: positiveInteger,
  created_at: time,
  source_question: decodeNativeQuestion,
  evidence_refs: evidence,
  events: array(event, 20),
});
export type HandoffView = ReturnType<typeof view>;

export async function readCodeHandoff(
  client: ApiClient,
  task: number,
  handoff: number,
  page = 1,
  signal?: AbortSignal,
) {
  positiveInteger(page);
  require(page <= 100000);
  const result = await client.read(
    detailPath(task, handoff),
    checked(view, (row) => {
      require(
        row.id === handoff &&
          row.task_id === task &&
          row.source_question.task_id === task &&
          row.source_question.id === row.question_id &&
          row.source_question.handoffs.some(
            (item) =>
              item.id === handoff &&
              item.target_document_id === row.target_document_id &&
              item.created_at === row.created_at,
          ),
      );
      distinct(row.events.map((item) => item.id));
      for (const [index, item] of row.events.entries()) {
        const prior = row.events[index - 1];
        require(
          item.handoff_id === handoff &&
            item.created_at >= row.created_at &&
            (item.kind !== 'PREPARED' || item.created_at === row.created_at) &&
            (!prior ||
              prior.created_at > item.created_at ||
              (prior.created_at === item.created_at && prior.id > item.id)),
        );
      }
    }),
    [['page', String(page)]],
    signal,
    codeErrorPolicy([
      'INVALID_INPUT',
      'NOT_FOUND',
      'CONTENT_NOT_READY',
      'CONFIG_NOT_READY',
      'STORAGE_UNAVAILABLE',
      'INTERNAL_ERROR',
    ]),
  );
  const pagination = result.meta.pagination;
  if (
    !pagination ||
    !('page' in pagination) ||
    pagination.page !== page ||
    result.data.events.length !== Math.min(20, Math.max(0, pagination.total - (page - 1) * 20))
  )
    throw new ApiUnknown(false);
  return { ...result, pagination };
}

function nil(value: unknown): null {
  require(value === null);
  return null;
}

const fixed = shape({
  ...prepareFields,
  task_id: positiveInteger,
  question_id: positiveInteger,
  fixed_basis: array(
    shape({ document_id: positiveInteger, revision_id: positiveInteger }),
    65536,
    1,
  ),
});
export const decodeHandoffOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['PREPARE_HANDOFF']),
    idempotency_key: text,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(['SUCCEEDED']),
    created_at: time,
    started_at: time,
    ended_at: time,
    failure_code: nil,
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(['VALIDATE', 'SAVE_FACT']),
        status: choices(['SUCCEEDED']),
        fixed_input: fixed,
        external_identity: nil,
        result_ref: (value: unknown) => value,
        started_at: time,
        ended_at: time,
        last_observed_at: time,
      }),
      2,
      2,
    ),
  }),
  (row) => {
    const input = row.fixed_input;
    registeredCommand(
      'POST',
      prepareHandoffPath(row.task_id, input.question_id),
      row.idempotency_key,
    );
    require(
      row.task_id === input.task_id &&
        row.task_id === row.resource_id &&
        row.expected_state_version === input.expected_state_version &&
        row.started_at === row.created_at &&
        row.ended_at === row.created_at,
    );
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === (index === 0 ? 'VALIDATE' : 'SAVE_FACT') &&
          step.started_at === row.created_at &&
          step.ended_at === row.created_at &&
          step.last_observed_at === row.created_at &&
          JSON.stringify(step.fixed_input) === JSON.stringify(input),
      );
      if (index === 0)
        require(
          positiveInteger(exact(step.result_ref, ['question_id']).question_id) ===
            input.question_id,
        );
      else linked(step.result_ref);
    }
  },
);
