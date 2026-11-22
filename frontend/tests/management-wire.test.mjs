import assert from 'node:assert/strict';
import test from 'node:test';

import { capacity, environmentBackups, operationDetail } from '../src/management/model.ts';
import { commandIntent } from '../src/management/command-intent.ts';
import { restoreOptions, restorePlan } from '../src/management/restore-model.ts';

const sampledAt = '2026-11-20T15:00:00.000Z';
const environment = '673bc7cb-5050-4ce8-a9bc-b7733dde9180';
const otherEnvironment = '0f9bc28b-39ef-456c-8c38-18b8d623a35d';
const run = 'ef9bd422-44a3-4d0c-a2d5-f830ed815a4d';

test('restore wire keeps the historical cutoff and the new generation in one original management operation', () => {
  const hash = 'a'.repeat(64);
  const version = 'd'.repeat(64);
  const variables = {
    environment_id: environment, expected_record_version: 4, expected_assignment_generation: 2,
    backup_id: run, target_release_ref: run, target_configuration_ref: environment,
    recovery_policy_ref: run, source_data_generation: otherEnvironment,
  };
  const source = {
    data_generation: otherEnvironment, deployment_id: environment, configuration_sha256: hash,
    program_sha256: hash, control_revision: 8, operation_id: run, control_sha256: hash,
    control_observation_sha256: hash, installation_sha256: hash, database_identity_sha256: hash,
  };
  const target = { data_generation: run, deployment_id: otherEnvironment,
    configuration_sha256: version, program_sha256: version };
  const cutoff = '2026-11-19T08:00:00.000Z';
  const preview = {
    kind: 'RESTORE', plan_id: run, expires_at: sampledAt, ...variables, operation_id: environment,
    source, target, source_attachment: { candidate_ref: environment, sha256: hash },
    target_attachment_ref: run, configuration_record_sha256: hash, release_candidate_sha256: hash,
    release_manifest_sha256: version, schema_contract_sha256: hash, recovery_requirement: 'LOCAL_VERIFIED',
    recovery_policy_sha256: hash, restore_authorization_sha256: hash, preserved_backup_id: environment,
    data_handling: 'PRESERVE_CURRENT_SOURCE',
    backup: { backup_id: run, source_data_generation: otherEnvironment, source_deployment_id: environment,
      cutoff_at: cutoff, backup_manifest_sha256: hash, logical_content_sha256: hash },
  };
  const plan = { plan_id: run, plan_sha256: hash, expires_at: sampledAt, preview };
  assert.equal(restorePlan(plan, variables).backup.cutoff, cutoff);
  assert.equal(restorePlan(plan, variables).target.generation, run);
  assert.throws(() => restorePlan({ ...plan, preview: { ...preview, target: {
    ...target, data_generation: variables.source_data_generation,
  } } }, variables), TypeError);
  assert.throws(() => restorePlan(plan, { ...variables, expected_record_version: 5 }), TypeError);
  const confirm = { action: 'RESTORE', ...variables, plan_id: run, plan_sha256: hash };
  assert.deepEqual(commandIntent(confirm), confirm);
  assert.throws(() => commandIntent({ ...confirm, path: 'a/host/path' }), TypeError);
  const blocked = { environment_id: environment, record_version: 4, assignment_generation: 2,
    state: 'SOURCE_NOT_STOPPED', restore_options: [] };
  assert.equal(restoreOptions(blocked, environment).state, 'SOURCE_NOT_STOPPED');
  assert.throws(() => restoreOptions({ ...blocked, state: 'READY' }, environment), TypeError);
});

const missingCapacity = {
  total: null,
  reserved: null,
  available: null,
  observed_at: null,
  waiting_count: 2,
  reason_code: 'HOST_CAPACITY_UNVERIFIED',
};

test('management capacity distinguishes unknown observation, a measured zero, and scoped waits', () => {
  const unknown = capacity(missingCapacity);
  assert.equal(unknown.available, null);
  assert.equal(unknown.at, null);
  assert.equal(unknown.waiting, 2);
  const measured = capacity({
    ...missingCapacity,
    available: 0,
    observed_at: sampledAt,
    reason_code: 'HOST_MEMORY_OBSERVED',
  });
  assert.equal(measured.available, 0);
  assert.equal(measured.at, sampledAt);
  assert.equal(measured.reserved, null);
  assert.equal(measured.total, null);
});

test('management capacity rejects inconsistent or unsafe host observations', () => {
  const measured = {
    ...missingCapacity,
    observed_at: sampledAt,
    available: 128 * 1024,
    reason_code: 'HOST_MEMORY_OBSERVED',
  };
  for (const patch of [
    { observed_at: null },
    { available: null },
    { available: -1 },
    { available: Number.MAX_SAFE_INTEGER + 1 },
    { reason_code: 'HOST_CAPACITY_UNVERIFIED' },
  ]) {
    assert.throws(() => capacity({ ...measured, ...patch }), TypeError);
  }
});


