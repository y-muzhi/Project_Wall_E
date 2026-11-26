import { useEffect, useState } from 'react';
import type { EnvironmentScope } from '../api/environment-binding.ts';
import { CommandRecoveryStore } from '../code-tasks/command-recovery-store.ts';
import type { ApplicationRouter } from './router.ts';
import type { RequirementDetailOwner } from '../requirements/detail-owner.ts';

type Draft = Readonly<{
  protected: boolean;
  text: string | null;
  originalMarkdown: boolean;
  pending: number;
}>;
type Recovery = Readonly<{
  draft: Draft | null;
  creationInput: boolean;
  pending: number | null;
}>;

export function ScopeRecovery({
  scope,
  router,
  detailOwner,
}: Readonly<{
  scope: EnvironmentScope;
  router: ApplicationRouter;
  detailOwner: RequirementDetailOwner | null;
}>) {
  const [result, setResult] = useState<Recovery | null>(null);
  useEffect(() => {
    let alive = true;
    async function check(): Promise<void> {
      const route = router.getSnapshot();
      const detail =
        route.route.kind === 'DETAIL' &&
        detailOwner?.getSnapshot().detail?.requirement.id === route.route.id
          ? detailOwner
          : null;
      const session = detail?.documents.getSnapshot().manual;
      const draft = session ? await session.scopeRecoverySnapshot() : null;
      const creation = route.creation;
      const store = new CommandRecoveryStore({ scope });
      let pending: number | null;
      try {
        const storedCommands = await store.list();
        const regions = detail?.regions;
        const directoryPhase = regions?.directory.getSnapshot().phase;
        const historyRestore = detail?.documents.getSnapshot().restore;
        pending =
          storedCommands.length +
          (draft?.pending ?? 0) +
          Number(!!creation && (creation.state.unknown || creation.state.busy)) +
          Number(directoryPhase === 'SUBMITTING' || directoryPhase === 'UNKNOWN') +
          (regions?.header.pendingScopeOperations ?? 0) +
          Number(historyRestore?.awaitingOriginalResult === true);
      } catch {
        pending = null;
      } finally {
        store.close();
      }
      if (alive) setResult({ draft, pending, creationInput: !!creation?.hasInput });
    }
    void check();
    return () => {
      alive = false;
    };
  }, [scope, router, detailOwner]);

  function exportDraft(): void {
    const draft = result?.draft;
    if (!draft || draft.text === null) return;
    const label = [
      'WALL-E 人工草稿',
      '来源 ' + scope.origin,
      '环境 ' + scope.environment_id,
      '数据代次 ' + scope.data_generation,
      draft.originalMarkdown ? '内容为原草稿 Markdown' : '当前正文显示为纯文本，请核对排版',
      '',
      '',
    ].join('\n');
    const file = new Blob([label, draft.text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'walle-' + scope.environment_id + '-' + scope.data_generation + '.txt';
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  if (!result) return <p role="status">正在核对原草稿的本机保护和待确认操作…</p>;
  return (
    <>
      {result.draft && (
        <p>
          {result.draft.protected
            ? '已核对当前草稿的本机保护。'
            : '当前草稿的本机保护未确认，请保留此页并导出正文。'}
        </p>
      )}
      {result.creationInput && <p>新建需求输入仍留在当前页面。</p>}
      <p>
        {result.pending === null
          ? '原待确认操作数量暂时无法核对。'
          : `原待确认操作 ${result.pending} 项。`}
      </p>
      <div className="application-entry-actions">
        {result.draft && result.draft.text !== null && (
          <button type="button" className="ui-button" onClick={exportDraft}>
            导出原草稿
          </button>
        )}
        <a className="ui-button" href="/" target="_blank" rel="noopener noreferrer">
          在新标签进入当前环境
        </a>
      </div>
    </>
  );
}
