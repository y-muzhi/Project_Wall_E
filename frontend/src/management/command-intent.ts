import { commandSha256 } from '../api/code-command-snapshot.ts';
import { parseEnvironmentJson } from '../api/environment-binding.ts';
import { exact, object, positiveInteger } from '../api/wire-shape.ts';
import { actor, hash, items, one, uuid } from './model.ts';
import type { Session } from './api.ts';
import { releaseConfirmation } from './release-model.ts';
import { backupConfirmation } from './backup-model.ts';
import { restoreConfirmation } from './restore-model.ts';

export const bodyLimit = 64 * 1024;

export type ManagementControl = 'RECONCILE' | 'CANCEL' | 'CONTINUE';
export type EnvironmentAction = 'START' | 'STOP' | 'ARCHIVE';

type Attach = Readonly<{
  action: 'ATTACH';
  candidate_ref: string;
  expected_candidate_sha256: string;
  environment_id?: string;
  expected_record_version?: number;
}>;
type Delivery = Readonly<{
  action: 'REGISTER_DELIVERY';
  environment_id: string;
  expected_record_version: number;
  expected_assignment_generation: number;
  commit: string;
  resource_refs: string[];
  check_refs: string[];
  manual_notes: string;
  not_covered: string[];
  source_environment_ids?: string[];
  source_commits?: string[];
}>;

export type ManagementIntent =
  | Attach
  | Delivery
  | ReturnType<typeof releaseConfirmation>
  | ReturnType<typeof environmentIntent>
  | ReturnType<typeof backupConfirmation>
  | ReturnType<typeof restoreConfirmation>;

function environmentIntent(input: Readonly<Record<string, unknown>>) {
  const action = one(input.action, ['START', 'STOP', 'ARCHIVE'] as const);
  const base = [
    'action',
    'environment_id',
    'expected_record_version',
    'expected_assignment_generation',
  ];
  const fields = { START: ['expected_configuration_sha256'], STOP: ['target'], ARCHIVE: [] };
  exact(input, [...base, ...fields[action]]);
  const scope = {
    environment_id: uuid(input.environment_id),
    expected_record_version: positiveInteger(input.expected_record_version),
    expected_assignment_generation: positiveInteger(input.expected_assignment_generation),
  };
  if (action === 'START')
    return {
      action,
      ...scope,
      expected_configuration_sha256: hash(input.expected_configuration_sha256),
    };
  if (action === 'ARCHIVE') return { action, ...scope };
  const target = exact(input.target, ['kind', 'run_id']);
  return {
    action,
    ...scope,
    target: { kind: one(target.kind, ['RUN'] as const), run_id: uuid(target.run_id) },
  };
}
export type ManagementScope = Readonly<{
  scope_version: 1;
  origin: string;
  manager_id: string;
  registry_generation: string;
}>;

export function commandScope(session: Session): ManagementScope {
  return {
    scope_version: 1,
    origin: session.config.origin,
    manager_id: session.config.manager,
    registry_generation: session.config.generation,
  };
}

export function scopeParts(scope: ManagementScope): [1, string, string, string] {
  return [1, scope.origin, scope.manager_id, scope.registry_generation];
}

export function scopeRecord(input: unknown) {
  const scope = exact(input, ['scope_version', 'origin', 'manager_id', 'registry_generation']);
  if (scope.scope_version !== 1 || typeof scope.origin !== 'string')
    throw new TypeError('Invalid scope');
  const origin = new URL(scope.origin);
  if (origin.protocol !== 'https:' || origin.origin !== scope.origin)
    throw new TypeError('Invalid origin');
  return {
    scope_version: 1 as const,
    origin: origin.origin,
    manager_id: uuid(scope.manager_id),
    registry_generation: uuid(scope.registry_generation),
  };
}

function refs(value: unknown, minimum = 0) {
  const list = items(value, uuid, 64);
  if (list.length < minimum || new Set(list).size !== list.length)
    throw new TypeError('Invalid references');
  return list;
}

