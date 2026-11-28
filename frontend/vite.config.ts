import { createReadStream, readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

function drawingFonts(): Plugin {
  const directory = new URL(
    './node_modules/@excalidraw/excalidraw/dist/prod/fonts/',
    import.meta.url,
  );
  const mount = 'assets/excalidraw-0.18.1/fonts/';
  const fonts = readdirSync(directory, { recursive: true, encoding: 'utf8' })
    .map((name) => name.replaceAll('\\', '/'))
    .filter((name) => name.endsWith('.woff2'));
  const paths = new Map(fonts.map((name) => [name, fileURLToPath(new URL(name, directory))]));
  return {
    name: 'walle-excalidraw-fonts',
    configureServer(server) {
      server.middlewares.use('/' + mount.slice(0, -1), (request, response, next) => {
        const path = paths.get(request.url?.slice(1) ?? '');
        if (!path) return next();
        response.setHeader('Content-Type', 'font/woff2');
        createReadStream(path).pipe(response);
      });
    },
    generateBundle() {
      for (const [name, path] of paths) {
        this.emitFile({ type: 'asset', fileName: mount + name, source: readFileSync(path) });
      }
    },
  };
}

const api = process.env.WALLE_API_URL ?? 'http://127.0.0.1:8000';
if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(api) || Number(new URL(api).port) > 65535)
  throw Error('WALLE_API_URL must identify the local API server.');

export default defineConfig({
  plugins: [react(), drawingFonts()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': { target: api } } },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': { target: api } } },
  build: { outDir: 'dist', emptyOutDir: true },
});
