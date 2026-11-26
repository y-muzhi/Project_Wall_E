import { useEffect, useState, useSyncExternalStore } from 'react';
import type { CSSProperties } from 'react';
import { environmentPurposeNames } from '../api/environment-binding.ts';
import { environmentMessages, type EnvironmentConnection } from '../api/environment-connection.ts';
import {
  ORDINARY_CODING_UNAVAILABLE,
  ORDINARY_TESTING_UNAVAILABLE,
  ORDINARY_SETTINGS_UNAVAILABLE,
} from '../api/environment-actions.ts';
import { ApplicationRouter } from './router.ts';
import { WorkbenchView } from '../requirements/workbench-view.tsx';
import { RequirementDetail } from '../requirements/detail.tsx';
import { ApplicationNavigation } from './navigation.tsx';
import { ApplicationHeaderHost } from './header.tsx';
import { activeModal, subscribeModal } from '../shared/modal.ts';
import { ApplicationConnectionNotice } from './connection-notice.ts';
import { ScopeRecovery } from './scope-recovery.tsx';
import { BrowserArchive } from './browser-archive-view.tsx';
import type { ArchivedDraftValidator } from './browser-archive.ts';
import type { RequirementDetailOwner } from '../requirements/detail-owner.ts';

export function Application({
  router,
  connection,
  validateArchivedDraft,
}: Readonly<{
  router: ApplicationRouter;
  connection: EnvironmentConnection;
  validateArchivedDraft: ArchivedDraftValidator;
}>) {
  const state = useSyncExternalStore(router.subscribe, router.getSnapshot);
  const { phase, environment } = useSyncExternalStore(connection.subscribe, connection.getSnapshot);
  const writeReason = connection.blockReason(true);
  const modal = useSyncExternalStore(subscribeModal, activeModal);
  const connectionNoticeInModal = modal?.hasAttribute('data-environment-connection-owner') ?? false;
  const route = state.route.kind;
  const unavailable =
    route === 'CODE_SETTINGS' || route === 'TESTING_SETTINGS'
      ? ORDINARY_SETTINGS_UNAVAILABLE
      : route.startsWith('CODE_')
        ? ORDINARY_CODING_UNAVAILABLE
        : route.startsWith('TESTING_')
          ? ORDINARY_TESTING_UNAVAILABLE
          : null;
  useEffect(() => {
    const retry = () => void connection.recheck();
    const visible = () => {
      if (document.visibilityState === 'visible') retry();
    };
    const show = (event: PageTransitionEvent) => {
      if (event.persisted) retry();
    };
    window.addEventListener('offline', connection.disconnected);
    window.addEventListener('online', retry);
    window.addEventListener('pageshow', show);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.removeEventListener('offline', connection.disconnected);
      window.removeEventListener('online', retry);
      window.removeEventListener('pageshow', show);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [connection]);
  useEffect(() => {
    let last = connection.getSnapshot().phase;
    return connection.subscribe(() => {
      const current = connection.getSnapshot().phase;
      const resumed = last !== 'READY' && current === 'READY';
      last = current;
      if (resumed) void router.getSnapshot().workbench?.refresh();
    });
  }, [connection, router]);
  const choosingCodeDocument = state.navIntent === 'CHOOSE_CODE_DOCUMENT';
  const [detailOwner, setDetailOwner] = useState<RequirementDetailOwner | null>(null);
  const [headerHost, setHeaderHost] = useState<HTMLDivElement | null>(null),
    [headerHeight, setHeaderHeight] = useState(68);
  useEffect(() => {
    const capture = () => {
      const current = router.getSnapshot();
      if (current.entry && current.workbench)
        router.saveEntry(current.workbench.state.requested, window.scrollY);
    };
    window.addEventListener('scroll', capture, { passive: true });
    return () => window.removeEventListener('scroll', capture);
  }, [router]);
  const connectionNotice =
    phase === 'READY' ? null : (
      <section className="application-warning environment-connection" aria-label="环境连接">
        <p role={phase === 'CHECKING' ? 'status' : 'alert'}>
          {phase === 'CHECKING' ? '正在重新核对环境和权限…' : environmentMessages[phase]}{' '}
          页面内容来自上次读取。
        </p>
        {phase === 'SCOPE_CHANGED' ? (
          <ScopeRecovery scope={environment.scope} router={router} detailOwner={detailOwner} />
        ) : (
          <div className="application-entry-actions">
            {phase === 'ACCESS' && (
              <a className="ui-button" href="/" target="_blank" rel="noopener noreferrer">
                打开登录入口
              </a>
            )}
            <button
              className="ui-button"
              type="button"
              disabled={phase === 'CHECKING'}
              onClick={() => void connection.recheck()}
            >
              {phase === 'CHECKING' ? '核对中…' : '重新核对连接'}
            </button>
          </div>
        )}
      </section>
    );
  const page = (
    <div
      className="application"
      style={{ '--application-header-height': `${headerHeight}px` } as CSSProperties}
    >
      <ApplicationNavigation
        headerHost={setHeaderHost}
        headerHeight={setHeaderHeight}
        current={
          choosingCodeDocument
            ? undefined
            : state.route.kind === 'WORKBENCH'
              ? 'page'
              : state.route.kind === 'DETAIL'
                ? 'location'
                : undefined
        }
        navigate={router.mainNavigation}
        coding={router.openCodeDevelopment}
        codingReason={ORDINARY_CODING_UNAVAILABLE}
        testingReason={ORDINARY_TESTING_UNAVAILABLE}
        settingsReason={ORDINARY_SETTINGS_UNAVAILABLE}
        codingCurrent={
          choosingCodeDocument && state.route.kind === 'DETAIL'
            ? 'location'
            : choosingCodeDocument ||
                ['CODE_TASK_LIST', 'CODE_TASK', 'CODE_PARAMETERS'].includes(state.route.kind)
              ? 'page'
              : undefined
        }
        testing={router.openTestingList}
        testingCurrent={
          ['TESTING_LIST', 'TESTING_TASK', 'TESTING_PLANS'].includes(state.route.kind)
            ? 'page'
            : undefined
        }
        settings={router.openCodeSettings}
        settingsCurrent={
          ['CODE_SETTINGS', 'TESTING_SETTINGS'].includes(state.route.kind) ? 'page' : undefined
        }
      />
      <ApplicationHeaderHost.Provider value={headerHost}>
        <div className="application-main" data-page={state.route.kind}>
          <BrowserArchive scope={environment.scope} validate={validateArchivedDraft}>
            <span>
              {environmentPurposeNames[environment.purpose]}
              {environment.displayName !== environmentPurposeNames[environment.purpose] &&
                ` · ${environment.displayName}`}
              {environment.userPermission === 'READ_ONLY' && !environment.recovery
                ? ' · 当前身份仅可查看'
                : ''}
            </span>
          </BrowserArchive>
          {phase === 'READY' && environment.recovery && (
            <p className="application-warning" role="status">
              恢复核对中。已核验的需求、文档与历史可查看。
            </p>
          )}
          {!connectionNoticeInModal && connectionNotice}
          {state.warning && (
            <p className="application-warning" role="status">
              <strong>提示：</strong>
              {state.warning}
            </p>
          )}
          {state.route.kind === 'WORKBENCH' && state.workbench && state.creation && state.entry && (
            <WorkbenchView
              key={state.epoch}
              workbench={state.workbench}
              choosingCodeDocument={choosingCodeDocument}
              creation={state.creation}
              writeReason={writeReason}
              restoreScroll={state.restoreScroll}
              openRequirement={router.openRequirement}
              saveEntry={router.saveEntry}
              navigationGuard={router.navigationGuard}
              discardCreation={router.discardCreation}
            />
          )}
          {state.route.kind === 'DETAIL' && (
            <RequirementDetail
              key={state.epoch}
              identity={state.route.id}
              api={router.applicationApi}
              back={router.backToWorkbench}
              reading={state.documentReading}
              handoff={state.documentHandoff}
              choosingCodeDocument={choosingCodeDocument}
              writeReason={writeReason}
              ready={(owner) => {
                setDetailOwner(owner);
                router.attachDeparture(owner.departure);
              }}
            />
          )}
          {unavailable && (
            <main className="application-missing">
              <h1>{unavailable}</h1>
              <button className="ui-button" type="button" onClick={router.mainNavigation}>
                返回需求工作台
              </button>
            </main>
          )}
          {state.route.kind === 'NOT_FOUND' && (
            <main className="application-missing">
              <h1>页面不存在</h1>
              <p>请从需求工作台打开需求。</p>
              <button className="ui-button" type="button" onClick={router.mainNavigation}>
                返回需求工作台
              </button>
            </main>
          )}
        </div>
      </ApplicationHeaderHost.Provider>
    </div>
  );
  return (
    <ApplicationConnectionNotice.Provider value={connectionNotice}>
      {page}
    </ApplicationConnectionNotice.Provider>
  );
}
