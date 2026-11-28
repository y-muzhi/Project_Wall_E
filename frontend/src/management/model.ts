import { exact, object, positiveInteger } from '../api/wire-shape.ts';

export const purposes = ['DEVELOPMENT', 'INTEGRATION', 'CANDIDATE', 'PRODUCTION'] as const;
export const operationStates = [
  'WAITING_CAPACITY',
  'ACCEPTED',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
  'UNKNOWN',
] as const;

export function text(value: unknown, maximum = 2000): string {
  if (typeof value !== 'string' || !value.length || value.length > maximum)
    throw new TypeError('Invalid management text');
  return value;
}

export function uuid(value: unknown): string {
  const id = text(value, 36);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id))
    throw new TypeError('Invalid management identity');
  return id;
}

export function hash(value: unknown, sizes: readonly number[] = [64]): string {
  const actual = text(value, 64);
  if (!sizes.includes(actual.length) || !/^[0-9a-f]+$/.test(actual))
    throw new TypeError('Invalid digest');
  return actual;
}

export function utc(value: unknown): string {
  const at = text(value, 24);
  if (new Date(at).toISOString() !== at) throw new TypeError('Invalid timestamp');
  return at;
}

export function one<T extends string>(value: unknown, choices: readonly T[]): T {
  const item = choices.find((choice) => choice === value);
  if (!item) throw new TypeError('Unknown management value');
  return item;
}

export function nullable<T>(value: unknown, decode: (item: unknown) => T): T | null {
  return value === null ? null : decode(value);
}

export function items<T>(value: unknown, decode: (item: unknown) => T, limit = 100): T[] {
  if (!Array.isArray(value) || value.length > limit) throw new TypeError('Invalid management list');
  return value.map((item) => decode(item));
}

function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new TypeError('Invalid management flag');
  return value;
}

function count(value: unknown): number {
  if (value === 0) return 0;
  return positiveInteger(value);
}

function action(value: unknown) {
  const row = exact(value, ['action', 'enabled', 'reason_code']);
  const action = one(row.action, [
    'CREATE',
    'ATTACH',
    'START',
    'STOP',
    'HANDOFF',
    'REGISTER_DELIVERY',
    'ARCHIVE',
    'CLEANUP',
  ] as const);
  return {
    action,
    enabled: boolean(row.enabled),
    reason: nullable(row.reason_code, (item) => text(item, 80)),
  };
}

const configKeys = [
  'format_version',
  'management_protocol',
  'manager_id',
  'host_id',
  'registry_generation',
  'display_name',
  'public_origin',
  'api_base',
] as const;

function configFields(row: Readonly<Record<string, unknown>>, origin: string) {
  if (
    row.format_version !== 1 ||
    row.management_protocol !== 1 ||
    row.api_base !== '/management/api/v1' ||
    row.public_origin !== origin ||
    !origin.startsWith('https://')
  )
    throw new TypeError('Invalid management entry binding');
  return {
    manager: uuid(row.manager_id),
    host: uuid(row.host_id),
    generation: uuid(row.registry_generation),
    name: text(row.display_name, 120),
    origin,
  };
}

export function configuration(value: unknown, origin: string) {
  return configFields(exact(value, configKeys), origin);
}

export function candidateCatalog(value: unknown) {
  const { candidates } = exact(value, ['candidates']);
  return items(
    candidates,
    (item) => {
      const row = exact(item, [
        'candidate_ref',
        'sha256',
        'display_name',
        'environment_id',
        'record_version',
        'observed_at',
        'state',
      ]);
      const state = one(row.state, [
        'READY',
        'REATTACH_READY',
        'EVIDENCE_REQUIRED',
        'REGISTERED',
        'BLOCKED',
      ] as const);
      const environment = nullable(row.environment_id, uuid);
      const version = nullable(row.record_version, positiveInteger);
      const at = nullable(row.observed_at, utc);
      if (
        (environment === null) !== (version === null) ||
        (state === 'READY' && (environment !== null || at === null)) ||
        (state === 'REATTACH_READY' && (environment === null || at === null)) ||
        ((state === 'BLOCKED' || state === 'REGISTERED') && environment === null)
      ) {
        throw new TypeError('Invalid attachment candidate');
      }
      return {
        id: uuid(row.candidate_ref),
        digest: hash(row.sha256),
        name: text(row.display_name, 120),
        state,
        environment,
        version,
        at,
      };
    },
    256,
  );
}

