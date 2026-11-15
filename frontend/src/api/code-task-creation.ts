/** Fixed task creation and original-key recovery. */
import type { ApiClient, JsonObject } from './client.ts';
import { exact, positiveInteger } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { COMMAND_BODY_BYTES, prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeBudget, formatCnyBalance, money, moneyMicro } from './code-values.ts';
import { localBranchRef } from './code-repository-observations.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  distinct,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';

const fixedIdFields = [
  'design_revision_id',
  'repository_id',
  'base_snapshot_id',
  'execution_profile_version_id',
  'authorization_id',
] as const;

const material = shape({ document_id: positiveInteger, revision_id: positiveInteger });
const materialList = array(material, COMMAND_BODY_BYTES);
type Material = ReturnType<typeof material>;
export type CreateCodeTaskInput = Readonly<
  Record<(typeof fixedIdFields)[number], number> & {
    material_refs: readonly Material[];
    target_branch: string;
    budget_limit_cny: string;
  }
>;

const taskActions = [
  'START',
  'RESUME',
  'ANSWER_QUESTION',
  'DECIDE_PERMISSION',
  'APPLY_CONFIGURATION',
  'INCREASE_BUDGET',
  'PREPARE_HANDOFF',
  'LINK_HANDOFF',
  'REGISTER_DEFECT',
  'VERIFY_CANDIDATE',
  'CAPTURE_AND_CHECK',
  'REPAIR',
  'HANDOFF_ROLE',
  'PREPARE_DELIVERY',
  'ACCEPT',
  'SUBMIT_FOR_TESTING',
  'LINK_TEST_REPORT',
  'TERMINATE',
  'RECONCILE',
] as const;

function nullOnly(value: unknown): null {
  require(value === null);
  return null;
}

function emptyList(value: unknown): readonly never[] {
  require(Array.isArray(value) && value.length === 0);
  return Object.freeze([]);
}

