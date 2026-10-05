import type { PagePagination } from '../api/client.ts';

export function pageNumbers(current: number, total: number): readonly (number | 'ellipsis')[] {
  if (!total) return [];
  const selected = new Set([1, total]);
  const center = Math.min(current, total);
  for (let page = Math.max(1, center - 2); page <= Math.min(total, center + 2); page++) selected.add(page);
  const result: (number | 'ellipsis')[] = [];
  for (const page of [...selected].sort((left, right) => left - right)) {
    const previous = result.at(-1); if (typeof previous === 'number' && page > previous + 1) result.push('ellipsis'); result.push(page);
  }
  return result;
}
export function Pagination({ value, loading, error, change, retry }: Readonly<{ value: PagePagination; loading: boolean; error?: string | null; change(page: number): void; retry?(): void }>) {
  const { page, page_size, total, total_pages } = value;
  if (!Number.isSafeInteger(page) || page < 1 || page_size !== 20 || !Number.isSafeInteger(total) || total < 0 || total_pages !== Math.ceil(total / 20)) throw new TypeError('Actual pagination required');
  const select = (target: number) => { if (!loading && target !== page && target >= 1 && target <= Math.max(1, total_pages)) change(target); };
  return <div className="pagination" aria-busy={loading}>
    <span>{total === 0 ? '暂无记录' : `共 ${total} 条`} · 第 {page} 页 / 共 {total_pages} 页 · 每页 20 条</span>
    <nav aria-label="分页"><button type="button" aria-label="上一页" disabled={loading || page <= 1 || total_pages === 0} onClick={() => select(Math.min(page - 1, total_pages))}>‹</button>
      {pageNumbers(page, total_pages).map((number, index) => number === 'ellipsis' ? <span key={'gap-' + index} aria-hidden="true">…</span> :
        <button type="button" key={number} aria-label={'第 ' + number + ' 页'} aria-current={number === page ? 'page' : undefined} disabled={loading || number === page} onClick={() => select(number)}>{number}</button>)}
      <button type="button" aria-label="下一页" disabled={loading || page >= total_pages} onClick={() => select(page + 1)}>›</button>
      {page > Math.max(1, total_pages) && <button type="button" disabled={loading} onClick={() => select(Math.max(1, total_pages))}>返回有效页</button>}
    </nav>{loading && <span role="status">正在加载</span>}{error && <p role="alert" className="inline-error">! {error} {retry && <button type="button" disabled={loading} onClick={retry}>重试</button>}</p>}
  </div>;
}
