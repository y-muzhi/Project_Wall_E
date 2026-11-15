/** Task-scoped operation history uses the same checked projections as the controls. */
import type { ApiClient } from './client.ts';
import { ApiUnknown, object, positiveInteger } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { taskStartOperationDecoder } from './code-task-start.ts';
import { decodeTaskStopOperation } from './code-task-stop.ts';
import { decodeTaskResumeOperation } from './code-task-resume.ts';
import { decodeConfigurationOperation } from './code-task-configuration.ts';
import {
  decodeCaptureOperation,
  decodeVerifyCandidateOperation,
} from './code-task-capture-operation.ts';
import { decodeHandoffOperation } from './code-task-handoff.ts';
import { decodePermissionOperation } from './code-task-permission-response.ts';
import { decodeQuestionOperation } from './code-task-question-response.ts';
import { decodeRoleHandoffOperation } from './code-task-role-operation.ts';
import { decodePublicationOperation } from './code-task-publication.ts';
import { decodePrepareDeliveryOperation, decodeDeliverOperation } from './code-task-delivery.ts';
import { decodeRepairOperation } from './code-task-repair.ts';
import { decodeReportLinkOperation } from './code-task-report-link.ts';
import { decodeReconciliationOperation } from './code-task-reconciliation.ts';
import { require } from './decoding.ts';
import { readPage } from './pagination.ts';

const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

function operationPath(taskId: number) {
  return '/api/v1/code-tasks/' + positiveInteger(taskId) + '/operations';
}

function decodeOperation(value: unknown, taskId: number, operationId?: number) {
  const objectValue = object(value);
  const id = positiveInteger(objectValue.id);
  require(operationId === undefined || id === operationId);
  require(objectValue.task_id === taskId);
  switch (objectValue.operation_type) {
    case 'START':
      return taskStartOperationDecoder(id, taskId)(value);
    case 'APPLY_CONFIGURATION':
      return decodeConfigurationOperation(value);
    case 'RESUME':
      return decodeTaskResumeOperation(value);
    case 'ANSWER_QUESTION':
      return decodeQuestionOperation(value);
    case 'DECIDE_PERMISSION':
      return decodePermissionOperation(value);
    case 'PREPARE_HANDOFF':
      return decodeHandoffOperation(value);
    case 'CAPTURE_AND_CHECK':
      return decodeCaptureOperation(value);
    case 'VERIFY_CANDIDATE':
      return decodeVerifyCandidateOperation(value);
    case 'HANDOFF_ROLE':
      return decodeRoleHandoffOperation(value);
    case 'SUBMIT_FOR_TESTING':
      return decodePublicationOperation(value);
    case 'PREPARE_DELIVERY':
      return decodePrepareDeliveryOperation(value);
    case 'DELIVER':
      return decodeDeliverOperation(value);
    case 'REPAIR':
      return decodeRepairOperation(value);
    case 'LINK_TEST_REPORT':
      return decodeReportLinkOperation(value);
    case 'RECONCILE':
      return decodeReconciliationOperation(value);
    case 'TERMINATE':
      return decodeTaskStopOperation(value);
    default:
      throw new TypeError('Unknown original Coding operation');
  }
}

export type CodeTaskOperation = ReturnType<typeof decodeOperation>;

export async function readTaskOperations(
  client: ApiClient,
  taskId: number,
  page: number,
  signal?: AbortSignal,
) {
  const result = await readPage(
    client,
    operationPath(taskId),
    (value) => decodeOperation(value, taskId),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    errors,
  );
  const rows = result.data.items;
  for (const [index, row] of rows.entries()) {
    const prior = rows[index - 1];
    if (
      prior &&
      !(
        prior.created_at > row.created_at ||
        (prior.created_at === row.created_at && prior.id > row.id)
      )
    )
      throw new ApiUnknown(false);
  }
  return result;
}

export async function readTaskOperation(
  client: ApiClient,
  taskId: number,
  operationId: number,
  signal?: AbortSignal,
) {
  const result = await client.read(
    operationPath(taskId) + '/' + positiveInteger(operationId),
    (value) => decodeOperation(value, taskId, operationId),
    [],
    signal,
    errors,
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
