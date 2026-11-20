import { createRoot } from 'react-dom/client';
import { Crepe } from '@milkdown/crepe';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import { ApiClient } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { RequirementDetail } from '../../src/requirements/detail.tsx';
import type { RequirementDetailOwner } from '../../src/requirements/detail-owner.ts';
import { installFocusFeedback } from '../../src/shared/focus-feedback.ts';
import '../../src/shared/styles.css';
import '../../src/shared/motion.css';
import '../../src/requirements/discussion-progress.css';
const host = document.createElement('div');
host.hidden = true;
document.body.append(host);
const parser = new Crepe({
  root: host,
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
await installSourceNodes(parser);
await parser.create();
parser.setReadonly(true);
installFocusFeedback(document);
let owner: RequirementDetailOwner | undefined,
  losePatch = false;
let loseCard = false;
let failRead: string | null = null;
let holdGuide = false;
let releaseGuide: (() => void) | null = null;
const readRequests: string[] = [];
const requests: { method: string; path: string; body: string | null; key: string | null }[] = [];
const send: typeof fetch = async (input, init) => {
  const path = String(input),
    method = init?.method ?? 'GET';
  if (method === 'GET') readRequests.push(path);
  if (method === 'GET' && failRead !== null && path.includes(failRead)) {
    failRead = null;
    throw new TypeError('Injected isolated read failure');
  }
  if (method !== 'GET')
    requests.push({
      method,
      path,
      body: typeof init?.body === 'string' ? init.body : null,
      key: new Headers(init?.headers).get('Idempotency-Key'),
    });
  const response = await fetch(input, init);
  if (holdGuide && method === 'POST' && path === '/api/v1/requirements/1/guide-runs') {
    holdGuide = false;
    await new Promise<void>((resolve) => {
      releaseGuide = resolve;
    });
  }
  if (loseCard && method === 'POST' && path.endsWith('/responses')) {
    loseCard = false;
    throw Error('Injected lost card result');
  }
  if (losePatch && method === 'PATCH' && path === '/api/v1/requirements/1') {
    losePatch = false;
    throw Error('Injected lost response');
  }
  return response;
};
const api = parser.editor.action((ctx) => new WalleApi(new ApiClient(send), ctx));
const root = createRoot(document.querySelector('#root')!);
const documentId = Number(new URL(location.href).searchParams.get('document') ?? 3);
if (![1, 3].includes(documentId)) throw Error('Owned fixture document required');
root.render(
  <RequirementDetail
    identity={1}
    api={api}
    reading={{ documentId, revisionId: null, scroll: 0 }}
    back={() => {}}
    ready={(value) => {
      owner = value;
    }}
  />,
);
Object.assign(window, {
  formationProduct: {
    state: () =>
      owner === undefined
        ? null
        : {
            ready: owner.getSnapshot().ready,
            error: owner.getSnapshot().error,
            current: owner.getSnapshot().detail?.selected_document_id,
            phase: owner.documents.getSnapshot().mode,
            formation: owner.regions?.formation?.getSnapshot(),
            reads: owner.regions?.formation?.read.getSnapshot(),
            composer: owner.regions?.conversation.composer.getSnapshot(),
            layout: owner.regions?.layout.getSnapshot(),
          },
    owner: () => owner,
    requests: () => requests.map((value) => ({ ...value })),
    readRequests: () => [...readRequests],
    failRead: (fragment: string) => {
      failRead = fragment;
    },
    holdGuide: () => {
      holdGuide = true;
    },
    releaseGuide: () => {
      holdGuide = false;
      releaseGuide?.();
      releaseGuide = null;
    },
    loseCard: () => {
      loseCard = true;
    },
    losePatch: () => {
      losePatch = true;
    },
    async destroy() {
      root.unmount();
      await owner?.retire();
      await parser.destroy();
      host.remove();
    },
  },
});
