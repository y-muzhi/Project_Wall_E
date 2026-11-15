import { readCodeTaskRecords } from './code-task-records.ts';
import { CREATE_CODE_DEFECT, readCodeDefect, readCodeDefects } from './code-task-defects.ts';
import { REQUEST_CODE_REPAIR, readRepair, readRepairs } from './code-task-repair.ts';
import {
  ACCEPT_DELIVERY,
  PREPARE_DELIVERY,
  readDeliveryPlan,
  readDeliveries,
  readDelivery,
} from './code-task-delivery.ts';
import { readPlanComparison } from './code-task-candidates.ts';
import type { CandidateComparisonSide as DeliverySide } from './code-task-candidates.ts';
import { readTestingCall, readTestingCalls } from './testing-usage.ts';
import {
  REVIEW_TESTING_FINDING,
  readTestingCases,
  readTestingFindings,
  readTestingReport,
  readTestingTaskReport,
  readTestingVerification,
} from './testing-reports.ts';
import { readTestingTaskOperation, readTestingTaskOperations } from './testing-task-operations.ts';
import {
  ATTACH_TESTING_ASSETS,
  CREATE_TESTING_TASK,
  INCREASE_TESTING_BUDGET,
  RECONCILE_TESTING_TASK,
  RESUME_TESTING_TASK,
  DRAFT_TESTING_PLAN,
  RUN_TESTING_TASK,
  STOP_TESTING_TASK,
  readTestingTask,
  readTestingTasks,
} from './testing-tasks.ts';
import type { TestingTaskFilters } from './testing-tasks.ts';
import { readTestingSeal, readTestingValidationOperation } from './testing-asset-operation.ts';
import {
  CREATE_TESTING_PACK,
  SEAL_TESTING_PACK,
  VALIDATE_TESTING_PACK,
  PUBLISH_TESTING_PACK,
  REVOKE_TESTING_PACK,
  readTestingPack,
  readTestingPacks,
  readTestingReferenceSets,
  readTestingValidation,
} from './testing-assets.ts';
import {
  CREATE_TEST_PLAN,
  TEST_PLAN_CONTROL_BINDINGS,
  TEST_PLAN_DRAFT_BINDINGS,
  readTestingPlan,
  readTestingPlans,
  readTestingPlanVersion,
  readTestingPlanVersions,
} from './testing-plans.ts';
import { readTestingProfileChoices } from './testing-profile-options.ts';
import {
  TESTING_POLICY_BINDINGS,
  readTestingAuthorization,
  readTestingProfile,
  readTestingProfiles,
} from './testing-policy.ts';
import { readRepositories, readRepository } from './code-repositories.ts';
import { readRepositoryObservation } from './code-repository-observations.ts';
import { readRepositoryOperation } from './code-repository-operations.ts';
import { readCodeBaselineFiles, readCodeSnapshot } from './code-snapshots.ts';
import { CREATE_CODE_TASK_BINDING, prepareCreateCodeTask } from './code-task-creation.ts';
import type { CreateCodeTaskInput } from './code-task-creation.ts';
import { readCodeTask, readDocumentCodeTasks } from './code-task-list.ts';
import type { CandidateComparisonSide } from './code-task-candidates.ts';
import {
  readCandidateComparison,
  readCandidateDiff,
  readCandidateFile,
  readCodeCandidate,
  readCodeCandidates,
} from './code-task-candidates.ts';
import { readTaskOperations, readTaskOperation } from './code-task-operations.ts';
import {
  CANDIDATE_CHECK_BINDINGS,
  readCodeVerification,
  readCodeVerificationCases,
  readCodeVerifications,
} from './code-task-checks.ts';
import { readTaskIssues } from './code-task-issues.ts';
import {
  LINK_HANDOFF_BINDING,
  PREPARE_HANDOFF_BINDING,
  readCodeHandoff,
} from './code-task-handoff.ts';
import { PERMISSION_RESPONSE_BINDING } from './code-task-permission-response.ts';
import { PUBLISH_TESTING_CANDIDATE } from './code-task-publication.ts';
import { LINK_TESTING_REPORT } from './code-task-report-link.ts';
import { RECONCILE_ROLE_DELIVERY } from './code-task-reconciliation.ts';
import { QUESTION_RESPONSE_BINDING } from './code-task-question-response.ts';
import type { IssueKind, IssueStatus } from './code-task-issues.ts';
import { readCodeModelCall, readCodeModelCalls } from './code-task-usage.ts';
import { START_CODE_TASK_BINDING, readTaskStartOperation } from './code-task-start.ts';
import { STOP_CODE_TASK_BINDING, readTaskStopOperation } from './code-task-stop.ts';
import { RESUME_CODE_TASK_BINDING, readTaskResumeOperation } from './code-task-resume.ts';
import { APPLY_CONFIGURATION } from './code-task-configuration.ts';
import { INCREASE_CODE_BUDGET_BINDING } from './code-task-budget.ts';
import type { CodeTaskFilters } from './code-task-list.ts';
import { readDesignRevisions } from './code-design-revisions.ts';
import type { DesignRevisionUsage } from './code-design-revisions.ts';
import {
  REPOSITORY_COMMAND_BINDINGS,
  prepareRegisterCodeBaseline,
  prepareRegisterRepository,
  prepareRefreshRepository,
} from './code-repository-commands.ts';
import type {
  RegisterCodeBaselineInput,
  RegisterRepositoryInput,
} from './code-repository-commands.ts';

import {
  AUTHORIZATION_BINDING,
  prepareAuthorization,
  readAuthorization,
  readAuthorizations,
} from './code-authorizations.ts';
import type { AuthorizationFilters, AuthorizationScope } from './code-authorizations.ts';
import {
  EXECUTION_PROFILE_VERSION_BINDING,
  prepareExecutionProfileVersion,
  readExecutionProfileVersion,
  readExecutionProfileVersions,
} from './code-execution-profiles.ts';
import type { ExecutionProfileContent } from './code-execution-profiles.ts';
/** Explicit V1.5 API bindings. Each action owns its original body/key and
 * response expectations; retry is a caller decision on the same action.
 */
