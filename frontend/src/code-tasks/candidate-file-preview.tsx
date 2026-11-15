import { useEffect, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CandidateComparisonSide, CodeCandidateDiff } from '../api/code-task-candidates.ts';
import { decodeCandidateBytes } from '../api/code-task-candidates.ts';
import type { WalleApi } from '../api/walle.ts';

type Scope = Readonly<{
  api: WalleApi;
  taskId: number;
  candidateId: number;
  filePath: string;
  item?: CodeCandidateDiff | undefined;
  planId?: number;
}>;
const baselineLabels = { BEFORE: '起点 Git 版本', AFTER: '待验收代码' };
const deliveryLabels = { BEFORE: '固定目标', AFTER: '候选结果' };
const chunkSize = 65536;
const comparisonLimit = 2 * 1024 * 1024;
const lineLimit = 20000;

type SideResult = Readonly<{
  exists: boolean;
  text: string;
  binary: boolean;
  total: number | null;
  next: number | null;
}>;

function useCandidateSide(
  { api, taskId, candidateId, filePath, item, planId }: Scope,
  side: CandidateComparisonSide,
  visible: boolean,
) {
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [value, setValue] = useState<SideResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const decoder = useRef<TextDecoder | null>(null);
  const saved = useRef<{ offset: number; value: SideResult } | null>(null);
  const expectedTotal = side === 'BEFORE' ? item?.before_size : item?.after_size;
  const knownBinary = item?.binary === true;
  useEffect(() => {
    if (!visible || knownBinary || saved.current?.offset === offset) return;
    const request = new AbortController();
    setLoading(true);
    setError(null);

    async function read() {
      try {
        const response =
          planId === undefined
            ? await api.codeTaskCandidateComparison(
                taskId,
                candidateId,
                filePath,
                side,
                offset,
                chunkSize,
                request.signal,
              )
            : await api.deliveryFile(
                taskId,
                planId,
                candidateId,
                filePath,
                side,
                offset,
                chunkSize,
                request.signal,
              );
        if (request.signal.aborted) return;
        const row = response.data;
        if (
          expectedTotal !== undefined &&
          (row.total_bytes !== expectedTotal || row.exists !== (expectedTotal !== null))
        )
          throw new Error('原固定文件与差异清单不一致');
        const previous = saved.current?.value;
        let text = '';
        let binary = previous?.binary ?? false;
        if (row.content_base64 !== null && !binary) {
          try {
            const bytes = decodeCandidateBytes(row.content_base64);
            if (bytes.includes(0)) throw new TypeError('Unexpected binary content');
            decoder.current ??= new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
            const chunk = decoder.current.decode(bytes, { stream: row.next_offset !== null });
            text =
              (row.total_bytes ?? 0) > comparisonLimit ? chunk : (previous?.text ?? '') + chunk;
          } catch {
            binary = true;
          }
        }
        const next: SideResult = {
          exists: row.exists,
          text,
          binary,
          total: row.total_bytes,
          next: binary ? null : row.next_offset,
        };
        saved.current = { offset, value: next };
        setValue(next);
      } catch (error: unknown) {
        if (!request.signal.aborted)
          setError(
            error instanceof ApiRejected && error.code === 'CONTENT_NOT_READY'
              ? '固定代码暂不可用，请核对原操作'
              : error instanceof ApiRejected && error.code === 'NOT_FOUND'
                ? '所选路径不在这份固定差异中'
                : error instanceof ApiRejected || error instanceof ApiUnknown
                  ? error.message
                  : '暂时无法读取所选文件',
          );
      } finally {
        if (!request.signal.aborted) setLoading(false);
      }
    }

    void read();
    return () => request.abort();
  }, [
    api,
    taskId,
    candidateId,
    planId,
    filePath,
    knownBinary,
    side,
    offset,
    retry,
    visible,
    expectedTotal,
  ]);
  return {
    value,
    loading,
    error,
    next: () => {
      if (value?.next !== null && value?.next !== undefined) setOffset(value.next);
    },
    retry: () => setRetry((current) => current + 1),
  };
}

function splitLines(text: string) {
  return text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
}

function lineSections(before: string, after: string) {
  const left = splitLines(before);
  const right = splitLines(after);
  if (left.length + right.length > lineLimit) return null;
  let start = 0;
  while (start < Math.min(left.length, right.length) && left[start] === right[start]) start++;
  let suffix = 0;
  while (
    suffix < Math.min(left.length, right.length) - start &&
    left[left.length - suffix - 1] === right[right.length - suffix - 1]
  )
    suffix++;
  return {
    prefix: left
      .slice(0, start)
      .map((line) => '  ' + line)
      .join(''),
    removed: left
      .slice(start, left.length - suffix)
      .map((line) => '- ' + line)
      .join(''),
    added: right
      .slice(start, right.length - suffix)
      .map((line) => '+ ' + line)
      .join(''),
    suffix: left
      .slice(left.length - suffix)
      .map((line) => '  ' + line)
      .join(''),
  };
}

