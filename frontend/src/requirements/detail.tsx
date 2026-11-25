import { REQUIREMENT_STATUS_LABELS, saveStatusLabel } from '../shared/status-labels.ts';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { WalleApi } from '../api/walle.ts';
import { DocumentHandoff } from './document-handoff.tsx';
import type { DocumentHandoffEntry, DocumentReading } from '../application/router.ts';
import { RequirementDetailOwner } from './detail-owner.ts';
import { DetailFrame } from './detail-frame.tsx';
import { RequirementHeader } from './header.tsx';
import { RequirementPropertyControl } from './property-control.tsx';
import { OwnedDocumentControls } from './document-controls.tsx';
import {
  DocumentCreationProvider,
  DocumentDirectory,
  DocumentMetadataBar,
  NewDocumentButton,
} from './document-directory-view.tsx';
import { CommentPanel, CommentDocumentTools } from '../comments/panel.tsx';
import { RevisionList, RevisionSaveControl } from '../revisions/components.tsx';
import { GuideConversation, ConversationSuggestions } from '../guide/conversation.tsx';
import { Confirmation } from '../shared/confirmation.tsx';
import { ToastViewport } from '../shared/toast.tsx';
import { localTime } from '../shared/time.ts';
import { DocumentRecords } from './document-records.tsx';
import { FormationProgress } from '../formation/progress-view.tsx';
import { DocumentAssociations } from './document-associations.tsx';
import { activeModal } from '../shared/modal.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import type { EmptyStateContent } from '../shared/empty-state.tsx';

type OpenCodeTasks = (
  requirementId: number,
  reading: DocumentReading,
  source?: DocumentReading | null,
) => void;

