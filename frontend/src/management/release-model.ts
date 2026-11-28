import { exact, object, positiveInteger } from '../api/wire-shape.ts';
import { backupStatus, hash, items, nullable, one, text, utc, uuid } from './model.ts';

export const releaseChoiceStates = [
  'READY',
  'SOURCE_UNVERIFIED',
  'CANDIDATE_UNVERIFIED',
  'RECOVERY_NOT_ADMITTED',
  'ENVIRONMENT_BUSY',
] as const;
export const releaseActions = ['RELEASE', 'ROLLBACK_CODE', 'RECONFIGURE'] as const;
export type ReleaseAction = (typeof releaseActions)[number];

const sharedRefFields = ['environment_id', 'configuration_ref'] as const;
const releaseRefFields = {
  RELEASE: [...sharedRefFields, 'compatibility_ref', 'release_ref', 'recovery_policy_ref'],
  ROLLBACK_CODE: [...sharedRefFields, 'compatibility_ref', 'retained_release_ref'],
  RECONFIGURE: [...sharedRefFields, 'recovery_policy_ref'],
} as const;
const releaseVersionFields = ['expected_record_version', 'expected_assignment_generation'] as const;

function confirmationFields(action: ReleaseAction) {
  return [
    ...releaseRefFields[action],
    ...releaseVersionFields,
    ...(action === 'ROLLBACK_CODE' ? ['repair_of_operation_id'] : []),
  ];
}

function releaseRefs(row: Readonly<Record<string, unknown>>, action: ReleaseAction) {
  const scope = {
    environment_id: uuid(row.environment_id),
    configuration_ref: uuid(row.configuration_ref),
  };
  if (action === 'RECONFIGURE')
    return { ...scope, recovery_policy_ref: uuid(row.recovery_policy_ref) };
  const compatibility_ref = uuid(row.compatibility_ref);
  if (action === 'ROLLBACK_CODE')
    return { ...scope, compatibility_ref, retained_release_ref: uuid(row.retained_release_ref) };
  return {
    ...scope,
    compatibility_ref,
    release_ref: uuid(row.release_ref),
    recovery_policy_ref: uuid(row.recovery_policy_ref),
  };
}

export function releaseCatalog(value: unknown, id: string, action: ReleaseAction = 'RELEASE') {
  const row = exact(value, [
    'environment_id',
    'record_version',
    'assignment_generation',
    'release_options',
  ]);
  if (uuid(row.environment_id) !== id) throw new TypeError('Invalid release catalog scope');
  const options = items(
    row.release_options,
    (value) => {
      const option = exact(value, [
        ...releaseRefFields[action],
        'state',
        'manifest_sha256',
        'commit',
        'target_os',
        'target_arch',
      ]);
      const refs = releaseRefs(option, action);
      const state = one(option.state, releaseChoiceStates);
      const commit = nullable(option.commit, (oid) => hash(oid, [40, 64]));
      const os = nullable(option.target_os, (os) => text(os, 40));
      const architecture = nullable(option.target_arch, (arch) => text(arch, 40));
      if (
        refs.environment_id !== id ||
        Boolean(commit) !== Boolean(os) ||
        Boolean(commit) !== Boolean(architecture) ||
        (state === 'READY' && !commit)
      )
        throw new TypeError('Invalid release choice');
      return { refs, state, commit, os, architecture, manifest: hash(option.manifest_sha256) };
    },
    256,
  );
  if (new Set(options.map((option) => option.refs.configuration_ref)).size !== options.length)
    throw new TypeError('Duplicate release choice');
  return {
    recordVersion: positiveInteger(row.record_version),
    generation: positiveInteger(row.assignment_generation),
    options,
  };
}

export type ReleaseSelection = ReturnType<typeof releaseCatalog>['options'][number];
export type ReleaseVariables = ReturnType<typeof releaseVariables>;

export function releaseVariables(
  input: Readonly<Record<string, unknown>>,
  action: ReleaseAction = 'RELEASE',
) {
  return {
    ...releaseRefs(input, action),
    expected_record_version: positiveInteger(input.expected_record_version),
    expected_assignment_generation: positiveInteger(input.expected_assignment_generation),
    ...(action === 'ROLLBACK_CODE' && {
      repair_of_operation_id: nullable(input.repair_of_operation_id, uuid),
    }),
  };
}

export function releaseConfirmation(value: unknown) {
  const action = one(object(value).action, releaseActions);
  const input = exact(value, ['action', ...confirmationFields(action), 'plan_id', 'plan_sha256']);
  return {
    action,
    ...releaseVariables(input, action),
    plan_id: uuid(input.plan_id),
    plan_sha256: hash(input.plan_sha256),
  };
}

function attachmentRef(value: unknown) {
  const ref = exact(value, ['candidate_ref', 'sha256']);
  return { id: uuid(ref.candidate_ref), manifest: hash(ref.sha256) };
}