function CompleteComparison({
  before,
  after,
  labels,
}: {
  before: SideResult;
  after: SideResult;
  labels: Readonly<Record<CandidateComparisonSide, string>>;
}) {
  if ((before.total ?? 0) + (after.total ?? 0) > comparisonLimit)
    return <p>文件超过完整行差异范围，仅显示已加载部分。</p>;
  const result = lineSections(before.text, after.text);
  if (!result) return <p>文件超过完整行差异范围，仅显示已加载部分。</p>;
  return (
    <div className="code-candidate-file__comparison" aria-label="完整行差异">
      <pre className="code-candidate-file__unified">
        {result.prefix}
        {result.removed && <span className="code-candidate-file__removed">{result.removed}</span>}
        {result.removed && result.added && !result.removed.endsWith('\n') && '\n'}
        {result.added && <span className="code-candidate-file__added">{result.added}</span>}
        {result.suffix}
      </pre>
      <div className="code-candidate-file__columns">
        <section aria-label={labels.BEFORE}>
          <h5>{labels.BEFORE}</h5>
          <pre>{before.text}</pre>
        </section>
        <section aria-label={labels.AFTER}>
          <h5>{labels.AFTER}</h5>
          <pre>{after.text}</pre>
        </section>
      </div>
    </div>
  );
}

export function CandidateFilePreview(props: Scope & { visible: boolean; close(): void }) {
  const { filePath, item, planId, visible, close } = props;
  const labels = planId === undefined ? baselineLabels : deliveryLabels;
  const [side, setSide] = useState<CandidateComparisonSide>(
    planId !== undefined || item?.change === 'DELETE' ? 'BEFORE' : 'AFTER',
  );
  const [comparison, setComparison] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const before = useCandidateSide(props, 'BEFORE', visible && side === 'BEFORE');
  const after = useCandidateSide(props, 'AFTER', visible && side === 'AFTER');
  const reader = side === 'BEFORE' ? before : after;
  const value = reader.value;
  const complete =
    before.value?.next === null &&
    after.value?.next === null &&
    !before.value.binary &&
    !after.value.binary
      ? { before: before.value, after: after.value }
      : null;
  const binary = item?.binary || value?.binary;
  const binarySize = item ? (side === 'BEFORE' ? item.before_size : item.after_size) : value?.total;
  const partial = value?.next !== null || (value?.total ?? 0) > comparisonLimit;

  function selectSide(next: CandidateComparisonSide) {
    setSide(next);
    setCopyStatus(null);
    setComparison(false);
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('已复制显示内容。');
    } catch {
      setCopyStatus('暂时无法复制显示内容。');
    }
  }

  return (
    <section
      className="code-candidate-file"
      aria-label={planId === undefined ? '所选文件内容' : '原文件对比'}
      aria-busy={reader.loading}
    >
      <h5>{filePath}</h5>
      <div className="code-candidate-file__actions">
        {(['BEFORE', 'AFTER'] as const).map((name) => (
          <button
            key={name}
            className="ui-button"
            type="button"
            aria-pressed={name === side}
            onClick={() => selectSide(name)}
          >
            {labels[name]}
          </button>
        ))}
        <button type="button" className="ui-button" onClick={close}>
          {planId === undefined ? '关闭文件' : '关闭对比'}
        </button>
        {complete && (
          <button
            className="ui-button"
            type="button"
            aria-pressed={comparison}
            onClick={() => setComparison((shown) => !shown)}
          >
            完整行差异
          </button>
        )}
      </div>
      {!binary && !reader.error && (reader.loading || value === null) && (
        <p role="status">正在读取原文件…</p>
      )}
      {reader.error && (
        <p role="alert" className="inline-error">
          {reader.error}{' '}
          <button className="ui-button" type="button" onClick={reader.retry}>
            重试读取文件
          </button>
        </p>
      )}
      {binary ? (
        <p>
          {binarySize === null
            ? '该比较版本中没有此文件。'
            : '二进制文件 · ' + binarySize + ' 字节'}
        </p>
      ) : comparison && complete ? (
        <CompleteComparison {...complete} labels={labels} />
      ) : (
        value && (
          <>
            {!value.exists ? (
              <p>
                {planId === undefined ? '该比较版本中没有此文件。' : labels[side] + '中无此文件。'}
              </p>
            ) : value.total === 0 ? (
              <p>此文件为空。</p>
            ) : (
              <>
                {partial && <p>仅显示已加载部分</p>}
                <pre aria-label={labels[side] + '的原文'}>{value.text}</pre>
                {value.text && (
                  <button className="ui-button" type="button" onClick={() => void copy(value.text)}>
                    {partial ? '复制已加载内容' : '复制文件内容'}
                  </button>
                )}
              </>
            )}
            {value.next !== null && !reader.error && (
              <button
                className="ui-button"
                type="button"
                disabled={reader.loading}
                onClick={reader.next}
              >
                {reader.loading ? '正在读取下一块' : '继续读取'}
              </button>
            )}
          </>
        )
      )}
      {copyStatus && <p role="status">{copyStatus}</p>}
    </section>
  );
}