import type { Ctx } from '@milkdown/kit/ctx';
import type { BlockState } from '../documents/contracts.ts';
import { ApiClient, ApiUnknown, ApiRejected, snapshotObject } from './client.ts';
import type { ApiErrorPolicy, ApiSuccess, JsonObject } from './client.ts';
import { array, checked, shape, id, require, distinct, choices } from './decoding.ts';
import type { Decoder } from './decoding.ts';
import { readPage } from './pagination.ts';
import { readConfigurationOptions } from './code-configuration-options.ts';
import {
  CHECK_SET_VERSION_BINDING,
  prepareCheckSetVersion,
  readCheckSetVersion,
  readCheckSetVersions,
} from './code-check-sets.ts';
import type { CheckSetContent } from './code-check-sets.ts';
import type { ConfigurationOptionKind } from './code-configuration-options.ts';
import * as models from './models.ts';
import { modelCalls, modelCallDetail } from './model-calls.ts';
import { suggestionMarkdown } from '../suggestions/preview.ts';
import { DetailReadScope } from './detail-read-scope.ts';
import { prepareCloseOriginalCommand } from './code-command-close.ts';
import type { CommandCloseReceipt } from './code-command-close.ts';
import { readCommandReceipt } from './code-command-receipts.ts';
import type { OriginalResultPolicy, CommandReceipt } from './code-command-receipts.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import {
  configurationCollection,
  configurationIdentityRow,
  configurationIdentityReadErrors,
  prepareConfigurationIdentity,
  CONFIGURATION_IDENTITY_BINDINGS,
} from './code-configuration-identities.ts';
import { CommandRecovery } from '../code-tasks/command-recovery.ts';
import type { OperationReader } from '../code-tasks/command-recovery.ts';
import type { CommandRecoveryStore } from '../code-tasks/command-recovery-store.ts';

export type ApiAction<T> = Readonly<{ submit: (signal?: AbortSignal) => Promise<ApiSuccess<T>> }>;
const sameJson = (left: unknown, right: unknown) =>
  JSON.stringify(left, (_key, value) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
      : value,
  ) ===
  JSON.stringify(right, (_key, value) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
      : value,
  );
export type RequirementFilters = Readonly<{
  keyword?: string;
  status?: readonly (typeof models.requirementStatuses)[number][];
  requirement_type?: readonly (typeof models.requirementTypes)[number][];
  page?: number;
}>;
export type GuideFilters = Readonly<{
  status?: readonly (typeof models.runStatuses)[number][];
  action_type?: readonly (typeof models.runActions)[number][];
  page?: number;
}>;
export type CreateRequirement = Readonly<{
  title: string;
  requirement_type: 'NEW' | 'CHANGE';
  initial_idea?: string;
}>;
export type DiscussionCommand = Readonly<
  | {
      type: 'SET_BINDING';
      target_document_id: number | null;
      source_refs: readonly ReturnType<typeof models.sourceRef>[];
      scope: Readonly<JsonObject> | null;
    }
  | { type: 'SET_FOCUS'; topic_ref: string }
>;
export type CreateDocument = Readonly<{
  name: string;
  document_kind: (typeof models.documentKinds)[number];
  template_ref: ReturnType<typeof models.resourceRef> | null;
}>;
export type DocumentChange = Readonly<
  | { type: 'RENAME'; name: string }
  | { type: 'ARCHIVE' | 'RESTORE' }
  | { type: 'CONFIRM'; expected_content_version: number; revision_id: number }
>;
export type CreateGuide = Readonly<{
  expected_discussion_version: number;
  operation: (typeof models.operations)[number];
  instruction: string;
  target: ReturnType<typeof models.targetRef> | null;
  scope: Readonly<JsonObject> | null;
  source_refs: readonly ReturnType<typeof models.sourceRef>[];
  proposal_ref: Readonly<{ message_id: number; card_key: string }> | null;
  acknowledge_source_changes: boolean;
}>;
export type CreateComment = Readonly<{
  document_id: number;
  expected_content_version: number;
  content: string;
  anchor_type: 'BLOCK' | 'SELECTION';
  block_id: number;
  selection?: Readonly<{ selected_text: string; prefix_text: string; suffix_text: string }>;
}>;
const root = '/api/v1';
const target = (collection: string, identity: number, suffix = '') =>
  `${root}/${collection}/${id(identity)}${suffix}`;
const owned = <T extends { requirement_id: number }>(decode: Decoder<T>, identity: number) =>
  checked(decode, (value) => require(value.requirement_id === identity));
const identified = <T extends { id: number }>(decode: Decoder<T>, identity: number) =>
  checked(decode, (value) => require(value.id === identity));

function bodyFields(
  value: JsonObject,
  mandatory: readonly string[],
  optional: readonly string[] = [],
): void {
  require(
    mandatory.every((key) => Object.hasOwn(value, key)) &&
      Object.keys(value).every((key) => [...mandatory, ...optional].includes(key)),
  );
}
function query(filters: RequirementFilters | GuideFilters): readonly (readonly [string, string])[] {
  const result: [string, string][] = [];
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value)) for (const item of value) result.push([key, item]);
    else if (value !== undefined) result.push([key, String(value)]);
  }
  return result;
}