const designDifference = shape({
  document_id: positiveInteger,
  fixed_revision_id: positiveInteger,
  current_revision_id: positiveInteger,
});
const taskView = shape({
  id: positiveInteger,
  document_id: positiveInteger,
  requirement_id: positiveInteger,
  design_revision_id: positiveInteger,
  material_refs: materialList,
  repository_id: positiveInteger,
  base_snapshot_id: positiveInteger,
  execution_profile_version_id: positiveInteger,
  authorization_id: positiveInteger,
  target_branch: localBranchRef,
  status: choices([
    'PENDING',
    'RUNNING',
    'WAITING',
    'VERIFYING',
    'AWAITING_TESTING',
    'AWAITING_ACCEPTANCE',
    'STOPPING',
    'COMPLETED',
    'TERMINATED',
  ]),
  phase: choices([
    'PREPARING',
    'BACKEND',
    'FRONTEND',
    'INTEGRATION',
    'TESTING',
    'ACCEPTANCE',
    'DELIVERY',
    'FINISHED',
  ]),
  state_version: positiveInteger,
  control_generation: positiveInteger,
  created_at: time,
  updated_at: time,
  current_candidate_id: nullable(positiveInteger),
  workspace_id: nullable(positiveInteger),
  active_session_id: nullable(positiveInteger),
  resume_phase: nullable(choices(['BACKEND', 'FRONTEND', 'INTEGRATION', 'DELIVERY'])),
  started_at: nullable(time),
  ended_at: nullable(time),
  stop_requested_at: nullable(time),
  stopped_at: nullable(time),
  last_observed_at: nullable(time),
  current_refs: shape({
    verification_id: nullable(positiveInteger),
    test_report_id: nullable(positiveInteger),
    delivery_plan_id: nullable(positiveInteger),
    delivery_id: nullable(positiveInteger),
  }),
  configuration_application: nullable(
    shape({
      id: positiveInteger,
      status: choices(['PENDING', 'APPLYING', 'APPLIED', 'FAILED', 'UNKNOWN']),
      new_profile_version_id: positiveInteger,
      authorization_id: positiveInteger,
      evidence_result: nullable(choices(['VERIFIED', 'UNAVAILABLE', 'UNKNOWN'])),
      difference_kinds: checked(
        array(
          choices([
            'SOURCE_SET',
            'PATH_BINDING',
            'EXTENSIONS',
            'DEPENDENCIES',
            'MODEL_ROUTE',
            'PERMISSIONS',
            'PROCESS_BOUNDARY',
          ]),
          7,
        ),
        distinct,
      ),
      observed_at: nullable(time),
    }),
  ),
  runtime: shape({
    isolation_mode: choices(['WINDOWS_LPAC']),
    environment_status: choices(['NOT_PREPARED', 'PREPARING', 'VERIFIED', 'UNKNOWN']),
    activity_status: choices(['NOT_STARTED', 'UNKNOWN', 'QUIESCENT']),
    stop_status: choices(['NONE', 'REQUESTED', 'ABORTING', 'TERMINATING', 'VERIFIED', 'UNKNOWN']),
    cleanup_status: choices(['NOT_STARTED', 'CLEANING', 'VERIFIED', 'UNKNOWN']),
    reason_codes: emptyList,
    active_process_count: nullable(count),
    observed_at: nullable(time),
  }),
  waiting_items: array(
    shape({
      id: positiveInteger,
      task_id: positiveInteger,
      testing_task_id: nullOnly,
      kind: choices([
        'BUDGET',
        'MODEL_RESULT',
        'QUESTION',
        'PERMISSION',
        'OPERATION_RESULT',
        'DELIVERY_RESULT',
        'CONFIGURATION',
      ]),
      source_kind: choices(['OPERATION', 'LLM_USE', 'QUESTION', 'PERMISSION', 'DELIVERY']),
      source_id: positiveInteger,
      resume_phase: choices(['BACKEND', 'FRONTEND', 'INTEGRATION', 'DELIVERY']),
      status: choices(['OPEN']),
      created_at: time,
      resolved_at: nullOnly,
      resolution_ref: nullOnly,
    }),
    COMMAND_BODY_BYTES,
  ),
  active_operations: array(
    shape({
      id: positiveInteger,
      operation_type: choices([
        'START',
        'RESUME',
        'TERMINATE',
        'ANSWER_QUESTION',
        'DECIDE_PERMISSION',
        'CAPTURE_AND_CHECK',
        'VERIFY_CANDIDATE',
        'HANDOFF_ROLE',
        'REPAIR',
        'APPLY_CONFIGURATION',
        'PREPARE_DELIVERY',
        'DELIVER',
      ]),
      status: choices(['PENDING', 'RUNNING', 'UNKNOWN']),
    }),
    2,
  ),
  budget: codeBudget,
  current_basis_difference: array(designDifference, COMMAND_BODY_BYTES),
  available_actions: array(
    shape({
      action: choices(taskActions),
      enabled: bool,
      reason_code: nullable(
        choices([
          'CONFIG_NOT_READY',
          'PRECONDITION_FAILED',
          'INVALID_STATE',
          'TASK_ENDED',
          'OPERATION_IN_PROGRESS',
          'EXTERNAL_RESULT_UNKNOWN',
          'CONTENT_NOT_READY',
          'WRITER_ACTIVE',
          'VERIFICATION_STAGE_NOT_READY',
          'CHECK_CONFIGURATION_INVALID',
          'TEST_SOURCE_MISMATCH',
          'OPERATION_CONFLICT',
          'CANDIDATE_NOT_CURRENT',
          'EXECUTION_NOT_STOPPED',
          'DELIVERY_NOT_AUTHORIZED',
          'DELIVERY_PLAN_STALE',
        ]),
      ),
      related_id: nullable(positiveInteger),
    }),
    taskActions.length,
    taskActions.length,
  ),
  termination_operation_id: nullable(positiveInteger),
  verification_purposes: array(
    shape({
      action: choices(['CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE']),
      purpose: choices(['HANDOFF']),
      enabled: bool,
      reason_code: nullable(
        choices([
          'TASK_STATE',
          'RESOURCE_NOT_READY',
          'WRITER_ACTIVE',
          'ROLE_CHAIN_INCOMPLETE',
          'ROLE_CHAIN_UNKNOWN',
          'SESSION_NOT_CURRENT',
          'CANDIDATE_NOT_CURRENT',
        ]),
      ),
    }),
    2,
    2,
  ),
});

export type CodeTaskView = ReturnType<typeof taskView>;
export type CreatedCodeTask = CodeTaskView;

function originalDocument(original: CommandIdentity) {
  require(original.owner_module === 'CODING' && original.decoder_kind === 'APP-CODE-CMD-C32');
  return positiveInteger(original.parameters.document_id);
}

function checkInput(value: JsonObject, original: CommandIdentity) {
  const documentId = originalDocument(original);
  const row = exact(value, [
    ...fixedIdFields,
    'material_refs',
    'target_branch',
    'budget_limit_cny',
  ]);
  for (const field of fixedIdFields) positiveInteger(row[field]);
  const materials = materialList(row.material_refs);
  distinct([documentId, ...materials.map((item) => item.document_id)]);
  const branch = localBranchRef(row.target_branch);
  const amount = moneyMicro(money(row.budget_limit_cny));
  require(amount > 0n);
  return { documentId, row, materials, branch, budget: formatCnyBalance(amount) };
}

