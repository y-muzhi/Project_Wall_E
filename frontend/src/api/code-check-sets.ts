/** Native CheckSetVersion input/results, never authority to execute checks. */
import { ApiUnknown, exact, positiveInteger, snapshotObject } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  distinct,
  nonempty,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { codeErrorDetails } from './code-errors.ts';
import { prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import {
  configurationCreateErrors,
  configurationIdentityReadErrors,
} from './code-configuration-identities.ts';
import { readPage } from './pagination.ts';

const MAX = 8 * 1024 * 1024;
const stage = choices(['BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'] as const);
const owner = choices(['CODING', 'TESTING'] as const);
function reference(value: unknown) {
  const result = nonempty(value);
  require(result.trim().length > 0 && !/[\u0000-\u001f\u007f]/u.test(result));
  return result;
}
const references = (minimum = 0) => checked(array(reference, MAX, minimum), distinct);
const stages = checked(array(stage, 4, 1), distinct);
function label(value: unknown) {
  const result = nonempty(value);
  require(result.trim().length > 0 && !result.includes('\0'));
  return result;
}
const target = shape({
  application_mode: choices(['REAL_CANDIDATE', 'CONTROLLED_STUB'] as const),
  external_dependency_mode: choices(['NONE', 'OFFLINE_STUB'] as const),
  command_ids: references(1),
  fixture_ref: nullable(reference),
});
const check = checked(
  shape({
    check_id: reference,
    name: label,
    stages,
    required: bool,
    check_kind: choices(['PROJECT_COMMAND', 'CONTROLLED_ASSERTION'] as const),
    command_id: nullable(reference),
    runner_ref: reference,
    case_pack_ref: nullable(reference),
    expected_exit_codes: nullable(array(count, 1)),
    environment_refs: references(),
    protected_input_refs: references(),
    target: nullable(target),
    timeout_seconds: positiveInteger,
    evidence_rule: shape({
      kind: choices(['PROCESS_EXIT', 'CONTENT_INTEGRITY', 'CONTROLLED_CASES'] as const),
    }),
  }),
  (row) => {
    if (row.check_kind === 'PROJECT_COMMAND') {
      require(
        row.command_id !== null &&
          row.expected_exit_codes?.length === 1 &&
          row.expected_exit_codes[0] === 0,
      );
      require(
        row.case_pack_ref === null &&
          row.target === null &&
          row.evidence_rule.kind === 'PROCESS_EXIT',
      );
    } else {
      require(row.command_id === null && row.expected_exit_codes === null);
      if (row.evidence_rule.kind === 'CONTENT_INTEGRITY') {
        require(row.case_pack_ref === null && row.target === null);
      } else {
        require(
          row.evidence_rule.kind === 'CONTROLLED_CASES' &&
            row.case_pack_ref !== null &&
            row.target !== null,
        );
      }
    }
  },
);
const basis = shape({
  document_id: positiveInteger,
  revision_id: positiveInteger,
  quote(value: unknown) {
    const result = nonempty(value);
    require(result.trim().length > 0 && !result.includes('\0'));
    return result;
  },
});
const coverage = checked(
  shape({
    coverage_id: reference,
    basis_refs: array(basis, MAX, 1),
    stages,
    mode: choices(['AUTO', 'MANUAL', 'NOT_APPLICABLE'] as const),
    check_ids: references(),
    explanation(value: unknown) {
      const result = text(value);
      require(!result.includes('\0'));
      return result;
    },
  }),
  (row) => {
    distinct(
      row.basis_refs.map((ref) => JSON.stringify([ref.document_id, ref.revision_id, ref.quote])),
    );
    if (row.mode === 'AUTO') require(row.check_ids.length > 0);
    else require(row.check_ids.length === 0 && row.explanation.trim().length > 0);
  },
);
const contentFields = {
  protocol_version: choices(['CHECK20-CONTROL-1'] as const),
  items: array(check, MAX),
  coverage_plan: array(coverage, MAX),
};
const contentShape = shape(contentFields);
function contentRules(content: ReturnType<typeof contentShape>, module: 'CODING' | 'TESTING') {
  require(
    new TextEncoder().encode(
      JSON.stringify({
        protocol_version: content.protocol_version,
        items: content.items,
        coverage_plan: content.coverage_plan,
      }),
    ).byteLength <= MAX,
  );
  distinct(content.items.map((item) => item.check_id));
  distinct(content.coverage_plan.map((row) => row.coverage_id));
  if (module === 'CODING') {
    require(!content.items.some((item) => item.stages.includes('ACCEPTANCE')));
    require(!content.coverage_plan.some((row) => row.stages.includes('ACCEPTANCE')));
  }
  const checks = new Map(content.items.map((item) => [item.check_id, item]));
  for (const row of content.coverage_plan) {
    if (row.mode === 'AUTO')
      for (const id of row.check_ids)
        require(checks.get(id)?.evidence_rule.kind === 'CONTROLLED_CASES');
  }
}
export const checkSetContent = checked(contentShape, (value) => contentRules(value, 'CODING'));
export type CheckSetContent = ReturnType<typeof checkSetContent>;
export const checkSetVersion = checked(
  shape({
    id: positiveInteger,
    check_set_id: positiveInteger,
    version: positiveInteger,
    owner_module: owner,
    ...contentFields,
    created_at: time,
    ready: bool,
    unresolved_capability_codes(value: unknown) {
      const codes = array(reference, 16)(value);
      distinct(codes);
      if (codes.length > 0) codeErrorDetails('CONFIG_NOT_READY', { capability_codes: [...codes] });
      return codes;
    },
  }),
  (row) => {
    contentRules(row, row.owner_module);
    require(row.ready === (row.unresolved_capability_codes.length === 0));
  },
);
export type CheckSetVersion = ReturnType<typeof checkSetVersion>;

function originalCheckSet(original: CommandIdentity) {
  const match = /^\/api\/v1\/code-check-sets\/([1-9][0-9]*)\/versions$/.exec(original.path);
  require(
    original.owner_module === 'CODING' &&
      original.method === 'POST' &&
      original.decoder_kind === 'APP-CODE-CMD-C08' &&
      match !== null,
  );
  return positiveInteger(Number(match[1]));
}
type CreatedVersion = Readonly<{ resource_kind: 'CHECK_SET_VERSION'; resource_id: number }>;
export const CHECK_SET_VERSION_BINDING: CodeCommandBinding<CreatedVersion> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C08',
  success_status: Object.freeze([201] as const),
  errors: configurationCreateErrors,
  validate_input(value: JsonObject, original: CommandIdentity) {
    originalCheckSet(original);
    checkSetContent(value);
  },
  decode(value: unknown, original: CommandIdentity, input: JsonObject) {
    originalCheckSet(original);
    checkSetContent(input);
    const row = exact(value, ['resource_kind', 'resource_id']);
    require(row.resource_kind === 'CHECK_SET_VERSION');
    return Object.freeze({
      resource_kind: 'CHECK_SET_VERSION' as const,
      resource_id: positiveInteger(row.resource_id),
    });
  },
});
export function prepareCheckSetVersion(
  client: ApiClient,
  checkSetId: number,
  content: CheckSetContent,
  origin: string,
) {
  positiveInteger(checkSetId);
  checkSetContent(content);
  return prepareCodeCommand(
    client,
    '/api/v1/code-check-sets/' + checkSetId + '/versions',
    snapshotObject(content),
    CHECK_SET_VERSION_BINDING,
    origin,
  );
}
export async function readCheckSetVersion(client: ApiClient, id: number, signal?: AbortSignal) {
  positiveInteger(id);
  const result = await client.read(
    '/api/v1/code-check-set-versions/' + id,
    checkSetVersion,
    [],
    signal,
    configurationIdentityReadErrors,
  );
  if (result.data.id !== id || result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
export async function readCheckSetVersions(
  client: ApiClient,
  checkSetId: number,
  page = 1,
  signal?: AbortSignal,
) {
  positiveInteger(checkSetId);
  const result = await readPage(
    client,
    '/api/v1/code-check-sets/' + checkSetId + '/versions',
    checkSetVersion,
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    configurationIdentityReadErrors,
  );
  let previous = Number.POSITIVE_INFINITY;
  for (const row of result.data.items) {
    if (row.check_set_id !== checkSetId || row.version >= previous) throw new ApiUnknown(false);
    previous = row.version;
  }
  return result;
}