export class WalleApi {
  private readonly client: ApiClient;
  private readonly ctx: Ctx;
  private readonly readScope: DetailReadScope | undefined;
  private readonly assistantDocumentId: number | null;
  constructor(
    client: ApiClient,
    ctx: Ctx,
    readScope?: DetailReadScope,
    assistantDocumentId: number | null = null,
  ) {
    this.assistantDocumentId = assistantDocumentId;
    this.client = client;
    this.ctx = ctx;
    this.readScope = readScope;
  }
  commandReceipt<T>(
    original: CommandIdentity,
    policy: OriginalResultPolicy<T>,
    signal?: AbortSignal,
  ): Promise<ApiSuccess<CommandReceipt<T>>> {
    return readCommandReceipt(this.client, original, policy, signal);
  }
  prepareCloseOriginalCommand<T>(
    identity: unknown,
    currentOrigin: string,
    policy: OriginalResultPolicy<T>,
  ): Promise<ApiAction<CommandCloseReceipt<T>>> {
    return prepareCloseOriginalCommand(this.client, identity, currentOrigin, policy);
  }
  codeConfigurationOptions(kind: ConfigurationOptionKind, page = 1, signal?: AbortSignal) {
    return readConfigurationOptions(this.client, kind, page, signal);
  }
  codeExecutionProfiles(page = 1, signal?: AbortSignal) {
    return this.page(
      configurationCollection('EXECUTION_PROFILE').path,
      configurationIdentityRow,
      [['page', String(page)]],
      page,
      signal,
      configurationIdentityReadErrors,
    );
  }
  codeCheckSets(page = 1, signal?: AbortSignal) {
    return this.page(
      configurationCollection('CHECK_SET').path,
      configurationIdentityRow,
      [['page', String(page)]],
      page,
      signal,
      configurationIdentityReadErrors,
    );
  }
  prepareCreateCodeExecutionProfile(name: string, currentOrigin: string) {
    return prepareConfigurationIdentity(this.client, 'EXECUTION_PROFILE', name, currentOrigin);
  }
  prepareCreateCodeCheckSet(name: string, currentOrigin: string) {
    return prepareConfigurationIdentity(this.client, 'CHECK_SET', name, currentOrigin);
  }
  codeCheckSetVersion(id: number, signal?: AbortSignal) {
    return readCheckSetVersion(this.client, id, signal);
  }
  codeCheckSetVersions(checkSetId: number, page = 1, signal?: AbortSignal) {
    return readCheckSetVersions(this.client, checkSetId, page, signal);
  }
  preparePublishCodeCheckSetVersion(
    checkSetId: number,
    content: CheckSetContent,
    currentOrigin: string,
  ) {
    return prepareCheckSetVersion(this.client, checkSetId, content, currentOrigin);
  }
  codeExecutionProfileVersion(id: number, signal?: AbortSignal) {
    return readExecutionProfileVersion(this.client, id, signal);
  }
  codeExecutionProfileVersions(profileId: number, page = 1, signal?: AbortSignal) {
    return readExecutionProfileVersions(this.client, profileId, page, signal);
  }
  preparePublishCodeExecutionProfileVersion(
    profileId: number,
    content: ExecutionProfileContent,
    currentOrigin: string,
  ) {
    return prepareExecutionProfileVersion(this.client, profileId, content, currentOrigin);
  }
  codeRepositories(page = 1, signal?: AbortSignal) {
    return readRepositories(this.client, page, signal);
  }
  codeRepository(id: number, signal?: AbortSignal) {
    return readRepository(this.client, id, signal);
  }
  repositoryOperation(operationId: number, signal?: AbortSignal) {
    return readRepositoryOperation(this.client, operationId, signal);
  }
  codeDesignRevisions(
    documentId: number,
    usage: DesignRevisionUsage = 'MAIN',
    page = 1,
    signal?: AbortSignal,
  ) {
    return readDesignRevisions(this.client, documentId, usage, page, signal);
  }
  codeDefects(task: number, page: number, signal?: AbortSignal) {
    return readCodeDefects(this.client, task, page, signal);
  }
  deliveryPlan(task: number, plan: number, page: number, signal?: AbortSignal) {
    return readDeliveryPlan(this.client, task, plan, page, signal);
  }
  deliveryFile(
    task: number,
    plan: number,
    candidate: number,
    path: string,
    side: DeliverySide,
    offset: number,
    length: number,
    signal?: AbortSignal,
  ) {
    return readPlanComparison(
      this.client,
      task,
      plan,
      candidate,
      path,
      side,
      offset,
      length,
      signal,
    );
  }
  deliveries(task: number, page: number, signal?: AbortSignal) {
    return readDeliveries(this.client, task, page, signal);
  }
  delivery(task: number, identity: number, signal?: AbortSignal) {
    return readDelivery(this.client, task, identity, signal);
  }
  codeRepairs(task: number, page: number, signal?: AbortSignal) {
    return readRepairs(this.client, task, page, signal);
  }
  codeRepair(task: number, identity: number, signal?: AbortSignal) {
    return readRepair(this.client, task, identity, signal);
  }
  codeTaskRecords(task: number, page: number, session: number | null, signal?: AbortSignal) {
    return readCodeTaskRecords(this.client, task, page, session, signal);
  }
  codeDefect(task: number, identity: number, signal?: AbortSignal) {
    return readCodeDefect(this.client, task, identity, signal);
  }
  taskStartOperation(id: number, taskId: number, signal?: AbortSignal, key?: string) {
    return readTaskStartOperation(this.client, id, taskId, signal, key);
  }
  taskResumeOperation(id: number, taskId: number, signal?: AbortSignal, key?: string) {
    return readTaskResumeOperation(this.client, id, taskId, signal, key);
  }
  taskStopOperation(id: number, taskId: number, signal?: AbortSignal) {
    return readTaskStopOperation(this.client, id, taskId, signal);
  }
  codeTaskIssues(
    taskId: number,
    kind: IssueKind,
    page: number,
    status: IssueStatus | '',
    signal?: AbortSignal,
  ) {
    return readTaskIssues(this.client, taskId, kind, page, status, signal);
  }
  codeTaskOperations(taskId: number, page: number, signal?: AbortSignal) {
    return readTaskOperations(this.client, taskId, page, signal);
  }
  codeTaskOperation(taskId: number, operationId: number, signal?: AbortSignal) {
    return readTaskOperation(this.client, taskId, operationId, signal);
  }
  codeTaskCandidates(taskId: number, page: number, signal?: AbortSignal) {
    return readCodeCandidates(this.client, taskId, page, signal);
  }
  codeTaskVerifications(taskId: number, candidateId: number, page: number, signal?: AbortSignal) {
    return readCodeVerifications(this.client, taskId, candidateId, page, signal);
  }
  codeTaskVerification(taskId: number, verificationId: number, signal?: AbortSignal) {
    return readCodeVerification(this.client, taskId, verificationId, signal);
  }
  codeTaskVerificationCases(
    taskId: number,
    verificationId: number,
    itemId: number,
    page: number,
    signal?: AbortSignal,
  ) {
    return readCodeVerificationCases(this.client, taskId, verificationId, itemId, page, signal);
  }
  codeTaskCandidateDiff(taskId: number, candidateId: number, page: number, signal?: AbortSignal) {
    return readCandidateDiff(this.client, taskId, candidateId, page, signal);
  }
  codeTaskCandidateFile(
    taskId: number,
    candidateId: number,
    file: string,
    offset: number,
    length: number,
    signal?: AbortSignal,
  ) {
    return readCandidateFile(this.client, taskId, candidateId, file, offset, length, signal);
  }
  codeTaskCandidateComparison(
    taskId: number,
    candidateId: number,
    file: string,
    side: CandidateComparisonSide,
    offset: number,
    length: number,
    signal?: AbortSignal,
  ) {
    return readCandidateComparison(
      this.client,
      taskId,
      candidateId,
      file,
      side,
      offset,
      length,
      signal,
    );
  }
  codeTaskCandidate(taskId: number, candidateId: number, signal?: AbortSignal) {
    return readCodeCandidate(this.client, taskId, candidateId, signal);
  }
  codeTask(taskId: number, signal?: AbortSignal) {
    return readCodeTask(this.client, taskId, signal);
  }
  documentCodeTasks(
    documentId: number,
    page = 1,
    filters: CodeTaskFilters = {},
    signal?: AbortSignal,
  ) {
    return readDocumentCodeTasks(this.client, documentId, page, filters, signal);
  }
  prepareCreateCodeTask(documentId: number, input: CreateCodeTaskInput, currentOrigin: string) {
    return prepareCreateCodeTask(this.client, documentId, input, currentOrigin);
  }
  codeSnapshot(snapshotId: number, signal?: AbortSignal) {
    return readCodeSnapshot(this.client, snapshotId, signal);
  }
  codeModelCalls(taskId: number, page = 1, signal?: AbortSignal) {
    return readCodeModelCalls(this.client, taskId, page, signal);
  }

  codeModelCall(taskId: number, useId: number, signal?: AbortSignal) {
    return readCodeModelCall(this.client, taskId, useId, signal);
  }

