import { Excalidraw, serializeAsJSON } from '@excalidraw/excalidraw';
import type {
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from '@excalidraw/excalidraw/types';
import { createRoot } from 'react-dom/client';
import { exact, stableJson } from '../api/client.ts';
import '@excalidraw/excalidraw/index.css';
import './drawing-canvas.css';

const fence = '```excalidraw\n';
const endFence = '\n```\n';
const maxMarkdownCodePoints = 1_000_000;

function readScene(markdown: string): ExcalidrawInitialDataState {
  const scene = /^(`{3,})excalidraw\n([^\r\n]+)\n\1\n$/.exec(markdown)?.[2];
  if (scene === undefined) throw Error('无法读取画板场景');
  const value = exact(JSON.parse(scene), [
    'type',
    'version',
    'source',
    'elements',
    'appState',
    'files',
  ]);
  if (value.type !== 'excalidraw' || value.version !== 2 || !Array.isArray(value.elements))
    throw Error('无法读取画板场景');
  return { ...(value as ExcalidrawInitialDataState), scrollToContent: true };
}

type SceneSnapshot = ExcalidrawInitialDataState & {
  readonly type: 'excalidraw';
  readonly version: 2;
  readonly source: string;
};

function sceneContents(scene: SceneSnapshot): string | undefined {
  const elements = scene.elements?.map((element) => {
    const {
      version: _version,
      versionNonce: _versionNonce,
      updated: _updated,
      ...content
    } = element;
    return content;
  });
  const files = Object.values(scene.files ?? {}).map((file) => {
    const { lastRetrieved: _lastRetrieved, ...content } = file;
    return content;
  });
  return stableJson({ elements, files, appState: scene.appState });
}

export interface DrawingCanvas {
  valid: boolean;
  setReadonly(readonly: boolean): void;
  replace(markdown: string): void;
  flush(): boolean;
  destroy(): void;
}

type DrawingEvents = Readonly<{
  change?(scene: string): void;
  validity?(): void;
  error?(message: string | null): void;
}>;

const canvasOptions = {
  canvasActions: { loadScene: false, saveToActiveFile: false, export: false as const },
};

export function mountDrawingCanvas(
  parent: HTMLElement,
  markdown: string,
  events: DrawingEvents = {},
): DrawingCanvas {
  let scene = readScene(markdown);
  const host = parent.ownerDocument.createElement('div');
  host.className = 'walle-drawing-canvas';
  host.setAttribute('aria-label', '画板');
  parent.append(host);
  const root = createRoot(host);
  let generation = 0;
  let readonly = true;
  let valid = false;
  let initialized = false;
  let closed = false;
  let pointerActive = false;
  let fingerprint: string | undefined;
  let api: ExcalidrawImperativeAPI | null = null;
  let pointerSubscriptions: (() => void)[] = [];

  function validity(next: boolean) {
    if (closed || next === valid) return;
    valid = next;
    events.validity?.();
  }

  function capture(): boolean {
    if (closed || api === null) return false;
    const state = api.getAppState();
    if (state.isLoading) return false;
    if (readonly) {
      if (!initialized) {
        initialized = true;
        validity(true);
      }
      return valid;
    }
    if (state.editingTextElement || state.multiElement || state.pendingImageElementId) {
      validity(false);
      return false;
    }
    // Wait for the gesture to settle before snapshotting. Selection and panning
    // also emit pointer events while the persisted scene stays the same.
    if (pointerActive) return false;
    initialized = true;
    try {
      const rendered = JSON.parse(
        serializeAsJSON(api.getSceneElements(), state, api.getFiles(), 'local'),
      ) as SceneSnapshot;
      const files = rendered.files ?? {};
      // Excalidraw's pending flag also covers images with local bytes that
      // have not been uploaded. WALL-E persists those bytes in the snapshot.
      const elements = (rendered.elements ?? []).map((element) =>
        element.type === 'image' &&
        element.status === 'pending' &&
        element.fileId &&
        files[element.fileId]?.dataURL
          ? { ...element, status: 'saved' as const }
          : element,
      );
      const snapshot: SceneSnapshot = {
        type: 'excalidraw',
        version: 2,
        source: 'WALL-E',
        elements,
        appState: { viewBackgroundColor: state.viewBackgroundColor },
        files,
      };
      if (
        snapshot.elements?.some(
          (element) =>
            element.type === 'embeddable' ||
            element.type === 'iframe' ||
            element.type === 'magicframe' ||
            (element.type === 'image' &&
              (element.status !== 'saved' || !element.fileId || !snapshot.files?.[element.fileId])),
        )
      ) {
        throw Error('场景包含未完成的图片或不支持的内容');
      }
      const comparable = sceneContents(snapshot);
      if (fingerprint !== undefined && comparable !== fingerprint) {
        const json = JSON.stringify(snapshot);
        if ([...json].length + fence.length + endFence.length > maxMarkdownCodePoints)
          throw Error('画板内容超出容量，请减少图片或图形后继续');
        events.change?.(json);
      }
      fingerprint = comparable;
      events.error?.(null);
      validity(true);
      return true;
    } catch (error) {
      events.error?.(error instanceof Error ? error.message : '画板内容暂时无法保存');
      validity(false);
      return false;
    }
  }

  function render() {
    const position = generation;
    root.render(
      <Excalidraw
        key={position}
        initialData={scene}
        viewModeEnabled={readonly}
        langCode="zh-CN"
        UIOptions={canvasOptions}
        handleKeyboardGlobally={false}
        validateEmbeddable={false}
        excalidrawAPI={(instance) => {
          if (closed || position !== generation || api === instance) return;
          api = instance;
          pointerSubscriptions = [
            instance.onPointerDown(() => {
              if (!readonly) pointerActive = true;
            }),
            instance.onPointerUp(() => {
              pointerActive = false;
              requestAnimationFrame(() => {
                if (position === generation) capture();
              });
            }),
          ];
        }}
        onChange={() => {
          if (position === generation) capture();
        }}
      />,
    );
  }

  function cancelPointer() {
    pointerActive = false;
    requestAnimationFrame(capture);
  }
  host.addEventListener('pointercancel', cancelPointer);

  render();
  return {
    get valid() {
      return valid;
    },
    flush: capture,
    setReadonly(value) {
      if (readonly === value) return;
      // Read the initialized baseline before allowing the first drawing event.
      if (fingerprint === undefined && readonly && !value && api && !api.getAppState().isLoading) {
        const state = api.getAppState();
        const data = JSON.parse(
          serializeAsJSON(api.getSceneElements(), state, api.getFiles(), 'local'),
        ) as SceneSnapshot;
        fingerprint = sceneContents({
          ...data,
          appState: { viewBackgroundColor: state.viewBackgroundColor },
        });
      }
      readonly = value;
      pointerActive = false;
      render();
    },
    replace(next) {
      scene = readScene(next);
      for (const release of pointerSubscriptions) release();
      pointerSubscriptions = [];
      api = null;
      pointerActive = false;
      fingerprint = undefined;
      initialized = false;
      generation += 1;
      validity(false);
      render();
    },
    destroy() {
      closed = true;
      host.removeEventListener('pointercancel', cancelPointer);
      for (const release of pointerSubscriptions) release();
      window.queueMicrotask(() => {
        root.unmount();
        host.remove();
      });
    },
  };
}
