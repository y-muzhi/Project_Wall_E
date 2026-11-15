import { useCallback, useState } from 'react';
import type { PagePagination } from '../api/client.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
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
}: Readonly<{
  label: string;
  value: number | null;
  change(id: number | null): void;
  load(page: number, signal: AbortSignal): Promise<OptionPage>;
  visible: boolean;
  disabled: boolean;
}>) {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [selectedLabel, setLabel] = useState('');
  const read = useCallback(
    (signal: AbortSignal) => {
      void retry;
      return load(page, signal);
    },
    [load, page, retry],
  );
  const state = useSettingsRead(read, visible, '暂时无法读取' + label);
  const options = state.value?.options ?? [];
  return (
    <div className="code-task-choice">
      <label>
        {label}{' '}
        <select
          aria-label={label}
          value={value ?? ''}
          disabled={disabled || state.loading || !state.value || !!state.error}
          onChange={(event) => {
            setLabel(event.target.selectedOptions[0]?.text ?? '');
            change(event.target.value ? Number(event.target.value) : null);
          }}
        >
          <option value="">请选择</option>
          {value !== null && !options.some((option) => option.id === value) && (
            <option value={value}>{selectedLabel || '原选项 #' + value}</option>
          )}
          {options.map((option) => (
            <option key={option.id} value={option.id} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {state.loading && <p role="status">正在读取{label}…</p>}
      {state.error && (
        <p role="alert">
          {state.error}{' '}
          <button
            className="ui-button"
            type="button"
            onClick={() => setRetry((value) => value + 1)}
          >
            重试读取{label}
          </button>
        </p>
      )}
      {!state.loading && !state.error && state.value && options.length === 0 && (
        <EmptyState icon="outline" message={'当前页没有' + label + '选项'} compact />
      )}
      {state.value && (
        <Pagination
          value={state.value.pagination}
          loading={state.loading}
          change={setPage}
          compactSingle
          showLoadingStatus={false}
        />
      )}
    </div>
  );
}
