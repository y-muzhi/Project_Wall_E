import { snapshotObject, stableJson } from '../../api/client.ts';
import type { EnvironmentScope } from '../../api/environment-binding.ts';
import { environmentBrowserStorage } from '../../api/environment-storage.ts';
import { array, choices, count, id, nullable, shape, text } from '../../api/decoding.ts';
import {
  planContentOf,
  testPlanAssertion,
  testPlanContent,
  testPlanStep,
  testingPlanDraftPath,
  testingPlanVersionsPath,
} from '../../api/testing-plans.ts';
import type { TestPlanContent, TestPlanVersion } from '../../api/testing-plans.ts';

export const stageLabels = {
  BACKEND: '后端',
  FRONTEND: '前端',
  INTEGRATION: '联调',
  ACCEPTANCE: '验收',
} as const;
export const importanceLabels = { BLOCKER: '阻断', CRITICAL: '关键', NORMAL: '普通' } as const;
export const modeLabels = {
  AUTO: '自动检查',
  MANUAL: '人工检查',
  NOT_APPLICABLE: '不适用',
  UNCOVERED: '未覆盖',
} as const;
export const driverLabels = { CLI: '命令行', HTTP: 'HTTP', BROWSER: '浏览器' } as const;

export type Stage = keyof typeof stageLabels;
export type Importance = keyof typeof importanceLabels;
export type Mode = keyof typeof modeLabels;
export type Driver = keyof typeof driverLabels;
const reference = shape({ document_id: id, revision_id: id });
const basis = shape({ document_id: id, revision_id: id, quote: text });
const behavior = shape({
  behavior_id: text,
  name: text,
  basis_refs: array(basis, 256),
  stages: array(choices(['BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'] as const), 4),
  importance: choices(['BLOCKER', 'CRITICAL', 'NORMAL'] as const),
  mode: choices(['AUTO', 'MANUAL', 'NOT_APPLICABLE', 'UNCOVERED'] as const),
  case_ids: array(text, 4096),
  explanation: text,
});
const testCase = shape({
  case_id: text,
  name: text,
  behavior_ids: array(text, 4096),
  visibility: choices(['PUBLIC', 'HELD_OUT'] as const),
  driver_kind: choices(['CLI', 'HTTP', 'BROWSER'] as const),
  steps: array(testPlanStep, 256),
  assertions: array(testPlanAssertion, 256),
  timeout_seconds: text,
});
const draft = shape({
  requirement_id: nullable(id),
  document_id: nullable(id),
  design_revision_id: nullable(id),
  material_refs: array(reference, 256),
  behaviors: array(behavior, 4096),
  cases: array(testCase, 4096),
  unresolved_questions: array(text, 256),
});
export type Source = ReturnType<typeof reference>;
export type Draft = ReturnType<typeof draft>;
export type Behavior = ReturnType<typeof behavior>;
export type Case = ReturnType<typeof testCase>;

export function initialDraft(version: TestPlanVersion | null): Draft {
  if (version === null)
    return {
      requirement_id: null,
      document_id: null,
      design_revision_id: null,
      material_refs: [],
      behaviors: [],
      cases: [],
      unresolved_questions: [],
    };
  const content = planContentOf(version);
  return {
    ...content,
    cases: content.cases.map((item) => ({
      ...item,
      timeout_seconds: String(item.timeout_seconds),
    })),
  };
}
export function newBehavior(): Behavior {
  return {
    behavior_id: 'behavior-' + crypto.randomUUID(),
    name: '',
    basis_refs: [],
    stages: [],
    importance: 'NORMAL',
    mode: 'MANUAL',
    case_ids: [],
    explanation: '',
  };
}
export function newCase(): Case {
  return {
    case_id: 'case-' + crypto.randomUUID(),
    name: '',
    behavior_ids: [],
    visibility: 'PUBLIC',
    driver_kind: 'CLI',
    steps: [],
    assertions: [],
    timeout_seconds: '',
  };
}
export function replace<T>(values: readonly T[], index: number, value: T) {
  return values.map((current, position) => (position === index ? value : current));
}
export function remove<T>(values: readonly T[], index: number) {
  return values.filter((_current, position) => position !== index);
}
export function linkCases(draft: Draft, cases: readonly Case[]): Draft {
  const mapped = new Map<string, string[]>();
  for (const item of cases) {
    for (const behaviorId of item.behavior_ids) {
      const linked = mapped.get(behaviorId) ?? [];
      linked.push(item.case_id);
      mapped.set(behaviorId, linked);
    }
  }
  return {
    ...draft,
    cases,
    behaviors: draft.behaviors.map((item) => ({
      ...item,
      case_ids: item.mode === 'AUTO' ? (mapped.get(item.behavior_id) ?? []) : [],
    })),
  };
}

