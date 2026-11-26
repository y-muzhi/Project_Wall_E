import { createRoot } from 'react-dom/client';
import { Crepe } from '@milkdown/crepe';
import { installSourceNodes } from './documents/source-nodes.ts';
import { validateLocalDraftSnapshot } from './documents/recovery-store.ts';
import { ApiClient } from './api/client.ts';
import {
  EnvironmentEntryError,
  loadBoundEnvironment,
  type BoundEnvironment,
} from './api/environment-binding.ts';
import { EnvironmentConnection, environmentMessages } from './api/environment-connection.ts';
import { WalleApi } from './api/walle.ts';
import { ApplicationRouter } from './application/router.ts';
import { Application } from './application/app.tsx';
import { installFocusFeedback } from './shared/focus-feedback.ts';
import './shared/styles.css';
import './shared/motion.css';
import './requirements/discussion-progress.css';

installFocusFeedback(document);
const container = document.getElementById('root')!;
async function mountApplication(environment: BoundEnvironment, signal: AbortSignal) {
  // A private parser context validates documents before any detail editor exists.
  // It is not a business document and is never displayed or persisted.
  const parserHost = document.createElement('div');
  parserHost.hidden = true;
  parserHost.inert = true;
  parserHost.setAttribute('aria-hidden', 'true');
  document.body.append(parserHost);
  const parser = new Crepe({
    root: parserHost,
    defaultValue: '',
    features: {
      [Crepe.Feature.CodeMirror]: false,
      [Crepe.Feature.ListItem]: false,
      [Crepe.Feature.LinkTooltip]: false,
      [Crepe.Feature.Cursor]: false,
      [Crepe.Feature.ImageBlock]: false,
      [Crepe.Feature.BlockEdit]: false,
      [Crepe.Feature.Toolbar]: false,
      [Crepe.Feature.Placeholder]: false,
      [Crepe.Feature.Table]: false,
      [Crepe.Feature.Latex]: false,
      [Crepe.Feature.TopBar]: false,
      [Crepe.Feature.AI]: false,
    },
  });
  const connection = new EnvironmentConnection(environment);
  let router: ApplicationRouter | undefined;
  try {
    await installSourceNodes(parser);
    await parser.create();
    if (signal.aborted) throw new EnvironmentEntryError('UNREACHABLE');
    parser.setReadonly(true);
    const api = parser.editor.action(
      (ctx) => new WalleApi(new ApiClient(undefined, undefined, environment, connection), ctx),
    );
    let storage: Storage | null = null;
    try {
      storage = window.sessionStorage;
    } catch {
      /* The history owner reports missing recovery storage. */
    }
    router = new ApplicationRouter(
      api,
      {
        history: window.history,
        pathname: () => location.pathname,
        search: () => location.search,
        scroll: () => window.scrollY,
        scrollTop: () => window.scrollTo(0, 0),
        listen: (listener) => {
          window.addEventListener('popstate', listener);
          return () => window.removeEventListener('popstate', listener);
        },
      },
      storage,
    );
    const root = createRoot(container);
    const validateArchivedDraft = (value: unknown) =>
      parser.editor.action((ctx) => validateLocalDraftSnapshot(ctx, value));
    root.render(
      <Application
        router={router}
        connection={connection}
        validateArchivedDraft={validateArchivedDraft}
      />,
    );
    function pageExit(event: PageTransitionEvent): void {
      connection.disconnected();
      if (event.persisted) return;
      window.removeEventListener('pagehide', pageExit);
      connection.dispose();
      router?.dispose();
      root.unmount();
      void parser
        .destroy()
        .finally(() => parserHost.remove())
        .catch(() => undefined);
    }
    window.addEventListener('pagehide', pageExit);
  } catch (error) {
    connection.dispose();
    router?.dispose();
    await parser.destroy().catch(() => undefined);
    parserHost.remove();
    throw error;
  }
}

type EntryAction = Readonly<{ label: string; click: () => void }>;

function showEntry(text: string, loading: boolean, actions: readonly EntryAction[] = []) {
  const shell = document.createElement('main');
  shell.className = 'application-missing';
  const message = document.createElement('p');
  message.setAttribute('role', loading ? 'status' : 'alert');
  message.textContent = text;
  shell.append(message);
  if (actions.length) {
    const controls = document.createElement('div');
    controls.className = 'application-entry-actions';
    for (const action of actions) {
      const button = document.createElement('button');
      button.className = 'ui-button';
      button.type = 'button';
      button.textContent = action.label;
      button.addEventListener('click', action.click);
      controls.append(button);
    }
    shell.append(controls);
  }
  container.replaceChildren(shell);
}

let attempt: AbortController | null = null;
async function connect() {
  if (attempt !== null) return;
  const operation = new AbortController();
  attempt = operation;
  const abort = () => operation.abort();
  window.addEventListener('pagehide', abort, { once: true });
  const cancel = { label: '取消等待', click: abort };
  const retry = { label: '重新核对连接', click: () => void connect() };
  try {
    const environment = await loadBoundEnvironment(
      location.origin,
      operation.signal,
      undefined,
      (phase) =>
        showEntry(
          phase === 'CONFIG_LOADING' ? '正在读取环境入口…' : '正在核对环境身份及权限…',
          true,
          [cancel],
        ),
    );
    if (operation.signal.aborted) throw new EnvironmentEntryError('UNREACHABLE');
    showEntry('正在打开需求工作台…', true);
    await mountApplication(environment, operation.signal);
  } catch (error) {
    if (operation.signal.aborted) {
      showEntry('已取消本次连接核对。', false, [retry]);
    } else if (error instanceof EnvironmentEntryError) {
      const actions =
        error.code === 'ACCESS'
          ? [
              {
                label: '打开登录入口',
                click: () => {
                  window.open('/', '_blank', 'noopener,noreferrer');
                },
              },
              retry,
            ]
          : [retry];
      const message =
        error.code === 'SCOPE_CHANGED'
          ? '入口描述与服务所属环境或数据版本不一致。'
          : environmentMessages[error.code];
      showEntry(message, false, actions);
    } else {
      console.error('WALL-E application initialization failed', error);
      showEntry('无法打开当前环境，请重新核对入口。', false, [retry]);
    }
  } finally {
    window.removeEventListener('pagehide', abort);
    if (attempt === operation) attempt = null;
  }
}

void connect();