function validateStartPreparation(task: CodeTaskView) {
  const stopping = task.status === 'STOPPING';
  const original = task.active_operations.at(-1);
  const start = task.available_actions.find((action) => action.action === 'START');
  require(start !== undefined && !start.enabled);
  const failed =
    start.related_id !== null &&
    (start.reason_code === 'CONTENT_NOT_READY' || start.reason_code === 'CONFIG_NOT_READY');
  if (!failed) require(original?.operation_type === 'START');
  const startId = positiveInteger(failed ? start.related_id : original?.id);
  const status = failed ? 'FAILED' : original?.status;
  const ready = task.workspace_id !== null;
  require(
    task.status !== 'TERMINATED' &&
      task.phase === 'PREPARING' &&
      task.state_version >= (stopping ? 3 : 2) &&
      task.active_operations.length === Number(stopping) + Number(!failed) &&
      task.active_session_id === null &&
      task.started_at === null &&
      task.ended_at === null &&
      task.stopped_at === null &&
      task.last_observed_at === null &&
      task.runtime.active_process_count === null &&
      task.runtime.observed_at === null,
  );
  if (ready) {
    require(status !== 'PENDING' && task.state_version >= (stopping ? 4 : 3));
  } else require(!failed);
  const restore = ready ? 'SUCCEEDED' : status;
  const environment =
    restore === 'RUNNING' ? 'PREPARING' : restore === 'UNKNOWN' ? 'UNKNOWN' : 'NOT_PREPARED';
  require(task.runtime.environment_status === environment);
  require(
    task.runtime.activity_status === (environment === 'NOT_PREPARED' ? 'NOT_STARTED' : 'UNKNOWN'),
  );
  if (stopping) {
    const stop = task.active_operations[0];
    require(
      stop?.operation_type === 'TERMINATE' &&
        stop.id === task.termination_operation_id &&
        stop.id !== startId &&
        (stop.status === 'PENDING' || stop.status === 'UNKNOWN'),
    );
    const requested = time(task.stop_requested_at);
    require(task.created_at <= requested && requested <= task.updated_at);
    for (const action of task.available_actions) {
      require(action.enabled === (action.action === 'TERMINATE' || action.action === 'RECONCILE'));
      const related =
        action.action === 'TERMINATE'
          ? stop.id
          : failed && action.action === 'START'
            ? startId
            : null;
      require(action.related_id === related);
    }
    require(task.runtime.stop_status === (stop.status === 'UNKNOWN' ? 'UNKNOWN' : 'REQUESTED'));
    require(
      task.runtime.cleanup_status === (stop.status === 'UNKNOWN' ? 'UNKNOWN' : 'NOT_STARTED'),
    );
  } else {
    require(task.termination_operation_id === null && task.stop_requested_at === null);
    require(task.runtime.stop_status === 'NONE' && task.runtime.cleanup_status === 'NOT_STARTED');
    require(
      start.related_id === startId &&
        start.reason_code ===
          (status === 'UNKNOWN'
            ? 'EXTERNAL_RESULT_UNKNOWN'
            : failed
              ? start.reason_code
              : 'OPERATION_IN_PROGRESS'),
    );
  }
}

