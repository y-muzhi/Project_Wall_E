import { Pagination } from '../../shared/pagination.tsx';
import { useCallback, useEffect, useState } from 'react';
import { reviewTestingFindingPath } from '../../api/testing-reports.ts';
import type { TestingFinding, TestingReport } from '../../api/testing-reports.ts';
import type { TestingTaskView } from '../../api/testing-tasks.ts';
import type { WalleApi } from '../../api/walle.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { ReadState, useTestingRead } from '../plans/read.tsx';
import { OriginalTaskRequests, useTestingRecovery } from '../task-recovery.tsx';
import { classificationText, clearSavedFindingDraft, FindingReview } from './finding-review.tsx';
import { FindingHandoff } from './finding-handoff.tsx';

const resultText = {
  PASSED: '通过',
  FAILED: '失败',
  UNAVAILABLE: '资源不可用',
  UNKNOWN: '结果未核清',
  CANCELLED: '已取消',
  INCONCLUSIVE: '证据不足以得出完整结论',
};
export const stageText = {
  BACKEND: '后端',
  FRONTEND: '前端',
  INTEGRATION: '联调',
  ACCEPTANCE: '验收',
};
const reasons = {
  RESULT_NOT_PASSED: '原报告未通过',
  TEST_ASSET_REVOKED: '原测试资产已撤销',
  SCOPE_INCOMPLETE: '固定测试阶段或覆盖范围不完整',
  DESIGN_MISMATCH: '报告依据与当前设计不一致',
  TARGET_NOT_CURRENT: '受测候选已变更',
  NOT_CODING_CANDIDATE: '受测对象为独立仓库快照',
  NOT_ACCEPTANCE: '原任务不属于产品验收',
  CODING_CHAIN_INCOMPLETE: '当前 Coding 交接链或自检不完整',
  UNCOVERED_BEHAVIOR: '存在未覆盖的行为',
  ACTIVITY_NOT_STOPPED: '原活动的停止和清理尚未核实',
  EVIDENCE_INCOMPLETE: '原证据或资源闭包不完整',
};

