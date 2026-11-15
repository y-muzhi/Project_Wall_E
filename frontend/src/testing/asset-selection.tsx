import { useCallback, useState } from 'react';
import type { TestingTaskView } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { optionPage, PagedTaskSelect } from '../code-tasks/create-selection.tsx';
import { useSettingsVisibility } from '../code-tasks/settings/read.ts';

type Basis = Pick<
  TestingTaskView,
  'requirement_id' | 'document_id' | 'design_revision_id' | 'material_refs'
>;
export type AssetChoice = Readonly<{ plan: number; pack: number }>;
function sameBasis(left: Basis, right: Basis) {
  return (
    left.requirement_id === right.requirement_id &&
    left.document_id === right.document_id &&
    left.design_revision_id === right.design_revision_id &&
    left.material_refs.length === right.material_refs.length &&
    left.material_refs.every((item) =>
      right.material_refs.some(
        (source) =>
          item.document_id === source.document_id && item.revision_id === source.revision_id,
      ),
    )
  );
}
export function AssetSelection({
  api,
  basis,
  disabled,
  change,
}: Readonly<{
  api: WalleApi;
  basis: Basis;
  disabled: boolean;
  change(value: AssetChoice | null): void;
}>) {
  const [plan, setPlan] = useState<number | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [pack, setPack] = useState<number | null>(null);
  const visible = useSettingsVisibility();
  const plans = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.testingPlans(page, signal), (row) => ({ id: row.id, label: row.name })),
    [api],
  );
  const versions = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.testingPlanVersions(plan!, page, signal), (row) => ({
        id: row.id,
        label:
          '版本 ' +
          row.version +
          (row.status === 'PUBLISHED' && sameBasis(basis, row)
            ? ' · 固定依据一致'
            : ' · 未发布或依据不匹配'),
        disabled: row.status !== 'PUBLISHED' || !sameBasis(basis, row),
      })),
    [api, plan, basis],
  );
  const packs = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.testingPacks(version!, page, signal), (row) => ({
        id: row.id,
        label: '测试包 ' + row.version + (row.status === 'PUBLISHED' ? ' · 已发布' : ' · 未发布'),
        disabled: row.status !== 'PUBLISHED',
      })),
    [api, version],
  );
  return (
    <div className="testing-editor-grid">
      <PagedTaskSelect
        label="测试计划"
        load={plans}
        visible={visible}
        value={plan}
        disabled={disabled}
        change={(id) => {
          setPlan(id);
          setVersion(null);
          setPack(null);
          change(null);
        }}
      />
      {plan !== null && (
        <PagedTaskSelect
          key={'version:' + plan}
          label="固定测试计划版本"
          load={versions}
          visible={visible}
          value={version}
          disabled={disabled}
          change={(id) => {
            setVersion(id);
            setPack(null);
            change(null);
          }}
        />
      )}
      {version !== null && (
        <PagedTaskSelect
          key={'pack:' + version}
          label="已发布测试包"
          load={packs}
          visible={visible}
          value={pack}
          disabled={disabled}
          change={(id) => {
            setPack(id);
            change(id === null ? null : { plan: version, pack: id });
          }}
        />
      )}
    </div>
  );
}