export function handshake(value: unknown, origin: string) {
  const row = exact(value, [
    ...configKeys,
    'manager_run_id',
    'phase',
    'observed_at',
    'access',
    'available_actions',
  ]);
  const access = exact(row.access, [
    'principal_id',
    'client_kind',
    'role',
    'visible_environment_ids',
  ]);
  if (access.client_kind !== 'WEB') throw new TypeError('Management browser access required');
  return {
    config: configFields(row, origin),
    run: uuid(row.manager_run_id),
    phase: one(row.phase, ['READY', 'RECOVERING', 'BLOCKED'] as const),
    observedAt: utc(row.observed_at),
    role: one(access.role, ['MANAGER', 'DEVELOPER', 'VIEWER'] as const),
    principal: actor(access.principal_id),
    visible: items(access.visible_environment_ids, uuid, 256),
    actions: items(row.available_actions, action),
  };
}

export function actor(value: unknown): string {
  const id = text(value, 64);
  if (!/^[a-z0-9][a-z0-9_.-]{0,63}$/i.test(id)) throw new TypeError('Invalid management actor');
  return id;
}

function observation(value: unknown) {
  const row = exact(value, [
    'source',
    'observed_at',
    'freshness',
    'runtime_state',
    'run_id',
    'reason_code',
  ]);
  return {
    source: nullable(row.source, (item) =>
      one(item, ['ATTACHMENT', 'HOST', 'APPLICATION'] as const),
    ),
    observedAt: nullable(row.observed_at, utc),
    freshness: one(row.freshness, ['FRESH', 'STALE', 'UNAVAILABLE'] as const),
    runtime: one(row.runtime_state, ['RUNNING', 'STOPPED', 'UNKNOWN'] as const),
    run: nullable(row.run_id, uuid),
    reason: text(row.reason_code, 100),
  };
}

const environmentKeys = [
  'environment_id',
  'purpose',
  'display_name',
  'task_id',
  'record_version',
  'assignment_generation',
  'registration_state',
  'preparation_state',
  'configuration_sha256',
  'owner_label',
  'baseline_commit',
  'program_sha256',
  'observation',
  'allowed_actions',
  'business_url',
] as const;

function entryUrl(value: unknown): string {
  const original = text(value);
  const target = new URL(original);
  if (
    target.protocol !== 'https:' ||
    target.username ||
    target.password ||
    target.pathname !== '/' ||
    target.search ||
    target.hash
  )
    throw new TypeError('Invalid business entry');
  return target.href;
}

function environmentFields(row: Readonly<Record<string, unknown>>) {
  return {
    id: uuid(row.environment_id),
    name: text(row.display_name, 120),
    purpose: one(row.purpose, purposes),
    owner: text(row.owner_label, 120),
    task: uuid(row.task_id),
    recordVersion: positiveInteger(row.record_version),
    generation: positiveInteger(row.assignment_generation),
    registration: one(row.registration_state, ['ACTIVE', 'ARCHIVED'] as const),
    preparation: one(row.preparation_state, ['PREPARING', 'PREPARED', 'INCOMPLETE'] as const),
    configuration: nullable(row.configuration_sha256, hash),
    program: nullable(row.program_sha256, hash),
    baseline: hash(row.baseline_commit, [40, 64]),
    observation: observation(row.observation),
    actions: items(row.allowed_actions, action),
    business: nullable(row.business_url, entryUrl),
  };
}

export function environmentList(value: unknown) {
  const row = exact(value, ['environments', 'next_cursor']);
  return {
    entries: items(row.environments, (item) => environmentFields(exact(item, environmentKeys))),
    next: nullable(row.next_cursor, (item) => text(item, 400)),
  };
}

