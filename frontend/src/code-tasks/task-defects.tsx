import { useCallback, useEffect, useState } from 'react';
import type { JsonObject } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import {
  createdDefect,
  decodeDefectBasis,
  decodeDefectEvidence,
  defectPath,
} from '../api/code-task-defects.ts';
import type { CodeDefect } from '../api/code-task-defects.ts';
import type { QuestionBasisRef, QuestionEvidenceRef } from '../api/code-task-question-response.ts';
import type { TestingFinding } from '../api/testing-reports.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { meta, Pager, ReadState, useTestingRead } from '../testing/plans/read.tsx';
import { evidenceLabel, EvidencePicker } from './evidence-picker.tsx';
import { useCodeTaskCommand } from './handoff-command.ts';
import { BasisPicker } from './question-response-control.tsx';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { TaskRepairControl } from './task-repair.tsx';

type Draft = {
  actual: string;
  expected: string;
  basis: QuestionBasisRef | null;
  evidence: readonly QuestionEvidenceRef[];
};

const emptyDraft = (): Draft => ({ actual: '', expected: '', basis: null, evidence: [] });
const visibleText = (value: string) => /[^\\p{White_Space}]/u.test(value);

function restore(key: string, candidate: number | null): Draft {
  try {
    const raw = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    if (
      candidate === null ||
      raw === null ||
      typeof raw.actual !== 'string' ||
      typeof raw.expected !== 'string'
    )
      return emptyDraft();
    return {
      actual: raw.actual,
      expected: raw.expected,
      basis: raw.basis === null ? null : decodeDefectBasis(raw.basis),
      evidence: decodeDefectEvidence(raw.evidence),
    };
  } catch {
    return emptyDraft();
  }
}

function recordId(value: string): number | null {
  const parsed = Number(value);
  return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(parsed) ? parsed : null;
}

