import { exact, positiveInteger } from '../api/wire-shape.ts';
import { hash, items, one, utc, uuid } from './model.ts';

const assets = ['BUSINESS_DATABASE', 'COUNT_AUDIT', 'FIXED_RESOURCES', 'ORIGINAL_RESULTS'] as const;
const limits = ['max_database_bytes', 'max_audit_files', 'max_audit_bytes'] as const;
const variables = [
  'environment_id',
  'expected_record_version',
  'expected_assignment_generation',
  'backup_policy_ref',
  'after_completion',
] as const;

function assetSet(value: unknown) {
  const returned = items(value, (item) => one(item, assets), assets.length);
  if (!assets.every((value, index) => value === returned[index]))
    throw new TypeError('Invalid backup coverage');
  return returned;
}

export function backupOptions(value: unknown, environmentId: string) {
  const row = exact(value, [
    'environment_id',
    'record_version',
    'assignment_generation',
    'backup_options',
  ]);
  if (uuid(row.environment_id) !== environmentId) throw new TypeError('Invalid backup scope');
  const options = items(
    row.backup_options,
    (value) => {
      const choice = exact(value, [
        'backup_policy_ref',
        'minimum_verification',
        'assets',
        'state',
        ...limits,
      ]);
      const state = one(choice.state, [
        'READY',
        'SOURCE_UNVERIFIED',
        'ENVIRONMENT_BUSY',
        'OFFHOST_REQUIRED',
      ] as const);
      const verification = one(choice.minimum_verification, [
        'LOCAL_VERIFIED',
        'OFFHOST_VERIFIED',
      ] as const);
      if ((state === 'OFFHOST_REQUIRED') !== (verification === 'OFFHOST_VERIFIED'))
        throw new TypeError('Invalid backup availability');
      return {
        policy: uuid(choice.backup_policy_ref),
        state,
        verification,
        assets: assetSet(choice.assets),
        maxDatabase: positiveInteger(choice.max_database_bytes),
        maxAudit: positiveInteger(choice.max_audit_bytes),
        maxAuditFiles: positiveInteger(choice.max_audit_files),
      };
    },
    256,
  );
  if (new Set(options.map((choice) => choice.policy)).size !== options.length)
    throw new TypeError('Duplicate backup policy');
  return {
    recordVersion: positiveInteger(row.record_version),
    generation: positiveInteger(row.assignment_generation),
    options,
  };
}

function backupVariables(input: Readonly<Record<string, unknown>>) {
  return {
    environment_id: uuid(input.environment_id),
    expected_record_version: positiveInteger(input.expected_record_version),
    expected_assignment_generation: positiveInteger(input.expected_assignment_generation),
    backup_policy_ref: uuid(input.backup_policy_ref),
    after_completion: one(input.after_completion, ['KEEP_STOPPED', 'RESUME_PREVIOUS'] as const),
  };
}

export type BackupVariables = ReturnType<typeof backupVariables>;

export function backupConfirmation(value: unknown) {
  const input = exact(value, ['action', ...variables, 'plan_id', 'plan_sha256']);
  if (input.action !== 'BACKUP') throw new TypeError('Invalid backup command');
  return {
    action: 'BACKUP' as const,
    ...backupVariables(input),
    plan_id: uuid(input.plan_id),
    plan_sha256: hash(input.plan_sha256),
  };
}

export function backupPlan(value: unknown, expected: BackupVariables) {
  const envelope = exact(value, ['plan_id', 'expires_at', 'plan_sha256', 'preview']);
  const plan = exact(envelope.preview, [
    'kind',
    'plan_id',
    'expires_at',
    ...variables,
    'source',
    'source_attachment',
    'completion',
    'backup_id',
    'backup_policy_sha256',
    'minimum_verification',
    'assets',
  ]);
  const id = uuid(envelope.plan_id);
  const expires = utc(envelope.expires_at);
  const requested = backupVariables(plan);
  if (
    plan.kind !== 'BACKUP' ||
    plan.plan_id !== id ||
    plan.expires_at !== expires ||
    JSON.stringify(requested) !== JSON.stringify(backupVariables(expected))
  )
    throw new TypeError('Backup plan changed');
  const source = exact(plan.source, [
    'data_generation',
    'deployment_id',
    'configuration_sha256',
    'program_sha256',
    'control_revision',
    'operation_id',
    'control_sha256',
    'installation_sha256',
  ]);
  const sourceRef = exact(plan.source_attachment, ['candidate_ref', 'sha256']);
  uuid(sourceRef.candidate_ref);
  hash(sourceRef.sha256);
  uuid(source.operation_id);
  hash(source.control_sha256);
  hash(source.installation_sha256);
  hash(plan.backup_policy_sha256);
  return {
    id,
    digest: hash(envelope.plan_sha256),
    expires,
    requested,
    backup: uuid(plan.backup_id),
    completion: one(plan.completion, ['KEEP_STOPPED'] as const),
    verification: one(plan.minimum_verification, ['LOCAL_VERIFIED'] as const),
    assets: assetSet(plan.assets),
    source: {
      deployment: uuid(source.deployment_id),
      generation: uuid(source.data_generation),
      configuration: hash(source.configuration_sha256),
      program: hash(source.program_sha256),
      revision: positiveInteger(source.control_revision),
    },
  };
}
