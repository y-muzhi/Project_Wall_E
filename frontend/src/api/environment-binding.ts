import { exact, positiveInteger } from './wire-shape.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const DNS_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const VALIDATION_PORT = ':9443';
const ENTRY_LIMIT = 16 * 1024;
const ENTRY_TIMEOUT = 30_000;

export const ENVIRONMENT_SCOPE_FIELDS = [
  'binding_protocol',
  'origin',
  'environment_id',
  'data_generation',
] as const;
export type EnvironmentScope = Readonly<{
  binding_protocol: 1;
  origin: string;
  environment_id: string;
  data_generation: string;
}>;
export const environmentPurposeNames = {
  DEVELOPMENT: '开发环境',
  INTEGRATION: '集成环境',
  CANDIDATE: '候选验证环境',
} as const;

type RecoveryObservation = Readonly<{
  controlRevision: number;
  maintenanceId: string;
  deploymentId: string;
  verificationRef: string;
  observedAt: string;
}>;

export type BoundEnvironment = Readonly<{
  scope: EnvironmentScope;
  displayName: string;
  purpose: keyof typeof environmentPurposeNames;
  configurationSha256: string;
  runId: string;
  userPermission: 'READ_ONLY' | 'DEVELOP';
  documentAiReady: boolean;
  recovery?: RecoveryObservation;
  onRunChanged?: (runId: string) => void;
}>;

const CAPABILITIES = [
  'DOCUMENT_READ',
  'DOCUMENT_WRITE',
  'DOCUMENT_AI',
  'TEST_PLAN_AI',
  'INTERNAL_EXECUTION',
  'INDEPENDENT_CHECK',
] as const;
const CONFIG_FIELDS = [
  'format_version',
  'binding_protocol',
  'environment_id',
  'data_generation',
  'display_name',
  'purpose',
  'public_origin',
  'api_base',
  'configuration_sha256',
  'management_url',
] as const;
const HANDSHAKE_FIELDS = [
  'binding_protocol',
  'environment_id',
  'data_generation',
  'purpose',
  'run_id',
  'phase',
  'observed_at',
  'configuration_sha256',
  'access',
  'maintenance',
  'capabilities',
] as const;

function uuid(value: unknown): string {
  if (typeof value !== 'string' || !UUID.test(value)) throw new TypeError('Invalid UUID');
  return value;
}
function sha256(value: unknown): string {
  if (typeof value !== 'string' || !SHA256.test(value)) throw new TypeError('Invalid digest');
  return value;
}
function utc(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) ||
    new Date(value).toISOString() !== value
  )
    throw new TypeError('Invalid observation time');
  return value;
}

/** JSON syntax uses the native parser; the token pass rejects overwritten members. */
export function parseEnvironmentJson(text: string): unknown {
  const parsed: unknown = JSON.parse(text);
  const tokens = [...text.matchAll(/"(?:[^"\\]|\\.)*"|[{}\[\]:]/g)].map((match) => match[0]);
  const containers: (Set<string> | null)[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === '{') containers.push(new Set());
    else if (token === '[') containers.push(null);
    else if (token === '}' || token === ']') containers.pop();
    else if (token?.startsWith('"') && tokens[index + 1] === ':') {
      const owner = containers.at(-1);
      const field = JSON.parse(token) as string;
      if (!owner || owner.has(field)) throw new TypeError('Repeated environment field');
      owner.add(field);
    }
  }
  return parsed;
}

function matchesBusinessOrigin(origin: string, environmentId: string): boolean {
  const prefix = `https://e-${environmentId}.`;
  if (!origin.startsWith(prefix)) return false;
  const authority = origin.slice(prefix.length);
  const domain = authority.endsWith(VALIDATION_PORT)
    ? authority.slice(0, -VALIDATION_PORT.length)
    : authority;
  const labels = domain.split('.');
  return (
    domain.length <= 214 &&
    labels.length >= 2 &&
    labels.every((label) => DNS_LABEL.test(label)) &&
    /[a-z]/.test(labels.at(-1) ?? '')
  );
}