function note(value: unknown, allowEmpty = false): string {
  if (
    typeof value !== 'string' ||
    [...value].length > 2000 ||
    (value === '' && !allowEmpty) ||
    value.trim() !== value ||
    /[\x00-\x08\x0b-\x1f\x7f\uD800-\uDFFF]/u.test(value)
  )
    throw new TypeError('Invalid management note');
  return value;
}

function commit(value: unknown) {
  const oid = hash(value, [40, 64]);
  if (/^0+$/.test(oid)) throw new TypeError('Invalid commit');
  return oid;
}

export function commandIntent(value: unknown): ManagementIntent {
  const input = object(value);
  if (input.action === 'ATTACH') {
    const archived = 'environment_id' in input || 'expected_record_version' in input;
    exact(input, [
      'action',
      'candidate_ref',
      'expected_candidate_sha256',
      ...(archived ? ['environment_id', 'expected_record_version'] : []),
    ]);
    return {
      action: 'ATTACH',
      candidate_ref: uuid(input.candidate_ref),
      expected_candidate_sha256: hash(input.expected_candidate_sha256),
      ...(archived && {
        environment_id: uuid(input.environment_id),
        expected_record_version: positiveInteger(input.expected_record_version),
      }),
    };
  }
  if (
    input.action === 'RELEASE' ||
    input.action === 'ROLLBACK_CODE' ||
    input.action === 'RECONFIGURE'
  )
    return releaseConfirmation(input);
  if (input.action === 'BACKUP') return backupConfirmation(input);
  if (input.action === 'RESTORE') return restoreConfirmation(input);
  if (input.action === 'START' || input.action === 'STOP' || input.action === 'ARCHIVE')
    return environmentIntent(input);
  if (input.action !== 'REGISTER_DELIVERY') throw new TypeError('Invalid management action');
  const integration = 'source_environment_ids' in input || 'source_commits' in input;
  exact(input, [
    'action',
    'environment_id',
    'expected_record_version',
    'expected_assignment_generation',
    'commit',
    'resource_refs',
    'check_refs',
    'manual_notes',
    'not_covered',
    ...(integration ? ['source_environment_ids', 'source_commits'] : []),
  ]);
  const environment = uuid(input.environment_id);
  const environments = integration ? refs(input.source_environment_ids, 1) : [];
  const commits = integration ? items(input.source_commits, commit, 64) : [];
  if (environments.includes(environment) || commits.length !== environments.length)
    throw new TypeError('Invalid integration sources');
  return {
    action: 'REGISTER_DELIVERY',
    environment_id: environment,
    expected_record_version: positiveInteger(input.expected_record_version),
    expected_assignment_generation: positiveInteger(input.expected_assignment_generation),
    commit: commit(input.commit),
    resource_refs: refs(input.resource_refs),
    check_refs: refs(input.check_refs),
    manual_notes: note(input.manual_notes, true),
    not_covered: items(input.not_covered, (item) => note(item), 64),
    ...(integration && { source_environment_ids: environments, source_commits: commits }),
  };
}

function originalBody(intent: ManagementIntent) {
  // The STOP target uses sorted keys from environmentIntent. Sort the outer fields to match registry bytes.
  const fields = Object.entries(intent).sort(([first], [second]) =>
    first < second ? -1 : first > second ? 1 : 0,
  );
  const body = JSON.stringify(Object.fromEntries(fields)) + '\n';
  if (new TextEncoder().encode(body).byteLength > bodyLimit)
    throw new TypeError('Management intent too large');
  return body;
}

export async function freezeIntent(input: unknown) {
  const intent = commandIntent(input);
  const body = originalBody(intent);
  return { body, digest: await commandSha256(body) };
}

export function recoverIntent(body: unknown) {
  if (typeof body !== 'string' || body.length > bodyLimit)
    throw new TypeError('Invalid original body');
  const result = commandIntent(parseEnvironmentJson(body));
  if (originalBody(result) !== body) throw new TypeError('Original body has changed');
  return result;
}

