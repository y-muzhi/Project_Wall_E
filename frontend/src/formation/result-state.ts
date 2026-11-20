import type { JsonObject } from '../api/client.ts';
import { stableJson } from '../api/client.ts';
import type { FormationStepDetail } from '../api/formation-values.ts';

export type ResultDisposition = Readonly<{
  result_ref: string;
  status: 'LANDED' | 'ANALYZED';
  artifact_refs: readonly string[];
  source_refs: readonly JsonObject[];
}>;
export type ResultChoices = Readonly<Record<string, ResultDisposition>>;
type ExpectedResult = FormationStepDetail['expected_results'][number];

export function changeResult(
  values: ResultChoices,
  result: ExpectedResult,
  status: 'OUTSTANDING' | ResultDisposition['status'],
): ResultChoices {
  const next = { ...values };
  if (status === 'OUTSTANDING') delete next[result.result_ref];
  else {
    if ((status === 'LANDED') !== (result.kind === 'CONTENT'))
      throw TypeError('Result disposition must match its real definition');
    if (next[result.result_ref]?.status !== status)
      next[result.result_ref] = {
        result_ref: result.result_ref,
        status,
        artifact_refs: [],
        source_refs: [],
      };
  }
  return Object.freeze(next);
}

export function resultProblem(
  values: ResultChoices,
  expected: FormationStepDetail['expected_results'],
): string | null {
  const rows = Object.values(values);
  if (rows.length > 20) return '一次最多处理20项成果';
  for (const row of rows) {
    const result = expected.find((item) => item.result_ref === row.result_ref);
    if (result === undefined || (row.status === 'LANDED') !== (result.kind === 'CONTENT'))
      return '成果定义已变化，请重新核对';
    if (row.status === 'LANDED' && row.artifact_refs.length === 0)
      return '请为文档成果选择实际关联，或保留为尚未完成';
    if (row.status === 'ANALYZED' && row.source_refs.length === 0)
      return '请为分析成果选择依据，或保留为尚未完成';
    if (row.source_refs.length > 100) return '每项成果最多选择100条依据';
    if (
      new Set(row.artifact_refs).size !== row.artifact_refs.length ||
      new Set(row.source_refs.map((source) => stableJson(source))).size !== row.source_refs.length
    )
      return '同一成果的依据不能重复选择';
  }
  return null;
}
