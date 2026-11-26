import { lstat, readFile, readlink, realpath } from 'node:fs/promises';
import { createServer as createHttpServer } from 'node:http';
import { once } from 'node:events';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { createServer } from 'vite';

const HMR_PATH = '/__walle_hmr';
const CONNECTION_MODULE = '/@vite/walle-connection';
const CONNECTION_CHECK = 'wall-e:check-development-connection';
const CONNECTION_READY = 'wall-e:development-connection-ready';
const CONNECTION_STATUS = 'wall-e-development-connection';
const CONNECTION_SCRIPT = `
import { createHotContext } from '/@vite/client';

const status = document.getElementById('${CONNECTION_STATUS}');
const hot = createHotContext('${CONNECTION_MODULE}');
const deadline = window.setTimeout(() => { status.hidden = false; }, 6000);
hot.on('${CONNECTION_READY}', () => {
  window.clearTimeout(deadline);
  status.hidden = true;
});
hot.on('vite:ws:disconnect', () => { status.hidden = false; });
hot.on('vite:ws:connect', () => hot.send('${CONNECTION_CHECK}', null));
hot.send('${CONNECTION_CHECK}', null);
`;
const PRIVATE_HEADERS = new Set(['authorization', 'proxy-authorization', 'cookie', 'forwarded']);

function within(root, path) {
  const child = relative(root, path);
  return child !== '' && !isAbsolute(child) && child !== '..' && !child.startsWith('../');
}

async function directory(path, label) {
  const metadata = await lstat(path);
  if ((await realpath(path)) !== path || !metadata.isDirectory()) {
    throw new Error(label + ' must be a real directory.');
  }
  return metadata;
}

async function sourcePaths(cache) {
  const frontend = dirname(fileURLToPath(import.meta.url));
  const workspace = dirname(frontend);
  const uid = process.getuid();
  const work = await directory(workspace, 'Workspace');
  const dependencies = await directory(join(frontend, 'node_modules'), 'Workspace dependencies');
  const cacheDirectory = await directory(cache, 'Vite cache');
  const resources = join(workspace, 'backend/resources');
  const shared = join(workspace, 'shared');
  await directory(resources, 'Frontend resources');
  await directory(shared, 'Shared source');
  if (
    work.uid !== uid ||
    (work.mode & 0o077) !== 0 ||
    dependencies.uid !== uid ||
    !within(workspace, cache) ||
    within(frontend, cache) ||
    cacheDirectory.uid !== uid ||
    (cacheDirectory.mode & 0o777) !== 0o700
  ) {
    throw new Error('Workspace, installed dependencies and cache must belong to the frontend UID.');
  }
  return { frontend, allowed: [frontend, resources, shared, cache] };
}

async function inheritedSocket(socket) {
  if (
    process.env.LISTEN_FDS !== '1' ||
    process.env.LISTEN_PID !== String(process.pid) ||
    !socket.endsWith('/vite.sock') ||
    Buffer.byteLength(socket) >= 108
  ) {
    throw new Error('One named systemd socket must be provided.');
  }
  const entry = await lstat(socket);
  if (!entry.isSocket() || entry.uid !== 0 || (entry.mode & 0o777) !== 0o660) {
    throw new Error('The Vite socket must be protected by the host.');
  }
  let parent = dirname(socket);
  while (parent !== '/') {
    const metadata = await directory(parent, 'Socket parent');
    if (metadata.uid !== 0 || (metadata.mode & 0o022) !== 0) {
      throw new Error('The Vite socket directory must be controlled by the host.');
    }
    parent = dirname(parent);
  }
  const descriptor = await readlink('/proc/self/fd/3');
  const inode = /^socket:\[(\d+)\]$/.exec(descriptor)?.[1];
  const rows = (await readFile('/proc/self/net/unix', 'utf8')).split('\n').slice(1);
  const listeners = rows
    .map((line) => line.trim().split(/\s+/, 8))
    .filter((fields) => fields[6] === inode && fields[7] === socket);
  if (
    !inode ||
    listeners.length !== 1 ||
    listeners[0][3] !== '00010000' ||
    listeners[0][4] !== '0001' ||
    listeners[0][5] !== '01'
  ) {
    throw new Error('The inherited descriptor is not the registered Unix listener.');
  }
}

