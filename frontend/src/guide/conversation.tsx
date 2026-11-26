import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { RequirementConversation } from './conversation-owner.ts';
import type { RequirementDiscussion } from '../requirements/discussion.ts';
import type { RequirementDocumentOwner } from '../requirements/document-owner.ts';
import type { DetailLayout } from '../requirements/detail-layout.ts';
import type { ToastStore } from '../shared/toast-store.ts';
import { AiReadPanel } from './read-view.tsx';
import { RunControls } from './run-controls.tsx';
import { GuideComposer } from './composer-view.tsx';
import { CardMessage } from './card-message.tsx';
import { SuggestionPanel } from '../suggestions/panel.tsx';
import { SuggestionTargetLocator } from '../suggestions/targets.ts';
import { ModelCallsProvider } from './model-call-view.tsx';
import { EmptyState } from '../shared/empty-state.tsx';

function BatchView({
  owner,
  documents,
  layout,
  toasts,
}: Readonly<{
  owner: NonNullable<ReturnType<RequirementConversation['getSnapshot']>['batch']>;
  documents: RequirementDocumentOwner;
  layout: DetailLayout;
  toasts: ToastStore;
}>) {
  const [selectedMark, selectMark] = useState<Readonly<{ identity: number }> | null>(null);
  const locator = useMemo(
    () =>
      new SuggestionTargetLocator(
        owner,
        () => documents.currentBinding,
        () => documents.historyBinding,
        (identity) => {
          if (!layout.getSnapshot().right_open) layout.openTab('SUGGESTIONS');
          selectMark({ identity });
        },
        () => {
          const view = layout.getSnapshot();
          return !view.split_view && view.document_open && view.right_tab === 'SUGGESTIONS';
        },
      ),
    [owner, documents, layout],
  );
  const viewing = useSyncExternalStore(documents.subscribe, documents.getSnapshot);
  const versionRequest = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      versionRequest.current?.abort();
      locator.dispose();
    },
    [locator],
  );
  const revealDocument = async () => {
    if (layout.getSnapshot().document_open) return;
    layout.showDocument();
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  };
  const locate = async (identity: number) => {
    await revealDocument();
    const view = layout.getSnapshot();
    const located = locator.locate(identity, !view.split_view && view.document_open);
    if (!located && !view.right_open && view.document_open) layout.openTab('SUGGESTIONS');
    return located;
  };
  const openVersion = async (kind: 'BASE' | 'APPLIED') => {
    versionRequest.current?.abort();
    const controller = new AbortController();
    versionRequest.current = controller;
    try {
      const revision = await owner.readReviewRevision(kind, controller.signal);
      if (controller.signal.aborted) return false;
      const { markdown_content: _markdown, block_state_json: _blocks, ...summary } = revision;
      const opened = await documents.openHistory(summary, revision);
      if (opened) await revealDocument();
      return opened;
    } finally {
      if (versionRequest.current === controller) versionRequest.current = null;
    }
  };
  return (
    <SuggestionPanel
      owner={owner}
      locate={locate}
      openVersion={openVersion}
      closeVersion={async () => {
        const closed = await documents.exitHistory();
        if (closed) await revealDocument();
        return closed;
      }}
      viewingVersion={viewing.revision?.id ?? null}
      selectedMark={selectedMark}
      notify={(message) => toasts.push('success', message)}
    />
  );
}

/** The original batch owner stays mounted in its own top-level panel. */
export function ConversationSuggestions({
  owner,
  documents,
  layout,
  toasts,
}: Readonly<{
  owner: RequirementConversation;
  documents: RequirementDocumentOwner;
  layout: DetailLayout;
  toasts: ToastStore;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    batch = state.batch;
  return (
    <div className="conversation-suggestions">
      {state.pendingBatchRead === 'ERROR' && (
        <p className="inline-error" role="alert">
          暂时无法读取当前文档的修改建议。
          <button
            className="ui-button"
            type="button"
            onClick={() => void owner.refreshPendingBatch()}
          >
            重试读取
          </button>
        </p>
      )}
      {batch ? (
        <BatchView
          key={batch.batchId}
          owner={batch}
          documents={documents}
          layout={layout}
          toasts={toasts}
        />
      ) : state.detail.selected_document_id === null ? (
        <EmptyState icon="suggestion" message="请选择文档查看修改建议" fill />
      ) : state.pendingBatchRead === 'READY' && state.pendingBatchId === null ? (
        <EmptyState icon="suggestion" message="暂无待审阅的修改建议" fill />
      ) : state.pendingBatchRead === 'LOADING' ? (
        <p className="read-status" role="status">
          正在读取修改建议…
        </p>
      ) : null}
    </div>
  );
}

/** AI keeps its message and composer owners independently of review visibility. */
export function GuideConversation({
  owner,
  documents,
  associations,
  handoff,
  discussion,
  openSuggestions,
}: Readonly<{
  owner: RequirementConversation;
  documents: RequirementDocumentOwner;
  associations?: ReactNode;
  handoff?: ReactNode;
  discussion: RequirementDiscussion;
  openSuggestions: () => void;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    read = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot),
    document = useSyncExternalStore(documents.subscribe, documents.getSnapshot);
  const [scrollPort, setScrollPort] = useState<HTMLDivElement | null>(null),
    [scrollContent, setScrollContent] = useState<HTMLDivElement | null>(null);
  // Retry display when the actual editor/parser becomes available or changes.
  // This only creates DOM fragments and never adopts content as CURRENT.
  const renderMarkdown = useCallback(
    (markdown: string) => documents.previewMarkdown(markdown),
    [documents, document.navigation],
  );
  return (
    <ModelCallsProvider
      cache={owner.modelCalls}
      api={owner.modelCallApi}
      requirementId={state.detail.requirement.id}
      active={state.visible && state.enabled}
      current={read.run}
    >
      <section className="guide-conversation" aria-label="需求 AI 辅助区">
        <div className="conversation-workspace">
          <div className="conversation-reading-region">
            <div
              className="conversation-discussion"
              ref={setScrollPort}
              role="region"
              aria-label="对话阅读区"
              tabIndex={0}
            >
              <div className="conversation-content" ref={setScrollContent}>
                <AiReadPanel
                  scrollPort={scrollPort}
                  scrollContent={scrollContent}
                  owner={owner.read}
                  openSuggestions={(id) => {
                    owner.openBatch(id);
                    openSuggestions();
                  }}
                  structured={(message) => (
                    <CardMessage
                      groups={owner.cards}
                      message={message}
                      documents={documents}
                      renderMarkdown={renderMarkdown}
                      busy={document.busy}
                    />
                  )}
                  commands={() => <RunControls owner={owner.runs} />}
                  renderMarkdown={renderMarkdown}
                />
              </div>
            </div>
          </div>
          <GuideComposer
            owner={owner.composer}
            documents={documents}
            associations={associations}
            handoff={handoff}
            discussion={discussion}
            review={read.run}
            viewingHistory={read.selection === 'HISTORY' ? read.selected : null}
          />
        </div>
      </section>
    </ModelCallsProvider>
  );
}