  codeBaselineFiles(snapshotId: number, page = 1, signal?: AbortSignal) {
    return readCodeBaselineFiles(this.client, snapshotId, page, signal);
  }
  prepareRegisterRepository(input: RegisterRepositoryInput, currentOrigin: string) {
    return prepareRegisterRepository(this.client, input, currentOrigin);
  }
  prepareRefreshRepository(repositoryId: number, currentOrigin: string) {
    return prepareRefreshRepository(this.client, repositoryId, currentOrigin);
  }
  prepareRegisterCodeBaseline(
    repositoryId: number,
    input: RegisterCodeBaselineInput,
    currentOrigin: string,
  ) {
    return prepareRegisterCodeBaseline(this.client, repositoryId, input, currentOrigin);
  }
  repositoryObservation(repositoryId: number, observationId: number, signal?: AbortSignal) {
    return readRepositoryObservation(this.client, repositoryId, observationId, signal);
  }
  codeAuthorization(id: number, signal?: AbortSignal) {
    return readAuthorization(this.client, id, signal);
  }
  codeAuthorizations(page = 1, filters: AuthorizationFilters = {}, signal?: AbortSignal) {
    return readAuthorizations(this.client, page, filters, signal);
  }
  prepareApproveCodeAuthorization(
    profileVersionId: number,
    scope: AuthorizationScope,
    currentOrigin: string,
  ) {
    return prepareAuthorization(this.client, profileVersionId, scope, currentOrigin);
  }
  testingTasks(filters: TestingTaskFilters, page = 1, signal?: AbortSignal) {
    return readTestingTasks(this.client, filters, page, signal);
  }
  testingTask(id: number, signal?: AbortSignal) {
    return readTestingTask(this.client, id, signal);
  }
  testingCalls(task: number, page: number, signal?: AbortSignal) {
    return readTestingCalls(this.client, task, page, signal);
  }
  testingCall(task: number, identity: number, signal?: AbortSignal) {
    return readTestingCall(this.client, task, identity, signal);
  }
  testingReport(identity: number, signal?: AbortSignal) {
    return readTestingReport(this.client, identity, signal);
  }
  testingTaskReport(task: number, identity: number, signal?: AbortSignal) {
    return readTestingTaskReport(this.client, task, identity, signal);
  }
  testingFindings(report: number, page: number, signal?: AbortSignal) {
    return readTestingFindings(this.client, report, page, signal);
  }
  testingVerification(task: number, verification: number, signal?: AbortSignal) {
    return readTestingVerification(this.client, task, verification, signal);
  }
  testingCases(
    task: number,
    verification: number,
    item: number,
    page: number,
    signal?: AbortSignal,
  ) {
    return readTestingCases(this.client, task, verification, item, page, signal);
  }
  testingTaskOperation(task: number, operation: number, signal?: AbortSignal) {
    return readTestingTaskOperation(this.client, task, operation, signal);
  }
  testingTaskOperations(task: number, page = 1, signal?: AbortSignal) {
    return readTestingTaskOperations(this.client, task, page, signal);
  }
  testingPlans(page = 1, signal?: AbortSignal) {
    return readTestingPlans(this.client, page, signal);
  }
  testingPlan(plan: number, signal?: AbortSignal) {
    return readTestingPlan(this.client, plan, signal);
  }
  testingPlanVersions(plan: number, page = 1, signal?: AbortSignal) {
    return readTestingPlanVersions(this.client, plan, page, signal);
  }
  testingPlanVersion(plan: number, version: number, signal?: AbortSignal) {
    return readTestingPlanVersion(this.client, plan, version, signal);
  }
  testingProfileChoices(signal?: AbortSignal) {
    return readTestingProfileChoices(this.client, signal);
  }
  testingPacks(versionId: number, page = 1, signal?: AbortSignal) {
    return readTestingPacks(this.client, versionId, page, signal);
  }
  testingPack(versionId: number, packId: number, signal?: AbortSignal) {
    return readTestingPack(this.client, versionId, packId, signal);
  }
  testingSeal(packId: number, operationId: number, signal?: AbortSignal) {
    return readTestingSeal(this.client, packId, operationId, signal);
  }
  testingValidationOperation(packId: number, operationId: number, signal?: AbortSignal) {
    return readTestingValidationOperation(this.client, packId, operationId, signal);
  }
  testingValidation(packId: number, validationId: number, signal?: AbortSignal) {
    return readTestingValidation(this.client, packId, validationId, signal);
  }
  testingReferenceSets(page = 1, signal?: AbortSignal) {
    return readTestingReferenceSets(this.client, page, signal);
  }
  testingProfiles(page = 1, name: string | null = null, signal?: AbortSignal) {
    return readTestingProfiles(this.client, page, name, signal);
  }
  testingProfile(id: number, signal?: AbortSignal) {
    return readTestingProfile(this.client, id, signal);
  }
  testingAuthorization(id: number, signal?: AbortSignal) {
    return readTestingAuthorization(this.client, id, signal);
  }
  configurationRecovery(
    store: CommandRecoveryStore,
    readOperation: OperationReader,
  ): CommandRecovery {
    return new CommandRecovery(
      this.client,
      store,
      [
        ...CONFIGURATION_IDENTITY_BINDINGS,
        ...REPOSITORY_COMMAND_BINDINGS,
        CREATE_CODE_TASK_BINDING,
        START_CODE_TASK_BINDING,
        STOP_CODE_TASK_BINDING,
        RESUME_CODE_TASK_BINDING,
        ...CANDIDATE_CHECK_BINDINGS,
        PUBLISH_TESTING_CANDIDATE,
        LINK_TESTING_REPORT,
        CREATE_CODE_DEFECT,
        REQUEST_CODE_REPAIR,
        PREPARE_DELIVERY,
        ACCEPT_DELIVERY,
        RECONCILE_ROLE_DELIVERY,
        QUESTION_RESPONSE_BINDING,
        PERMISSION_RESPONSE_BINDING,
        PREPARE_HANDOFF_BINDING,
        LINK_HANDOFF_BINDING,
        APPLY_CONFIGURATION,
        INCREASE_CODE_BUDGET_BINDING,
        CHECK_SET_VERSION_BINDING,
        EXECUTION_PROFILE_VERSION_BINDING,
        AUTHORIZATION_BINDING,
        ...TESTING_POLICY_BINDINGS,
        CREATE_TEST_PLAN,
        ...TEST_PLAN_CONTROL_BINDINGS,
        ...TEST_PLAN_DRAFT_BINDINGS,
        CREATE_TESTING_PACK,
        SEAL_TESTING_PACK,
        VALIDATE_TESTING_PACK,
        PUBLISH_TESTING_PACK,
        REVOKE_TESTING_PACK,
        CREATE_TESTING_TASK,
        ATTACH_TESTING_ASSETS,
        INCREASE_TESTING_BUDGET,
        RECONCILE_TESTING_TASK,
        RESUME_TESTING_TASK,
        DRAFT_TESTING_PLAN,
        RUN_TESTING_TASK,
        STOP_TESTING_TASK,
        REVIEW_TESTING_FINDING,
      ],
      readOperation,
    );
  }
  forDetailReads(): WalleApi {
    return new WalleApi(this.client, this.ctx, new DetailReadScope(), this.assistantDocumentId);
  }
  forDocumentAssistant(documentId: number | null): WalleApi {
    return new WalleApi(
      this.client,
      this.ctx,
      this.readScope,
      documentId === null ? null : id(documentId),
    );
  }
  private assistantOwner(): number {
    if (this.assistantDocumentId === null) throw TypeError('请先选择文档');
    return this.assistantDocumentId;
  }
  get detailReadEpoch(): number {
    return this.readScope?.generation ?? 0;
  }
  invalidateDetailReads(): void {
    this.readScope?.invalidate();
  }
  waitForDetailWrites(): Promise<void> {
    return this.readScope?.afterWrites() ?? Promise.resolve();
  }
  disposeDetailReads(): void {
    this.readScope?.dispose();
  }
  private readTogether<T>(
    key: string,
    signal: AbortSignal | undefined,
    load: (signal?: AbortSignal) => Promise<T>,
  ): Promise<T> {
    return this.readScope
      ? this.waitForDetailWrites().then(() =>
          this.readScope!.read(key, signal, (owned) =>
            load(owned).then((value) => snapshotObject(value as object) as unknown as T),
          ),
        )
      : load(signal);
  }
  previewMarkdown(markdown: string, columns?: number): DocumentFragment {
    return suggestionMarkdown(this.ctx, markdown, columns);
  }
  private action<T>(
    method: 'POST' | 'PATCH' | 'PUT' | 'DELETE',
    path: string,
    body: unknown | null,
    decoder: (original: JsonObject | null) => Decoder<T>,
    status: 200 | 201 | 202 | readonly (200 | 201 | 202)[] = 200,
    keyed = true,
  ): ApiAction<T> {
    const original = body === null ? null : snapshotObject(body);
    const decode = decoder(original),
      handle = this.client.prepare(method, path, original, {
        idempotent: keyed,
        success_status: status,
      });
    return Object.freeze({
      submit: async (signal?: AbortSignal) => {
        this.readScope?.beginWrite();
        try {
          const response = await this.client.commit(handle, decode, signal);
          if (response.meta.pagination !== undefined) throw new ApiUnknown(true);
          return response;
        } finally {
          this.readScope?.endWrite();
        }
      },
    });
  }
  private async single<T>(
    path: string,
    decode: Decoder<T>,
    signal?: AbortSignal,
    parameters: readonly (readonly [string, string])[] = [],
  ) {
    const response = await this.client.read(path, decode, parameters, signal);
    if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
    return response;
  }
  private async page<T extends { id: number }>(
    path: string,
    decode: Decoder<T>,
    parameters: readonly (readonly [string, string])[],
    requestedPage: number,
    signal?: AbortSignal,
    errorPolicy?: ApiErrorPolicy,
  ) {
    return readPage(
      this.client,
      path,
      decode,
      (row) => row.id,
      parameters,
      requestedPage,
      signal,
      errorPolicy,
    );
  }
  private current = (identity: number) =>
    owned(models.documentDecoder(this.ctx, 'CURRENT'), identity);
  private draft = (identity: number) =>
    owned(models.documentDecoder(this.ctx, 'MANUAL_DRAFT'), identity);