function trustedHeaders(request, origin) {
  const headers = request.headersDistinct;
  return (
    headers.host?.length === 1 &&
    headers.host[0] === origin.host &&
    !Object.keys(headers).some(
      (name) => PRIVATE_HEADERS.has(name) || name.startsWith('x-wall-e-auth-'),
    )
  );
}

function requestPath(request, origin) {
  if (!request.url?.startsWith('/') || request.url.startsWith('//')) return null;
  try {
    return new URL(request.url, origin).pathname;
  } catch {
    return null;
  }
}

function connectionStatus() {
  return {
    name: 'wall-e-development-connection',
    transformIndexHtml() {
      return [
        {
          tag: 'p',
          attrs: {
            id: CONNECTION_STATUS,
            role: 'status',
            hidden: true,
            style: 'margin:0;padding:8px 16px;background:#fff4d5;color:#423317;',
          },
          children: '开发连接异常',
          injectTo: 'body-prepend',
        },
        {
          tag: 'script',
          attrs: { type: 'module', src: CONNECTION_MODULE },
          injectTo: 'head-prepend',
        },
      ];
    },
  };
}

function proxyRequests(vite, origin, upgrades) {
  const frontend = createHttpServer((request, response) => {
    if (!trustedHeaders(request, origin)) {
      response.writeHead(403).end();
      return;
    }
    const path = requestPath(request, origin);
    if (
      !['GET', 'HEAD'].includes(request.method) ||
      !path ||
      path === '/api' ||
      path.startsWith('/api/') ||
      path === '/__open-in-editor' ||
      path === HMR_PATH
    ) {
      response.writeHead(404).end();
      return;
    }
    if (path === CONNECTION_MODULE) {
      response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' });
      response.end(CONNECTION_SCRIPT);
      return;
    }
    vite.middlewares(request, response);
  });
  frontend.on('upgrade', (request, transport, head) => {
    const headers = request.headersDistinct;
    const protocol = headers['sec-websocket-protocol'];
    if (
      !trustedHeaders(request, origin) ||
      request.method !== 'GET' ||
      requestPath(request, origin) !== HMR_PATH ||
      headers.origin?.length !== 1 ||
      headers.origin[0] !== origin.origin ||
      protocol?.length !== 1 ||
      !['vite-hmr', 'vite-ping'].includes(protocol[0])
    ) {
      transport.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');
      return;
    }
    upgrades.emit('upgrade', request, transport, head);
  });
  return frontend;
}

async function main() {
  const [publicOrigin, socket, cache] = process.argv.slice(2);
  if (
    process.platform !== 'linux' ||
    process.getuid() === 0 ||
    process.argv.length !== 5 ||
    !isAbsolute(socket) ||
    !isAbsolute(cache) ||
    resolve(socket) !== socket ||
    resolve(cache) !== cache
  ) {
    throw new Error('Use a non-root Linux identity and supply the HTTPS origin, socket and cache.');
  }
  const origin = new URL(publicOrigin);
  if (
    origin.origin !== publicOrigin ||
    origin.protocol !== 'https:' ||
    !['', '9443'].includes(origin.port)
  ) {
    throw new Error('Use the registered HTTPS origin.');
  }
  await inheritedSocket(socket);
  const { frontend: root, allowed } = await sourcePaths(cache);
  const upgrades = createHttpServer();
  const vite = await createServer({
    root,
    cacheDir: cache,
    configFile: false,
    envDir: false,
    plugins: [react(), connectionStatus()],
    server: {
      host: '127.0.0.1',
      strictPort: true,
      allowedHosts: [origin.hostname],
      cors: false,
      middlewareMode: true,
      fs: { strict: true, allow: allowed },
      ws: {
        server: upgrades,
        protocol: 'wss',
        host: origin.hostname,
        clientPort: Number(origin.port || '443'),
        path: HMR_PATH,
      },
    },
  });
  vite.ws.on(CONNECTION_CHECK, (_data, client) => client.send(CONNECTION_READY, null));
  const frontend = proxyRequests(vite, origin, upgrades);
  const stop = async () => {
    await vite.close();
    frontend.closeAllConnections();
    if (frontend.listening) frontend.close();
  };
  try {
    frontend.listen({ fd: 3 });
    await once(frontend, 'listening');
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    console.log('WALL-E isolated Vite is ready.');
  } catch (error) {
    await stop();
    throw error;
  }
}

await main();