test('management backup history keeps the failed attempt, earlier valid point and unknown offsite freshness separate', () => {
  const cutoff = '2026-11-20T13:00:00.000Z';
  const point = {
    backup_id: run,
    source_environment_id: environment,
    source_data_generation: otherEnvironment,
    source_deployment_id: run,
    source_control_revision: 3,
    cutoff_at: cutoff,
    backup_manifest_sha256: 'a'.repeat(64),
    database_bytes: 4096,
    logical_content_sha256: 'b'.repeat(64),
    count_audit_state: 'FILES',
    program_sha256: 'c'.repeat(64),
    configuration_sha256: 'd'.repeat(64),
    verification_status: 'LOCAL_VERIFIED',
    local_verification: {
      verification_id: run,
      verified_at: sampledAt,
      verified_scopes: ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
    },
    local_snapshot_retrieval: { snapshot_id: 'e'.repeat(64), retrieved_at: sampledAt },
  };
  const body = {
    environment_id: environment,
    backups: [point],
    next_cursor: null,
    backup_status: {
      as_of: sampledAt,
      indexed_at: sampledAt,
      backup_policy_ref: otherEnvironment,
      rpo_target_seconds: 86400,
      rto_target_seconds: 14400,
      latest_attempt: {
        operation_id: run,
        status: 'FAILED',
        observed_at: sampledAt,
        reason_code: 'BACKUP_ASSET_UNSUPPORTED',
      },
      latest_local: { backup_id: run, cutoff_at: cutoff, verified_at: sampledAt },
      latest_offhost: null,
      rpo_status: 'UNVERIFIED',
    },
  };
  const checked = environmentBackups(body, environment);
  assert.equal(checked.local.cutoff, cutoff);
  assert.equal(checked.attempt.status, 'FAILED');
  assert.equal(checked.entries[0].retrieval.retrievedAt, sampledAt);
  assert.equal(checked.offhost, null);
  assert.equal(checked.rpo, 'UNVERIFIED');
  assert.throws(() => environmentBackups(body, otherEnvironment), TypeError);
  for (const patch of [
    { source_environment_id: otherEnvironment },
    { verification_status: 'UNVERIFIED' },
    { local_verification: null },
    { path: '/private/path' },
  ]) {
    assert.throws(
      () => environmentBackups({ ...body, backups: [{ ...point, ...patch }] }, environment),
      TypeError,
    );
  }
  assert.throws(
    () => environmentBackups({ ...body, backup_status: { ...body.backup_status, rpo_status: 'MET' } }, environment),
    TypeError,
  );
});

test('management reads pending and terminal lifecycle receipts without accepting foreign effects', () => {
  const operation = {
    operation_id: '68dd33a1-1de7-4f5c-b44e-5f87efc009de',
    request_key: '52468f0f-8985-485e-b634-115df2b8a901',
    action: 'STOP',
    environment_id: environment,
    status: 'SUCCEEDED',
    revision: 2,
    created_at: sampledAt,
    intent_sha256: '7'.repeat(64),
    cancel_requested: false,
    submitted_by: 'developer',
  };
  const result = {
    environment_id: environment,
    run_id: run,
    runtime_state: 'STOPPED',
    observed_at: sampledAt,
    proof_id: '2a55d008-b25c-4c8b-86df-9e4f252afe8a',
  };
  const step = { ordinal: 1, kind: 'RUNTIME_STOPPED', status: 'SUCCEEDED', result };
  assert.equal(operationDetail({ operation, steps: [step] }).steps[0].result.run, run);
  const cancelled = { ...operation, action: 'START', status: 'CANCELLED', cancel_requested: true };
  const started = {
    ...step,
    kind: 'RUNTIME_STARTED',
    result: { ...result, runtime_state: 'RUNNING' },
  };
  const stopped = { ...step, ordinal: 2, kind: 'RUNTIME_START_CANCELLED' };
  const unready = {
    ...started,
    status: 'FAILED',
    result: { ...result, runtime_state: 'STARTED_UNREADY' },
  };
  assert.equal(
    operationDetail({ operation: cancelled, steps: [unready, stopped] }).steps[0].status,
    'FAILED',
  );
  assert.throws(
    () =>
      operationDetail({
        operation: cancelled,
        steps: [{ ...unready, status: 'SUCCEEDED' }, stopped],
      }),
    TypeError,
  );
  assert.equal(
    operationDetail({ operation: cancelled, steps: [started, stopped] }).steps[1].result.run,
    run,
  );
  assert.throws(
    () =>
      operationDetail({
        operation: cancelled,
        steps: [started, { ...stopped, result: { ...result, run_id: otherEnvironment } }],
      }),
    TypeError,
  );
  assert.throws(
    () =>
      operationDetail({
        operation: { ...cancelled, status: 'UNKNOWN' },
        steps: [started, stopped],
      }),
    TypeError,
  );

  const skipped = { ...started, status: 'SKIPPED', result: null };
  const retired = {
    ordinal: 2,
    kind: 'RUNTIME_PREPARATION_CANCELLED',
    status: 'SUCCEEDED',
    result: {
      environment_id: environment,
      observed_at: sampledAt,
      proof_id: result.proof_id,
      control_revision: 3,
      outcome: 'RETIRED',
    },
  };
  assert.equal(
    operationDetail({ operation: cancelled, steps: [skipped, retired] }).steps[1].result
      .controlRevision,
    3,
  );
  for (const steps of [
    [started, retired],
    [skipped, { ...retired, status: 'UNKNOWN' }],
    [skipped, { ...retired, result: { ...retired.result, run_id: run } }],
  ]) {
    assert.throws(() => operationDetail({ operation: cancelled, steps }), TypeError);
  }

  const unresolved = operationDetail({
    operation: { ...operation, status: 'UNKNOWN' },
    steps: [{ ...step, status: 'UNKNOWN', result: null }],
  });
  assert.equal(unresolved.steps[0].result, null);
  for (const effect of [
    { ...result, environment_id: otherEnvironment },
    { ...result, runtime_state: 'RUNNING' },
    { ...result, private_systemd_unit: 'not-public' },
  ]) {
    assert.throws(
      () => operationDetail({ operation, steps: [{ ...step, result: effect }] }),
      TypeError,
    );
  }
});