function DocumentMount({
  host,
  empty,
}: Readonly<{ host: HTMLElement; empty: EmptyStateContent | null }>) {
  const container = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    container.current!.append(host);
    return () => host.remove();
  }, [host]);
  return (
    <div className="detail-document-host">
      <div className="detail-editor-mount" ref={container} hidden={empty !== null} />
      {empty && <EmptyState {...empty} fill />}
    </div>
  );
}
function SaveStatus({ owner }: Readonly<{ owner: RequirementDetailOwner }>) {
  const state = useSyncExternalStore(owner.documents.subscribe, owner.documents.getSnapshot);
  const version = state.detail?.current?.content_version,
    identity =
      state.mode === 'EMPTY'
        ? '尚无文档'
        : state.mode === 'HISTORY'
          ? state.revision
            ? `历史版本 V${state.revision.version_no} · 来源正文 v${state.revision.source_content_version} · 只读`
            : '历史版本 · 只读'
          : state.mode === 'MANUAL'
            ? `人工草稿 · 基于正式正文 v${version}`
            : `正式正文 v${version} · 只读`;
  const activity = state.detail?.activity,
    task =
      state.mode === 'CURRENT'
        ? activity?.kind === 'GUIDE'
          ? 'AI 运行中'
          : activity?.kind === 'BATCH'
            ? '建议待处理 · 尚未应用'
            : null
        : null;
  return (
    <div className="document-view-status">
      <span>{identity}</span>
      {task && <span className="task-state">{task}</span>}
      {state.manual && (
        <ManualSaveStatus session={state.manual} retained={state.mode === 'HISTORY'} />
      )}
    </div>
  );
}
function ManualSaveStatus({
  session,
  retained,
}: Readonly<{
  session: NonNullable<ReturnType<RequirementDetailOwner['documents']['getSnapshot']>['manual']>;
  retained: boolean;
}>) {
  const state = useSyncExternalStore(
      (listener) => session.autosave.subscribe(() => listener()),
      () => session.autosave.state,
    ),
    manual = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const recovery = useSyncExternalStore(session.recovery.subscribe, session.recovery.getSnapshot),
    ending = useSyncExternalStore(session.ending.subscribe, session.ending.getSnapshot);
  return (
    <span role="status">
      {retained ? '保留草稿：' : ''}
      {saveStatusLabel(state.status, manual.valid)}
      {manual.valid && state.status === 'SAVED' ? ' · ' + localTime(state.saved_at) : ''}
      {!retained &&
      ending.phase === 'EDITING' &&
      !['RESTORED', 'SERVER_SELECTED'].includes(recovery.phase)
        ? recovery.checking
          ? ' · 正在检查草稿'
          : recovery.local
            ? ' · 待处理恢复内容'
            : ' · 编辑恢复受阻'
        : ''}
    </span>
  );
}
function LoadedDetail({
  owner,
  api,
  host,
  back,
  openCodeTasks,
  choosingCodeDocument,
  handoff,
}: Readonly<{
  owner: RequirementDetailOwner;
  api: WalleApi;
  host: HTMLElement;
  back(): void;
  handoff: DocumentHandoffEntry;
  openCodeTasks?: OpenCodeTasks | undefined;
  choosingCodeDocument: boolean;
}>) {
  const [documentActionHost, setDocumentActionHost] = useState<HTMLDivElement | null>(null);
  const product = useRef<HTMLDivElement>(null);
  const composerFocus = useRef(false);
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    document = useSyncExternalStore(owner.documents.subscribe, owner.documents.getSnapshot),
    departure = useSyncExternalStore(owner.departure.subscribe, owner.departure.getSnapshot),
    regions = owner.regions!;
  const readingDocument =
    document.mode === 'CURRENT'
      ? document.detail?.current
      : document.mode === 'HISTORY'
        ? document.revision
        : null;
  const emptyDocument =
    document.mode === 'EMPTY' || readingDocument?.markdown_content.trim() === '';
  const geometry = useSyncExternalStore(regions.layout.subscribe, regions.layout.getSnapshot),
    viewport = useSyncExternalStore(regions.viewport.subscribe, regions.viewport.getSnapshot),
    historical = owner.documents.historical;
  const supported = geometry.mode !== 'BLOCKED' && viewport.phase === 'SUPPORTED',
    blocked = !supported || departure.phase !== 'IDLE',
    actual = state.detail!,
    activity =
      actual.activity.kind === 'GUIDE'
        ? 'AI 运行中'
        : actual.activity.kind === 'BATCH'
          ? '待处理建议'
          : null;
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      const session = owner.documents.getSnapshot().manual;
      if (
        session &&
        (session.autosave.state.status !== 'SAVED' ||
          !['EDITING', 'CLOSED'].includes(session.ending.getSnapshot().phase))
      ) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [owner]);
  const selectedDocument = actual.selected_document_id;
  useEffect(() => {
    if (handoff && handoff !== 'INVALID' && supported) regions.layout.openTab('AI');
  }, [handoff, regions.layout, supported]);
  const codeTasksBlocked = blocked || document.busy || state.loading || !!state.error;
  function readCodeDocument(documentId: number): DocumentReading {
    return {
      documentId,
      revisionId:
        document.mode === 'HISTORY' && document.revision?.document_id === documentId
          ? document.revision.id
          : null,
      scroll: selectedDocument === documentId ? host.scrollTop : 0,
    };
  }
  function visitDocumentCodeTasks(documentId: number) {
    if (
      !openCodeTasks ||
      codeTasksBlocked ||
      actual.documents.find((item) => item.id === documentId)?.document_kind === 'DRAWING'
    )
      return;
    openCodeTasks(
      actual.requirement.id,
      readCodeDocument(documentId),
      selectedDocument === null ? null : readCodeDocument(selectedDocument),
    );
  }
  function visitSelectedCodeTasks() {
    if (selectedDocument !== null) visitDocumentCodeTasks(selectedDocument);
  }
  const discuss = () => {
    composerFocus.current = true;
    regions.layout.openTab('AI');
  };
  useEffect(() => {
    if (!composerFocus.current) return;
    if (geometry.right_tab !== 'AI' || !geometry.right_open) {
      composerFocus.current = false;
      return;
    }
    if (!supported || state.loading || !state.ready || document.busy || activeModal()) return;
    const input =
      product.current?.querySelector<HTMLTextAreaElement>('[aria-label="给 AI 的消息"]');
    if (input && !input.disabled) {
      composerFocus.current = false;
      input.focus({ preventScroll: true });
    }
  }, [
    supported,
    state.loading,
    state.ready,
    document.busy,
    geometry.right_open,
    geometry.right_tab,
  ]);
  return (
    <DocumentCreationProvider owner={owner}>
      <div className="detail-product" ref={product} data-requirement-id={actual.requirement.id}>
        <DetailFrame
          layout={regions.layout}
          viewport={regions.viewport}
          title={actual.requirement.title}
          titleEditor={
            <RequirementPropertyControl
              flow={regions.header.title}
              blocked={blocked || document.busy || historical || regions.header.blockedFor('TITLE')}
              writeReady={state.ready}
              refresh={owner.refresh}
            />
          }
          status={
            <div className="requirement-metadata">
              <span>{actual.requirement.requirement_no}</span>
              {handoff === 'INVALID' && <span role="alert">文档移交入口参数无效。</span>}
              <span>{actual.requirement.requirement_type === 'NEW' ? '需求新增' : '需求改造'}</span>
              <span className="requirement-state-badge" data-state={actual.requirement.status}>
                {REQUIREMENT_STATUS_LABELS[actual.requirement.status]}
              </span>
            </div>
          }
          actions={null}
          properties={
            <RequirementHeader
              documentActions={
                <div className="requirement-document-actions" ref={setDocumentActionHost} />
              }
              toolHint={openCodeTasks && selectedDocument === null ? '请先选择文档' : undefined}
              commands={regions.header}
              ready={state.ready}
              blocked={blocked || document.busy}
              history={historical}
              refresh={owner.refresh}
              refreshRevisions={async () => {
                if (!(await owner.documents.revisions.refresh()))
                  throw Error('实际版本列表暂时无法读取');
              }}
              notifyConfirmed={owner.notifyConfirmed}
              tools={
                <>
                  {openCodeTasks && (
                    <button
                      className="ui-button"
                      type="button"
                      disabled={
                        selectedDocument === null ||
                        codeTasksBlocked ||
                        actual.current?.document_kind === 'DRAWING'
                      }
                      title={
                        actual.current?.document_kind === 'DRAWING'
                          ? '画板不能作为文字设计依据'
                          : undefined
                      }
                      onClick={visitSelectedCodeTasks}
                    >
                      代码任务
                    </button>
                  )}
                  <button
                    className="ui-button"
                    type="button"
                    disabled={blocked || document.busy || state.loading}
                    onClick={() => regions.layout.openTab('REVISIONS')}
                  >
                    文档记录
                  </button>
                  <button
                    className="ui-button"
                    type="button"
                    disabled={blocked || document.busy || state.loading}
                    onClick={() => void owner.refresh().catch(() => undefined)}
                  >
                    重新读取详情
                  </button>
                </>
              }
            />
          }
          outline={
            <DocumentDirectory
              owner={owner}
              codeTasks={choosingCodeDocument && openCodeTasks ? visitDocumentCodeTasks : undefined}
              codeTasksBlocked={codeTasksBlocked}
            />
          }
          outlineActions={<NewDocumentButton owner={owner} iconOnly />}
          document={(navigation) => (
            <>
              <DocumentMetadataBar owner={owner} navigation={navigation} />
              <OwnedDocumentControls
                actionHost={documentActionHost}
                showSaveStatus={false}
                owner={owner.documents}
                blocked={blocked}
                auxiliary={document.mode !== 'CURRENT' || !owner.documents.currentBinding}
                notifyConfirmed={owner.notifyConfirmed}
              />
              <CommentDocumentTools
                panel={regions.comments}
                documents={owner.documents}
                openPanel={owner.openComments}
              />
              {state.error && (
                <p className="inline-error" role="alert">
                  {state.error}
                </p>
              )}
              <DocumentMount
                host={host}
                empty={
                  emptyDocument && !state.error && !document.error
                    ? {
                        icon: document.mode === 'HISTORY' ? 'history' : 'document',
                        message:
                          document.mode === 'EMPTY'
                            ? actual.documents.length
                              ? '请选择文档'
                              : '暂无文档'
                            : document.mode === 'HISTORY'
                              ? '此版本暂无内容'
                              : '文档暂无内容',
                      }
                    : null
                }
              />
            </>
          )}
          ai={
            actual.current ? (
              <GuideConversation
                key={actual.current.id}
                owner={regions.conversation}
                documents={owner.documents}
                discussion={regions.discussion}
                handoff={
                  handoff &&
                  handoff !== 'INVALID' && (
                    <DocumentHandoff
                      api={api}
                      owner={owner}
                      link={handoff}
                      active={supported && geometry.right_open && geometry.right_tab === 'AI'}
                      blocked={blocked || document.busy || historical || !state.ready}
                    />
                  )
                }
                associations={
                  <DocumentAssociations
                    owner={owner}
                    blocked={blocked || document.busy}
                    active={supported && geometry.right_open && geometry.right_tab === 'AI'}
                  />
                }
              />
            ) : (
              <EmptyState icon="robot" message="请先创建或选择文档" fill />
            )
          }
          suggestions={
            <ConversationSuggestions
              key={actual.selected_document_id}
              owner={regions.conversation}
              documents={owner.documents}
              toasts={owner.toasts}
            />
          }
          progress={
            actual.current ? (
              <FormationProgress
                key={actual.selected_document_id}
                owner={owner}
                active={
                  actual.current !== null &&
                  supported &&
                  geometry.right_open &&
                  geometry.right_tab === 'PROGRESS'
                }
                blocked={blocked || document.busy || historical}
                discuss={discuss}
              />
            ) : (
              <EmptyState icon="outline" message="请选择文档查看进展" fill />
            )
          }
          comments={
            <CommentPanel
              key={actual.selected_document_id}
              panel={regions.comments}
              documents={owner.documents}
            />
          }
          revisions={
            <DocumentRecords
              key={actual.selected_document_id}
              cache={regions.conversation.modelCalls}
              modelCallApi={regions.conversation.modelCallApi}
              requirementId={actual.requirement.id}
              active={
                actual.current !== null &&
                supported &&
                geometry.right_open &&
                geometry.right_tab === 'REVISIONS'
              }
              blocked={blocked || document.busy}
              revisions={owner.documents.revisions}
              history={regions.conversation.read.history}
              readRun={owner.readRunRecord}
              versions={
                <>
                  {state.revisionSave && (
                    <RevisionSaveControl
                      flow={state.revisionSave}
                      ready={state.ready && state.revisionSave.allowed}
                      blocked={blocked || historical}
                      refreshActual={owner.refresh}
                      saved={(receipt) => owner.savedRevision(receipt)}
                    />
                  )}
                  {actual.current ? (
                    <RevisionList
                      flow={owner.documents.revisions}
                      blocked={blocked || document.busy}
                      open={(summary) => void owner.openHistory(summary).catch(() => undefined)}
                    />
                  ) : (
                    <EmptyState icon="versions" message="请先选择文档" fill />
                  )}
                </>
              }
            />
          }
          activity={activity}
          saveStatus={<SaveStatus owner={owner} />}
          back={() => void owner.departure.request(back)}
          readPanel={(tab, signal) => owner.readPanel(tab, signal)}
        />
        {departure.phase === 'SAVING' && (
          <p className="detail-leave-status" role="status">
            正在保存草稿，确认后离开…
          </p>
        )}
        <Confirmation
          open={departure.phase === 'WARNING'}
          title="仍有未同步的编辑内容"
          description={
            departure.local_protected
              ? '后端草稿仍保留，本地最新内容已暂存。可以继续编辑，或明确离开后在此浏览器恢复。'
              : '后端草稿仍保留，但最新本地内容尚未确认能够跨页面恢复。请继续编辑或先复制需要的文字；明确离开可能丢失尚未同步内容。'
          }
          busy={false}
          dangerous
          confirmLabel="仍然离开"
          cancelLabel="继续编辑"
          error={departure.error}
          confirm={() => owner.departure.confirmLeave()}
          cancel={() => owner.departure.continueEditing()}
        />
        <ToastViewport store={owner.toasts} />
      </div>
    </DocumentCreationProvider>
  );
}