export function environment(value: unknown) {
  const row = exact(value, [...environmentKeys, 'work', 'resources']);
  const work = exact(row.work, [
    'goal',
    'scope',
    'checks',
    'branch',
    'data_generation',
    'deployment_id',
  ]);
  return {
    ...environmentFields(row),
    work: {
      goal: text(work.goal),
      scope: text(work.scope),
      checks: text(work.checks),
      branch: text(work.branch),
      generation: uuid(work.data_generation),
      deployment: uuid(work.deployment_id),
    },
    resources: items(row.resources, (item) => {
      const resource = exact(item, ['resource_id', 'kind', 'claimed']);
      return {
        id: uuid(resource.resource_id),
        kind: text(resource.kind, 64),
        claimed: boolean(resource.claimed),
      };
    }),
  };
}

function backupStamp(value: unknown) {
  const row = exact(value, ['backup_id', 'cutoff_at', 'verified_at']);
  const cutoff = utc(row.cutoff_at);
  const verifiedAt = utc(row.verified_at);
  if (verifiedAt < cutoff) throw new TypeError('Restoration observation predates the backup');
  return { id: uuid(row.backup_id), cutoff, verifiedAt };
}

function offhostVerification(value: unknown, cutoff: string) {
  const proof = exact(value, ['verification_id', 'snapshot_id', 'retrieved_at']);
  const retrievedAt = utc(proof.retrieved_at);
  if (retrievedAt < cutoff) throw new TypeError('Invalid offhost retrieval time');
  return { id: uuid(proof.verification_id), snapshot: hash(proof.snapshot_id), retrievedAt };
}

