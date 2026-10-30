import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { RequirementConversation } from './conversation-owner.ts';
import type { RequirementDocumentOwner } from '../requirements/document-owner.ts';
import type { ToastStore } from '../shared/toast-store.ts';
import { AiReadPanel } from './read-view.tsx';
import { RunControls } from './run-controls.tsx';
import { GuideComposer } from './composer-view.tsx';
import { CardMessage } from './card-message.tsx';
import { SuggestionPanel } from '../suggestions/panel.tsx';
import { SuggestionTargetLocator } from '../suggestions/targets.ts';
import { ModelCallsProvider } from './model-call-view.tsx';

function BatchView({
  owner,
  documents,
  toasts,
}: Readonly<{
  owner: NonNullable<ReturnType<RequirementConversation['getSnapshot']>['batch']>;
  documents: RequirementDocumentOwner;
  toasts: ToastStore;
}>) {
  const locator = useMemo(
    () => new SuggestionTargetLocator(owner, () => documents.currentBinding),
    [owner, documents],
  );
  useEffect(() => () => locator.dispose(), [locator]);
  const render = useCallback(
    (markdown: string, columns?: number) => {
      return documents.previewMarkdown(markdown, columns);
    },
    [documents],
  );
  return (
    <SuggestionPanel
      owner={owner}
      render={render}
      locate={(identity) => locator.locate(identity)}
      notify={(message) => toasts.push('success', message)}
    />
  );
}

/** The original batch owner stays mounted in its own top-level panel. */
export function ConversationSuggestions({
  owner,
  documents,
  toasts,
}: Readonly<{
  owner: RequirementConversation;
  documents: RequirementDocumentOwner;
  toasts: ToastStore;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    batch = state.batch;
  return (
    <div className="conversation-suggestions">
      {batch ? (
        <BatchView key={batch.batchId} owner={batch} documents={documents} toasts={toasts} />
      ) : (
        <section className="suggestions-empty">
          <h2>暂无修改建议</h2>
          <p>提出修改建议后，可在这里审阅并处理。</p>
        </section>
      )}
    </div>
  );
}

/** AI keeps its message and composer owners independently of review visibility. */
export function GuideConversation({
  owner,
  documents,
}: Readonly<{ owner: RequirementConversation; documents: RequirementDocumentOwner }>) {
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
                  structured={(message) => (
                    <CardMessage
                      groups={owner.cards}
                      message={message}
                      documents={documents}
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
            review={read.run}
            viewingHistory={read.selection === 'HISTORY' ? read.selected : null}
          />
        </div>
      </section>
    </ModelCallsProvider>
  );
}
