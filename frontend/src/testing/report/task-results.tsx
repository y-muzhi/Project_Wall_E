import { useCallback } from 'react';
import type { TestingTaskView } from '../../api/testing-tasks.ts';
import type { WalleApi } from '../../api/walle.ts';
import { useSettingsVisibility } from '../../code-tasks/settings/read.ts';
import { VerificationCases } from '../../code-tasks/verification-cases.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { ReadState, useTestingRead } from '../plans/read.tsx';
import { stageText } from './task-report.tsx';

const itemResult = {
  NOT_RUN: '未执行',
  RUNNING: '执行中',
  PASSED: '通过',
  FAILED: '失败',
  UNAVAILABLE: '资源不可用',
  UNKNOWN: '待核对',
  CANCELLED: '已取消',
};
const statusText = {
  PENDING: '等待执行',
  RUNNING: '执行中',
  FINISHED: '已结束',
  UNKNOWN: '待核对',
  CANCELLED: '已取消',
};
const boundary = {
  NOT_STARTED: '尚未开始',
  ACTIVE: '仍有活动',
  CLEANING: '清理中',
  VERIFIED: '已核实',
  FAILED: '失败',
  UNKNOWN: '待核对',
  NOT_CHECKED: '尚未核验',
  CHANGED: '已变更',
};
const reasons = {
  REQUIRED_NOT_PASSED: '存在未通过的必检项',
  NO_CONTROLLED_CASES: '缺少受控用例',
  RESOURCE_NOT_READY: '原测试资源未就绪',
  COVERAGE_NOT_READY: '固定检查范围不完整',
  ACTIVITY_NOT_STOPPED: '原活动的停止和清理尚未核实',
  EVIDENCE_INCOMPLETE: '原执行证据不完整',
  TEST_ASSET_REVOKED: '原测试资产已撤销',
};

export function TaskResults({ api, task }: Readonly<{ api: WalleApi; task: TestingTaskView }>) {
  const identity = task.current_verification_id;
  const visible = useSettingsVisibility();
  const load = useCallback(
    (signal: AbortSignal) => api.testingVerification(task.id, identity!, signal),
    [api, task.id, identity],
  );
  const read = useTestingRead(
    'testing-verification:' + task.id + ':' + identity,
    identity === null ? null : load,
  );
  const result = read.data?.data;
  const mismatch =
    result !== undefined &&
    (result.candidate_id !== task.candidate_id ||
      result.snapshot_id !== task.snapshot_id ||
      result.purpose !== task.purpose ||
      result.testing_profile_version_id !== task.profile_version_id);
  return (
    <section className="testing-editor-panel" aria-label="独立执行结果">
      {identity === null ? (
        <EmptyState icon="outline" message="此任务尚无独立执行结果" compact />
      ) : (
        <ReadState
          loading={read.loading}
          error={read.error}
          stale={result !== undefined}
          retry={read.reload}
        />
      )}
      {mismatch && (
        <p role="alert" className="inline-error">
          验证记录的固定目标与此任务不一致。
        </p>
      )}
      {result && !mismatch && (
        <>
          <h3>
            原验证 #{result.id} · {statusText[result.status]}
          </h3>
          <p>执行阶段 {result.scope_stages.map((item) => stageText[item]).join('、')}</p>
          <p>
            停止 {boundary[result.stop_status]} · 清理 {boundary[result.cleanup_status]} ·
            输入完整性 {boundary[result.source_integrity_status]}
          </p>
          <p>
            原环境 #{result.environment_record_id} · 核对时间{' '}
            {localTime(result.environment_record.observed_at)}
          </p>
          {result.ineligibility_reason_codes.length > 0 && (
            <ul aria-label="验证资格原因">
              {result.ineligibility_reason_codes.map((code) => (
                <li key={code}>{reasons[code]}</li>
              ))}
            </ul>
          )}
          <ol className="code-settings-version-items">
            {result.items.map((item) => (
              <li key={item.id}>
                <h4>
                  {item.evidence_kind === 'CONTENT_INTEGRITY' ? '内容完整性' : item.check_id} ·{' '}
                  {itemResult[item.result]}
                </h4>
                {item.evidence_kind === 'CONTROLLED_CASES' && (
                  <VerificationCases
                    api={api}
                    taskId={task.id}
                    item={item}
                    visible={visible}
                    testing
                  />
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
