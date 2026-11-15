/** API44 and API45 read only the persisted original request views. */
import type { ApiClient } from './client.ts';
import { ApiUnknown, exact, positiveInteger } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

export const issueStatuses = [
  'OPEN',
  'ANSWERING',
  'RESOLVED',
  'REJECTED',
  'UNKNOWN',
  'OBSOLETE',
] as const;
export type IssueStatus = (typeof issueStatuses)[number];
export type IssueKind = 'questions' | 'permissions';
const errorPolicy = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
const reasons = [
  'TASK_ENDED',
  'INVALID_STATE',
  'SESSION_NOT_CURRENT',
  'EXTERNAL_RESULT_UNKNOWN',
  'QUESTION_NOT_OPEN',
  'CONFIG_NOT_READY',
  'OPERATION_IN_PROGRESS',
  'PERMISSION_NOT_GRANTED',
] as const;
const action = shape({
  action: choices(['ANSWER_QUESTION', 'PREPARE_HANDOFF', 'ALLOW_ONCE', 'DENY']),
  enabled: bool,
  reason_code: nullable(choices(reasons)),
  related_id: positiveInteger,
});
const base = {
  id: positiveInteger,
  task_id: positiveInteger,
  session_id: positiveInteger,
  instance_id: positiveInteger,
  control_generation: positiveInteger,
  status: choices(issueStatuses),
  observed_at: time,
  resolved_at: nullable(time),
  available_actions: array(action, 2, 2),
};
const question = checked(
  shape({
    ...base,
    native_question_id: text,
    questions: array(
      shape({
        index: (value: unknown) => {
          require(typeof value === 'number' && Number.isSafeInteger(value) && value >= 0);
          return value;
        },
        header: text,
        text,
        options: array(shape({ label: text, description: text }), 65536),
        multiple: bool,
        custom: bool,
      }),
      65536,
      1,
    ),
    handoffs: array(
      shape({ id: positiveInteger, target_document_id: positiveInteger, created_at: time }),
      65536,
    ),
  }),
  (value) => {
    require(/^que_[0-9A-Za-z]{1,96}$/.test(value.native_question_id));
    distinct(value.handoffs.map((entry) => entry.id));
    for (const [index, item] of value.questions.entries())
      require(
        index === item.index &&
          item.header.length > 0 &&
          item.text.length > 0 &&
          item.options.every((option) => option.label.length > 0),
      );
  },
);
const permission = checked(
  shape({
    ...base,
    native_permission_id: text,
    tool_name: text,
    patterns: array(text, 65536),
    object_refs: array(shape({ kind: choices(['WORKSPACE_PATH']), path: text }), 1),
    requested_action: choices(['READ', 'WRITE', 'EXECUTE', 'NETWORK', 'UNKNOWN']),
    tool_ref: nullable((value: unknown) => {
      const row = exact(value, ['messageID', 'callID']);
      const messageID = text(row.messageID),
        callID = text(row.callID);
      require(/^msg_[0-9A-Za-z]{1,96}$/.test(messageID) && callID.length > 0);
      return { messageID, callID };
    }),
  }),
  (value) =>
    require(
      /^per_[0-9A-Za-z]{1,96}$/.test(value.native_permission_id) && value.tool_name.length > 0,
    ),
);

export const decodeNativeQuestion = question;
export type NativeQuestion = ReturnType<typeof question>;
export type NativePermission = ReturnType<typeof permission>;
export type NativeIssue = NativeQuestion | NativePermission;

export async function readTaskIssues(
  client: ApiClient,
  taskId: number,
  kind: IssueKind,
  page: number,
  status: IssueStatus | '',
  signal?: AbortSignal,
) {
  positiveInteger(taskId);
  const parameters: [string, string][] = [['page', String(page)]];
  if (status) parameters.push(['status', status]);
  const actions =
    kind === 'questions' ? ['ANSWER_QUESTION', 'PREPARE_HANDOFF'] : ['ALLOW_ONCE', 'DENY'];
  const response = await readPage(
    client,
    '/api/v1/code-tasks/' + taskId + '/' + kind,
    (raw): NativeIssue => {
      const row = kind === 'questions' ? question(raw) : permission(raw);
      require(
        row.task_id === taskId &&
          (!status || row.status === status) &&
          (row.resolved_at === null || row.resolved_at >= row.observed_at) &&
          row.available_actions.every(
            (item, i) =>
              item.action === actions[i] &&
              item.enabled === (item.reason_code === null) &&
              (!item.enabled || row.status === 'OPEN') &&
              item.related_id === row.id,
          ),
      );
      return row;
    },
    (row) => row.id,
    parameters,
    page,
    signal,
    errorPolicy,
  );
  const rows = response.data.items;
  for (const [index, row] of rows.entries()) {
    const prior = rows[index - 1];
    if (
      prior &&
      !(
        prior.observed_at > row.observed_at ||
        (prior.observed_at === row.observed_at && prior.id > row.id)
      )
    )
      throw new ApiUnknown(false);
  }
  return response;
}