export function ReportFacts({ report }: Readonly<{ report: TestingReport }>) {
  const source = report.provenance;
  return (
    <>
      <h3>
        报告 #{report.id} · {resultText[report.result]}
      </h3>
      <p>原报告时间 {localTime(report.created_at)}</p>
      <p>
        需求 #{source.requirement_id} · 文档 #{source.document_id} · 设计版本 #
        {source.design_revision_id}
        {source.target_kind === 'CANDIDATE'
          ? ' · Coding 候选 #' + source.candidate_id
          : ' · 仓库快照 #' + source.snapshot_id}
      </p>
      {source.material_refs.length > 0 && (
        <ul aria-label="固定补充材料">
          {source.material_refs.map((item) => (
            <li key={item.document_id}>
              文档 #{item.document_id} · 版本 #{item.revision_id}
            </li>
          ))}
        </ul>
      )}
      <p>
        计划 #{report.plan_version_id} · 测试包 #{report.test_pack_version_id} · 配置 #
        {source.profile_version_id}
      </p>
      <p>自动检查阶段 {report.scope_stages.map((item) => stageText[item]).join('、') || '无'}</p>
      <p>人工检查范围 {report.manual_coverage_ids.join('、') || '无'}</p>
      <p>未覆盖行为 {report.uncovered_behavior_ids.join('、') || '无'}</p>
      <p>{report.eligible ? '当前独立测试资格有效' : '当前独立测试资格不可用'}</p>
      {report.ineligibility_reason_codes.length > 0 && (
        <ul aria-label="独立测试资格原因">
          {report.ineligibility_reason_codes.map((code) => (
            <li key={code}>{reasons[code]}</li>
          ))}
        </ul>
      )}
      <p>{report.delivery_eligible ? '具备 Coding 交付测试资格' : '当前无法用于 Coding 交付'}</p>
      {report.delivery_ineligibility_reason_codes.length > 0 && (
        <ul aria-label="Coding 交付资格原因">
          {report.delivery_ineligibility_reason_codes.map((code) => (
            <li key={code}>{reasons[code]}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function Findings({ api, record }: Readonly<{ api: WalleApi; record: TestingReport }>) {
  const report = record.id;
  const { source_code_task_id: codingTask, candidate_id: candidate } = record.provenance;
  const [page, setPage] = useState(1),
    [editor, setEditor] = useState<number | null>(null),
    [handoff, setHandoff] = useState<number | null>(null);
  const load = useCallback(
    (signal: AbortSignal) => api.testingFindings(report, page, signal),
    [api, report, page],
  );
  const list = useTestingRead('testing-findings:' + report + ':' + page, load);
  const rows = list.data?.data.items;
  const selected =
    rows?.find((row) => row.id === handoff && row.classification === 'PRODUCT') ?? null;
  const paths = new Set(rows?.map((row) => reviewTestingFindingPath(row.id)));
  const scope = [...paths].join(',');
  const access = useTestingRecovery(
    api,
    (record) => paths.has(record.path),
    (_record, result) => {
      const outcome = result.original_receipt?.original_outcome;
      if (outcome?.success !== true) return;
      const saved = outcome.data as TestingFinding;
      if (saved.test_report_id === report && clearSavedFindingDraft(saved, api.environmentScope))
        setEditor((opened) => (opened === saved.id ? null : opened));
      list.reload();
    },
  );
  useEffect(() => {
    void access.reader.refresh();
  }, [scope, access.reader]);
  function refresh() {
    list.reload();
    void access.reader.refresh();
  }
  return (
    <section className="testing-editor-panel" aria-label="测试发现项">
      <h3>发现项与归因</h3>
      <OriginalTaskRequests access={access} />
      <ReadState
        loading={list.loading}
        error={list.error}
        stale={rows !== undefined}
        retry={list.reload}
      />
      {rows?.length === 0 && !list.loading && !list.error && (
        <EmptyState
          icon="outline"
          message={page === 1 ? '此报告没有已记录的发现项' : '此页没有发现项'}
          compact
        />
      )}
      {rows?.map((row) => (
        <article key={row.id} className="testing-editor-panel" aria-label={'发现项 #' + row.id}>
          <h4>
            发现项 #{row.id} · {classificationText[row.classification]}
          </h4>
          <p>{row.actual_behavior}</p>
          {row.expected_behavior !== null && <p>预期行为 · {row.expected_behavior}</p>}
          {row.basis_ref !== null && (
            <blockquote>
              <p>
                文档 #{row.basis_ref.document_id} · 版本 #{row.basis_ref.revision_id}
              </p>
              <p>{row.basis_ref.quote}</p>
            </blockquote>
          )}
          {row.review_reason !== null && <p>归因理由 · {row.review_reason}</p>}
          {codingTask !== null && candidate !== null && row.classification === 'PRODUCT' && (
            <button
              className="ui-button"
              type="button"
              disabled={list.loading || list.error !== null}
              title={
                list.loading ? '正在读取原发现项' : list.error ? '请先恢复原发现项读取' : undefined
              }
              onClick={() => setHandoff(row.id)}
            >
              交给 Coding
            </button>
          )}
          {editor === row.id ? (
            <FindingReview
              finding={row}
              scope={api.environmentScope}
              access={access}
              stale={list.loading || list.error !== null}
              refreshed={refresh}
              closed={() => setEditor(null)}
            />
          ) : (
            <button className="ui-button" type="button" onClick={() => setEditor(row.id)}>
              编辑发现项 #{row.id} 归因
            </button>
          )}
        </article>
      ))}
      {codingTask !== null && candidate !== null && (
        <FindingHandoff
          api={api}
          source={record.provenance}
          task={codingTask}
          candidate={candidate}
          finding={selected}
          stale={list.loading || list.error !== null}
          close={() => setHandoff(null)}
        />
      )}
      {list.data && (
        <Pagination
          value={list.data.meta.pagination}
          loading={list.loading}
          showLoadingStatus={false}
          change={(next) => {
            setEditor(null);
            setHandoff(null);
            setPage(next);
          }}
        />
      )}
    </section>
  );
}

export function TaskReport({
  api,
  task,
  openResults,
}: Readonly<{
  api: WalleApi;
  task: TestingTaskView;
  openResults(verification: number): void;
}>) {
  const identity = task.report_id;
  const load = useCallback(
    (signal: AbortSignal) => api.testingTaskReport(task.id, identity!, signal),
    [api, task.id, identity],
  );
  const read = useTestingRead(
    'testing-report:' + task.id + ':' + identity,
    identity === null ? null : load,
  );
  const report = read.data?.data;
  const mismatch = report !== undefined && report.verification_id !== task.current_verification_id;
  return (
    <>
      <section className="testing-editor-panel" aria-label="独立测试报告">
        {identity === null ? (
          <EmptyState icon="outline" message="此任务尚无测试报告" compact />
        ) : (
          <ReadState
            loading={read.loading}
            error={read.error}
            stale={report !== undefined}
            retry={read.reload}
          />
        )}
        {mismatch && (
          <p role="alert" className="inline-error">
            报告的原验证与此任务不一致。
          </p>
        )}
        {report && !mismatch && (
          <>
            <ReportFacts report={report} />
            <div className="code-settings-form-actions">
              <button
                className="ui-button"
                type="button"
                onClick={() => openResults(report.verification_id)}
              >
                查看原验证 #{report.verification_id}
              </button>
              <button
                className="ui-button"
                type="button"
                disabled={read.loading}
                onClick={read.reload}
              >
                核对当前报告资格
              </button>
            </div>
          </>
        )}
      </section>
      {report && !mismatch && <Findings key={report.id} api={api} record={report} />}
    </>
  );
}