function publicRecord(value: unknown, origin: string) {
  const record = exact(value, CONFIG_FIELDS);
  if (record.format_version !== 1 || record.binding_protocol !== 1)
    throw new EnvironmentEntryError('PROTOCOL');
  const environment_id = uuid(record.environment_id);
  const data_generation = uuid(record.data_generation);
  if (record.public_origin !== origin || !matchesBusinessOrigin(origin, environment_id))
    throw new EnvironmentEntryError('SCOPE_CHANGED');
  if (
    record.api_base !== '/api/v1' ||
    record.management_url !== null ||
    (record.purpose !== 'DEVELOPMENT' &&
      record.purpose !== 'INTEGRATION' &&
      record.purpose !== 'CANDIDATE') ||
    typeof record.display_name !== 'string' ||
    !record.display_name.trim() ||
    [...record.display_name].length > 80 ||
    /[\p{Cc}\p{Cs}]/u.test(record.display_name)
  )
    throw new TypeError('Public environment description differs');
  const scope: EnvironmentScope = Object.freeze({
    binding_protocol: 1,
    origin,
    environment_id,
    data_generation,
  });
  return {
    scope,
    displayName: record.display_name,
    purpose: record.purpose,
    configurationSha256: sha256(record.configuration_sha256),
  } as const;
}

function readMaintenance(value: unknown, scope: EnvironmentScope): RecoveryObservation | undefined {
  const maintenance = exact(value, [
    'contract_version',
    'admission',
    'maintenance_id',
    'stage',
    'control_revision',
    'reason_code',
    'allowed_drain_actions',
    'recovery_read',
  ]);
  const recovery = exact(maintenance.recovery_read, [
    'status',
    'observed_at',
    'deployment_id',
    'data_generation',
    'control_revision',
    'verification_ref',
    'verified_scopes',
    'blockers',
  ]);
  const revision = positiveInteger(maintenance.control_revision);
  if (
    maintenance.contract_version !== 1 ||
    !Array.isArray(maintenance.allowed_drain_actions) ||
    maintenance.allowed_drain_actions.length !== 0 ||
    recovery.data_generation !== scope.data_generation ||
    recovery.control_revision !== revision ||
    !Array.isArray(recovery.verified_scopes) ||
    !Array.isArray(recovery.blockers)
  )
    throw new EnvironmentEntryError('NOT_READY');
  const deploymentId = uuid(recovery.deployment_id);
  const observedAt = utc(recovery.observed_at);
  if (maintenance.admission === 'OPEN') {
    if (
      maintenance.maintenance_id !== null ||
      maintenance.stage !== null ||
      maintenance.reason_code !== null ||
      recovery.status !== 'NOT_APPLICABLE' ||
      recovery.verification_ref !== null ||
      recovery.verified_scopes.length !== 0 ||
      recovery.blockers.length !== 0
    )
      throw new EnvironmentEntryError('NOT_READY');
    return undefined;
  }
  if (
    maintenance.admission !== 'CLOSED' ||
    maintenance.stage !== 'BLOCKED' ||
    maintenance.reason_code !== 'RECOVERY_RECONCILIATION_REQUIRED' ||
    recovery.status !== 'AVAILABLE' ||
    recovery.verified_scopes.length !== 2 ||
    recovery.verified_scopes[0] !== 'DOCUMENT_CONTENT' ||
    recovery.verified_scopes[1] !== 'DOCUMENT_HISTORY' ||
    recovery.blockers.length !== 1 ||
    recovery.blockers[0] !== maintenance.reason_code
  )
    throw new EnvironmentEntryError('NOT_READY');
  return Object.freeze({
    controlRevision: revision,
    maintenanceId: uuid(maintenance.maintenance_id),
    deploymentId,
    verificationRef: sha256(recovery.verification_ref),
    observedAt,
  });
}