function validateStartedTask(task: CodeTaskView) {
  const started = time(task.started_at);
  const observed = time(task.last_observed_at);
  positiveInteger(task.workspace_id);
  const handoff = task.active_operations.find(
    (operation) => operation.operation_type === 'HANDOFF_ROLE',
  );
  if (!handoff || task.active_session_id !== null) positiveInteger(task.active_session_id);
  if (handoff) {
    positiveInteger(task.current_candidate_id);
    positiveInteger(task.current_refs.verification_id);
    require(task.phase === 'BACKEND' || task.phase === 'FRONTEND');
    require(
      task.status === (handoff.status === 'UNKNOWN' ? 'WAITING' : 'VERIFYING') &&
        (handoff.status !== 'UNKNOWN' ||
          task.waiting_items.some(
            (item) => item.kind === 'OPERATION_RESULT' && item.source_id === handoff.id,
          )),
    );
  }
  require(
    task.created_at <= started &&
      started <= observed &&
      observed <= task.updated_at &&
      task.ended_at === null &&
      task.stopped_at === null &&
      task.runtime.activity_status === 'UNKNOWN' &&
      task.runtime.active_process_count === null &&
      task.runtime.observed_at === observed,
  );
  if (task.status === 'RUNNING' || task.status === 'WAITING' || handoff) {
    require(
      task.state_version >= (task.status === 'WAITING' ? 5 : 4) &&
        task.stop_requested_at === null &&
        task.termination_operation_id === null &&
        task.runtime.environment_status === 'VERIFIED' &&
        task.runtime.stop_status === 'NONE' &&
        task.runtime.cleanup_status === 'NOT_STARTED',
    );
    const active = task.active_operations[0];
    require(
      task.active_operations.length <= 1 &&
        (!active ||
          active === handoff ||
          active.operation_type === 'REPAIR' ||
          (task.status === 'RUNNING' && active.operation_type === 'CAPTURE_AND_CHECK') ||
          (task.status === 'WAITING' &&
            (active.operation_type === 'RESUME' ||
              active.operation_type === 'APPLY_CONFIGURATION' ||
              ((active.operation_type === 'ANSWER_QUESTION' ||
                active.operation_type === 'DECIDE_PERMISSION') &&
                task.waiting_items.some(
                  (item) =>
                    item.kind ===
                    (active.operation_type === 'ANSWER_QUESTION' ? 'QUESTION' : 'PERMISSION'),
                ))))),
    );
    const configuration = active?.operation_type === 'APPLY_CONFIGURATION' ? active : null;
    if (configuration) {
      require(
        task.status === 'WAITING' &&
          configuration.status !== 'PENDING' &&
          task.configuration_application?.status ===
            (configuration.status === 'UNKNOWN' ? 'UNKNOWN' : 'PENDING') &&
          task.waiting_items.length === 1 &&
          task.waiting_items[0]?.kind === 'CONFIGURATION' &&
          task.waiting_items[0]?.source_id === configuration.id,
      );
    }
    const activeResume = active?.operation_type === 'RESUME' ? active : null;
    for (const item of task.available_actions) {
      if (item.action === 'APPLY_CONFIGURATION') {
        require(
          !item.enabled &&
            item.related_id === (configuration?.id ?? null) &&
            (configuration
              ? item.reason_code === 'OPERATION_IN_PROGRESS'
              : item.reason_code === 'OPERATION_IN_PROGRESS'
                ? active !== undefined
                : ['INVALID_STATE', 'CONFIG_NOT_READY', 'WRITER_ACTIVE'].includes(
                    item.reason_code ?? '',
                  )),
        );
        continue;
      }
      if (
        item.action === 'CAPTURE_AND_CHECK' ||
        item.action === 'VERIFY_CANDIDATE' ||
        item.action === 'SUBMIT_FOR_TESTING' ||
        item.action === 'REGISTER_DEFECT' ||
        item.action === 'REPAIR' ||
        item.action === 'PREPARE_DELIVERY' ||
        item.action === 'ACCEPT' ||
        item.action === 'LINK_TEST_REPORT'
      )
        continue;
      if (item.action === 'RECONCILE' && item.related_id !== null) {
        const original = handoff ?? (active?.operation_type === 'REPAIR' ? active : null);
        require(
          original?.status === 'UNKNOWN' &&
            task.status === 'WAITING' &&
            item.related_id === original.id &&
            task.waiting_items.some(
              (waiting) => waiting.kind === 'OPERATION_RESULT' && waiting.source_id === original.id,
            ) &&
            item.enabled === (item.reason_code === null) &&
            (item.reason_code === null ||
              item.reason_code === 'OPERATION_IN_PROGRESS' ||
              item.reason_code === 'CONFIG_NOT_READY'),
        );
        continue;
      }
      if (item.action === 'RESUME' && task.status === 'WAITING' && item.related_id !== null) {
        if (activeResume)
          require(
            item.related_id === activeResume.id &&
              item.reason_code ===
                (activeResume.status === 'UNKNOWN'
                  ? 'EXTERNAL_RESULT_UNKNOWN'
                  : 'OPERATION_IN_PROGRESS'),
          );
        else require(item.reason_code === null || item.reason_code === 'EXTERNAL_RESULT_UNKNOWN');
      } else
        require(
          (item.action !== 'RESUME' || !activeResume) &&
            item.enabled === (item.action === 'TERMINATE' || item.action === 'INCREASE_BUDGET') &&
            item.related_id === null,
        );
    }
    return;
  }
  const requested = time(task.stop_requested_at);
  const stopId = positiveInteger(task.termination_operation_id);
  const [stop] = task.active_operations;
  require(
    task.status === 'STOPPING' &&
      task.state_version >= 5 &&
      task.control_generation >= 2 &&
      task.active_operations.length === 1 &&
      stop?.operation_type === 'TERMINATE' &&
      stop.id === stopId &&
      started <= requested &&
      requested <= task.updated_at &&
      task.runtime.environment_status === 'UNKNOWN' &&
      task.runtime.stop_status === (stop.status === 'UNKNOWN' ? 'UNKNOWN' : 'REQUESTED') &&
      task.runtime.cleanup_status === (stop.status === 'UNKNOWN' ? 'UNKNOWN' : 'NOT_STARTED'),
  );
  for (const item of task.available_actions) {
    const terminate = item.action === 'TERMINATE';
    require(
      item.enabled === (terminate || item.action === 'RECONCILE') &&
        item.related_id === (terminate ? stopId : null),
    );
  }
}

