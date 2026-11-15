import { exact } from '../api/client.ts';
import { authorizationScope } from '../api/code-authorizations.ts';
import type { AuthorizationScope } from '../api/code-authorizations.ts';
import type { ExecutionProfileVersion } from '../api/code-execution-profiles.ts';
import { moneyMicro } from '../api/code-values.ts';
import { safeId } from './list-model.ts';

type Material = Readonly<{ document_id: number; revision_id: number }>;
export type CreateTaskDraft = Readonly<{
  schema_version: 1;
  requirement_id: number;
  document_id: number;
  design_revision_id: number | null;
  material_refs: readonly Material[];
  repository_id: number | null;
  observation_id: number | null;
  base_snapshot_id: number | null;
  execution_profile_id: number | null;
  execution_profile_version_id: number | null;
  authorization_id: number | null;
  target_branch: string | null;
  commit_oid: string;
  budget_text: string;
  original_key: string | null;
  original_path: string | null;
}>;

export function freshDraft(requirementId: number, documentId: number): CreateTaskDraft {
  return {
    schema_version: 1,
    requirement_id: requirementId,
    document_id: documentId,
    design_revision_id: null,
    material_refs: [],
    repository_id: null,
    observation_id: null,
    base_snapshot_id: null,
    execution_profile_id: null,
    execution_profile_version_id: null,
    authorization_id: null,
    target_branch: null,
    commit_oid: '',
    budget_text: '',
    original_key: null,
    original_path: null,
  };
}

export const createTaskPath = (documentId: number) =>
  '/api/v1/documents/' + documentId + '/code-tasks';

function draftId(value: unknown): number | null {
  if (value === null || safeId(value)) return value;
  throw TypeError('Invalid draft ID');
}

export function restoreCreateDraft(raw: string | null, requirementId: number, documentId: number) {
  const empty = freshDraft(requirementId, documentId);
  if (raw === null) return empty;
  const row = exact(JSON.parse(raw), Object.keys(empty));
  if (
    row.schema_version !== 1 ||
    row.requirement_id !== requirementId ||
    row.document_id !== documentId ||
    !Array.isArray(row.material_refs) ||
    typeof row.commit_oid !== 'string' ||
    typeof row.budget_text !== 'string' ||
    (row.target_branch !== null && typeof row.target_branch !== 'string')
  )
    throw TypeError('Invalid draft scope');
  const materials = row.material_refs.map((item: unknown) => {
    const material = exact(item, ['document_id', 'revision_id']);
    if (
      !safeId(material.document_id) ||
      !safeId(material.revision_id) ||
      material.document_id === documentId
    )
      throw TypeError('Invalid draft material');
    return { document_id: material.document_id, revision_id: material.revision_id };
  });
  if (new Set(materials.map((item) => item.document_id)).size !== materials.length)
    throw TypeError('Duplicated draft material');
  const repository = draftId(row.repository_id);
  const paths = [createTaskPath(documentId), '/api/v1/code-authorizations'];
  if (repository !== null) {
    paths.push('/api/v1/code-repositories/' + repository + '/snapshots');
    paths.push('/api/v1/code-repositories/' + repository + '/refresh');
  }
  if (
    (row.original_key === null) !== (row.original_path === null) ||
    (row.original_key !== null &&
      (typeof row.original_key !== 'string' ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
          row.original_key,
        ) ||
        typeof row.original_path !== 'string' ||
        !paths.includes(row.original_path)))
  )
    throw TypeError('Invalid draft original command');
  return {
    ...empty,
    design_revision_id: draftId(row.design_revision_id),
    material_refs: materials,
    repository_id: repository,
    observation_id: draftId(row.observation_id),
    base_snapshot_id: draftId(row.base_snapshot_id),
    execution_profile_id: draftId(row.execution_profile_id),
    execution_profile_version_id: draftId(row.execution_profile_version_id),
    authorization_id: draftId(row.authorization_id),
    target_branch: row.target_branch,
    commit_oid: row.commit_oid,
    budget_text: row.budget_text,
    original_key: row.original_key,
    original_path: typeof row.original_path === 'string' ? row.original_path : null,
  } satisfies CreateTaskDraft;
}

export function positiveBudget(text: string): boolean {
  try {
    return moneyMicro(text) > 0n;
  } catch {
    return false;
  }
}

export function proposedScope(
  profile: ExecutionProfileVersion,
  commands: readonly string[],
  models: readonly string[],
  allowDelivery: boolean,
): AuthorizationScope {
  return authorizationScope({
    read_roots: [],
    write_workspace_only: true,
    allowed_command_ids: commands,
    network_targets: [],
    model_profile_refs: models,
    allow_local_delivery: allowDelivery && profile.delivery !== null,
    limits: profile.limits,
  });
}