function readCapabilities(value: unknown, recovery: boolean, allowsDocumentAi: boolean) {
  if (!Array.isArray(value) || value.length !== CAPABILITIES.length)
    throw new TypeError('Unexpected capability list');
  let documentAiReady = false;
  for (const [index, expected] of CAPABILITIES.entries()) {
    const row = exact(value[index], ['code', 'state', 'reason_code']);
    const documentAi = expected === 'DOCUMENT_AI' && allowsDocumentAi && row.state === 'READY';
    const ready =
      expected === 'DOCUMENT_READ' || (expected === 'DOCUMENT_WRITE' && !recovery) || documentAi;
    const reason = ready
      ? null
      : expected === 'DOCUMENT_WRITE'
        ? 'RECOVERY_READ_ONLY'
        : 'CONFIG_DISABLED';
    if (
      row.code !== expected ||
      row.state !== (ready ? 'READY' : 'DISABLED') ||
      row.reason_code !== reason
    )
      throw new EnvironmentEntryError('NOT_READY');
    if (documentAi) documentAiReady = true;
  }
  return documentAiReady;
}

function responseIdentity(headers: Headers) {
  return {
    environment: uuid(headers.get('X-WALL-E-Environment-ID')),
    generation: uuid(headers.get('X-WALL-E-Data-Generation')),
    run: uuid(headers.get('X-WALL-E-Run-ID')),
  };
}

function handshakeRecord(
  value: unknown,
  response: Response,
  config: ReturnType<typeof publicRecord>,
) {
  const envelope = exact(value, ['success', 'data', 'error', 'meta']);
  if (envelope.success !== true || envelope.error !== null)
    throw new EnvironmentEntryError('NOT_READY');
  uuid(exact(envelope.meta, ['request_id']).request_id);
  const record = exact(envelope.data, HANDSHAKE_FIELDS);
  const actual = responseIdentity(response.headers);
  const runId = uuid(record.run_id);
  if (record.binding_protocol !== 1) throw new EnvironmentEntryError('PROTOCOL');
  if (
    config.scope.environment_id !== uuid(record.environment_id) ||
    config.scope.data_generation !== uuid(record.data_generation) ||
    config.scope.environment_id !== actual.environment ||
    config.scope.data_generation !== actual.generation ||
    runId !== actual.run ||
    record.purpose !== config.purpose
  )
    throw new EnvironmentEntryError('SCOPE_CHANGED');
  const configurationMatches = sha256(record.configuration_sha256) === config.configurationSha256;
  if (record.phase !== 'READY' || !configurationMatches)
    throw new EnvironmentEntryError('NOT_READY');
  utc(record.observed_at);
  const recovery = readMaintenance(record.maintenance, config.scope);
  const access = exact(record.access, ['client_kind', 'permission']);
  if (
    access.client_kind !== 'WEB' ||
    (access.permission !== 'READ_ONLY' && access.permission !== 'DEVELOP') ||
    (recovery !== undefined && access.permission !== 'READ_ONLY')
  )
    throw new EnvironmentEntryError('PERMISSION');
  const documentAiReady = readCapabilities(
    record.capabilities,
    recovery !== undefined,
    recovery === undefined && config.purpose === 'DEVELOPMENT' && access.permission === 'DEVELOP',
  );
  const result = { ...config, runId, userPermission: access.permission, documentAiReady } as const;
  return Object.freeze(recovery === undefined ? result : { ...result, recovery });
}

export class EnvironmentEntryError extends Error {
  readonly code:
    'ACCESS' | 'PERMISSION' | 'SCOPE_CHANGED' | 'PROTOCOL' | 'NOT_READY' | 'UNREACHABLE';
  constructor(code: EnvironmentEntryError['code']) {
    super(code);
    this.code = code;
  }
}

async function readBody(response: Response): Promise<unknown> {
  if (
    response.headers.get('Content-Type')?.split(';')[0]?.toLowerCase().trim() !==
      'application/json' ||
    !response.headers
      .get('Cache-Control')
      ?.split(',')
      .some((value) => value.trim().toLowerCase() === 'no-store')
  )
    throw new TypeError('Invalid environment response headers');
  const reader = response.body?.getReader();
  if (reader === undefined) throw new TypeError('Empty environment response');
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  let text = '';
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > ENTRY_LIMIT) throw new TypeError('Environment response too large');
      text += decoder.decode(part.value, { stream: true });
    }
    return parseEnvironmentJson(text + decoder.decode());
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