export function releasePlan(
  value: unknown,
  expected: ReleaseVariables,
  action: ReleaseAction = 'RELEASE',
) {
  const envelope = exact(value, ['plan_id', 'plan_sha256', 'expires_at', 'preview']);
  const preview = exact(envelope.preview, [
    'kind',
    'plan_id',
    'expires_at',
    ...confirmationFields(action),
    ...(action === 'ROLLBACK_CODE' ? ['rollback_source_sha256'] : []),
    ...(action === 'RECONFIGURE' ? ['target_access_sha256', 'fixed_release_ref'] : []),
    'configuration_record_sha256',
    'release_candidate_sha256',
    'release_manifest_sha256',
    'schema_manifest_sha256',
    'runtime_manifest_sha256',
    'schema_contract_sha256',
    'verification_state',
    'compatibility_sha256',
    'recovery_policy_sha256',
    'recovery_requirement',
    'source_attachment',
    'target_attachment',
    'source_observation_sha256',
    'source_observed_at',
    'source_database_identity_sha256',
    'source',
    'target',
    'required_capabilities',
    'compatibility_mode',
    'completion',
  ]);
  const variables = releaseVariables(preview, action);
  if (action === 'ROLLBACK_CODE') hash(preview.rollback_source_sha256);
  if (action === 'RECONFIGURE') uuid(preview.fixed_release_ref);
  const id = uuid(envelope.plan_id);
  const expires = utc(envelope.expires_at);
  if (
    preview.kind !== action ||
    preview.plan_id !== id ||
    preview.expires_at !== expires ||
    JSON.stringify(variables) !== JSON.stringify(releaseVariables(expected, action))
  )
    throw new TypeError('Release plan changed');
  const current = exact(preview.source, [
    ...deploymentFields,
    'installation_sha256',
    'control_revision',
    'control_sha256',
  ]);
  const next = exact(preview.target, [...deploymentFields, 'installation_sha256']);
  hash(current.installation_sha256);
  hash(current.control_sha256);
  hash(next.installation_sha256);
  for (const key of [
    'configuration_record_sha256',
    'release_candidate_sha256',
    'schema_manifest_sha256',
    'runtime_manifest_sha256',
    'schema_contract_sha256',
    'compatibility_sha256',
    'recovery_policy_sha256',
    'source_observation_sha256',
    'source_database_identity_sha256',
  ])
    hash(preview[key]);
  const source = deployment(current);
  const target = deployment(next);
  const sourceAttachment = attachmentRef(preview.source_attachment);
  const targetAttachment = attachmentRef(preview.target_attachment);
  if (
    source.generation !== target.generation ||
    source.id === target.id ||
    sourceAttachment.id === targetAttachment.id ||
    (action === 'RECONFIGURE' &&
      (source.program !== target.program || source.configuration === target.configuration))
  )
    throw new TypeError('Release plan changes the data boundary');
  return {
    variables,
    id,
    expires,
    digest: hash(envelope.plan_sha256),
    source,
    target,
    accessPolicy: action === 'RECONFIGURE' ? hash(preview.target_access_sha256) : null,
    controlRevision: positiveInteger(current.control_revision),
    observed: utc(preview.source_observed_at),
    manifest: hash(preview.release_manifest_sha256),
    compatibility: one(preview.compatibility_mode, ['SAME_SCHEMA'] as const),
    recovery: one(preview.recovery_requirement, ['LOCAL_VERIFIED', 'OFFHOST_VERIFIED'] as const),
    completion: one(preview.completion, ['OPEN_TARGET'] as const),
    verified: one(preview.verification_state, ['REQUIRED_EVIDENCE_RECORDED'] as const),
    capabilities: items(
      preview.required_capabilities,
      (value) => one(value, ['DOCUMENT_READ', 'DOCUMENT_WRITE'] as const),
      2,
    ),
  };
}

const deploymentFields = [
  'data_generation',
  'deployment_id',
  'configuration_sha256',
  'program_sha256',
] as const;

function deployment(row: Record<string, unknown>) {
  return {
    generation: uuid(row.data_generation),
    id: uuid(row.deployment_id),
    configuration: hash(row.configuration_sha256),
    program: hash(row.program_sha256),
  };
}

function observedControl(value: unknown) {
  const row = exact(value, [
    ...deploymentFields,
    'control_revision',
    'operation_id',
    'admission',
    'closed_reason',
    'outbound_hold',
    'last_open',
  ]);
  const admission = one(row.admission, ['OPEN', 'DRAINING', 'CLOSED'] as const);
  const reason = one(row.closed_reason, [
    'NONE',
    'NORMAL_STOP',
    'MAINTENANCE',
    'RECOVERY_REQUIRED',
  ] as const);
  if (typeof row.outbound_hold !== 'boolean' || (admission === 'OPEN') !== (reason === 'NONE'))
    throw new TypeError('Invalid maintenance admission');
  const lastOpen = nullable(row.last_open, (value) => {
    const previous = exact(value, ['deployment_id', 'run_id', 'opened_at']);
    return {
      deployment: uuid(previous.deployment_id),
      run: uuid(previous.run_id),
      at: utc(previous.opened_at),
    };
  });
  if (admission === 'OPEN' && lastOpen?.deployment !== row.deployment_id)
    throw new TypeError('Invalid last opening');
  return {
    ...deployment(row),
    admission,
    reason,
    lastOpen,
    operation: uuid(row.operation_id),
    revision: positiveInteger(row.control_revision),
    hold: row.outbound_hold,
  };
}

