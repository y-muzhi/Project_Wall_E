import { useCallback, useState } from 'react';
import type { WalleApi } from '../../api/walle.ts';
import type { TestingReferenceSet } from '../../api/testing-assets.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { meta, Pager, ReadState, useTestingRead } from './read.tsx';

export function ReferenceSets({
  api,
  selected,
  choose,
  blocked,
}: Readonly<{
  api: WalleApi;
  selected?: string | undefined;
  choose?: ((value: TestingReferenceSet) => void) | undefined;
  blocked?: string | null | undefined;
}>) {
  const [page, setPage] = useState(1);
  const load = useCallback(
    (signal: AbortSignal) => api.testingReferenceSets(page, signal),
    [api, page],
  );
  const read = useTestingRead('reference-sets:' + page, load);
  const result = read.data;
  return (
    <section className="testing-editor-panel" aria-label="预登记参考集">
      <h4>预登记参考集</h4>
      <ReadState
        loading={read.loading}
        error={read.error}
        stale={result !== null}
        retry={read.reload}
      />
      {result && (
        <>
          {result.data.items.length === 0 && !read.loading && !read.error && (
            <EmptyState
              icon="outline"
              message={page === 1 ? '尚无预登记参考集' : '此页没有参考集'}
              compact
            />
          )}
          {result.data.items.length > 0 && (
            <ul>
              {result.data.items.map((row) => (
                <li key={row.reference_set_ref}>
                  <strong>{row.reference_set_ref}</strong>
                  {choose && (
                    <button
                      className="ui-button"
                      type="button"
                      aria-pressed={selected === row.reference_set_ref}
                      disabled={!row.ready || Boolean(blocked)}
                      title={blocked ?? (!row.ready ? '固定参考资源尚不可用' : undefined)}
                      onClick={() => choose(row)}
                    >
                      选择参考集 {row.reference_set_ref}
                    </button>
                  )}
                  <p>
                    正向样本 {row.positive_count} · 缺陷对照 {row.negative_count} · 每个样本重复{' '}
                    {row.repeat_count} 次
                  </p>
                  <p>
                    依据指纹 <code>{row.basis_fingerprint}</code>
                  </p>
                  {!row.ready && <p className="read-status">登记的固定内容暂时不可读取</p>}
                </li>
              ))}
            </ul>
          )}
          <Pager
            meta={meta(result.meta.pagination)}
            page={page}
            busy={read.loading}
            select={setPage}
          />
        </>
      )}
    </section>
  );
}
