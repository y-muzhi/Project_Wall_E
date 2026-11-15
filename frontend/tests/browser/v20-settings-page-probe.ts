import {ApiClient} from '../../src/api/client.ts';
import {prepareConfigurationIdentity} from '../../src/api/code-configuration-identities.ts';
import {prepareRegisterRepository} from '../../src/api/code-repository-commands.ts';
import {CommandRecoveryStore} from '../../src/code-tasks/command-recovery-store.ts';

export async function seedSettingsRecovery(): Promise<void> {
  const client = new ApiClient(() => { throw new Error('Seed cannot send HTTP'); });
  const store = new CommandRecoveryStore();
  try {
    const commands = [
      await prepareConfigurationIdentity(client, 'EXECUTION_PROFILE', 'NOT_VISIBLE_BODY', location.origin),
      await prepareRegisterRepository(client, {name:'NOT_VISIBLE_BODY',root_path:'C:\\isolated-repository'}, location.origin),
    ];
    for (const command of commands) {
      const reserved = await store.reserve(command.frozen);
      if (reserved.kind !== 'PREPARED') throw new Error('New isolated intent required');
      const dispatched = await store.dispatch(reserved.record, command.frozen, crypto.randomUUID(), false);
      if (dispatched === null) throw new Error('Durable test dispatch missing');
      await store.markUnknown(dispatched);
    }
  } finally { store.close(); }
}