  // I01 / I03 / I08 / I10 / I24 / I25 / I27 / I28 / I16 / I19 / I20 / I35 / I37.
  listRequirements(filters: RequirementFilters = {}, signal?: AbortSignal) {
    return this.page(
      `${root}/requirements`,
      models.requirementSummary,
      query(filters),
      filters.page ?? 1,
      signal,
    );
  }
  codeHandoff(taskId: number, handoffId: number, page = 1, signal?: AbortSignal) {
    return readCodeHandoff(this.client, taskId, handoffId, page, signal);
  }
  getRequirementDetail(
    identity: number,
    signal?: AbortSignal,
    expandDiscussion = false,
    documentId: number | null = this.assistantDocumentId,
  ) {
    const decode = checked(models.requirementDetail, (value) => {
      require(value.requirement.id === identity);
      require(expandDiscussion === (value.discussion !== null));
    });
    return this.readTogether(
      `requirement:${identity}:${documentId}:${expandDiscussion}`,
      signal,
      (owned) =>
        this.single(target('requirements', identity), decode, owned, [
          ...(expandDiscussion ? [['expand', 'discussion'] as const] : []),
          ...(documentId === null ? [] : [['document_id', String(id(documentId))] as const]),
        ]),
    );
  }
  async getRequirement(identity: number, signal?: AbortSignal) {
    const response = await this.getRequirementDetail(identity, signal);
    return { ...response, data: response.data.requirement };
  }
  getCurrentDocument(identity: number, documentId: number, signal?: AbortSignal) {
    return this.readTogether(`document:${identity}:${documentId}`, signal, (owned) =>
      this.single(
        target('requirements', identity, '/current-document'),
        checked(this.current(identity), (document) => require(document.id === documentId)),
        owned,
        [['document_id', String(id(documentId))]],
      ),
    );
  }
  getManualDraft(identity: number, documentId: number, signal?: AbortSignal) {
    return this.single(
      target('requirements', identity, '/manual-draft'),
      checked(this.draft(identity), (draft) => require(draft.target_document_id === documentId)),
      signal,
      [['document_id', String(id(documentId))]],
    );
  }
  listRevisions(identity: number, documentId: number, page = 1, signal?: AbortSignal) {
    return this.page(
      target('requirements', identity, '/revisions'),
      checked(owned(models.revisionSummary, identity), (row) =>
        require(row.document_id === documentId),
      ),
      [
        ['document_id', String(id(documentId))],
        ['page', String(page)],
      ],
      page,
      signal,
    );
  }
  getRevision(identity: number, signal?: AbortSignal) {
    return this.single(
      target('revisions', identity),
      identified(models.revisionDecoder(this.ctx), identity),
      signal,
    );
  }
  listComments(identity: number, documentId: number, page = 1, signal?: AbortSignal) {
    return this.page(
      target('requirements', identity, '/comments'),
      checked(owned(models.commentItem, identity), (comment) =>
        require(comment.document_id === documentId),
      ),
      [
        ['document_id', String(id(documentId))],
        ['page', String(page)],
      ],
      page,
      signal,
    );
  }
  getComment(identity: number, signal?: AbortSignal) {
    return this.single(target('comments', identity), identified(models.comment, identity), signal);
  }
  getGuideRun(identity: number, signal?: AbortSignal) {
    return this.readTogether(`run:${identity}`, signal, (owned) =>
      this.single(
        target('guide-runs', identity),
        checked(identified(models.guideRun, identity), (row) =>
          require(
            this.assistantDocumentId === null || row.document_id === this.assistantDocumentId,
          ),
        ),
        owned,
      ),
    );
  }
  listModelCalls(identity: number, signal?: AbortSignal) {
    return this.readTogether(`calls:${identity}`, signal, (owned) =>
      this.single(
        target('guide-runs', identity, '/model-calls'),
        identified(modelCalls, identity),
        owned,
      ),
    );
  }
  getModelCall(identity: number, signal?: AbortSignal) {
    return this.single(
      target('model-calls', identity),
      checked(modelCallDetail, (value) => require(value.call.id === identity)),
      signal,
    );
  }
  listGuideRuns(identity: number, filters: GuideFilters = {}, signal?: AbortSignal) {
    return this.page(
      target('requirements', identity, '/guide-runs'),
      checked(owned(models.guideSummary, identity), (row) =>
        require(row.document_id === this.assistantOwner()),
      ),
      [...query(filters), ['document_id', String(this.assistantOwner())]],
      filters.page ?? 1,
      signal,
    );
  }
  getBatch(identity: number, signal?: AbortSignal) {
    return this.single(
      target('suggestion-batches', identity),
      identified(models.batch, identity),
      signal,
    );
  }
  getCommentIndex(identity: number, documentId: number, signal?: AbortSignal) {
    return this.readTogether(`comment-index:${identity}:${documentId}`, signal, (signal) =>
      this.single(
        target('requirements', identity, '/comment-index'),
        checked(owned(models.commentIndex, identity), (index) =>
          require(index.document_id === documentId),
        ),
        signal,
        [['document_id', String(id(documentId))]],
      ),
    );
  }
  getMessage(requirement: number, identity: number, signal?: AbortSignal) {
    return this.single(
      target('conversation-messages', identity),
      checked(owned(models.message, requirement), (row) => require(row.id === identity)),
      signal,
      [['requirement_id', String(id(requirement))]],
    );
  }
  async listMessages(identity: number, before: number | null = null, signal?: AbortSignal) {
    const parameters: [string, string][] =
      before === null ? [] : [['before_sequence_no', String(id(before))]];
    parameters.push(['document_id', String(this.assistantOwner())]);
    const response = await this.readTogether(
      `messages:${identity}:${this.assistantDocumentId}:${before}`,
      signal,
      (ownedSignal) =>
        this.client.read(
          target('requirements', identity, '/messages'),
          shape({
            items: array(
              checked(owned(models.message, identity), (row) =>
                require(row.document_id === this.assistantOwner()),
              ),
              20,
            ),
          }),
          parameters,
          ownedSignal,
        ),
    );
    try {
      const pagination = response.meta.pagination;
      require(pagination !== undefined && 'has_more' in pagination);
      const sequences = response.data.items.map((item) => item.sequence_no);
      distinct(sequences);
      distinct(response.data.items.map((item) => item.id));
      require(
        sequences.every(
          (value, index) =>
            (index === 0 || sequences[index - 1]! < value) && (before === null || value < before),
        ),
      );
      require(
        !pagination.has_more || (sequences.length > 0 && pagination.next_cursor === sequences[0]),
      );
      return response;
    } catch {
      throw new ApiUnknown(false);
    }
  }

