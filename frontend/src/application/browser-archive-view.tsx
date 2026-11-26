import { useEffect, useId, useState, type ReactNode } from 'react';
import type { EnvironmentScope } from '../api/environment-binding.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import {
  readArchivedDraft,
  readBrowserArchive,
  type ArchiveScan,
  type ArchivedDraftValidator,
} from './browser-archive.ts';

type ArchiveEntry = ArchiveScan['entries'][number];
type DraftEntry = Extract<ArchiveEntry, { kind: 'DRAFT' }>;
type ScanState =
  { phase: 'LOADING' } | { phase: 'UNAVAILABLE' } | { phase: 'READY'; result: ArchiveScan };
type PreviewState =
  { phase: 'LOADING' } | { phase: 'UNAVAILABLE' } | { phase: 'READY'; markdown: string };
const statusLabels = {
  PREPARED: '待提交',
  DISPATCHING: '提交中',
  ACCEPTED: '已接收，待核对',
  UNKNOWN: '结果待核实',
};

function scopeLabel(scope: EnvironmentScope | null): string {
  return scope
    ? '旧环境记录 · 环境 ' + scope.environment_id + ' · 数据代次 ' + scope.data_generation
    : '未绑定的旧版本记录';
}

function download(entry: DraftEntry, markdown: string, origin: string): void {
  const name = entry.scope
    ? 'walle-' + entry.scope.environment_id + '-' + entry.scope.data_generation
    : 'walle-unbound-draft';
  const text = ['WALL-E 人工草稿', '来源 ' + origin, scopeLabel(entry.scope), '', markdown].join(
    '\n',
  );
  const address = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = address;
  link.download = name + '.txt';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(address), 0);
}

function DraftPreview({
  entry,
  origin,
  validate,
}: Readonly<{
  entry: DraftEntry;
  origin: string;
  validate: ArchivedDraftValidator;
}>) {
  const [state, setState] = useState<PreviewState>({ phase: 'LOADING' });
  useEffect(() => {
    let live = true;
    void readArchivedDraft(entry, validate).then(
      (markdown) => {
        if (live) setState({ phase: 'READY', markdown });
      },
      () => {
        if (live) setState({ phase: 'UNAVAILABLE' });
      },
    );
    return () => {
      live = false;
    };
  }, [entry, validate]);
  if (state.phase === 'LOADING') return <p role="status">正在核对草稿正文…</p>;
  if (state.phase === 'UNAVAILABLE')
    return <p role="alert">草稿已变化、损坏或暂时无法读取。可关闭后重新检查。</p>;
  return (
    <div>
      <pre aria-label="旧草稿正文" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {state.markdown}
      </pre>
      <button
        className="ui-button"
        type="button"
        onClick={() => download(entry, state.markdown, origin)}
      >
        导出旧草稿
      </button>
    </div>
  );
}

function ArchiveContents({
  scope,
  validate,
}: Readonly<{
  scope: EnvironmentScope;
  validate: ArchivedDraftValidator;
}>) {
  const [state, setState] = useState<ScanState>({ phase: 'LOADING' });
  const [selected, select] = useState<DraftEntry | null>(null);
  useEffect(() => {
    let live = true;
    void readBrowserArchive(scope).then(
      (result) => {
        if (live) setState({ phase: 'READY', result });
      },
      () => {
        if (live) setState({ phase: 'UNAVAILABLE' });
      },
    );
    return () => {
      live = false;
    };
  }, [scope]);
  if (state.phase === 'LOADING') return <p role="status">正在检查本机旧记录…</p>;
  if (state.phase === 'UNAVAILABLE') return <p role="alert">浏览器暂时无法检查本机旧记录。</p>;
  const { entries, damaged, unreadable, truncated } = state.result;
  if (!entries.length && !damaged && !unreadable && !truncated)
    return <EmptyState icon="history" message="当前网址没有可查看的本机旧记录。" compact />;
  return (
    <>
      {damaged > 0 && <p role="alert">有 {damaged} 条本机记录无法核对，原记录已保留。</p>}
      {unreadable > 0 && <p role="alert">有 {unreadable} 个本机库暂时无法读取。</p>}
      {truncated && <p role="alert">本机记录超出检查上限，部分条目未核对。</p>}
      {entries.length > 0 && (
        <ul>
          {entries.map((entry) => (
            <li
              key={
                (entry.kind === 'DRAFT' ? entry.source.name : 'command') +
                JSON.stringify([entry.scope, entry.key])
              }
            >
              <p style={{ overflowWrap: 'anywhere' }}>{scopeLabel(entry.scope)}</p>
              {entry.kind === 'COMMAND' ? (
                <p style={{ overflowWrap: 'anywhere' }}>
                  {entry.action} · {statusLabels[entry.state]} · {entry.key}
                </p>
              ) : (
                <>
                  <p>
                    人工草稿 · 基于版本 {entry.version} · {localTime(entry.updatedAt)}
                  </p>
                  <button
                    className="ui-button"
                    type="button"
                    aria-expanded={selected === entry}
                    onClick={() => select(selected === entry ? null : entry)}
                  >
                    {selected === entry ? '收起草稿' : '查看草稿'}
                  </button>
                  {selected === entry && (
                    <DraftPreview entry={entry} origin={scope.origin} validate={validate} />
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function BrowserArchive({
  scope,
  validate,
  children,
}: Readonly<{
  scope: EnvironmentScope;
  validate: ArchivedDraftValidator;
  children: ReactNode;
}>) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section className="application-warning" aria-label="环境状态">
      <div className="environment-overview">
        {children}
        <button
          className="ui-button"
          type="button"
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          onClick={() => setOpen(!open)}
        >
          {open ? '关闭本机恢复' : '本机恢复'}
        </button>
      </div>
      {open && (
        <div id={id} role="region" aria-label="本机旧记录" tabIndex={0} className="browser-archive">
          <ArchiveContents scope={scope} validate={validate} />
        </div>
      )}
    </section>
  );
}