export const dispatchStates = ['PREPARED', 'DISPATCHING', 'UNCERTAIN'] as const;
export type PendingCommand = Readonly<{
  record_version: 1;
  scope: ManagementScope;
  actor: string;
  submit_intent_id: string;
  command_key: string;
  method: 'POST';
  body: string;
  intent_sha256: string;
  dispatch_owner: string | null;
  revision: number;
  state: (typeof dispatchStates)[number];
}> &
  CommandBinding;

type CommandBinding = Readonly<
  | {
      kind: 'ACTION';
      path: '/management/api/v1/operations';
      operation_id: null;
      action: ManagementIntent['action'];
      target: string;
      target_version: number | null;
      assignment_generation: number | null;
    }
  | {
      kind: 'CONTROL';
      path: `/management/api/v1/operations/${string}/commands`;
      operation_id: string;
      action: ManagementControl;
      target: string;
      target_version: number;
      assignment_generation: null;
    }
>;

function controlInput(command: unknown, revision: unknown) {
  return {
    command: one(command, ['RECONCILE', 'CANCEL', 'CONTINUE'] as const),
    expected_revision: positiveInteger(revision),
  };
}

export async function freezeControl(command: ManagementControl, revision: number) {
  const body = JSON.stringify(controlInput(command, revision)) + '\n';
  return { body, digest: await commandSha256(body) };
}

function recoverControl(body: unknown) {
  if (typeof body !== 'string' || body.length > bodyLimit)
    throw new TypeError('Invalid original control');
  const input = exact(parseEnvironmentJson(body), ['command', 'expected_revision']);
  const command = controlInput(input.command, input.expected_revision);
  if (JSON.stringify(command) + '\n' !== body) throw new TypeError('Original control has changed');
  return command;
}

export function commandBinding(body: unknown, operation: unknown): CommandBinding {
  if (operation !== null) {
    const id = uuid(operation);
    const control = recoverControl(body);
    return {
      kind: 'CONTROL',
      path: `/management/api/v1/operations/${id}/commands`,
      operation_id: id,
      action: control.command,
      target: id,
      target_version: control.expected_revision,
      assignment_generation: null,
    };
  }
  const intent = recoverIntent(body);
  return {
    kind: 'ACTION',
    path: '/management/api/v1/operations',
    operation_id: null,
    action: intent.action,
    target: intent.action === 'ATTACH' ? intent.candidate_ref : intent.environment_id,
    target_version: intent.expected_record_version ?? null,
    assignment_generation:
      intent.action === 'ATTACH' ? null : intent.expected_assignment_generation,
  };
}

export function pendingCommand(value: unknown): PendingCommand {
  const row = exact(value, [
    'record_version',
    'kind',
    'scope',
    'actor',
    'submit_intent_id',
    'command_key',
    'method',
    'path',
    'body',
    'intent_sha256',
    'target',
    'target_version',
    'assignment_generation',
    'operation_id',
    'action',
    'dispatch_owner',
    'revision',
    'state',
  ]);
  const binding = commandBinding(row.body, row.operation_id);
  const state = one(row.state, dispatchStates);
  const owner = row.dispatch_owner === null ? null : uuid(row.dispatch_owner);
  if (
    row.record_version !== 1 ||
    row.method !== 'POST' ||
    Object.entries(binding).some(([key, expected]) => row[key] !== expected) ||
    (state === 'DISPATCHING') !== (owner !== null)
  ) {
    throw new TypeError('Invalid pending management command');
  }
  return {
    record_version: 1,
    ...binding,
    scope: scopeRecord(row.scope),
    actor: actor(row.actor),
    submit_intent_id: uuid(row.submit_intent_id),
    command_key: uuid(row.command_key),
    method: 'POST',
    body: String(row.body),
    intent_sha256: hash(row.intent_sha256),
    dispatch_owner: owner,
    revision: positiveInteger(row.revision),
    state,
  };
}
