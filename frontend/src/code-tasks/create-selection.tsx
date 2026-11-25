import { useCallback, useId, useState } from 'react';
import type { PagePagination } from '../api/client.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { SingleSelect } from '../shared/single-select.tsx';
import { useSettingsRead } from './settings/read.ts';

export type Option = Readonly<{ id: number; label: string; disabled?: boolean }>;
export type OptionPage = Readonly<{ options: readonly Option[]; pagination: PagePagination }>;
export function optionPage<T>(
  result: Readonly<{
    data: { items: readonly T[] };
    meta: { pagination?: unknown };
  }>,
  option: (row: T) => Option | null,
): OptionPage {
  const pagination = result.meta.pagination;
  if (!pagination || typeof pagination !== 'object' || !('page' in pagination))
    throw Error('Missing option pagination');
  return {
    options: result.data.items.flatMap((row) => {
      const mapped = option(row);
      return mapped ? [mapped] : [];
    }),
    pagination: pagination as PagePagination,
  };
}

export function PagedTaskSelect({
  label,
  value,
  change,
  load,
  visible,
  disabled,
  emptyMessage,
}: Readonly<{
  label: string;
  value: number | null;
  change(id: number | null): void;
  load(page: number, signal: AbortSignal): Promise<OptionPage>;
  visible: boolean;
  disabled: boolean;
  emptyMessage?: string;
}>) {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [selection, setSelection] = useState<{ id: number; label: string } | null>(null);
  const controlId = useId();
  const read = useCallback(
    (signal: AbortSignal) => {
      void retry;
      return load(page, signal);
    },
    [load, page, retry],
  );
  const state = useSettingsRead(read, visible, '暂时无法读取' + label);
  const result = state.value?.pagination.page === page ? state.value : null;
  const loading = state.loading || (result === null && state.error === null);
  const options = result?.options ?? [];
  const selected = value === null ? '' : String(value);
  const items = options.map((option) => ({
    value: String(option.id),
    label: option.label,
    disabled: option.disabled ?? false,
  }));
  if (value !== null && !options.some((item) => item.id === value)) {
    items.unshift({
      value: selected,
      label: selection?.id === value ? selection.label : '原选项 #' + value,
      disabled: true,
    });
  }
  if (options.length > 0 || value !== null)
    items.unshift({ value: '', label: '请选择', disabled: false });
  const noOptions = !loading && !state.error && result !== null && options.length === 0;
  const empty =
    page > 1 || (result?.pagination.total ?? 0) > 0
      ? '此页没有可选的' + label
      : (emptyMessage ?? '暂无可选的' + label);
  return (
    <div className="code-task-choice code-drawer-field">
      <label htmlFor={controlId}>{label}</label>
      <SingleSelect
        id={controlId}
        label={label}
        value={selected}
        options={items}
        placeholder={loading ? '正在读取…' : state.error ? '暂时不可用' : '请选择'}
        disabled={disabled || loading || !!state.error}
        describedBy={noOptions || state.error || loading ? controlId + '-status' : undefined}
        change={(next) => {
          const option = options.find((item) => String(item.id) === next);
          setSelection(option ? { id: option.id, label: option.label } : null);
          change(option?.id ?? null);
        }}
      />
      {loading && (
        <p className="read-status" id={controlId + '-status'} role="status">
          正在读取{label}…
        </p>
      )}
      {state.error && (
        <div className="code-task-toolbar">
          <span className="inline-error" id={controlId + '-status'} role="alert">
            {state.error}
          </span>
          <button
            className="ui-button"
            type="button"
            disabled={disabled}
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取{label}
          </button>
        </div>
      )}
      {noOptions && (
        <div className="code-choice-empty" id={controlId + '-status'}>
          <EmptyState icon="outline" message={empty} compact />
        </div>
      )}
      {state.value && (state.value.pagination.total_pages > 1 || page > 1) && (
        <Pagination
          value={state.value.pagination}
          loading={loading || disabled}
          change={setPage}
          showLoadingStatus={false}
        />
      )}
    </div>
  );
}
