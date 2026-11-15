import { useEffect, useState, useSyncExternalStore } from 'react';
import type { CSSProperties } from 'react';
import { ApplicationRouter } from './router.ts';
import { WorkbenchView } from '../requirements/workbench-view.tsx';
import { RequirementDetail } from '../requirements/detail.tsx';
import { CodeSettings } from '../code-tasks/settings/settings.tsx';
import { TestingSettings } from '../testing/settings/settings.tsx';
import { TestingPlans } from '../testing/plans/plans.tsx';
import { TestingTaskList } from '../testing/task-list.tsx';
import { TestingTaskWorkspace } from '../testing/task-workspace.tsx';
import { DocumentCodeTasks } from '../code-tasks/list.tsx';
import { CodeTaskWorkspace } from '../code-tasks/workspace.tsx';
import { ApplicationNavigation } from './navigation.tsx';
import { ApplicationHeaderHost } from './header.tsx';

export function Application({ router }: Readonly<{ router: ApplicationRouter }>) {
  const state = useSyncExternalStore(router.subscribe, router.getSnapshot);
  const choosingCodeDocument = state.navIntent === 'CHOOSE_CODE_DOCUMENT';
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
  return (
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
              openCodeTasks={router.openCodeTaskList}
              choosingCodeDocument={choosingCodeDocument}
              ready={(owner) => router.attachDeparture(owner.departure)}
            />
          )}
          {state.route.kind === 'CODE_TASK_LIST' && state.taskList && (
            <DocumentCodeTasks
              key={state.epoch}
              api={router.applicationApi}
              requirementId={state.route.requirementId}
              documentId={state.route.documentId}
              query={state.taskList.query}
              restoreScroll={state.taskList.scroll}
              revisionId={state.taskList.revisionId}
              update={router.saveCodeTaskList}
              openTask={router.openCodeTask}
              back={router.returnToCodeDocument}
              settings={router.openCodeSettings}
            />
          )}
          {state.route.kind === 'CODE_TASK' && (
            <CodeTaskWorkspace
              key={state.epoch}
              api={router.applicationApi}
              taskId={state.route.taskId}
              route={state.taskWorkspace}
              restoreScroll={state.restoreScroll}
              navigate={router.openCodeTaskWorkspace}
              pinFileScope={router.pinCodeTaskFileScope}
              back={router.returnToTaskList}
              openDocument={router.returnToCodeDocument}
              openHandoff={router.openCodeHandoff}
            />
          )}
          {state.route.kind === 'CODE_PARAMETERS' && (
            <main className="application-missing">
              <h1>代码任务页面参数无效</h1>
              <button className="ui-button" type="button" onClick={router.mainNavigation}>
                返回需求工作台
              </button>
            </main>
          )}
          {state.route.kind === 'CODE_SETTINGS' && (
            <CodeSettings
              api={router.applicationApi}
              reset={router.openCodeSettings}
              openTesting={router.openTestingSettings}
              selectSection={router.selectCodeSettingsSection}
            />
          )}
          {state.route.kind === 'TESTING_SETTINGS' && (
            <TestingSettings
              api={router.applicationApi}
              openCoding={router.openCodeSettings}
              openPlans={router.openTestingPlans}
            />
          )}
          {state.route.kind === 'TESTING_LIST' && (
            <TestingTaskList
              api={router.applicationApi}
              query={window.location.search}
              navigate={router.selectTestingList}
              open={router.openTestingTask}
              plans={router.openTestingPlans}
              settings={router.openTestingSettings}
            />
          )}
          {state.route.kind === 'TESTING_TASK' && (
            <TestingTaskWorkspace
              key={state.route.taskId}
              api={router.applicationApi}
              identity={state.route.taskId}
              query={window.location.search}
              back={router.openTestingList}
              select={(query) => {
                if (state.route.kind === 'TESTING_TASK')
                  router.openTestingTask(state.route.taskId, query);
              }}
              plans={router.openTestingPlans}
            />
          )}
          {state.route.kind === 'TESTING_PARAMETERS' && (
            <main className="application-missing">
              <h1>测试任务页面参数无效</h1>
              <button className="ui-button" type="button" onClick={router.openTestingList}>
                返回测试任务列表
              </button>
            </main>
          )}
          {state.route.kind === 'TESTING_PLANS' && (
            <TestingPlans
              api={router.applicationApi}
              query={window.location.search}
              select={router.openTestingPlans}
              openTask={router.openTestingTask}
              settings={router.openTestingSettings}
            />
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
}