function validateCapturedTask(task: CodeTaskView) {
  const observed = time(task.runtime.observed_at);
  positiveInteger(task.current_candidate_id);
  require(
    task.status === 'VERIFYING' &&
      (task.phase === 'BACKEND' || task.phase === 'FRONTEND' || task.phase === 'INTEGRATION') &&
      ((task.runtime.activity_status === 'QUIESCENT' && task.runtime.active_process_count === 1) ||
        (task.current_refs.verification_id !== null &&
          task.runtime.activity_status === 'UNKNOWN' &&
          task.runtime.active_process_count === null)) &&
      time(task.started_at) <= observed &&
      observed <= time(task.last_observed_at) &&
      task.active_operations.length <= 1 &&
      task.active_operations.every(
        (item) =>
          item.operation_type === 'CAPTURE_AND_CHECK' || item.operation_type === 'VERIFY_CANDIDATE',
      ),
  );
  validateStartedTask({
    ...task,
    status: 'RUNNING',
    current_candidate_id: null,
    active_operations: [],
    runtime: {
      ...task.runtime,
      activity_status: 'UNKNOWN',
      active_process_count: null,
      observed_at: task.last_observed_at,
    },
  });
}

function validateOwnedStop(task: CodeTaskView) {
  const identity = positiveInteger(task.termination_operation_id);
  const requested = time(task.stop_requested_at);
  const stopped = task.runtime.stop_status === 'VERIFIED';
  const terminal = task.status === 'TERMINATED';
  require(
    task.state_version >= 4 &&
      task.control_generation >= 2 &&
      task.created_at <= requested &&
      requested <= task.updated_at &&
      (task.started_at === null ||
        (task.created_at <= task.started_at && task.started_at <= requested)) &&
      task.runtime.environment_status === 'UNKNOWN' &&
      task.runtime.activity_status === 'UNKNOWN' &&
      task.runtime.observed_at === task.last_observed_at &&
      task.runtime.active_process_count === (stopped ? 0 : null),
  );
  if (stopped) require(time(task.last_observed_at) >= requested);
  for (const item of task.available_actions) {
    const terminate = item.action === 'TERMINATE';
    require(
      item.enabled === (item.action === 'RECONCILE' || (terminate && !terminal)) &&
        item.related_id === (terminate ? identity : null),
    );
  }
  if (terminal) {
    require(
      task.phase === 'FINISHED' &&
        stopped &&
        task.runtime.cleanup_status === 'VERIFIED' &&
        task.active_session_id === null &&
        task.active_operations.length === 0 &&
        task.ended_at !== null &&
        task.ended_at === task.stopped_at &&
        task.ended_at === task.last_observed_at &&
        task.updated_at >= task.ended_at,
    );
    return;
  }
  const [stop] = task.active_operations;
  require(
    task.phase !== 'FINISHED' &&
      task.active_operations.length === 1 &&
      stop?.id === identity &&
      stop.operation_type === 'TERMINATE' &&
      (stop.status === 'PENDING' || stop.status === 'RUNNING' || stop.status === 'UNKNOWN') &&
      task.ended_at === null &&
      task.stopped_at === null &&
      (stop.status === 'UNKNOWN'
        ? (stopped || task.runtime.stop_status === 'UNKNOWN') &&
          task.runtime.cleanup_status === 'UNKNOWN'
        : stop.status === 'PENDING'
          ? task.runtime.stop_status === 'REQUESTED' &&
            task.runtime.cleanup_status === 'NOT_STARTED'
          : stopped
            ? task.runtime.cleanup_status === 'NOT_STARTED' ||
              task.runtime.cleanup_status === 'CLEANING'
            : (task.runtime.stop_status === 'REQUESTED' ||
                task.runtime.stop_status === 'ABORTING' ||
                task.runtime.stop_status === 'TERMINATING') &&
              task.runtime.cleanup_status === 'NOT_STARTED'),
  );
}