function DefectFacts({ record }: Readonly<{ record: CodeDefect }>) {
  return (
    <div>
      <p>
        来源候选 #{record.candidate_id} · {localTime(record.created_at)}
      </p>
      {record.testing_finding_id !== null && <p>独立测试发现项 #{record.testing_finding_id}</p>}
      <dl>
        <dt>实际行为</dt>
        <dd>{record.actual_behavior}</dd>
        <dt>预期行为</dt>
        <dd>{record.expected_behavior}</dd>
        <dt>固定依据</dt>
        <dd>
          文档 #{record.basis_ref.document_id} · 版本 #{record.basis_ref.revision_id}
          <blockquote>{record.basis_ref.quote}</blockquote>
        </dd>
      </dl>
      {record.evidence_refs.length > 0 && (
        <ul>
          {record.evidence_refs.map((ref) => (
            <li key={ref.kind + ':' + ref.id}>{evidenceLabel(ref)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingSelection({
  api,
  task,
  candidate,
  selected,
  choose,
}: Readonly<{
  api: WalleApi;
  task: number;
  candidate: number;
  selected: TestingFinding | null;
  choose(value: TestingFinding | null): void;
}>) {
  const [input, setInput] = useState('');
  const [reportId, setReportId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const readReport = useCallback(
    (signal: AbortSignal) => api.testingReport(reportId!, signal),
    [api, reportId],
  );
  const report = useTestingRead('defect-report:' + reportId, reportId === null ? null : readReport);
  const source = report.data?.data;
  const matching =
    source?.provenance.source_code_task_id === task &&
    source.provenance.candidate_id === candidate &&
    source.provenance.target_kind === 'CANDIDATE';
  const readFindings = useCallback(
    (signal: AbortSignal) => api.testingFindings(reportId!, page, signal),
    [api, reportId, page],
  );
  const findings = useTestingRead(
    'defect-findings:' + reportId + ':' + page,
    matching ? readFindings : null,
  );
  const rows = findings.data?.data.items.filter((row) => row.classification === 'PRODUCT') ?? [];
  const pagination = meta(findings.data?.meta.pagination);
  return (
    <div>
      <div className="code-task-toolbar">
        <label>
          独立测试报告编号{' '}
          <input
            inputMode="numeric"
            value={input}
            onChange={(event) => {
              setInput(event.currentTarget.value);
              setReportId(null);
              choose(null);
            }}
          />
        </label>
        <button
          type="button"
          className="ui-button"
          disabled={recordId(input) === null}
          onClick={() => {
            const next = recordId(input);
            choose(null);
            setPage(1);
            if (next === reportId) report.reload();
            else setReportId(next);
          }}
        >
          核对原测试报告
        </button>
      </div>
      <ReadState
        loading={report.loading}
        error={report.error}
        stale={source !== undefined}
        retry={report.reload}
      />
      {source && !matching && <p role="alert">此报告不属于当前代码候选。</p>}
      {matching && (
        <>
          <ReadState
            loading={findings.loading}
            error={findings.error}
            stale={findings.data !== null}
            retry={findings.reload}
          />
          {!findings.loading && !findings.error && rows.length === 0 && (
            <EmptyState icon="outline" message="此页没有已归因为产品偏差的发现项" compact />
          )}
          {rows.length > 0 && (
            <label>
              原产品发现项{' '}
              <select
                value={selected?.id ?? ''}
                disabled={findings.loading || findings.error !== null}
                onChange={(event) =>
                  choose(rows.find((row) => row.id === Number(event.currentTarget.value)) ?? null)
                }
              >
                <option value="">选择发现项</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    发现项 #{row.id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {pagination && (
            <Pager
              meta={pagination}
              page={page}
              busy={findings.loading}
              select={(next) => {
                choose(null);
                setPage(next);
              }}
            />
          )}
          {selected && (
            <>
              <p>{selected.actual_behavior}</p>
              <p>{selected.expected_behavior}</p>
              {selected.basis_ref && <blockquote>{selected.basis_ref.quote}</blockquote>}
            </>
          )}
        </>
      )}
    </div>
  );
}

export function TaskDefects({
  api,
  task,
  page,
  selectPage,
  ready,
  visible,
  changed,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  page: number;
  selectPage(page: number): void;
  ready: boolean;
  visible: boolean;
  changed(): void;
}>) {
  const candidate = task.current_candidate_id;
  const key =
    'walle:v2.0:code:draft:' + location.origin + ':' + task.id + ':defect:' + (candidate ?? 'none');
  const [draft, setDraft] = useState(() => restore(key, candidate));
  const [storageError, setStorageError] = useState(false);
  const [mode, setMode] = useState<'manual' | 'import' | null>(null);
  const [finding, setFinding] = useState<TestingFinding | null>(null);
  const [confirm, setConfirm] = useState<JsonObject | null>(null);
  const [selection, setSelection] = useState<number | null>(null);
  const [repairDefects, setRepairDefects] = useState<number[]>([]);
  useEffect(() => {
    try {
      if (draft.actual || draft.expected || draft.basis || draft.evidence.length)
        sessionStorage.setItem(key, JSON.stringify(draft));
      else sessionStorage.removeItem(key);
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [draft, key]);

  const load = useCallback(
    (signal: AbortSignal) => api.codeDefects(task.id, page, signal),
    [api, task.id, page],
  );
  const list = useTestingRead('coding-defects:' + task.id + ':' + page, load);
  const loadRecord = useCallback(
    (signal: AbortSignal) => api.codeDefect(task.id, selection!, signal),
    [api, task.id, selection],
  );
  const detail = useTestingRead(
    'coding-defect:' + task.id + ':' + selection,
    selection === null ? null : loadRecord,
  );
  const command = useCodeTaskCommand(
    api,
    defectPath(task.id),
    (result) => {
      const original = createdDefect(result);
      setSelection(original.defect_id);
      if (original.candidate_id === candidate && mode === 'manual') setDraft(emptyDraft());
      setMode(null);
    },
    () => {
      list.reload();
      changed();
    },
    '缺陷登记',
    '缺陷报告已保存。',
  );
  const action = task.available_actions.find((row) => row.action === 'REGISTER_DEFECT');
  const reason = !ready
    ? '请先核对最新任务和候选'
    : candidate === null
      ? '此任务尚无可登记的固定候选'
      : !action?.enabled
        ? '当前任务状态不允许登记缺陷'
        : !command.ready
          ? '正在读取缺陷原请求'
          : command.pending
            ? '请先核对原缺陷请求'
            : command.busy
              ? '正在保存原报告'
              : null;

  const bases = [
    { document_id: task.document_id, revision_id: task.design_revision_id },
    ...task.material_refs,
  ];
  const manualReady =
    visibleText(draft.actual) && visibleText(draft.expected) && draft.basis !== null;
  const allowed = reason === null && (mode === 'manual' ? manualReady : finding?.basis_ref != null);
  function prepare() {
    if (!allowed || candidate === null) return;
    const base = { candidate_id: candidate, expected_state_version: task.state_version };
    if (mode === 'manual' && draft.basis)
      setConfirm({
        ...base,
        actual_behavior: draft.actual,
        expected_behavior: draft.expected,
        basis_ref: draft.basis,
        evidence_refs: [...draft.evidence],
      });
    else if (mode === 'import' && finding) setConfirm({ ...base, testing_finding_id: finding.id });
  }
  function submit() {
    if (
      !allowed ||
      confirm === null ||
      confirm.candidate_id !== candidate ||
      confirm.expected_state_version !== task.state_version ||
      ('testing_finding_id' in confirm && confirm.testing_finding_id !== finding?.id)
    )
      return;
    command.submit(confirm);
    setConfirm(null);
  }
  const pagination = meta(list.data?.meta.pagination);
  const rows = list.data?.data.items ?? [];
  return (
    <section className="code-task-result" aria-label="缺陷报告">
      <h2>缺陷报告</h2>
      <ReadState
        loading={list.loading}
        error={list.error}
        stale={list.data !== null}
        retry={list.reload}
      />
      {!list.loading && !list.error && rows.length === 0 && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页没有缺陷报告' : '此任务尚未登记缺陷报告'}
          compact
        />
      )}
      {rows.length > 0 && (
        <ul>
          {rows.map((row) => (
            <li key={row.id}>
              <button type="button" className="ui-button" onClick={() => setSelection(row.id)}>
                查看缺陷 #{row.id}
              </button>{' '}
              候选 #{row.candidate_id}
              {row.candidate_id !== candidate && ' · 历史候选'}
              {row.candidate_id === candidate && (
                <label>
                  <input
                    type="checkbox"
                    checked={repairDefects.includes(row.id)}
                    disabled={!ready || list.loading || list.error !== null}
                    onChange={(event) => {
                      const selected = event.currentTarget.checked;
                      setRepairDefects((previous) =>
                        selected ? [...previous, row.id] : previous.filter((id) => id !== row.id),
                      );
                    }}
                  />
                  选择缺陷 #{row.id} 用于修复
                </label>
              )}
            </li>
          ))}
        </ul>
      )}
      {pagination && (
        <Pager meta={pagination} page={page} busy={list.loading} select={selectPage} />
      )}
      {selection !== null && (
        <section aria-label={'原缺陷 #' + selection}>
          <ReadState
            loading={detail.loading}
            error={detail.error}
            stale={detail.data !== null}
            retry={detail.reload}
          />
          {detail.data && <DefectFacts record={detail.data.data} />}
          <button type="button" className="ui-button" onClick={() => setSelection(null)}>
            关闭缺陷详情
          </button>
        </section>
      )}
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={reason !== null}
          title={reason ?? undefined}
          onClick={() => setMode('manual')}
        >
          登记人工缺陷
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={reason !== null}
          title={reason ?? undefined}
          onClick={() => {
            setFinding(null);
            setMode('import');
          }}
        >
          导入独立测试发现项
        </button>
      </div>
      {reason && <p className="read-status">{reason}</p>}
      {mode === 'manual' && (
        <div>
          <label>
            实际行为{' '}
            <textarea
              value={draft.actual}
              onChange={(event) => setDraft({ ...draft, actual: event.currentTarget.value })}
            />
          </label>
          <label>
            预期行为{' '}
            <textarea
              value={draft.expected}
              onChange={(event) => setDraft({ ...draft, expected: event.currentTarget.value })}
            />
          </label>
          <BasisPicker
            api={api}
            bases={bases}
            visible={visible}
            value={draft.basis ? [draft.basis] : []}
            changed={(rows) => setDraft({ ...draft, basis: rows.at(-1) ?? null })}
          />
          <EvidencePicker
            value={draft.evidence}
            changed={(evidence) => setDraft({ ...draft, evidence })}
          />
          {storageError && <p role="alert">本标签页暂时无法保存缺陷草稿。</p>}
        </div>
      )}
      {mode === 'import' && candidate !== null && (
        <FindingSelection
          api={api}
          task={task.id}
          candidate={candidate}
          selected={finding}
          choose={setFinding}
        />
      )}
      {mode !== null && (
        <div className="code-task-toolbar">
          <button
            type="button"
            className="ui-button"
            disabled={!allowed}
            title={
              !allowed
                ? (reason ??
                  (mode === 'manual'
                    ? '请填写两项行为并选取固定原文'
                    : '请选择有固定依据的原产品发现项'))
                : undefined
            }
            onClick={prepare}
          >
            保存缺陷报告
          </button>
          <button type="button" className="ui-button" onClick={() => setMode(null)}>
            关闭
          </button>
        </div>
      )}
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            type="button"
            className="ui-button"
            disabled={command.busy}
            onClick={command.lookup}
          >
            核对原缺陷请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={false}
            settled={command.settled}
          />
        </div>
      )}
      <TaskRepairControl
        api={api}
        task={task}
        ready={ready}
        chosen={repairDefects}
        reset={() => setRepairDefects([])}
        changed={changed}
      />
      <Confirmation
        open={confirm !== null}
        busy={command.busy}
        title="保存缺陷报告"
        description={'将缺陷报告固定到代码候选 #' + candidate + '，供后续核对。'}
        confirmDisabled={!allowed || confirm?.expected_state_version !== task.state_version}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
