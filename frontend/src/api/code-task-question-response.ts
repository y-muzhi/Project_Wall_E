/** Original C46 command and the public answer operation. */
import { exact, positiveInteger } from './client.ts';
import type { JsonObject } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
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

export const answerActions = ['CITE_FIXED_BASIS', 'USE_FIXED_BASIS', 'CLARIFY_FACTS'] as const;
export const factKinds = ['OBSERVATION', 'REPRODUCTION', 'EXISTING_BEHAVIOR'] as const;
export const evidenceKinds = [
  'VERIFICATION_ITEM',
  'QUESTION',
  'OPERATION',
  'COMMAND',
  'LLM_USE',
] as const;
export const questionResponsePath = (task: number, question: number) =>
  '/api/v1/code-tasks/' +
  positiveInteger(task) +
  '/questions/' +
  positiveInteger(question) +
  '/responses';

function index(value: unknown) {
  require(typeof value === 'number' && Number.isSafeInteger(value) && value >= 0);
  return value;
}
const basisRef = shape({ document_id: positiveInteger, revision_id: positiveInteger, quote: text });
const evidenceRef = shape({ kind: choices(evidenceKinds), id: positiveInteger });
export type QuestionBasisRef = ReturnType<typeof basisRef>;
export type QuestionEvidenceRef = ReturnType<typeof evidenceRef>;
export const decodeQuestionEvidenceRef = evidenceRef;
const answer = checked(
  shape({
    index,
    action: choices(answerActions),
    basis_refs: array(basisRef, 65536),
    clarification: nullable(
      shape({
        kind: choices(factKinds),
        text,
        option_indices: array(index, 65536),
        evidence_refs: array(evidenceRef, 65536),
      }),
    ),
  }),
  (row) => {
    const hasBasis = row.basis_refs.length > 0;
    require(row.basis_refs.every((ref) => /[^\p{White_Space}]/u.test(ref.quote)));
    if (row.action === 'CLARIFY_FACTS') {
      const fact = row.clarification;
      require(fact !== null);
      const normalized = fact.text.replace(/\r\n?/g, '\n');
      require(
        /[^\p{White_Space}]/u.test(normalized) &&
          [...normalized].length <= 2000 &&
          (fact.kind !== 'EXISTING_BEHAVIOR' || hasBasis),
      );
      distinct(fact.option_indices);
    } else require(row.clarification === null && hasBasis === (row.action === 'CITE_FIXED_BASIS'));
  },
);
export type NativeQuestionAnswer = ReturnType<typeof answer>;
const answers = checked(array(answer, 65536, 1), (rows) =>
  require(rows.every((row, i) => row.index === i)),
);
const inputFields = {
  expected_state_version: positiveInteger,
  session_id: positiveInteger,
  answers,
};
export const decodeQuestionResponseInput = shape(inputFields);
const fixed = shape({ task_id: positiveInteger, question_id: positiveInteger, ...inputFields });
const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['RUNNING', 'WAITING']),
  state_version: positiveInteger,
});

function input(value: JsonObject, original: CommandIdentity) {
  require(original.decoder_kind === 'APP-CODE-CMD-C46' && original.owner_module === 'CODING');
  return decodeQuestionResponseInput(value);
}

export const QUESTION_RESPONSE_BINDING: CodeCommandBinding<ReturnType<typeof receipt>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C46',
    success_status: Object.freeze([202] as const),
    errors: Object.freeze([
      'INVALID_INPUT',
      'NOT_FOUND',
      'INVALID_STATE',
      'TASK_ENDED',
      'VERSION_CONFLICT',
      'OPERATION_CONFLICT',
      'OPERATION_IN_PROGRESS',
      'COMMAND_CLOSED',
      'QUESTION_NOT_OPEN',
      'SESSION_NOT_CURRENT',
      'BASIS_REF_INVALID',
      'PERMISSION_NOT_GRANTED',
      'CONFIG_NOT_READY',
      'STORAGE_UNAVAILABLE',
      'INTERNAL_ERROR',
    ] as const),
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
const progression = {
  PENDING: ['PENDING', 'PENDING', 'PENDING'],
  RUNNING: ['SUCCEEDED', 'RUNNING', 'PENDING'],
  UNKNOWN: ['SUCCEEDED', 'UNKNOWN', 'PENDING'],
  FAILED: ['FAILED', 'PENDING', 'PENDING'],
  CANCELLED: ['PENDING', 'PENDING', 'PENDING'],
  SUCCEEDED: ['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED'],
} as const;
export const decodeQuestionOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['ANSWER_QUESTION']),
    idempotency_key: text,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(statuses),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(
      choices(['QUESTION_NOT_OPEN', 'CONFIG_NOT_READY', 'TASK_ENDED', 'EXTERNAL_RESULT_UNKNOWN']),
    ),
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(statuses),
        external_identity: nullable((value: unknown) => exact(value, [])),
        fixed_input: fixed,
        result_ref: nullable(shape({ question_id: positiveInteger })),
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
      questionResponsePath(row.task_id, base.question_id),
      row.idempotency_key,
    );
    require(
      row.resource_id === row.task_id &&
        row.task_id === base.task_id &&
        row.session_id === base.session_id &&
        row.expected_state_version === base.expected_state_version,
    );
    const terminal = status === 'FAILED' || status === 'CANCELLED' || status === 'SUCCEEDED';
    const untouched = status === 'PENDING' || status === 'CANCELLED';
    require(
      (started === null) === untouched &&
        (ended !== null) === terminal &&
        created <= (started ?? created) &&
        (started ?? created) <= (ended ?? started ?? created),
    );
    require(
      status === 'FAILED'
        ? row.failure_code === 'QUESTION_NOT_OPEN' || row.failure_code === 'CONFIG_NOT_READY'
        : row.failure_code ===
            (status === 'UNKNOWN'
              ? 'EXTERNAL_RESULT_UNKNOWN'
              : status === 'CANCELLED'
                ? 'TASK_ENDED'
                : null),
    );
    for (const [i, step] of row.steps.entries()) {
      const phase = progression[status][i];
      const complete = phase === 'SUCCEEDED' || phase === 'FAILED';
      const stepStarted = step.started_at ?? created,
        observed = step.last_observed_at ?? created,
        finish = step.ended_at ?? observed;
      require(
        step.operation_id === row.id &&
          step.step_no === i + 1 &&
          step.step_type === steps[i] &&
          step.status === phase &&
          JSON.stringify(step.fixed_input) === JSON.stringify(base) &&
          (step.external_identity !== null) === (i === 1 && phase !== 'PENDING') &&
          (step.started_at === null) === (phase === 'PENDING') &&
          (step.last_observed_at === null) === (phase === 'PENDING') &&
          (step.ended_at !== null) === complete &&
          created <= stepStarted &&
          stepStarted <= finish &&
          finish <= observed,
      );
      require(
        (step.result_ref?.question_id ?? null) ===
          (phase === 'SUCCEEDED' && i !== 1 ? base.question_id : null),
      );
    }
  },
);
export type QuestionOperation = ReturnType<typeof decodeQuestionOperation>;