/** Route-local lifetime. Required real reads precede any editable document.
 * The actual owned host moves into the single main region after initialization. */
export function RequirementDetail({
  identity,
  api,
  back,
  ready,
  reading,
  openCodeTasks,
  choosingCodeDocument = false,
  handoff = null,
}: Readonly<{
  identity: number;
  api: WalleApi;
  back(): void;
  ready?: (owner: RequirementDetailOwner) => void;
  reading?: DocumentReading | null;
  handoff?: DocumentHandoffEntry;
  openCodeTasks?: OpenCodeTasks | undefined;
  choosingCodeDocument?: boolean;
}>) {
  const host = useMemo(() => {
    const element = document.createElement('div');
    element.className = 'requirement-owned-document';
    return element;
  }, [identity, api]);
  const [owner, setOwner] = useState<RequirementDetailOwner | null>(null),
    callbacks = useRef({ back, ready });
  callbacks.current = { back, ready };
  const [restoreError, setRestoreError] = useState(false);
  useEffect(() => {
    let storage: Storage | null = null;
    try {
      storage = window.localStorage;
    } catch {}
    const owned = new RequirementDetailOwner(
      identity,
      api,
      host,
      () => window.innerWidth,
      storage,
      host,
      reading?.documentId,
    );
    const controller = new AbortController();
    setRestoreError(false);
    setOwner(owned);
    callbacks.current.ready?.(owned);
    async function restoreReading() {
      const actual = await owned.refresh();
      if (
        controller.signal.aborted ||
        !reading ||
        actual.selected_document_id !== reading.documentId
      )
        return;
      if (reading.revisionId !== null) {
        const revision = (await api.getRevision(reading.revisionId, controller.signal)).data;
        if (controller.signal.aborted) return;
        if (
          revision.requirement_id !== identity ||
          revision.document_id !== reading.documentId ||
          owned.getSnapshot().detail?.selected_document_id !== reading.documentId
        )
          throw Error('History source differs from original document');
        await owned.openHistory(revision);
      }
      if (!controller.signal.aborted) host.scrollTop = reading.scroll;
    }
    void restoreReading().catch(() => {
      if (!controller.signal.aborted && reading?.revisionId !== null && reading)
        setRestoreError(true);
    });
    return () => {
      controller.abort();
      void owned.retire().catch((error) => console.error('WALL-E detail retirement failed', error));
      host.remove();
    };
  }, [identity, api, host, reading]);
  return owner ? (
    <>
      {restoreError && (
        <p role="alert" className="inline-error">
          原阅读版本暂时无法恢复。
        </p>
      )}
      <DetailSurface
        owner={owner}
        api={api}
        handoff={handoff}
        host={host}
        back={() => callbacks.current.back()}
        openCodeTasks={openCodeTasks}
        choosingCodeDocument={choosingCodeDocument}
      />
    </>
  ) : (
    <main aria-busy="true">
      <p role="status">正在读取需求与正文…</p>
      <DocumentMount host={host} empty={null} />
    </main>
  );
}
function DetailSurface({
  owner,
  api,
  host,
  back,
  openCodeTasks,
  choosingCodeDocument,
  handoff,
}: Readonly<{
  owner: RequirementDetailOwner;
  api: WalleApi;
  host: HTMLElement;
  back(): void;
  handoff: DocumentHandoffEntry;
  openCodeTasks?: OpenCodeTasks | undefined;
  choosingCodeDocument: boolean;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  if (owner.regions)
    return (
      <LoadedDetail
        owner={owner}
        api={api}
        handoff={handoff}
        host={host}
        back={back}
        openCodeTasks={openCodeTasks}
        choosingCodeDocument={choosingCodeDocument}
      />
    );
  return (
    <main className="detail-initial-state" aria-busy={state.loading}>
      <button
        className="ui-button"
        type="button"
        onClick={() => void owner.departure.request(back)}
      >
        返回需求工作台
      </button>
      <h1>需求详情</h1>
      {state.loading ? (
        <p role="status">正在读取需求、正文与实际活动…</p>
      ) : state.error ? (
        <>
          <p role="alert">{state.error}</p>
          {owner.read.getSnapshot().error_kind !== 'MISSING' && (
            <button
              className="ui-button"
              type="button"
              onClick={() => void owner.refresh().catch(() => undefined)}
            >
              重新读取详情
            </button>
          )}
        </>
      ) : (
        <p role="status">正在展示正式正文…</p>
      )}
      <div hidden inert>
        <DocumentMount host={host} empty={null} />
      </div>
    </main>
  );
}
