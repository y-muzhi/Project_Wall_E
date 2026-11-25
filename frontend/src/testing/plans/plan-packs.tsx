import { Pagination } from '../../shared/pagination.tsx';
import { useCallback, useEffect, useRef, useState } from 'react';
import { positiveInteger } from '../../api/client.ts';
import { testingPackListPath } from '../../api/testing-assets.ts';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import type { WalleApi } from '../../api/walle.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { localTime } from '../../shared/time.ts';
import { PackSeal } from './pack-seal.tsx';
import { PackLifecycle } from './pack-lifecycle.tsx';
import { errorText, ReadState, useTestingRead } from './read.tsx';

const statuses = {
  DRAFT: '草稿',
  SEALED: '已封存',
  PUBLISHED: '已发布',
  REVOKED: '已撤销',
} as const;
const reasons = {
  PACK_NOT_SEALED: '测试包尚未封存',
  PACK_NOT_PUBLISHED: '测试包尚未发布',
  TEST_ASSET_REVOKED: '测试包或所属计划已撤销',
  REFERENCE_SET_NOT_REGISTERED: '该固定设计尚无预登记参考集',
  'Q20-CHECKS': '独立测试资源尚未准入',
} as const;
type Props = Readonly<{
  api: WalleApi;
  version: TestPlanVersion;
  packId: number | null;
  validationId: number | null;
  validationReceipt: number | undefined;
  controlVersion: number | undefined;
  pending(path: string): string | null;
  openTask(id: number): void;
  recovery: CommandRecovery;
  unavailable: string | null;
  receipt: number | undefined;
  sealReceipt: number | undefined;
  sealUnavailable: string | null;
  select(id: number | null, validation?: number | null): void;
  refresh(): void;
}>;
export function PlanPacks({
  api,
  version,
  packId,
  validationId,
  validationReceipt,
  controlVersion,
  pending,
  openTask,
  recovery,
  unavailable,
  receipt,
  sealReceipt,
  sealUnavailable,
  select,
  refresh,
}: Props) {
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(false);
  const submitting = useRef(false);
  const inspectedValidation = useRef<number | null>(null);
  const load = useCallback(
    (signal: AbortSignal) => api.testingPacks(version.id, page, signal),
    [api, version.id, page],
  );
  const loadPack = useCallback(
    (signal: AbortSignal) => api.testingPack(version.id, packId!, signal),
    [api, version.id, packId],
  );
  const list = useTestingRead('packs:' + version.id + ':' + page, load);
  const pack = useTestingRead(
    'pack:' + version.id + ':' + packId,
    packId === null ? null : loadPack,
  );
  const blocked = busy
    ? '正在登记原测试包草稿'
    : (unavailable ??
      (version.status !== 'PUBLISHED' ? '仅已发布且有效的计划可以登记测试包' : null));
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (receipt !== undefined) list.reload();
  }, [receipt, list.reload]);
  useEffect(() => {
    if (controlVersion === undefined) return;
    pack.reload();
    list.reload();
  }, [controlVersion, pack.reload, list.reload]);
  useEffect(() => {
    if (
      packId === null ||
      validationReceipt === undefined ||
      validationId !== null ||
      inspectedValidation.current === validationReceipt
    )
      return;
    inspectedValidation.current = validationReceipt;
    select(packId, validationReceipt);
  }, [packId, validationId, validationReceipt, select]);
  const refreshPack = useCallback(() => {
    list.reload();
    pack.reload();
    refresh();
  }, [list.reload, pack.reload, refresh]);
  async function create() {
    if (!confirm || blocked !== null || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      const original = await recovery.stageIntent(testingPackListPath(version.id), {});
      if (original.kind !== 'PREPARED') {
        if (live.current) setError('已有原测试包登记请求，请先核对');
        return;
      }
      if (!live.current) return;
      const response = await recovery.send(original.record.key, original.record.record_revision);
      if (!live.current) return;
      const result = response.response.data as { test_pack_version_id: number };
      select(positiveInteger(result.test_pack_version_id));
      list.reload();
    } catch (failure) {
      if (live.current) setError(errorText(failure, '暂时无法核实测试包登记结果'));
    } finally {
      submitting.current = false;
      if (live.current) {
        setBusy(false);
        setConfirm(false);
        refresh();
      }
    }
  }

  return (
    <section className="code-settings-versions testing-plan-version" aria-label="测试包目录">
      <header className="code-settings-section-heading">
        <h2>测试包</h2>
        <button
          type="button"
          className="ui-button"
          disabled={blocked !== null}
          title={blocked ?? undefined}
          onClick={() => setConfirm(true)}
        >
          登记测试包草稿
        </button>
      </header>
      {blocked && <p className="read-status">{blocked}</p>}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <ReadState
        loading={list.loading}
        error={list.error}
        stale={list.data !== null}
        retry={list.reload}
      />
      {list.data && (
        <>
          {list.data.data.items.length === 0 && !list.loading && !list.error && (
            <EmptyState
              icon="outline"
              message={page === 1 ? '所选计划尚无测试包' : '此页没有测试包'}
              compact
            />
          )}
          <ol className="code-settings-version-items">
            {list.data.data.items.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  className="ui-button"
                  aria-pressed={row.id === packId}
                  onClick={() => select(row.id)}
                >
                  测试包 {row.version} · {statuses[row.status]}
                </button>
              </li>
            ))}
          </ol>
          <Pagination
            value={list.data.meta.pagination}
            loading={list.loading}
            showLoadingStatus={false}
            change={setPage}
          />
        </>
      )}
      <ReadState
        loading={pack.loading}
        error={pack.error}
        stale={pack.data !== null}
        retry={pack.reload}
      />
      {pack.data && (
        <section className="testing-editor-panel" aria-label="所选测试包">
          <h3>
            测试包 {pack.data.data.version} · {statuses[pack.data.data.status]}
          </h3>
          <p>登记时间 {localTime(pack.data.data.created_at)}</p>
          {pack.data.data.sha256 && (
            <p>
              封存摘要 <code>{pack.data.data.sha256}</code>
            </p>
          )}
          {pack.data.data.validation_id && <p>有效性验证 #{pack.data.data.validation_id}</p>}
          {pack.data.data.revocation_reason && <p>撤销原因 {pack.data.data.revocation_reason}</p>}
          {pack.data.data.reason_codes.length > 0 && (
            <ul>
              {pack.data.data.reason_codes.map((code) => (
                <li key={code}>{reasons[code]}</li>
              ))}
            </ul>
          )}
          <PackSeal
            key={'seal:' + pack.data.data.id}
            api={api}
            pack={pack.data.data}
            plan={version}
            recovery={recovery}
            unavailable={pack.error || pack.loading ? '请先核实固定测试包' : sealUnavailable}
            recovered={sealReceipt}
            refresh={refreshPack}
          />
          <PackLifecycle
            key={'lifecycle:' + pack.data.data.id}
            api={api}
            pack={pack.data.data}
            plan={version}
            validationId={validationId}
            recovery={recovery}
            unavailable={pack.error || pack.loading ? '请先核实固定测试包' : null}
            pending={pending}
            select={(id) => select(pack.data!.data.id, id)}
            openTask={openTask}
            refresh={refreshPack}
          />
        </section>
      )}
      {packId === null && (list.data?.data.items.length ?? 0) > 0 && (
        <EmptyState icon="outline" message="请选择测试包" compact />
      )}
      <Confirmation
        open={confirm}
        title="登记测试包草稿"
        description="按所选已发布计划版本登记一个测试包草稿。"
        busy={busy}
        confirmLabel="确认登记"
        confirmDisabled={blocked !== null && !busy}
        confirm={() => void create()}
        cancel={() => setConfirm(false)}
      />
    </section>
  );
}
