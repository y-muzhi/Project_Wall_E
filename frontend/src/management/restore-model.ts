import { exact, positiveInteger } from '../api/wire-shape.ts';
import { hash, items, one, utc, uuid } from './model.ts';

const choiceStates = [
  'READY',
  'SOURCE_NOT_STOPPED',
  'OPERATION_ACTIVE',
  'CAPACITY_RESERVED',
  'NO_VERIFIED_CONFIGURATION',
] as const;

const referenceFields = [
  'backup_id',
  'target_release_ref',
  'target_configuration_ref',
  'recovery_policy_ref',
  'source_data_generation',
] as const;
const environmentFields = [
  'environment_id',
  'expected_record_version',
  'expected_assignment_generation',
] as const;
const deploymentFields = [
  'data_generation',
  'deployment_id',
  'configuration_sha256',
  'program_sha256',
] as const;

function references(row: Readonly<Record<string, unknown>>) {
  return {
    backup_id: uuid(row.backup_id),
    target_release_ref: uuid(row.target_release_ref),
    target_configuration_ref: uuid(row.target_configuration_ref),
    recovery_policy_ref: uuid(row.recovery_policy_ref),
    source_data_generation: uuid(row.source_data_generation),
  };
}

function variables(row: Readonly<Record<string, unknown>>) {
  return {
    environment_id: uuid(row.environment_id),
    expected_record_version: positiveInteger(row.expected_record_version),
    expected_assignment_generation: positiveInteger(row.expected_assignment_generation),
    ...references(row),
  };
}

function identity(row: Readonly<Record<string, unknown>>) {
  return {
    generation: uuid(row.data_generation),
    deployment: uuid(row.deployment_id),
    configuration: hash(row.configuration_sha256),
    program: hash(row.program_sha256),
  };
}

export type RestoreVariables = ReturnType<typeof variables>;

export function restoreOptions(value: unknown, environment: string) {
  const row = exact(value, [
    'environment_id',
    'record_version',
    'assignment_generation',
    'state',
    'restore_options',
  ]);
  const id = uuid(row.environment_id);
  if (id !== environment) throw new TypeError('Invalid restore options scope');
  const state = one(row.state, choiceStates);
  const options = items(
    row.restore_options,
    (entry) => {
      const choice = exact(entry, [
        ...referenceFields,
        'cutoff_at',
        'backup_source_data_generation',
        'backup_manifest_sha256',
      ]);
      return {
        refs: references(choice),
        cutoff: utc(choice.cutoff_at),
        backupGeneration: uuid(choice.backup_source_data_generation),
        backupManifest: hash(choice.backup_manifest_sha256),
      };
    },
    256,
  );
  if (
    (state === 'READY') !== options.length > 0 ||
    new Set(options.map((option) => option.refs.target_configuration_ref)).size !== options.length
  )
    throw new TypeError('Invalid restore choices');
  return {
    state,
    options,
    recordVersion: positiveInteger(row.record_version),
    assignmentGeneration: positiveInteger(row.assignment_generation),
  };
}

export function restoreConfirmation(value: unknown) {
  const row = exact(value, [
    'action',
    ...environmentFields,
    ...referenceFields,
    'plan_id',
    'plan_sha256',
  ]);
  return {
    action: one(row.action, ['RESTORE'] as const),
    ...variables(row),
    plan_id: uuid(row.plan_id),
    plan_sha256: hash(row.plan_sha256),
  };
}

export function restorePlan(value: unknown, expected: RestoreVariables) {
  const envelope = exact(value, ['plan_id', 'plan_sha256', 'expires_at', 'preview']);
  const preview = exact(envelope.preview, [
    'kind',
    'plan_id',
    'expires_at',
    ...environmentFields,
    ...referenceFields,
    'operation_id',
    'source',
    'target',
    'source_attachment',
    'target_attachment_ref',
    'configuration_record_sha256',
    'release_candidate_sha256',
    'release_manifest_sha256',
    'schema_contract_sha256',
    'recovery_requirement',
    'recovery_policy_sha256',
    'restore_authorization_sha256',
    'preserved_backup_id',
    'data_handling',
    'backup',
  ]);
  const requested = variables(preview);
  const id = uuid(envelope.plan_id);
  const expires = utc(envelope.expires_at);
  if (
    preview.kind !== 'RESTORE' ||
    preview.plan_id !== id ||
    preview.expires_at !== expires ||
    JSON.stringify(requested) !== JSON.stringify(variables(expected))
  )
    throw new TypeError('Restore plan changed');
  const current = exact(preview.source, [
    ...deploymentFields,
    'control_revision',
    'operation_id',
    'control_sha256',
    'control_observation_sha256',
    'installation_sha256',
    'database_identity_sha256',
  ]);
  const source = identity(current);
  const target = identity(exact(preview.target, deploymentFields));
  uuid(current.operation_id);
  const sourceAttachment = exact(preview.source_attachment, ['candidate_ref', 'sha256']);
  hash(sourceAttachment.sha256);
  const preserved = uuid(preview.preserved_backup_id);
  const rawBackup = exact(preview.backup, [
    'backup_id',
    'source_data_generation',
    'source_deployment_id',
    'cutoff_at',
    'backup_manifest_sha256',
    'logical_content_sha256',
  ]);
  const backup = {
    id: uuid(rawBackup.backup_id),
    generation: uuid(rawBackup.source_data_generation),
    deployment: uuid(rawBackup.source_deployment_id),
    cutoff: utc(rawBackup.cutoff_at),
    manifest: hash(rawBackup.backup_manifest_sha256),
  };
  if (
    source.generation !== requested.source_data_generation ||
    source.generation === target.generation ||
    source.deployment === target.deployment ||
    uuid(sourceAttachment.candidate_ref) === uuid(preview.target_attachment_ref) ||
    backup.id !== requested.backup_id ||
    backup.id === preserved ||
    backup.generation === target.generation ||
    backup.deployment === target.deployment
  )
    throw new TypeError('Invalid restore generation');
  for (const field of [
    'configuration_record_sha256',
    'release_candidate_sha256',
    'schema_contract_sha256',
    'recovery_policy_sha256',
    'restore_authorization_sha256',
  ])
    hash(preview[field]);
  for (const field of [
    'control_sha256',
    'control_observation_sha256',
    'installation_sha256',
    'database_identity_sha256',
  ])
    hash(current[field]);
  hash(rawBackup.logical_content_sha256);
  one(preview.recovery_requirement, ['LOCAL_VERIFIED'] as const);
  one(preview.data_handling, ['PRESERVE_CURRENT_SOURCE'] as const);
  return {
    id,
    expires,
    digest: hash(envelope.plan_sha256),
    operation: uuid(preview.operation_id),
    variables: requested,
    source,
    target,
    backup,
    preserved,
    controlRevision: positiveInteger(current.control_revision),
    manifest: hash(preview.release_manifest_sha256),
  };
}