function backupPoint(value: unknown, environmentId: string) {
  const hasOffhost = Object.hasOwn(object(value), 'offhost_verification');
  const keys = hasOffhost ? ['offhost_verification'] : [];
  const row = exact(value, [
    ...keys,
    'backup_id',
    'source_environment_id',
    'source_data_generation',
    'source_deployment_id',
    'source_control_revision',
    'cutoff_at',
    'backup_manifest_sha256',
    'database_bytes',
    'logical_content_sha256',
    'count_audit_state',
    'program_sha256',
    'configuration_sha256',
    'verification_status',
    'local_verification',
    'local_snapshot_retrieval',
  ]);
  const state = one(row.verification_status, [
    'UNVERIFIED',
    'LOCAL_VERIFIED',
    'OFFHOST_VERIFIED',
  ] as const);
  const cutoff = utc(row.cutoff_at);
  const local = nullable(row.local_verification, (value) => {
    const proof = exact(value, ['verification_id', 'verified_at', 'verified_scopes']);
    const scopes = items(
      proof.verified_scopes,
      (scope) => one(scope, ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'] as const),
      2,
    );
    const verifiedAt = utc(proof.verified_at);
    if (
      scopes.length !== 2 ||
      scopes[0] !== 'DOCUMENT_CONTENT' ||
      scopes[1] !== 'DOCUMENT_HISTORY' ||
      verifiedAt < cutoff
    )
      throw new TypeError('Invalid locally verified recovery scope');
    return { id: uuid(proof.verification_id), verifiedAt, scopes };
  });
  const retrieval = nullable(row.local_snapshot_retrieval, (value) => {
    const proof = exact(value, ['snapshot_id', 'retrieved_at']);
    const retrievedAt = utc(proof.retrieved_at);
    if (retrievedAt < cutoff) throw new TypeError('Invalid snapshot retrieval time');
    return { snapshot: hash(proof.snapshot_id), retrievedAt };
  });
  const offhost = hasOffhost ? offhostVerification(row.offhost_verification, cutoff) : null;
  if (
    uuid(row.source_environment_id) !== environmentId ||
    (state !== 'UNVERIFIED') !== !!local ||
    (state === 'OFFHOST_VERIFIED') !== !!offhost
  )
    throw new TypeError('Backup point belongs to another scope or observation');
  return {
    id: uuid(row.backup_id),
    generation: uuid(row.source_data_generation),
    deployment: uuid(row.source_deployment_id),
    revision: positiveInteger(row.source_control_revision),
    cutoff,
    manifest: hash(row.backup_manifest_sha256),
    bytes: positiveInteger(row.database_bytes),
    content: hash(row.logical_content_sha256),
    audit: one(row.count_audit_state, ['ABSENT', 'EMPTY', 'FILES'] as const),
    program: hash(row.program_sha256),
    configuration: hash(row.configuration_sha256),
    state,
    local,
    retrieval,
    offhost,
  };
}

export function backupStatus(value: unknown) {
  const details = exact(value, [
    'as_of',
    'indexed_at',
    'backup_policy_ref',
    'rpo_target_seconds',
    'rto_target_seconds',
    'latest_attempt',
    'latest_local',
    'latest_offhost',
    'rpo_status',
  ]);
  const attempt = nullable(details.latest_attempt, (value) => {
    const observed = exact(value, ['operation_id', 'status', 'observed_at', 'reason_code']);
    return {
      id: uuid(observed.operation_id),
      status: one(observed.status, [
        'CREATING',
        'SUCCEEDED',
        'FAILED',
        'UNVERIFIED',
        'PENDING_RECONCILIATION',
      ] as const),
      at: utc(observed.observed_at),
      reason: nullable(observed.reason_code, (reason) => text(reason, 80)),
    };
  });
  const asOf = utc(details.as_of);
  const indexedAt = nullable(details.indexed_at, utc);
  const policy = nullable(details.backup_policy_ref, uuid);
  const rpoTarget = nullable(details.rpo_target_seconds, positiveInteger);
  const rtoTarget = nullable(details.rto_target_seconds, positiveInteger);
  const local = nullable(details.latest_local, backupStamp);
  const offhost = nullable(details.latest_offhost, backupStamp);
  const rpo = one(details.rpo_status, ['UNVERIFIED', 'MET', 'MISSED'] as const);
  if (
    (indexedAt !== null && indexedAt > asOf) ||
    (policy === null && (rpoTarget !== null || rtoTarget !== null)) ||
    (policy !== null && (rpoTarget === null || rtoTarget === null)) ||
    (rpo !== 'UNVERIFIED' && (offhost === null || rpoTarget === null)) ||
    (local !== null && local.verifiedAt > (indexedAt ?? asOf)) ||
    (offhost !== null && offhost.verifiedAt > (indexedAt ?? asOf))
  )
    throw new TypeError('Backup freshness evidence is inconsistent');
  if (offhost !== null && rpoTarget !== null && rpo !== 'UNVERIFIED') {
    const gap = Date.parse(asOf) - Date.parse(offhost.cutoff);
    if ((rpo === 'MET') !== gap <= rpoTarget * 1000)
      throw new TypeError('Backup freshness does not match its cutoff');
  }
  return { asOf, indexedAt, policy, rpoTarget, rtoTarget, attempt, local, offhost, rpo };
}

export function environmentBackups(value: unknown, environmentId: string) {
  const row = exact(value, ['environment_id', 'backups', 'backup_status', 'next_cursor']);
  if (uuid(row.environment_id) !== environmentId) throw new TypeError('Incorrect backup scope');
  const entries = items(row.backups, (item) => backupPoint(item, environmentId));
  if (new Set(entries.map((point) => point.id)).size !== entries.length)
    throw new TypeError('Duplicate backup point');
  const next = nullable(row.next_cursor, (value) => {
    const cursor = text(value, 400);
    if (!/^[A-Za-z0-9_-]+$/.test(cursor)) throw new TypeError('Invalid backup cursor');
    return cursor;
  });
  const status = backupStatus(row.backup_status);
  for (const entry of entries) {
    if (!entry.offhost) continue;
    const latest = status.offhost;
    if (
      !latest ||
      entry.cutoff > latest.cutoff ||
      entry.offhost.retrievedAt > (status.indexedAt ?? status.asOf) ||
      (entry.id === latest.id &&
        (entry.cutoff !== latest.cutoff || entry.offhost.retrievedAt !== latest.verifiedAt))
    )
      throw new TypeError('Offhost point differs from the recovery status');
  }
  return { entries, next, ...status };
}

export function operation(value: unknown) {
  const row = exact(value, [
    'operation_id',
    'request_key',
    'action',
    'environment_id',
    'status',
    'revision',
    'created_at',
    'intent_sha256',
    'cancel_requested',
    'submitted_by',
  ]);
  return {
    id: uuid(row.operation_id),
    key: uuid(row.request_key),
    action: one(row.action, [
      'ATTACH',
      'REGISTER_DELIVERY',
      'START',
      'STOP',
      'ARCHIVE',
      'RELEASE',
      'ROLLBACK_CODE',
      'RECONFIGURE',
      'BACKUP',
      'RESTORE',
    ] as const),
    environment: uuid(row.environment_id),
    state: one(row.status, operationStates),
    revision: positiveInteger(row.revision),
    at: utc(row.created_at),
    intent: hash(row.intent_sha256),
    cancelling: boolean(row.cancel_requested),
    by: text(row.submitted_by, 64),
  };
}

export function operationList(value: unknown) {
  const row = exact(value, ['operations', 'next_cursor']);
  return {
    entries: items(row.operations, operation),
    next: nullable(row.next_cursor, (item) => text(item, 400)),
  };
}

const lifecycleSteps = [
  'RUNTIME_STARTED',
  'RUNTIME_STOPPED',
  'RUNTIME_START_CANCELLED',
  'RUNTIME_PREPARATION_CANCELLED',
] as const;
const operationSteps = [
  'ATTACH_REGISTERED',
  'DELIVERY_REGISTERED',
  'RELEASE_DEPLOYMENT',
  'BACKUP_RECOVERY_POINT',
  'RESTORE_ENVIRONMENT',
  'ENVIRONMENT_ARCHIVED',
  ...lifecycleSteps,
] as const;
const stepByAction = {
  ATTACH: 'ATTACH_REGISTERED',
  REGISTER_DELIVERY: 'DELIVERY_REGISTERED',
  START: 'RUNTIME_STARTED',
  STOP: 'RUNTIME_STOPPED',
  ARCHIVE: 'ENVIRONMENT_ARCHIVED',
  RELEASE: 'RELEASE_DEPLOYMENT',
  ROLLBACK_CODE: 'RELEASE_DEPLOYMENT',
  RECONFIGURE: 'RELEASE_DEPLOYMENT',
  BACKUP: 'BACKUP_RECOVERY_POINT',
  RESTORE: 'RESTORE_ENVIRONMENT',
} as const;

function receipt(value: unknown, kind: (typeof operationSteps)[number]) {
  if (kind === 'ENVIRONMENT_ARCHIVED') {
    const row = exact(value, [
      'environment_id',
      'record_version',
      'assignment_generation',
      'archived_at',
    ]);
    return {
      kind,
      environment: uuid(row.environment_id),
      recordVersion: positiveInteger(row.record_version),
      generation: positiveInteger(row.assignment_generation),
      archivedAt: utc(row.archived_at),
    };
  }
  if (kind === 'BACKUP_RECOVERY_POINT') {
    const hasOffhost = Object.hasOwn(object(value), 'offhost_observation_max_age_seconds');
    const row = exact(value, [
      'environment_id',
      'observed_at',
      'point',
      ...(hasOffhost ? ['offhost_observation_max_age_seconds'] : []),
    ]);
    const environment = uuid(row.environment_id);
    const observed = utc(row.observed_at);
    const point = backupPoint(row.point, environment);
    if (
      !point.local ||
      point.local.verifiedAt > observed ||
      hasOffhost !== Boolean(point.offhost) ||
      (point.offhost !== null &&
        (point.offhost.retrievedAt > observed ||
          positiveInteger(row.offhost_observation_max_age_seconds) > 365 * 86400))
    )
      throw new TypeError('Invalid backup receipt');
    return { kind, environment, observed, point };
  }
  if (kind === 'RELEASE_DEPLOYMENT' || kind === 'RESTORE_ENVIRONMENT') {
    const restored = kind === 'RESTORE_ENVIRONMENT';
    const row = exact(value, [
      'environment_id',
      'data_generation',
      'deployment_id',
      'configuration_sha256',
      'run_id',
      'opened_at',
      'control_revision',
      'release_ref',
      'release_manifest_sha256',
      'proof_id',
      'record_version',
      'assignment_generation',
      ...(restored
        ? [
            'source_data_generation',
            'backup_id',
            'backup_cutoff_at',
            'restore_authorization_sha256',
          ]
        : []),
    ]);
    const result = {
      environment: uuid(row.environment_id),
      dataGeneration: uuid(row.data_generation),
      deployment: uuid(row.deployment_id),
      configuration: hash(row.configuration_sha256),
      run: uuid(row.run_id),
      opened: utc(row.opened_at),
      controlRevision: positiveInteger(row.control_revision),
      release: uuid(row.release_ref),
      manifest: hash(row.release_manifest_sha256),
      proof: uuid(row.proof_id),
      recordVersion: positiveInteger(row.record_version),
      generation: positiveInteger(row.assignment_generation),
    };
    if (kind === 'RESTORE_ENVIRONMENT') {
      const source = uuid(row.source_data_generation);
      if (source === result.dataGeneration) throw new TypeError('Invalid restored generation');
      return {
        kind,
        ...result,
        source,
        backup: uuid(row.backup_id),
        cutoff: utc(row.backup_cutoff_at),
        authorization: hash(row.restore_authorization_sha256),
      };
    }
    return { kind, ...result };
  }
  if (kind === 'RUNTIME_PREPARATION_CANCELLED') {
    const row = exact(value, [
      'environment_id',
      'control_revision',
      'outcome',
      'observed_at',
      'proof_id',
    ]);
    return {
      kind,
      environment: uuid(row.environment_id),
      controlRevision: positiveInteger(row.control_revision),
      outcome: one(row.outcome, ['UNCHANGED', 'RETIRED'] as const),
      observed: utc(row.observed_at),
      proof: uuid(row.proof_id),
    };
  }
  if (
    kind === 'RUNTIME_STARTED' ||
    kind === 'RUNTIME_STOPPED' ||
    kind === 'RUNTIME_START_CANCELLED'
  ) {
    const row = exact(value, [
      'environment_id',
      'run_id',
      'runtime_state',
      'observed_at',
      'proof_id',
    ]);
    const state = one(row.runtime_state, ['RUNNING', 'STARTED_UNREADY', 'STOPPED'] as const);
    if ((kind === 'RUNTIME_STARTED') === (state === 'STOPPED'))
      throw new TypeError('Invalid runtime effect');
    return {
      kind,
      environment: uuid(row.environment_id),
      run: uuid(row.run_id),
      state,
      observed: utc(row.observed_at),
      proof: uuid(row.proof_id),
    };
  }
  if (kind === 'ATTACH_REGISTERED') {
    const row = exact(value, [
      'record_version',
      'assignment_generation',
      'environment_id',
      'purpose',
      'data_generation',
      'configuration_sha256',
      'worktree_evidence_sha256',
      'proof_id',
      'observed_at',
      'operation_committed_at',
      'preparation_state',
      'runtime_state',
    ]);
    return {
      kind,
      environment: uuid(row.environment_id),
      recordVersion: positiveInteger(row.record_version),
      generation: positiveInteger(row.assignment_generation),
      dataGeneration: uuid(row.data_generation),
      purpose: one(row.purpose, purposes),
      proof: uuid(row.proof_id),
      observed: utc(row.observed_at),
      at: utc(row.operation_committed_at),
      configuration: hash(row.configuration_sha256),
      workspace: hash(row.worktree_evidence_sha256),
      runtime: one(row.runtime_state, ['UNKNOWN'] as const),
      preparation: one(row.preparation_state, ['PREPARED'] as const),
    };
  }
  const row = exact(value, [
    'environment_id',
    'repository_ref',
    'record_version',
    'assignment_generation',
    'commit',
    'tree',
    'branch',
    'proof_id',
    'workspace_evidence_sha256',
    'resource_refs',
    'check_refs',
    'manual_notes',
    'not_covered',
    'source_deliveries',
    'submitted_by',
    'verified_at',
  ]);
  const references = items(row.resource_refs, (item) => {
    const ref = exact(item, ['ref', 'sha256', 'bytes']);
    return { id: uuid(ref.ref), digest: hash(ref.sha256), bytes: count(ref.bytes) };
  });
  const evidence = items(row.check_refs, (item) => {
    const ref = exact(item, ['ref', 'sha256', 'bytes', 'result', 'checked_at']);
    return {
      id: uuid(ref.ref),
      digest: hash(ref.sha256),
      bytes: count(ref.bytes),
      result: one(ref.result, ['PASSED', 'FAILED', 'INCONCLUSIVE'] as const),
      at: utc(ref.checked_at),
    };
  });
  const sources = items(row.source_deliveries, (item) => {
    const ref = exact(item, ['environment_id', 'commit', 'delivery_operation_id']);
    return {
      environment: uuid(ref.environment_id),
      commit: hash(ref.commit, [40, 64]),
      operation: uuid(ref.delivery_operation_id),
    };
  });
  return {
    kind,
    environment: uuid(row.environment_id),
    repository: uuid(row.repository_ref),
    recordVersion: positiveInteger(row.record_version),
    generation: positiveInteger(row.assignment_generation),
    commit: hash(row.commit, [40, 64]),
    tree: hash(row.tree, [40, 64]),
    branch: text(row.branch),
    proof: uuid(row.proof_id),
    workspace: hash(row.workspace_evidence_sha256),
    references,
    evidence,
    sources,
    manual: row.manual_notes === '' ? '' : text(row.manual_notes),
    uncovered: items(row.not_covered, text),
    by: text(row.submitted_by, 64),
    at: utc(row.verified_at),
  };
}

export function operationDetail(value: unknown) {
  const row = exact(value, ['operation', 'steps']);
  const original = operation(row.operation);
  const steps = items(row.steps, (item) => {
    const step = exact(item, ['ordinal', 'kind', 'status', 'result']);
    const kind = one(step.kind, operationSteps);
    const status = one(step.status, [
      'SUCCEEDED',
      'PLANNED',
      'DISPATCHING',
      'FAILED',
      'UNKNOWN',
      'SKIPPED',
    ] as const);
    if (original.state === 'WAITING_CAPACITY') {
      if (kind !== 'RUNTIME_STARTED' || original.action !== 'START' || status !== 'PLANNED')
        throw new TypeError('Invalid capacity wait step');
      const detail = exact(step.result, ['observed_at', 'missing']);
      const missing = items(
        detail.missing,
        (value) => one(value, ['memory_bytes', 'cpu_percent', 'tasks', 'run_slots'] as const),
        4,
      );
      if (!missing.length || new Set(missing).size !== missing.length)
        throw new TypeError('Invalid missing capacity');
      return {
        ordinal: positiveInteger(step.ordinal),
        kind,
        status,
        result: null,
        wait: { at: utc(detail.observed_at), missing },
      };
    }
    const result = nullable(step.result, (result) => receipt(result, kind));
    const ordinal = positiveInteger(step.ordinal);
    const matchesAction =
      ordinal === 1
        ? kind === stepByAction[original.action]
        : ordinal === 2 &&
          original.action === 'START' &&
          original.state === 'CANCELLED' &&
          original.cancelling &&
          (kind === 'RUNTIME_START_CANCELLED' || kind === 'RUNTIME_PREPARATION_CANCELLED') &&
          status === 'SUCCEEDED';
    const unready = result?.kind === 'RUNTIME_STARTED' && result.state === 'STARTED_UNREADY';
    const unreadyCancelled = unready && status === 'FAILED' && original.state === 'CANCELLED';
    if (
      (unready && !unreadyCancelled) ||
      (status === 'SUCCEEDED' || unreadyCancelled) !== Boolean(result) ||
      !matchesAction ||
      (result && result.environment !== original.environment)
    )
      throw new TypeError('Inconsistent original receipt');
    return { ordinal, kind, status, result, wait: null };
  });
  if (steps.length === 2) {
    const [start, stop] = steps;
    if (start?.kind !== 'RUNTIME_STARTED')
      throw new TypeError('Inconsistent cancellation evidence');
    if (stop?.kind === 'RUNTIME_PREPARATION_CANCELLED') {
      if (
        start.status !== 'SKIPPED' ||
        start.result !== null ||
        stop.result?.kind !== 'RUNTIME_PREPARATION_CANCELLED'
      )
        throw new TypeError('Inconsistent preparation cancellation evidence');
    } else if (
      stop?.kind !== 'RUNTIME_START_CANCELLED' ||
      start.result?.kind !== 'RUNTIME_STARTED' ||
      stop.result?.kind !== 'RUNTIME_START_CANCELLED' ||
      start.result.run !== stop.result.run
    ) {
      throw new TypeError('Inconsistent cancellation evidence');
    }
  }
  if (steps.length > 2) throw new TypeError('Unexpected operation steps');
  return { original, steps };
}

export function controlResult(value: unknown, operationId: string, key: string) {
  const row = exact(value, ['control_receipt', 'operation', 'steps']);
  const operation = operationDetail({ operation: row.operation, steps: row.steps });
  const { original } = operation;
  const receipt = exact(row.control_receipt, [
    'control_key',
    'operation_id',
    'command',
    'revision',
    'operation_revision',
    'result',
    'recorded_at',
  ]);
  const command = one(receipt.command, ['CONTINUE', 'CANCEL', 'RECONCILE'] as const);
  const result = one(receipt.result, [
    'WAITING_CAPACITY',
    'ACCEPTED',
    'CANCELLED',
    'CANCELLATION_REQUESTED',
    'RECONCILED',
  ] as const);
  const expectedResults = {
    CONTINUE: ['WAITING_CAPACITY', 'ACCEPTED'],
    CANCEL: ['CANCELLED', 'CANCELLATION_REQUESTED'],
    RECONCILE: ['RECONCILED'],
  };
  const revision = positiveInteger(receipt.revision);
  const operationRevision = positiveInteger(receipt.operation_revision);
  if (
    uuid(receipt.control_key) !== key ||
    uuid(receipt.operation_id) !== operationId ||
    original.id !== operationId ||
    operationRevision > original.revision ||
    !expectedResults[command].includes(result)
  )
    throw new TypeError('Inconsistent original control receipt');
  return {
    operation,
    receipt: { command, result, revision, operationRevision, recorded: utc(receipt.recorded_at) },
  };
}

export function controlReceipt(value: unknown, operationId: string, key: string) {
  return controlResult(value, operationId, key).receipt;
}

export function capacity(value: unknown) {
  const row = exact(value, [
    'observed_at',
    'total',
    'reserved',
    'available',
    'waiting_count',
    'reason_code',
  ]);
  const at = nullable(row.observed_at, utc);
  const available = nullable(row.available, count);
  const reason = one(row.reason_code, [
    'HOST_MEMORY_OBSERVED',
    'HOST_CAPACITY_UNVERIFIED',
  ] as const);
  if (
    (reason === 'HOST_MEMORY_OBSERVED') !== (available !== null && at !== null) ||
    (available === null) !== (at === null)
  )
    throw new TypeError('Inconsistent capacity observation');
  const total = nullable(row.total, count);
  const reserved = nullable(row.reserved, count);
  if ((total === null) !== (reserved === null))
    throw new TypeError('Inconsistent managed capacity');
  return {
    at,
    total,
    reserved,
    available,
    waiting: count(row.waiting_count),
    reason,
  };
}
