import { commandSha256 } from '../api/code-command-snapshot.ts';
import {
  ManagementClient,
  ManagementReadError,
  managementWriteBlocked,
  same,
  type Session,
} from './api.ts';
import {
  commandScope,
  freezeIntent,
  freezeControl,
  recoverIntent,
  scopeParts,
  type ManagementControl,
  type PendingCommand,
} from './command-intent.ts';
import { ManagementCommandStore, ManagementStorageError } from './command-store.ts';
import { uuid, type controlResult, type operationDetail } from './model.ts';

export type PreparationKeys = Readonly<{ command_key: string; submit_intent_id: string }>;
type Result = ReturnType<typeof operationDetail>;
const terminal = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED']);

export function newPreparationKeys(): PreparationKeys {
  return { command_key: crypto.randomUUID(), submit_intent_id: crypto.randomUUID() };
}

export class ManagementCommands {
  readonly store: ManagementCommandStore;

  constructor(
    readonly client: ManagementClient,
    readonly session: Session,
  ) {
    this.store = new ManagementCommandStore(session);
  }

  private requireSession(current: Session | null) {
    if (
      !current ||
      !same(current.config, this.session.config) ||
      current.principal !== this.session.principal ||
      current.role !== this.session.role
    ) {
      throw new ManagementReadError('STALE', '管理账号或登记范围已变化，请重新进入后核对。');
    }
    return current;
  }

  private async checkCommand(command: PendingCommand) {
    this.requireSession(this.client.current());
    if (
      command.actor !== this.session.principal ||
      JSON.stringify(scopeParts(command.scope)) !==
        JSON.stringify(scopeParts(commandScope(this.session))) ||
      (await commandSha256(command.body)) !== command.intent_sha256
    ) {
      throw new ManagementStorageError('CORRUPT');
    }
  }

  private requireWritableSession() {
    const current = this.client.current();
    if (current?.bindingChanged) {
      throw new ManagementReadError('STALE', '管理入口或登记代次已变化，请重新核对入口。');
    }
    const session = this.requireSession(current);
    if (session.phase === 'BLOCKED') throw managementWriteBlocked();
    return session;
  }

  async prepare(input: unknown, keys: PreparationKeys) {
    this.requireWritableSession();
    const frozen = await freezeIntent(input);
    this.requireWritableSession();
    return this.store.persist({ ...keys, body: frozen.body, intent_sha256: frozen.digest });
  }

  async prepareControl(operationId: string, revision: number, action: ManagementControl) {
    const session = this.requireWritableSession();
    if (session.role === 'VIEWER') {
      throw new ManagementReadError('MANAGEMENT_ACCESS_DENIED', '当前账号不能控制原操作。');
    }
    if (!navigator.locks) throw new ManagementStorageError('UNAVAILABLE');
    const id = uuid(operationId);
    const frozen = await freezeControl(action, revision);
    return navigator.locks.request('walle-control:' + this.store.key(id), async () => {
      this.requireWritableSession();
      const pending = (await this.store.list()).find(
        (command) => command.kind === 'CONTROL' && command.operation_id === id,
      );
      return (
        pending ??
        this.store.persist(
          { ...newPreparationKeys(), body: frozen.body, intent_sha256: frozen.digest },
          id,
        )
      );
    });
  }

  private async confirmControl(command: PendingCommand, outcome: ReturnType<typeof controlResult>) {
    const { operation, receipt } = outcome;
    if (
      command.kind !== 'CONTROL' ||
      ![
        'RELEASE',
        'ROLLBACK_CODE',
        'RECONFIGURE',
        'START',
        'STOP',
        'ARCHIVE',
        'BACKUP',
        'RESTORE',
      ].includes(operation.original.action) ||
      operation.original.id !== command.operation_id ||
      receipt.command !== command.action ||
      receipt.operationRevision < command.target_version ||
      receipt.operationRevision > command.target_version + 1
    )
      throw new ManagementReadError('STALE', '返回的控制回执无法与本机原核对匹配。');
    await this.store.finish(command, operation);
    if (terminal.has(operation.original.state)) {
      const release = await this.store.read(operation.original.key);
      if (release?.kind === 'ACTION') await this.confirm(release, operation);
    }
    return operation;
  }