const readStatus = ['NOT_APPLICABLE', 'BLOCKED', 'AVAILABLE'] as const;
const readScopes = ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY', 'EXISTING_REPORTS'] as const;
const blockerCodes = [
  'SOURCE_UNVERIFIED',
  'BINDING_UNVERIFIED',
  'ASSET_UNVERIFIED',
  'EXECUTION_NOT_FENCED',
  'OBSERVATION_UNAVAILABLE',
  'RECOVERY_RECONCILIATION_REQUIRED',
] as const;

function recoveryRead(value: unknown) {
  const row = exact(value, [
    'status',
    'observed_at',
    'deployment_id',
    'data_generation',
    'control_revision',
    'verification_ref',
    'verified_scopes',
    'blockers',
  ]);
  const status = one(row.status, readStatus);
  const observed = nullable(row.observed_at, utc);
  const deployment = nullable(row.deployment_id, uuid);
  const generation = nullable(row.data_generation, uuid);
  const revision = nullable(row.control_revision, positiveInteger);
  const verification = nullable(row.verification_ref, hash);
  const scopes = items(row.verified_scopes, (scope) => one(scope, readScopes), 3);
  const blockers = items(
    row.blockers,
    (blocker) => one(exact(blocker, ['code']).code, blockerCodes),
    blockerCodes.length,
  );
  if (
    (status === 'AVAILABLE' &&
      (!scopes.length ||
        !observed ||
        !deployment ||
        !generation ||
        !revision ||
        !verification ||
        blockers.some((code) => code !== 'RECOVERY_RECONCILIATION_REQUIRED'))) ||
    (status !== 'AVAILABLE' && (scopes.length || verification)) ||
    (status === 'BLOCKED' && !blockers.length) ||
    (status === 'NOT_APPLICABLE' && blockers.length) ||
    new Set(scopes).size !== scopes.length ||
    new Set(blockers).size !== blockers.length
  )
    throw new TypeError('Invalid recovery read status');
  return { status, observed, deployment, generation, revision, verification, scopes, blockers };
}

export function maintenanceDetails(value: unknown, id: string) {
  const row = exact(value, [
    'environment_id',
    'registered',
    'desired',
    'phase',
    'freshness',
    'actual',
    'last_observation',
    'operation',
    'recovery_read',
    'backup_status',
  ]);
  if (uuid(row.environment_id) !== id) throw new TypeError('Invalid maintenance scope');
  const actual = nullable(row.actual, observedControl);
  const last = nullable(row.last_observation, (value) => {
    const observed = exact(value, ['observed_at', 'control']);
    return { at: utc(observed.observed_at), control: observedControl(observed.control) };
  });
  const phase = one(row.phase, [
    'OBSERVATION_UNAVAILABLE',
    'IDLE',
    'MAINTENANCE_UNTRACKED',
    'WAITING_FOR_MAINTENANCE',
    'MAINTENANCE_CLOSED',
    'TARGET_SELECTED',
    'OPENED_AWAITING_REGISTRY',
  ] as const);
  const freshness = one(row.freshness, ['FRESH', 'STALE', 'UNAVAILABLE'] as const);
  if (
    (freshness === 'FRESH') !== Boolean(actual) ||
    (freshness === 'UNAVAILABLE') !== !last ||
    (actual && JSON.stringify(actual) !== JSON.stringify(last?.control))
  )
    throw new TypeError('Invalid freshness evidence');
  const recovery = recoveryRead(row.recovery_read);
  if (
    recovery.status === 'AVAILABLE' &&
    (!actual ||
      !actual.hold ||
      actual.admission !== 'CLOSED' ||
      actual.reason !== 'MAINTENANCE' ||
      recovery.deployment !== actual.id ||
      recovery.generation !== actual.generation ||
      recovery.revision !== actual.revision)
  )
    throw new TypeError('Invalid live recovery binding');
  const operation = nullable(row.operation, (value) => {
    const entry = exact(value, ['operation_id', 'status', 'revision']);
    return {
      id: uuid(entry.operation_id),
      status: one(entry.status, ['ACCEPTED', 'RUNNING', 'UNKNOWN'] as const),
      revision: positiveInteger(entry.revision),
    };
  });
  return {
    registered: nullable(row.registered, (value) => deployment(exact(value, deploymentFields))),
    desired: nullable(row.desired, (value) => deployment(exact(value, deploymentFields))),
    phase,
    freshness,
    actual,
    last,
    operation,
    recovery,
    backup: backupStatus(row.backup_status),
  };
}