  // I02 / I04 / I05 / I06 / I07.
  prepareCreateRequirement(body: CreateRequirement) {
    return this.action(
      'POST',
      `${root}/requirements`,
      body,
      (original) => {
        bodyFields(original!, ['title', 'requirement_type'], ['initial_idea']);
        return checked(
          shape({
            requirement: models.requirement,
            initial_message_id: id,
            documents: array(models.documentDecoder(this.ctx, 'CURRENT'), 0),
          }),
          (value) => {
            require(
              value.requirement.status === 'PLANNING' &&
                value.requirement.document_work_state === 'IDLE' &&
                value.requirement.initial_message_id === value.initial_message_id,
            );
            for (const field of ['title', 'requirement_type'] as const)
              require(value.requirement[field] === original![field]);
          },
        );
      },
      201,
    );
  }
  prepareUpdateRequirement(
    identity: number,
    body: Readonly<{
      expected_metadata_version: number;
      changes: Readonly<{ title?: string; status?: models.Requirement['status'] }>;
    }>,
  ) {
    return this.action('PATCH', target('requirements', identity), body, (original) => {
      bodyFields(original!, ['expected_metadata_version', 'changes']);
      id(original!.expected_metadata_version);
      const changes = snapshotObject(original!.changes);
      require(
        Object.keys(changes).length > 0 &&
          Object.keys(changes).every((key) => key === 'title' || key === 'status'),
      );
      if (Object.hasOwn(changes, 'status')) choices(models.requirementStatuses)(changes.status);
      return checked(identified(models.requirement, identity), (value) => {
        require(
          Object.entries(changes).every(
            ([key, submitted]) => value[key as 'title' | 'status'] === submitted,
          ),
        );
      });
    });
  }

