import { relativePath } from '../api/code-snapshots.ts';

export const workspaceTabs = {
  execution: '执行',
  code: '代码',
  checks: '开发自检',
  testing: '独立测试',
  delivery: '交付',
  usage: '用量',
} as const;

export type WorkspaceTab = keyof typeof workspaceTabs;
export type WorkspaceRoute = Readonly<{
  tab: WorkspaceTab;
  operationId?: number;
  candidateId?: number;
  verificationId?: number;
  planId?: number;
  reportId?: number;
  filePath?: string;
  page?: number;
}>;

function selectedId(value: string) {
  const id = Number(value);
  return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(id) ? id : null;
}

export function readWorkspaceRoute(search: string): WorkspaceRoute | null {
  const query = new URLSearchParams(search);
  const tabValues = query.getAll('tab');
  const tab = tabValues[0] ?? 'execution';
  if (tabValues.length > 1 || !Object.hasOwn(workspaceTabs, tab)) return null;

  const selectionKeys: Readonly<Partial<Record<WorkspaceTab, string>>> = {
    execution: 'operation_id',
    code: 'candidate_id',
    checks: 'verification_id',
    delivery: 'plan_id',
    testing: 'test_report_id',
  };
  const selectionKey = selectionKeys[tab as WorkspaceTab];
  const allowed = new Set(['tab', 'page', selectionKey]);
  if (tab === 'code' || tab === 'delivery') allowed.add('path');
  if ([...query.keys()].some((key) => !allowed.has(key))) return null;
  const pages = query.getAll('page');
  const page = pages[0] === undefined ? 1 : selectedId(pages[0]);
  if (pages.length > 1 || page === null) return null;
  const location = { tab: tab as WorkspaceTab, ...(page === 1 ? {} : { page }) };
  const paths = query.getAll('path');
  if (paths.length > 1) return null;
  let filePath: string | undefined;
  if (paths.length === 1) {
    try {
      filePath = relativePath(paths[0]);
    } catch {
      return null;
    }
  }
  const values = selectionKey === undefined ? [] : query.getAll(selectionKey);
  if (values.length > 1) return null;
  const selected = values[0];
  if (selected === undefined) return filePath === undefined ? location : { ...location, filePath };
  const id = selectedId(selected);
  if (id === null) return null;
  if (tab === 'execution') return { ...location, operationId: id };
  if (tab === 'code')
    return { ...location, candidateId: id, ...(filePath === undefined ? {} : { filePath }) };
  if (tab === 'delivery')
    return { ...location, planId: id, ...(filePath === undefined ? {} : { filePath }) };
  // A fixed check or report is a detail. Its nested lists have separate owners.
  if (page !== 1) return null;
  if (tab === 'checks') return { ...location, verificationId: id };
  return { ...location, reportId: id };
}

export function workspacePath(task: number, route: WorkspaceRoute) {
  const query = new URLSearchParams({ tab: route.tab });
  if (route.operationId !== undefined) query.set('operation_id', String(route.operationId));
  if (route.candidateId !== undefined) query.set('candidate_id', String(route.candidateId));
  if (route.verificationId !== undefined)
    query.set('verification_id', String(route.verificationId));
  if (route.planId !== undefined) query.set('plan_id', String(route.planId));
  if (route.reportId !== undefined) query.set('test_report_id', String(route.reportId));
  if (route.filePath !== undefined) query.set('path', relativePath(route.filePath));
  if (route.page !== undefined && route.page !== 1) query.set('page', String(route.page));
  return '/code-tasks/' + task + '?' + query.toString();
}