export function decodeTaskView(value: unknown) {
  const task = taskView(value);
  const design = new Map([[task.document_id, task.design_revision_id]]);
  for (const item of task.material_refs) {
    require(!design.has(item.document_id));
    design.set(item.document_id, item.revision_id);
  }
  distinct(task.current_basis_difference.map((row) => row.document_id));
  for (const change of task.current_basis_difference) {
    require(
      design.get(change.document_id) === change.fixed_revision_id &&
        change.current_revision_id !== change.fixed_revision_id,
    );
  }
  distinct(task.available_actions.map((action) => action.action));
  for (const action of task.available_actions)
    require(action.enabled === (action.reason_code === null));
  distinct(task.verification_purposes.map((purpose) => purpose.action));
  for (const purpose of task.verification_purposes) {
    const action = task.available_actions.find((item) => item.action === purpose.action);
    require(
      purpose.enabled === (purpose.reason_code === null) &&
        action !== undefined &&
        action.enabled === purpose.enabled &&
        action.related_id === null &&
        (!purpose.enabled ||
          task.status === 'VERIFYING' ||
          task.status === 'AWAITING_TESTING' ||
          (purpose.action === 'CAPTURE_AND_CHECK' && task.status === 'RUNNING')),
    );
  }
  if (task.current_refs.verification_id !== null) require(task.current_candidate_id !== null);
  if (task.configuration_application) {
    const observed = task.configuration_application;
    require(
      (observed.evidence_result === null) === (observed.observed_at === null) &&
        (observed.status !== 'APPLIED' || observed.evidence_result === 'VERIFIED') &&
        (observed.evidence_result !== 'VERIFIED' || observed.difference_kinds.length === 0),
    );
  }
  require(task.created_at <= task.updated_at && moneyMicro(task.budget.limit_cny) > 0n);
  const waiting = task.status === 'WAITING';
  require(task.resume_phase === (waiting ? task.phase : null));
  require(
    (!waiting || task.waiting_items.length > 0) &&
      (waiting || task.status === 'STOPPING' || task.waiting_items.length === 0),
  );
  distinct(task.waiting_items.map((row) => row.id));
  let previousWait: (typeof task.waiting_items)[number] | null = null;
  for (const item of task.waiting_items) {
    require(
      item.task_id === task.id &&
        item.created_at <= task.updated_at &&
        (
          {
            BUDGET: ['OPERATION', 'LLM_USE'],
            MODEL_RESULT: ['LLM_USE'],
            OPERATION_RESULT: ['OPERATION'],
            CONFIGURATION: ['OPERATION'],
            DELIVERY_RESULT: ['DELIVERY'],
            QUESTION: ['QUESTION'],
            PERMISSION: ['PERMISSION'],
          } satisfies Record<typeof item.kind, string[]>
        )[item.kind].includes(item.source_kind),
    );
    if (previousWait !== null)
      require(
        previousWait.created_at < item.created_at ||
          (previousWait.created_at === item.created_at && previousWait.id < item.id),
      );
    previousWait = item;
  }

  if (waiting && task.waiting_items.some((item) => item.kind === 'CONFIGURATION'))
    require(
      task.active_operations.length === 1 &&
        task.active_operations[0]?.operation_type === 'APPLY_CONFIGURATION',
    );

  const stoppingWithWorkspace =
    task.workspace_id !== null &&
    (task.status === 'STOPPING' || task.status === 'TERMINATED') &&
    !task.active_operations.some((operation) => operation.operation_type === 'START');
  if (stoppingWithWorkspace) {
    validateOwnedStop(task);
    return task;
  }
  const publication = task.available_actions.find(
    (action) => action.action === 'SUBMIT_FOR_TESTING',
  );
  if (publication?.enabled) {
    require(
      task.status === 'VERIFYING' &&
        task.phase === 'INTEGRATION' &&
        task.current_candidate_id !== null &&
        task.current_refs.verification_id !== null &&
        task.active_operations.length === 0 &&
        task.waiting_items.length === 0,
    );
  }
  const defect = task.available_actions.find((action) => action.action === 'REGISTER_DEFECT');
  if (defect?.enabled)
    require(
      defect.related_id === null &&
        task.current_candidate_id !== null &&
        task.stop_requested_at === null &&
        ['VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE', 'WAITING'].includes(task.status),
    );
  const linking = task.available_actions.find((action) => action.action === 'LINK_TEST_REPORT');
  if (linking?.enabled)
    require(
      task.current_candidate_id !== null &&
        ['VERIFYING', 'AWAITING_TESTING', 'AWAITING_ACCEPTANCE'].includes(task.status),
    );
  if (task.status === 'COMPLETED' || (task.status === 'WAITING' && task.phase === 'DELIVERY')) {
    const complete = task.status === 'COMPLETED';
    const stopped = task.runtime.stop_status === 'VERIFIED';
    require(
      task.phase === (complete ? 'FINISHED' : 'DELIVERY') &&
        task.workspace_id !== null &&
        task.started_at !== null &&
        task.last_observed_at !== null &&
        task.started_at <= task.last_observed_at &&
        task.last_observed_at <= task.updated_at &&
        task.current_candidate_id !== null &&
        task.current_refs.verification_id !== null &&
        task.current_refs.test_report_id !== null &&
        task.current_refs.delivery_plan_id !== null &&
        task.current_refs.delivery_id !== null &&
        task.stop_requested_at === null &&
        task.stopped_at === null &&
        task.termination_operation_id === null &&
        task.runtime.environment_status === 'UNKNOWN' &&
        task.runtime.activity_status === 'UNKNOWN' &&
        task.runtime.observed_at === task.last_observed_at &&
        task.runtime.active_process_count === (stopped ? 0 : null),
    );
    if (complete) {
      require(
        stopped &&
          task.runtime.cleanup_status === 'VERIFIED' &&
          task.ended_at === task.last_observed_at &&
          task.active_session_id === null &&
          task.active_operations.length === 0,
      );
    } else {
      const [operation] = task.active_operations;
      const [wait] = task.waiting_items;
      require(
        (task.runtime.cleanup_status === 'NOT_STARTED' ||
          task.runtime.cleanup_status === 'UNKNOWN') &&
          (stopped || task.runtime.stop_status === 'NONE') &&
          task.ended_at === null &&
          task.active_session_id !== null &&
          task.active_operations.length === 1 &&
          operation?.operation_type === 'DELIVER' &&
          operation.status !== 'PENDING' &&
          task.waiting_items.length === 1 &&
          wait?.kind === 'DELIVERY_RESULT' &&
          wait.source_id === task.current_refs.delivery_id,
      );
    }
    return task;
  }
  if (task.status === 'AWAITING_TESTING' || task.status === 'AWAITING_ACCEPTANCE') {
    const linked = task.status === 'AWAITING_ACCEPTANCE';
    require(
      task.phase === (linked ? 'ACCEPTANCE' : 'TESTING') &&
        linked === (task.current_refs.test_report_id !== null) &&
        task.current_candidate_id !== null &&
        task.current_refs.verification_id !== null &&
        task.active_operations.length <= Number(linked) &&
        task.active_operations.every(
          (operation) =>
            operation.operation_type ===
            (task.current_refs.delivery_id === null ? 'PREPARE_DELIVERY' : 'DELIVER'),
        ),
    );
    const runtime = task.runtime;
    const quiet = runtime.activity_status === 'QUIESCENT';
    require(
      quiet
        ? task.active_operations.length === 0 &&
            runtime.active_process_count !== null &&
            runtime.observed_at !== null &&
            time(task.started_at) <= runtime.observed_at &&
            runtime.observed_at <= time(task.last_observed_at)
        : runtime.activity_status === 'UNKNOWN' &&
            runtime.active_process_count === null &&
            runtime.observed_at === null,
    );
    require(
      (linked || task.current_refs.delivery_plan_id === null) &&
        (task.current_refs.delivery_id === null || task.current_refs.delivery_plan_id !== null),
    );
    const configuration = task.available_actions.find(
      (item) => item.action === 'APPLY_CONFIGURATION',
    );
    require(
      configuration !== undefined &&
        configuration.related_id === null &&
        configuration.enabled === (configuration.reason_code === null) &&
        [
          null,
          'INVALID_STATE',
          'OPERATION_IN_PROGRESS',
          'CONFIG_NOT_READY',
          'WRITER_ACTIVE',
        ].includes(configuration.reason_code),
    );
    validateStartedTask({
      ...task,
      available_actions: task.available_actions.map((item) =>
        item.action === 'APPLY_CONFIGURATION'
          ? { ...item, enabled: false, reason_code: 'INVALID_STATE' as const }
          : item,
      ),
      status: 'RUNNING',
      phase: 'INTEGRATION',
      active_operations: [],
      current_refs: {
        ...task.current_refs,
        test_report_id: null,
        delivery_plan_id: null,
        delivery_id: null,
      },
      runtime: {
        ...runtime,
        activity_status: 'UNKNOWN',
        active_process_count: null,
        observed_at: task.last_observed_at,
      },
    });
    return task;
  }
  require(
    task.current_refs.test_report_id === null &&
      task.current_refs.delivery_plan_id === null &&
      task.current_refs.delivery_id === null,
  );
  if (task.active_operations.some((operation) => operation.operation_type === 'HANDOFF_ROLE')) {
    validateStartedTask(task);
    return task;
  }
  if (task.status === 'VERIFYING') {
    const configuration = task.available_actions.find(
      (item) => item.action === 'APPLY_CONFIGURATION',
    );
    require(configuration !== undefined && configuration.related_id === null);
    require(
      configuration.enabled === (configuration.reason_code === null) &&
        (configuration.reason_code === 'OPERATION_IN_PROGRESS'
          ? task.active_operations.length === 1
          : [null, 'INVALID_STATE', 'CONFIG_NOT_READY', 'WRITER_ACTIVE'].includes(
              configuration.reason_code,
            )),
    );
    validateCapturedTask({
      ...task,
      available_actions: task.available_actions.map((item) =>
        item.action === 'APPLY_CONFIGURATION'
          ? { ...item, enabled: false, reason_code: 'INVALID_STATE' as const }
          : item,
      ),
    });
    return task;
  }
  if (task.phase === 'BACKEND' || task.phase === 'FRONTEND' || task.phase === 'INTEGRATION') {
    validateStartedTask(task);
    return task;
  }
  require(task.current_candidate_id === null);
  require(
    task.budget.limit_cny === task.budget.available_cny &&
      task.budget.settled_cny === '0.000000' &&
      task.budget.reserved_cny === '0.000000' &&
      task.budget.unresolved_call_count === 0,
  );
  if (
    task.active_operations.some((operation) => operation.operation_type === 'START') ||
    task.available_actions.some(
      (action) =>
        action.action === 'START' &&
        action.related_id !== null &&
        (action.reason_code === 'CONTENT_NOT_READY' || action.reason_code === 'CONFIG_NOT_READY'),
    )
  ) {
    validateStartPreparation(task);
    return task;
  }
  require(
    task.workspace_id === null &&
      task.active_session_id === null &&
      task.started_at === null &&
      task.runtime.environment_status === 'NOT_PREPARED' &&
      task.runtime.activity_status === 'NOT_STARTED',
  );
  if (task.status === 'PENDING') {
    require(
      task.phase === 'PREPARING' &&
        task.control_generation === 1 &&
        (task.state_version > 1 || task.created_at === task.updated_at) &&
        task.termination_operation_id === null &&
        task.stop_requested_at === null &&
        task.ended_at === null &&
        task.stopped_at === null &&
        task.last_observed_at === null &&
        task.active_operations.length === 0 &&
        task.runtime.stop_status === 'NONE' &&
        task.runtime.cleanup_status === 'NOT_STARTED' &&
        task.runtime.active_process_count === null &&
        task.runtime.observed_at === null &&
        task.available_actions.every((item) => item.related_id === null),
    );
  } else {
    const stopId = positiveInteger(task.termination_operation_id);
    const requested = time(task.stop_requested_at);
    require(
      task.control_generation === 2 && task.created_at <= requested && requested <= task.updated_at,
    );
    const terminal = task.status === 'TERMINATED';
    for (const item of task.available_actions) {
      const terminate = item.action === 'TERMINATE';
      require(
        item.enabled === (item.action === 'RECONCILE' || (terminate && !terminal)) &&
          item.related_id === (terminate ? stopId : null),
      );
    }
    if (terminal) {
      const stopped = time(task.stopped_at);
      require(
        task.phase === 'FINISHED' &&
          task.state_version >= 3 &&
          requested <= stopped &&
          task.ended_at === stopped &&
          task.last_observed_at === stopped &&
          task.updated_at >= stopped &&
          task.active_operations.length === 0 &&
          task.runtime.stop_status === 'VERIFIED' &&
          task.runtime.cleanup_status === 'VERIFIED' &&
          task.runtime.active_process_count === 0 &&
          task.runtime.observed_at === stopped,
      );
    } else {
      require(
        task.phase === 'PREPARING' &&
          task.state_version >= 2 &&
          task.ended_at === null &&
          task.stopped_at === null &&
          task.last_observed_at === null &&
          task.active_operations.length === 1 &&
          task.active_operations[0]?.id === stopId &&
          ['PENDING', 'RUNNING'].includes(task.active_operations[0]?.status ?? '') &&
          task.runtime.stop_status === 'REQUESTED' &&
          task.runtime.cleanup_status === 'NOT_STARTED' &&
          task.runtime.active_process_count === null &&
          task.runtime.observed_at === null,
      );
    }
  }
  return task;
}