  // I09 / I11 / I12 / I13 / I26. Draft version never substitutes CURRENT version.
  prepareUpdateDiscussion(
    identity: number,
    body: Readonly<{ expected_discussion_version: number; discussion_command: DiscussionCommand }>,
  ) {
    return this.action(
      'PATCH',
      target('requirements', identity),
      { ...body, document_id: this.assistantOwner() },
      (original) => {
        bodyFields(original!, ['document_id', 'expected_discussion_version', 'discussion_command']);
        const version = id(original!.expected_discussion_version);
        return checked(
          shape({ requirement_id: id, discussion_version: id, discussion: models.discussionState }),
          (value) => {
            require(
              value.requirement_id === identity &&
                (value.discussion_version === version || value.discussion_version === version + 1),
            );
            const command = original!.discussion_command as JsonObject;
            if (command.type === 'SET_FOCUS')
              require(value.discussion.focus_topic_ref === command.topic_ref);
            if (command.type === 'SET_BINDING')
              require(
                value.discussion.binding.target_document_id === command.target_document_id &&
                  sameJson(value.discussion.binding.source_refs, command.source_refs) &&
                  sameJson(value.discussion.binding.scope, command.scope),
              );
          },
        );
      },
    );
  }
  prepareStartManualDraft(
    identity: number,
    documentId: number,
    version: number,
    restoreRevisionId?: number,
  ) {
    return this.action(
      'POST',
      target('requirements', identity, '/manual-draft'),
      {
        document_id: id(documentId),
        expected_version: id(version),
        ...(restoreRevisionId === undefined ? {} : { restore_revision_id: id(restoreRevisionId) }),
      },
      () =>
        checked(
          shape({
            manual_draft: this.draft(identity),
            requirement: identified(models.requirement, identity),
          }),
          (value) => {
            require(
              value.manual_draft.content_version === 1 &&
                value.requirement.document_work_state === 'MANUAL_EDITING' &&
                value.requirement.active_operation_id === value.manual_draft.id,
            );
            require(
              value.manual_draft.target_document_id === documentId &&
                value.manual_draft.base_content_version === version,
            );
          },
        ),
      201,
    );
  }
  prepareSaveManualDraft(
    identity: number,
    body: Readonly<{
      document_id: number;
      draft_id: number;
      expected_version: number;
      markdown_content: string;
      block_state_json: BlockState;
    }>,
  ) {
    return this.action(
      'PUT',
      target('requirements', identity, '/manual-draft'),
      body,
      (original) => {
        bodyFields(original!, [
          'document_id',
          'draft_id',
          'expected_version',
          'markdown_content',
          'block_state_json',
        ]);
        id(original!.expected_version);
        id(original!.document_id);
        id(original!.draft_id);
        const ids = (original!.block_state_json as JsonObject).blocks;
        require(Array.isArray(ids));
        const blockIds = ids.map((item) => id((item as JsonObject).block_id));
        return checked(this.draft(identity), (value) => {
          require(
            value.content_version === (original!.expected_version as number) + 1 &&
              value.markdown_content === original!.markdown_content,
          );
          require(
            value.id === original!.draft_id && value.target_document_id === original!.document_id,
          );
          require(
            value.block_state_json.next_block_id ===
              (original!.block_state_json as JsonObject).next_block_id,
          );
          require(
            JSON.stringify(value.block_state_json.blocks.map((item) => item.block_id)) ===
              JSON.stringify(blockIds),
          );
        });
      },
    );
  }
  prepareCancelManualDraft(identity: number, documentId: number, draftId: number, version: number) {
    return this.action(
      'DELETE',
      target('requirements', identity, '/manual-draft'),
      { document_id: id(documentId), draft_id: id(draftId), expected_version: id(version) },
      () =>
        checked(
          shape({
            requirement_id: id,
            document_id: id,
            manual_draft_id: id,
            cancelled: (value) => {
              require(value === true);
              return true as const;
            },
          }),
          (value) =>
            require(
              value.requirement_id === identity &&
                value.document_id === documentId &&
                value.manual_draft_id === draftId,
            ),
        ),
    );
  }
  prepareCompleteManualDraft(
    identity: number,
    documentId: number,
    draftId: number,
    version: number,
  ) {
    return this.action(
      'POST',
      target('requirements', identity, '/manual-draft/complete'),
      { document_id: id(documentId), draft_id: id(draftId), expected_version: id(version) },
      () =>
        checked(models.documentEffect, (effect) =>
          require(effect.document_id === documentId && effect.result !== 'CREATED'),
        ),
    );
  }
  prepareCreateRevision(
    identity: number,
    body: Readonly<{ document_id: number; expected_version: number; description?: string | null }>,
  ) {
    return this.action('POST', target('requirements', identity, '/revisions'), body, (original) => {
      bodyFields(original!, ['document_id', 'expected_version'], ['description']);
      id(original!.document_id);
      id(original!.expected_version);
      return models.versionMarker;
    });
  }
  prepareCreateDocument(identity: number, body: CreateDocument) {
    return this.action(
      'POST',
      target('requirements', identity, '/documents'),
      body,
      (original) => {
        bodyFields(original!, ['name', 'document_kind', 'template_ref']);
        return checked(shape({ document: this.current(identity), revision_id: id }), (result) =>
          require(
            result.document.name === original!.name &&
              result.document.document_kind === original!.document_kind &&
              result.document.content_version === 1 &&
              result.revision_id === result.document.current_revision_id,
          ),
        );
      },
      201,
    );
  }
  prepareUpdateDocument(
    identity: number,
    body: Readonly<{ expected_metadata_version: number; change: DocumentChange }>,
  ) {
    return this.action('PATCH', target('documents', identity), body, (original) => {
      bodyFields(original!, ['expected_metadata_version', 'change']);
      id(original!.expected_metadata_version);
      return checked(
        shape({
          document: identified(models.documentSummary, identity),
          event_id: models.nullableId,
        }),
        (result) => {
          const change = original!.change as JsonObject;
          if (change.type === 'RENAME') require(result.document.name === change.name);
          if (change.type === 'ARCHIVE') require(result.document.archived_at !== null);
          if (change.type === 'RESTORE') require(result.document.archived_at === null);
          if (change.type === 'CONFIRM')
            require(
              result.document.confirmed_revision_id === change.revision_id &&
                result.document.current_revision_id === change.revision_id &&
                result.document.content_version === change.expected_content_version,
            );
        },
      );
    });
  }

  // I14 / I15 / I17 / I18 / I34 / I36.
  prepareCreateGuide(identity: number, body: CreateGuide) {
    return this.action(
      'POST',
      target('requirements', identity, '/guide-runs'),
      { ...body, document_id: this.assistantOwner() },
      (original) => {
        bodyFields(original!, [
          'document_id',
          'expected_discussion_version',
          'operation',
          'instruction',
          'target',
          'scope',
          'source_refs',
          'proposal_ref',
          'acknowledge_source_changes',
        ]);
        id(original!.expected_discussion_version);
        if (original!.target !== null) models.targetRef(original!.target);
        if (original!.scope !== null) models.collaborationValue('legacy_scope')(original!.scope);
        return models.runReceipt;
      },
      202,
    );
  }
  prepareContinueGuide(identity: number, instruction: string, discussionVersion: number) {
    return this.action(
      'POST',
      target('guide-runs', identity, '/continue'),
      { instruction, expected_discussion_version: id(discussionVersion) },
      () => checked(models.runReceipt, (value) => require(value.guide_run_id !== identity)),
      202,
    );
  }
  prepareCancelGuide(identity: number) {
    return this.action('POST', target('guide-runs', identity, '/cancel'), null, () => (value) => {
      const row = snapshotObject(value);
      if (row.status === 'COMPLETED') return identified(models.guideRun, identity)(row);
      return checked(identified(models.guideAccepted, identity), (actual) =>
        require(actual.status === 'CANCELLED' && actual.current_step === 'FINISHED'),
      )(row);
    });
  }
  prepareRetryGuide(identity: number) {
    return this.action(
      'POST',
      target('guide-runs', identity, '/retry'),
      null,
      () => checked(models.runReceipt, (value) => require(value.guide_run_id !== identity)),
      202,
    );
  }
  prepareModifyFromComment(
    identity: number,
    version: number,
    discussionVersion: number,
    scopeMode?: 'COMMENT' | 'BLOCK' | 'SECTION' | 'DOCUMENT',
  ) {
    if (scopeMode !== undefined && !['COMMENT', 'BLOCK', 'SECTION', 'DOCUMENT'].includes(scopeMode))
      throw TypeError('Invalid comment scope mode');
    return this.action(
      'POST',
      target('comments', identity, '/guide-runs'),
      {
        expected_content_version: id(version),
        expected_discussion_version: id(discussionVersion),
        ...(scopeMode === undefined ? {} : { scope_mode: scopeMode }),
      },
      () => models.runReceipt,
      202,
    );
  }