async function readEntry(send: typeof fetch, path: string, signal?: AbortSignal) {
  if (signal?.aborted) throw new EnvironmentEntryError('UNREACHABLE');
  const controller = new AbortController();
  let abort!: () => void;
  const interrupted = new Promise<never>((_resolve, reject) => {
    abort = () => {
      controller.abort();
      reject(new EnvironmentEntryError('UNREACHABLE'));
    };
  });
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, ENTRY_TIMEOUT);
  try {
    const exchange = (async () => {
      const response = await send(path, {
        signal: controller.signal,
        headers: { Accept: 'application/json', 'X-WALL-E-Client': 'web-v1' },
        credentials: 'same-origin',
        cache: 'no-store',
        redirect: 'error',
      });
      if (controller.signal.aborted) {
        void response.body?.cancel().catch(() => undefined);
        throw new EnvironmentEntryError('UNREACHABLE');
      }
      if (response.status !== 200) {
        void response.body?.cancel().catch(() => undefined);
        if (response.status === 401) throw new EnvironmentEntryError('ACCESS');
        if (response.status === 403) throw new EnvironmentEntryError('PERMISSION');
        throw new EnvironmentEntryError('NOT_READY');
      }
      return { response, raw: await readBody(response) };
    })();
    return await Promise.race([exchange, interrupted]);
  } catch (error) {
    if (error instanceof EnvironmentEntryError) throw error;
    throw new EnvironmentEntryError('UNREACHABLE');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export type EnvironmentEntryStage = 'CONFIG_LOADING' | 'HANDSHAKING';

export async function loadBoundEnvironment(
  origin: string,
  signal?: AbortSignal,
  send: typeof fetch = globalThis.fetch.bind(globalThis),
  observe?: (stage: EnvironmentEntryStage) => void,
): Promise<BoundEnvironment> {
  observe?.('CONFIG_LOADING');
  const expected = await readEntry(send, '/.well-known/walle-environment.json', signal);
  const config = publicRecord(expected.raw, origin);
  observe?.('HANDSHAKING');
  const handshake = await readEntry(send, '/api/v1/environment', signal);
  return handshakeRecord(handshake.raw, handshake.response, config);
}

export function environmentHeaders(scope: EnvironmentScope): Record<string, string> {
  return {
    'X-WALL-E-Environment-ID': scope.environment_id,
    'X-WALL-E-Data-Generation': scope.data_generation,
    'X-WALL-E-Binding-Protocol': String(scope.binding_protocol),
    'X-WALL-E-Client': 'web-v1',
  };
}

export function compareResponseScope(headers: Headers, scope: EnvironmentScope): string {
  const actual = responseIdentity(headers);
  if (actual.environment !== scope.environment_id || actual.generation !== scope.data_generation)
    throw new EnvironmentEntryError('SCOPE_CHANGED');
  return actual.run;
}

export function decodeEnvironmentScope(value: unknown): EnvironmentScope {
  const row = exact(value, ENVIRONMENT_SCOPE_FIELDS);
  if (
    row.binding_protocol !== 1 ||
    typeof row.origin !== 'string' ||
    !row.origin.startsWith('https://') ||
    new URL(row.origin).origin !== row.origin
  )
    throw new TypeError('Invalid environment scope');
  return Object.freeze({
    binding_protocol: 1,
    origin: row.origin,
    environment_id: uuid(row.environment_id),
    data_generation: uuid(row.data_generation),
  });
}

export function sameEnvironmentScope(value: unknown, scope: EnvironmentScope): boolean {
  const record = exact(value, ENVIRONMENT_SCOPE_FIELDS);
  return ENVIRONMENT_SCOPE_FIELDS.every((key) => record[key] === scope[key]);
}
