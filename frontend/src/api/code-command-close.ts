/** Original-key close control; no new business command or UUID. */
import { ApiClient, exact, object, snapshotObject } from './client.ts';
import type { ApiSuccess } from './client.ts';
import { commandReceipt } from './code-command-receipts.ts';
import type { CommandReceipt, OriginalResultPolicy } from './code-command-receipts.ts';
import { verifiedCommandIdentity } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';

export type CommandCloseReceipt<T> = Readonly<{
  close_status: 'CLOSED' | 'ALREADY_RECEIVED';
  original_receipt: CommandReceipt<T>;
}>;
export async function prepareCloseOriginalCommand<T>(
  client: ApiClient,
  frozenIdentity: unknown,
  currentOrigin: string,
  nativePolicy: OriginalResultPolicy<T>,
): Promise<
  Readonly<{ submit: (signal?: AbortSignal) => Promise<ApiSuccess<CommandCloseReceipt<T>>> }>
> {
  // Body damage must not prevent closing a verifiable original identity.
  const source = object(frozenIdentity);
  const identity = snapshotObject(
    Object.fromEntries(
      ['origin', 'owner_module', 'method', 'path', 'key', 'decoder_kind', 'identity_sha256'].map(
        (field) => [field, source[field]],
      ),
    ),
  );
  const policy = Object.freeze({
    ...nativePolicy,
    success_status: Object.freeze([...nativePolicy.success_status]),
    errors: Object.freeze([...nativePolicy.errors]),
  });
  const original = await verifiedCommandIdentity(identity, currentOrigin);
  if (policy.decoder_kind !== original.decoder_kind || typeof policy.decode !== 'function')
    throw new TypeError('Original close decoder differs');
  const handle = client.restorePrepared(
    {
      method: 'POST',
      path: '/api/v1/command-intents/close',
      key: original.key,
      body: JSON.stringify({ method: original.method, path: original.path }),
    },
    {
      idempotent: true,
      success_status: 200,
      error_policy: codeErrorPolicy([
        'INVALID_INPUT',
        'NOT_FOUND',
        'AUTHORIZATION_NOT_APPLICABLE',
        'STORAGE_UNAVAILABLE',
        'INTERNAL_ERROR',
      ]),
    },
  );
  function decode(value: unknown): CommandCloseReceipt<T> {
    const row = exact(value, ['close_status', 'original_receipt']);
    const receipt = commandReceipt(row.original_receipt, original, policy);
    if (row.close_status === 'CLOSED') {
      if (receipt.lookup_status !== 'FOUND' || receipt.record_status !== 'CLOSED')
        throw new TypeError('Close control lacks the original closed record');
    } else if (row.close_status === 'ALREADY_RECEIVED') {
      if (!(
        (receipt.lookup_status === 'FOUND' &&
          (receipt.record_status === 'SUCCEEDED' || receipt.record_status === 'REJECTED')) ||
        ((receipt.lookup_status === 'IN_PROGRESS' || receipt.lookup_status === 'UNKNOWN') &&
          receipt.record_status === 'PROCESSING')
      ))
        throw new TypeError('Already received control lacks the original received record');
    } else throw new TypeError('Unknown close control status');
    return Object.freeze({ close_status: row.close_status, original_receipt: receipt });
  }
  return Object.freeze({ submit: (signal?: AbortSignal) => client.commit(handle, decode, signal) });
}
