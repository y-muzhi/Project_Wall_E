import { useCallback, useState, type FormEvent } from 'react';
import { EmptyState } from '../shared/empty-state.tsx';
import type { ManagementClient } from './api.ts';
import { priorResultInput, type PriorResultInput } from './prior-result-model.ts';
import { ReadStatus, useRead } from './ui.tsx';

type LookupProps = { client: ManagementClient; id: string };

const receiptStates = {
  SUCCEEDED: '已成功',
  REJECTED: '原请求被拒绝',
  CLOSED: '原请求已关闭',
} as const;

function PriorLookup({ client, id }: LookupProps) {
  const loadScopes = useCallback(
    (signal: AbortSignal) => client.priorResultScopes(id, signal),
    [client, id],
  );
  const scopes = useRead(id, loadScopes);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<PriorResultInput | null>(null);
  const fetchResult = useCallback(
    (signal: AbortSignal) => {
      if (!submitted) throw new TypeError('Missing original command scope');
      return client.priorResult(id, submitted, signal);
    },
    [client, id, submitted],
  );
  const result = useRead(
    id + '|' + submitted?.source_data_generation,
    fetchResult,
    submitted !== null,
  );

  function clearResult() {
    setError(null);
    setSubmitted(null);
  }

  function query(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearResult();
    if (scopes.waiting || scopes.error || result.waiting) return;
    const fields = new FormData(event.currentTarget);
    try {
      const generation = String(fields.get('generation') ?? '');
      if (!scopes.value?.includes(generation))
        throw new TypeError('Original generation unavailable');
      setSubmitted(
        priorResultInput(
          generation,
          String(fields.get('capability') ?? ''),
          String(fields.get('target') ?? ''),
          String(fields.get('key') ?? ''),
        ),
      );
    } catch {
      setError('请核对原代次、动作编号、对象标识和原请求键。');
    }
  }

  return (
    <>
      <ReadStatus state={scopes} />
      {scopes.value?.length === 0 && !scopes.error && (
        <EmptyState icon="history" compact message="当前账号暂无获准核对的原数据代次。" />
      )}
      {scopes.value && scopes.value.length > 0 && (
        <form className="command-form" onSubmit={query} onChange={clearResult}>
          <label>
            原数据代次
            <select
              name="generation"
              required
              defaultValue={scopes.value.length === 1 ? scopes.value[0] : ''}
            >
              <option value="">请选择</option>
              {scopes.value.map((generation) => (
                <option key={generation} value={generation}>
                  {generation}
                </option>
              ))}
            </select>
          </label>
          <label>
            原动作编号
            <input name="capability" maxLength={64} placeholder="APP-REQ-CMD-C01" required />
          </label>
          <label>
            原对象标识
            <input name="target" maxLength={512} required />
          </label>
          <label>
            原请求键
            <input name="key" maxLength={36} autoComplete="off" required />
          </label>
          <button
            type="submit"
            className="command-primary"
            disabled={scopes.waiting || Boolean(scopes.error) || result.waiting}
          >
            查询原代次结果
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="feedback error">
          {error}
        </p>
      )}
      <ReadStatus state={result} />
      {result.value && (
        <div className="feedback">
          <p role="status">
            {result.value.result
              ? receiptStates[result.value.result.state] +
                ' · 原请求状态码 ' +
                result.value.result.code
              : '现有资料无法核实原请求结果。'}
          </p>
          {result.value.evidence && (
            <details>
              <summary>查看封存证据摘要</summary>
              <dl className="definitions">
                <div>
                  <dt>备份清单</dt>
                  <dd>
                    <code>{result.value.evidence.backup}</code>
                  </dd>
                </div>
                <div>
                  <dt>原结果索引</dt>
                  <dd>
                    <code>{result.value.evidence.index}</code>
                  </dd>
                </div>
                <div>
                  <dt>原保全回执</dt>
                  <dd>
                    <code>{result.value.evidence.capture}</code>
                  </dd>
                </div>
              </dl>
            </details>
          )}
        </div>
      )}
    </>
  );
}

export function PriorResults(props: LookupProps) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details className="card lower" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>核对原代次请求</summary>
      {expanded && <PriorLookup {...props} />}
    </details>
  );
}
