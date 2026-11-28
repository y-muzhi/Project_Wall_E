export async function loadDrawingCanvas() {
  const windowWithExcalidraw = window as Window & { EXCALIDRAW_ASSET_PATH?: string };
  windowWithExcalidraw.EXCALIDRAW_ASSET_PATH = '/assets/excalidraw-0.18.1/';
  return import('./drawing-canvas.tsx');
}
