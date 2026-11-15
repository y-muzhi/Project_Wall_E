/** Nonsecret immutable options for the independent profile form. */
import type { ApiClient } from './client.ts';
import { commandDefinition } from './code-execution-profiles.ts';
import { configurationIdentityReadErrors } from './code-configuration-identities.ts';
import { array, bool, checked, choices, distinct, nonempty, require, shape } from './decoding.ts';
import type { Decoder } from './decoding.ts';
import { readPage } from './pagination.ts';

const types = {
  RUNNER: shape({
    runner_ref: nonempty,
    protocol_version: nonempty,
    capabilities: array(nonempty, 256),
    protected_input_refs: array(nonempty, 256),
  }),
  RUNTIME: shape({
    runtime_ref: nonempty,
    runtime_kind: choices(['PYTHON', 'NODE', 'PACKAGE_MANAGER'] as const),
    version: nonempty,
  }),
  COMMAND: commandDefinition,
  CAPABILITY: shape({ capability_code: nonempty, evidence_ref: nonempty }),
};
type Kind = keyof typeof types;
type ProfileOption<T> = { option_id: string; label: string; ready: boolean; value: T };
export type TestingProfileChoices = {
  [K in Kind]: readonly ProfileOption<ReturnType<(typeof types)[K]>>[];
};

async function readOptions<T>(
  client: ApiClient,
  kind: Kind,
  value: Decoder<T>,
  signal?: AbortSignal,
) {
  const decode = checked(
    shape({
      option_id: nonempty,
      kind: choices([kind]),
      label: nonempty,
      ready: bool,
      unresolved_capability_codes: checked(array(nonempty, 32), distinct),
      value,
    }),
    (row) => require(row.ready === (row.unresolved_capability_codes.length === 0)),
  );
  const items: ReturnType<typeof decode>[] = [];
  let page = 1;
  for (;;) {
    const response = await readPage(
      client,
      '/api/v1/code-configuration-options',
      decode,
      (row) => row.option_id,
      [
        ['kind', kind],
        ['page', String(page)],
      ],
      page,
      signal,
      configurationIdentityReadErrors,
    );
    items.push(...response.data.items);
    const pagination = response.meta.pagination;
    require(pagination !== undefined && 'total_pages' in pagination);
    if (page >= pagination.total_pages) break;
    // Configuration requests themselves bound each selection to 256.
    if (page === 13) throw new TypeError('Too many registered options for the profile editor');
    page += 1;
  }
  distinct(items.map((item) => item.option_id));
  return items;
}

export async function readTestingProfileChoices(
  client: ApiClient,
  signal?: AbortSignal,
): Promise<TestingProfileChoices> {
  const [RUNNER, RUNTIME, commands, CAPABILITY] = await Promise.all([
    readOptions(client, 'RUNNER', types.RUNNER, signal),
    readOptions(client, 'RUNTIME', types.RUNTIME, signal),
    readOptions(client, 'COMMAND', types.COMMAND, signal),
    readOptions(client, 'CAPABILITY', types.CAPABILITY, signal),
  ]);
  return {
    RUNNER,
    RUNTIME,
    COMMAND: commands.filter((entry) => entry.value.purpose !== 'EXECUTION'),
    CAPABILITY,
  };
}