  prepareCardResponses(identity: number, body: models.Responses, discussionVersion: number) {
    const action = this.action(
      'POST',
      target('conversation-messages', identity, '/responses'),
      { ...body, expected_discussion_version: id(discussionVersion) },
      (original) => {
        const answers = models.responses(
          Object.fromEntries(
            Object.entries(original!).filter(([key]) => key !== 'expected_discussion_version'),
          ),
        );
        void answers;
        return (value: unknown) => {
          const row = snapshotObject(value);
          return row.processing === 'MODEL' ? models.runReceipt(row) : models.programReceipt(row);
        };
      },
      [200, 202],
    );
    return Object.freeze({
      submit: async (signal?: AbortSignal) => {
        const response = await action.submit(signal);
        if (
          response.status !== (response.data.processing === 'MODEL' ? 202 : 200) ||
          response.data.user_message_id === identity
        )
          throw new ApiUnknown(true);
        return response;
      },
    });
  }

  // I20 read above; I21 / I22 / I23.
  prepareDecideSuggestion(
    identity: number,
    body: Readonly<{
      decision: 'ACCEPTED' | 'REJECTED' | 'EDITED';
      edited_content?: string | null;
    }>,
  ) {
    return this.action('PUT', target('suggestions', identity, '/decision'), body, (original) => {
      bodyFields(original!, ['decision'], ['edited_content']);
      require(
        original!.decision === 'EDITED'
          ? typeof original!.edited_content === 'string'
          : !('edited_content' in original!),
      );
      return checked(
        shape({ suggestion: identified(models.suggestion, identity), counts: models.counts }),
        (value) => {
          require(
            value.suggestion.status === original!.decision &&
              value.counts[
                value.suggestion.status.toLowerCase() as 'accepted' | 'rejected' | 'edited'
              ] > 0,
          );
        },
      );
    });
  }
  prepareAcceptPendingBatch(identity: number, version: number, pendingIds: readonly number[]) {
    return this.action(
      'POST',
      target('suggestion-batches', identity, '/accept-pending'),
      { expected_content_version: id(version), expected_pending_ids: [...pendingIds] },
      (original) => {
        bodyFields(original!, ['expected_content_version', 'expected_pending_ids']);
        const ids = array(id, 100, 1)(original!.expected_pending_ids);
        require(new Set(ids).size === ids.length);
        return checked(
          shape({
            batch: identified(models.batch, identity),
            accepted_suggestion_ids: array(id, 100, 1),
          }),
          (value) => {
            require(
              value.batch.status === 'PENDING' &&
                value.batch.base_content_version === original!.expected_content_version &&
                value.batch.counts.pending === 0,
            );
            require(
              JSON.stringify(value.accepted_suggestion_ids) === JSON.stringify(ids) &&
                ids.every((identity) =>
                  value.batch.suggestions.some(
                    (item) => item.id === identity && item.status === 'ACCEPTED',
                  ),
                ),
            );
          },
        );
      },
    );
  }
  prepareCompleteBatch(identity: number, version: number) {
    return this.action(
      'POST',
      target('suggestion-batches', identity, '/complete'),
      { expected_content_version: id(version) },
      (original) =>
        checked(
          shape({
            batch: identified(models.batchMetadata, identity),
            counts: models.counts,
            current_document: models.documentBodyDecoder(this.ctx, 'CURRENT'),
            document_effect: models.documentEffect,
            applied_suggestion_ids: array(id, 100),
          }),
          (value) => {
            require(
              value.batch.status === 'COMPLETED' &&
                value.counts.pending === 0 &&
                value.batch.base_content_version === original!.expected_content_version,
            );
            require(
              value.current_document.requirement_id === value.batch.requirement_id &&
                value.current_document.content_version ===
                  (value.batch.applied_content_version ?? value.batch.base_content_version),
            );
            const effect = value.document_effect;
            require(
              value.current_document.id === value.batch.target_document_id &&
                effect.document_id === value.current_document.id &&
                effect.before_content_version === value.batch.base_content_version &&
                effect.after_content_version === value.current_document.content_version &&
                effect.result ===
                  (value.batch.completion_result === 'NO_CHANGE' ? 'NO_CHANGE' : 'UPDATED'),
            );
            require(
              new Set(value.applied_suggestion_ids).size === value.applied_suggestion_ids.length &&
                value.applied_suggestion_ids.length === value.counts.accepted + value.counts.edited,
            );
          },
        ),
    );
  }
  prepareDiscardBatch(identity: number) {
    return this.action('POST', target('suggestion-batches', identity, '/discard'), null, () =>
      checked(
        shape({ batch: identified(models.batchMetadata, identity), counts: models.counts }),
        (value) => require(value.batch.status === 'DISCARDED'),
      ),
    );
  }

  // I29 / I30 / I31 / I32 / I33.
  prepareCreateComment(identity: number, body: CreateComment) {
    return this.action(
      'POST',
      target('requirements', identity, '/comments'),
      body,
      (original) => {
        bodyFields(
          original!,
          ['document_id', 'expected_content_version', 'content', 'anchor_type', 'block_id'],
          ['selection'],
        );
        return checked(owned(models.comment, identity), (value) =>
          require(
            value.document_id === original!.document_id &&
              value.status === 'OPEN' &&
              value.anchor_status === 'ATTACHED' &&
              value.deleted_at === null &&
              value.block_id === original!.block_id &&
              value.anchor_type === original!.anchor_type,
          ),
        );
      },
      201,
    );
  }
  prepareEditComment(identity: number, content: string) {
    return this.action('PATCH', target('comments', identity), { content }, () =>
      identified(models.comment, identity),
    );
  }
  prepareResolveComment(identity: number) {
    return this.action('POST', target('comments', identity, '/resolve'), null, () =>
      checked(identified(models.comment, identity), (value) =>
        require(value.status === 'RESOLVED'),
      ),
    );
  }
  prepareReopenComment(identity: number) {
    return this.action('POST', target('comments', identity, '/reopen'), null, () =>
      checked(identified(models.comment, identity), (value) => require(value.status === 'OPEN')),
    );
  }
  prepareDeleteComment(identity: number) {
    return this.action('DELETE', target('comments', identity), null, () =>
      checked(identified(models.comment, identity), (value) => require(value.deleted_at !== null)),
    );
  }
}

// Rejected transport errors retain their authoritative identity; success/meta
// projection failures above become ApiUnknown. Export for parent controllers.
export { ApiUnknown, ApiRejected };