  private async confirm(command: PendingCommand, result: Result) {
    const { original } = result;
    const intent = recoverIntent(command.body);
    if (
      original.key !== command.command_key ||
      original.intent !== command.intent_sha256 ||
      original.by !== command.actor ||
      original.action !== command.action ||
      (intent.environment_id !== undefined && original.environment !== intent.environment_id)
    ) {
      throw new ManagementReadError('STALE', '返回的回执无法与本机原请求匹配。');
    }
    if (terminal.has(original.state)) {
      await this.store.finish(command, result);
    }
    return result;
  }

  async lookup(command: PendingCommand, signal: AbortSignal): Promise<Result | null> {
    await this.checkCommand(command);
    try {
      if (command.kind === 'CONTROL')
        return this.confirmControl(
          command,
          await this.client.originalControl(command.operation_id, command.command_key, signal),
        );
      return this.confirm(command, await this.client.original(command.command_key, signal));
    } catch (error) {
      if (error instanceof ManagementReadError && error.code === 'MANAGEMENT_RECORD_NOT_FOUND')
        return null;
      throw error;
    }
  }

  async frozenRequest(command: PendingCommand) {
    await this.checkCommand(command);
    const original: unknown = JSON.parse(command.body);
    return (
      JSON.stringify({
        format_version: 1,
        host_id: this.session.config.host,
        input:
          command.kind === 'ACTION'
            ? original
            : { ...(original as object), action: 'CONTROL', operation_id: command.operation_id },
        manager_id: command.scope.manager_id,
        principal: command.actor,
        registry_generation: command.scope.registry_generation,
        request_key: command.command_key,
      }) + '\n'
    );
  }

  private async dispatchOwned(command: PendingCommand, signal: AbortSignal) {
    const deadline = AbortSignal.any([signal, AbortSignal.timeout(20000)]);
    const session = this.requireSession(await this.client.check(deadline));
    if (session.phase === 'BLOCKED') throw managementWriteBlocked();
    if (command.action === 'ATTACH' && session.phase !== 'READY') {
      throw new ManagementReadError('RECOVERING', '管理登记仍在核对，请先查询原请求。');
    }
    const current = await this.store.read(command.command_key);
    if (!current || current.state !== 'PREPARED') {
      const previous = await this.lookup(command, deadline);
      if (previous) return previous;
    }
    if (!current || current.intent_sha256 !== command.intent_sha256) {
      throw new ManagementStorageError('CONFLICT');
    }
    await this.checkCommand(current);
    deadline.throwIfAborted();
    const claimed = await this.store.claim(current, crypto.randomUUID());
    try {
      const input = { key: claimed.command_key, body: claimed.body };
      if (claimed.kind === 'CONTROL')
        return await this.confirmControl(
          claimed,
          await this.client.submitControl(session, claimed.operation_id, input, deadline),
        );
      return await this.confirm(
        claimed,
        await this.client.submitOperation(session, input, deadline),
      );
    } catch (error) {
      // The network may already have delivered it. Keep the same key and frozen body.
      await this.store.uncertain(claimed).catch(() => undefined);
      throw error;
    }
  }

  async dispatch(command: PendingCommand, signal: AbortSignal) {
    await this.checkCommand(command);
    if (!navigator.locks) throw new ManagementStorageError('UNAVAILABLE');
    const outcome = await navigator.locks.request(
      'walle-management:' + this.store.key(command.command_key),
      { ifAvailable: true },
      async (lock) => {
        if (!lock) return { error: new ManagementStorageError('IN_USE') } as const;
        try {
          return { result: await this.dispatchOwned(command, signal) } as const;
        } catch (error) {
          return { error } as const;
        }
      },
    );
    if ('error' in outcome) throw outcome.error;
    return outcome.result;
  }
}