function projectTask(value: unknown, original: CommandIdentity, input: JsonObject) {
  const fixed = checkInput(input, original);
  const task = decodeTaskView(value);
  require(
    task.status === 'PENDING' && task.state_version === 1 && task.active_operations.length === 0,
  );
  require(task.document_id === fixed.documentId && task.target_branch === fixed.branch);
  for (const field of fixedIdFields) require(task[field] === fixed.row[field]);
  require(task.material_refs.length === fixed.materials.length);
  for (const [index, item] of task.material_refs.entries()) {
    const expected = fixed.materials[index];
    require(
      expected?.document_id === item.document_id && expected.revision_id === item.revision_id,
    );
  }
  require(task.budget.limit_cny === fixed.budget);
  return task;
}

export const CREATE_CODE_TASK_BINDING: CodeCommandBinding<CreatedCodeTask> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C32',
  success_status: Object.freeze([201] as const),
  errors: Object.freeze([
    'INVALID_INPUT',
    'NOT_FOUND',
    'ACTIVE_TASK_EXISTS',
    'BASIS_NOT_CONFIRMED',
    'CONFIG_NOT_READY',
    'AUTHORIZATION_NOT_APPLICABLE',
    'CONTENT_NOT_READY',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'OPERATION_CONFLICT',
    'OPERATION_IN_PROGRESS',
    'COMMAND_CLOSED',
    'PRECONDITION_FAILED',
  ] as const),
  validate_input: checkInput,
  decode: projectTask,
});

export function prepareCreateCodeTask(
  client: ApiClient,
  documentId: number,
  input: CreateCodeTaskInput,
  currentOrigin: string,
) {
  positiveInteger(documentId);
  return prepareCodeCommand(
    client,
    '/api/v1/documents/' + documentId + '/code-tasks',
    { ...input, material_refs: input.material_refs.map((item) => ({ ...item })) },
    CREATE_CODE_TASK_BINDING,
    currentOrigin,
  );
}