const whiteSpace = /^[\p{White_Space}]+|[\p{White_Space}]+$/gu;
function normalized(value: string) {
  return value.replace(/\r\n?/g, '\n').replace(whiteSpace, '');
}
function fits(value: string, maximum: number, minimum = 1) {
  const length = [...value].length;
  return length >= minimum && length <= maximum;
}
type Check = { content: TestPlanContent; reason: null } | { content: null; reason: string };
export function validateDraft(value: Draft): Check {
  if (!value.requirement_id || !value.document_id || !value.design_revision_id)
    return { content: null, reason: '请选择实际需求、主文档和固定版本' };
  const sources = new Map(value.material_refs.map((item) => [item.document_id, item.revision_id]));
  sources.set(value.document_id, value.design_revision_id);
  for (const [index, item] of value.behaviors.entries()) {
    if (!fits(normalized(item.name), 256) || !item.stages.length || !item.basis_refs.length)
      return { content: null, reason: '行为 ' + (index + 1) + ' 需要名称、阶段和原文引用' };
    if (!fits(normalized(item.explanation), 2000, 0))
      return { content: null, reason: '行为 ' + (index + 1) + ' 的说明最多 2000 个字符' };
    if (
      item.basis_refs.some(
        (ref) =>
          sources.get(ref.document_id) !== ref.revision_id ||
          !fits(ref.quote, 4096) ||
          !ref.quote.trim(),
      )
    )
      return { content: null, reason: '行为 ' + (index + 1) + ' 含已失效的原文引用' };
  }
  for (const [index, item] of value.cases.entries()) {
    if (
      !fits(normalized(item.name), 256) ||
      !item.behavior_ids.length ||
      !/^[1-9][0-9]*$/.test(item.timeout_seconds) ||
      Number(item.timeout_seconds) > 3600
    )
      return {
        content: null,
        reason: '用例 ' + (index + 1) + ' 需要名称、关联行为和 1 到 3600 秒的超时',
      };
  }
  const questions = value.unresolved_questions.map(normalized);
  if (questions.some((item) => !fits(item, 2000)))
    return { content: null, reason: '待解决问题每项需 1 到 2000 个字符' };
  try {
    const content = testPlanContent({
      ...value,
      material_refs: [...value.material_refs].sort(
        (left, right) => left.document_id - right.document_id,
      ),
      behaviors: value.behaviors.map((item) => ({
        ...item,
        name: normalized(item.name),
        explanation: normalized(item.explanation),
      })),
      cases: value.cases.map((item) => ({
        ...item,
        name: normalized(item.name),
        timeout_seconds: Number(item.timeout_seconds),
      })),
      unresolved_questions: questions,
    });
    const bytes = new TextEncoder().encode(
      JSON.stringify(snapshotObject({ plan_content: content })),
    );
    if (bytes.length > 8 * 1024 * 1024 - 64)
      return { content: null, reason: '草稿超过单次请求容量，请减少内容' };
    return { content, reason: null };
  } catch {
    return { content: null, reason: '草稿字段或用例数据无效，请核对当前输入' };
  }
}

const cached = shape({
  draft,
  base: nullable(id),
  change: count,
  sent: nullable(shape({ key: text, change: count })),
});
export type LocalDraft = ReturnType<typeof cached>;
export type DraftReceipt = { key: string; version: TestPlanVersion };

export function draftPath(planId: number, versionId: number | null) {
  return versionId === null ? testingPlanVersionsPath(planId) : testingPlanDraftPath(versionId);
}
function storageKey(planId: number, versionId: number | null) {
  return 'walle:v20:testing-plan-draft:' + planId + ':' + (versionId ?? 'new');
}
export function loadDraft(
  planId: number,
  version: TestPlanVersion | null,
  scope: EnvironmentScope | undefined,
): LocalDraft {
  const initial = {
    draft: initialDraft(version),
    base: version?.state_version ?? null,
    change: 0,
    sent: null,
  };
  try {
    const saved = environmentBrowserStorage('sessionStorage', scope).getItem(
      storageKey(planId, version?.id ?? null),
    );
    if (saved === null) return initial;
    const local = cached(JSON.parse(saved));
    if ((local.base === null) !== (version === null)) return initial;
    return local;
  } catch {
    return initial;
  }
}
export function saveLocal(
  planId: number,
  versionId: number | null,
  local: LocalDraft | null,
  scope: EnvironmentScope | undefined,
): boolean {
  try {
    const key = storageKey(planId, versionId);
    const storage = environmentBrowserStorage('sessionStorage', scope);
    if (local === null) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(local));
    return true;
  } catch {
    return false;
  }
}
export function receiptMatches(local: LocalDraft, receipt: DraftReceipt) {
  return (
    local.sent?.key === receipt.key &&
    local.sent.change === local.change &&
    stableJson(validateDraft(local.draft).content) === stableJson(planContentOf(receipt.version))
  );
}
