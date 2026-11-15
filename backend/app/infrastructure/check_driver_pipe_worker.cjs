'use strict';
// Fixed SDK adapter: data-only commands over private anonymous stdio.
// The Python root retains case interpretation, comparisons and result frames.
const path = require('path');
const fs = require('fs');
const privateTemp = process.env.WALLE_SDK_TEMP;
delete process.env.WALLE_SDK_TEMP;
if (!privateTemp || !path.isAbsolute(privateTemp) || !fs.statSync(privateTemp).isDirectory())
  throw new Error('SDK_PRIVATE_TEMP_REQUIRED');
process.env.TEMP = privateTemp;
process.env.TMP = privateTemp;
const packagePath=path.join(__dirname, 'vendor/playwright/driver/package');
const broker=require('./browser-broker.cjs').install(packagePath,value=>send(value),()=>generation);
const sdk = require(packagePath);
const MAX = 8 * 1024 * 1024;
let buffered = Buffer.alloc(0);
let context = null;
let next = 0;
let generation = 0;
const pages = new Map();
const routes = new Map();
const websockets = new Map();

function send(value) {
  const raw = Buffer.from(JSON.stringify(value), 'utf8');
  if (raw.length === 0 || raw.length > MAX) throw new Error('SDK_FRAME_LIMIT');
  const header = Buffer.alloc(4);
  header.writeUInt32LE(raw.length);
  process.stdout.write(Buffer.concat([header, raw]));
}
function pageId(page) {
  for (const [id, original] of pages) if (original === page) return id;
  const id = ++next;
  pages.set(id, page);
  return id;
}
function pageFor(id) {
  const page = pages.get(id);
  if (!page) throw new Error('SDK_ORIGINAL_PAGE_REQUIRED');
  return page;
}
function locator(page, value) {
  if (value.kind === 'ROLE')
    return page.getByRole(value.value, {name: value.name, exact: true});
  if (value.kind === 'TEST_ID') return page.getByTestId(value.value);
  throw new Error('SDK_LOCATOR_REQUIRED');
}
async function launch(value) {
  if (context) throw new Error('SDK_CONTEXT_ALREADY_OPEN');
  if (value.sandbox !== true || value.serviceWorkers !== 'block' || value.acceptDownloads !== false)
    throw new Error('SDK_SANDBOX_REQUIRED');
  const allowed = ['--disable-background-networking','--disable-component-update','--disable-sync'];
  if (JSON.stringify(value.args) !== JSON.stringify(allowed)) throw new Error('SDK_ARGUMENTS_DIFFER');
  const executable = path.join(__dirname, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  if (path.resolve(value.executable) !== executable) throw new Error('SDK_FIXED_BROWSER_REQUIRED');
  if (!Number.isSafeInteger(value.generation) || value.generation <= generation)
    throw new Error('SDK_CONTEXT_GENERATION_REQUIRED');
  const epoch = value.generation;
  generation = epoch;
  context = await sdk.chromium.launchPersistentContext(value.profile, {
    executablePath: executable, chromiumSandbox: true, headless: true,
    serviceWorkers: 'block', acceptDownloads: false, args: allowed, timeout: value.timeout
  });
  await context.route('**/*', async route => {
    if (routes.size >= 128) { await route.abort('blockedbyclient'); throw new Error('SDK_ROUTE_LIMIT'); }
    const id = ++next;
    const request = route.request();
    const body = request.postDataBuffer() || Buffer.alloc(0);
    if (body.length > 1024 * 1024) { await route.abort('blockedbyclient'); throw new Error('SDK_BODY_LIMIT'); }
    const pending = new Promise(resolve => routes.set(id, {route, resolve}));
    send({event:'ROUTE', epoch, route:id, request:{
      url:request.url(), method:request.method(), headers:await request.allHeaders(), body:body.toString('base64')
    }});
    await pending;
  });
  await context.routeWebSocket('**/*', socket => {
    const id = ++next;
    if (websockets.size >= 128) { socket.close({code:1008}); throw new Error('SDK_WEBSOCKET_LIMIT'); }
    websockets.set(id,socket);
    send({event:'WEBSOCKET',epoch,socket:id});
  });
  return {pages:context.pages().map(pageId)};
}
async function dispatch(op, value) {
  if (op === 'LAUNCH') return launch(value);
  if (!context) throw new Error('SDK_CONTEXT_REQUIRED');
  if (op === 'NEW_PAGE') return {page:pageId(await context.newPage())};
  if (op === 'GOTO') {
    await pageFor(value.page).goto(value.url,{waitUntil:'domcontentloaded',timeout:value.timeout});
    return null;
  }
  if (op === 'LOCATOR') {
    const found = locator(pageFor(value.page),value.locator);
    const options = {timeout:value.timeout};
    switch(value.method) {
      case 'click': await found.click(options); return null;
      case 'fill': await found.fill(value.value,options); return null;
      case 'select_option': await found.selectOption({value:value.value},options); return null;
      case 'press': await found.press(value.value,options); return null;
      case 'is_visible': return await found.isVisible();
      case 'inner_text': return await found.innerText(options);
      case 'count': return await found.count();
      default: throw new Error('SDK_METHOD_REQUIRED');
    }
  }
  if (op === 'ROUTE_REPLY') {
    const held = routes.get(value.route);
    if (!held) throw new Error('SDK_ORIGINAL_ROUTE_REQUIRED');
    try {
      if (value.action === 'abort') await held.route.abort('blockedbyclient');
      else if (value.action === 'fulfill') {
        const body = Buffer.from(value.body,'base64');
        if (body.length > 4 * 1024 * 1024) throw new Error('SDK_BODY_LIMIT');
        await held.route.fulfill({status:value.status,headers:value.headers,body});
      } else throw new Error('SDK_ROUTE_ACTION_REQUIRED');
    } finally {routes.delete(value.route);held.resolve();}
    return null;
  }
  if (op === 'WEBSOCKET_CLOSE') {
    const socket = websockets.get(value.socket);
    if (!socket || value.code !== 1008) throw new Error('SDK_ORIGINAL_WEBSOCKET_REQUIRED');
    socket.close({code:1008});
    websockets.delete(value.socket);
    return null;
  }
  if (op === 'CLOSE') {
    await context.close();
    for (const held of routes.values()) held.resolve();
    routes.clear();websockets.clear();pages.clear();context=null;
    return null;
  }
  throw new Error('SDK_OPERATION_REQUIRED');
}
process.stdin.on('data',chunk=>{
  buffered=Buffer.concat([buffered,chunk]);
  if (buffered.length > MAX + 4) {process.exitCode=1;process.stdin.destroy();return;}
  while (buffered.length>=4) {
    const size=buffered.readUInt32LE(0);
    if (size===0 || size>MAX) {process.exitCode=1;process.stdin.destroy();return;}
    if (buffered.length<size+4) break;
    const raw=buffered.subarray(4,size+4);buffered=buffered.subarray(size+4);
    let row;
    try {
      row=JSON.parse(raw.toString('utf8'));
      if (typeof row.transport==='string') {
        if (Object.keys(row).sort().join(',')!=='transport,value') throw new Error('SDK_TRANSPORT_REQUIRED');
        broker.receive(row.transport,row.value);
        continue;
      }
      if (!Number.isSafeInteger(row.id) || row.id<1 || typeof row.op!=='string' ||
          !row.value || typeof row.value!=='object') throw new Error('SDK_REQUEST_REQUIRED');
    } catch {process.exitCode=1;process.stdin.destroy();return;}
    dispatch(row.op,row.value).then(
      result=>send({id:row.id,result}),
      error=>send({id:row.id,error:{code:'SDK_OPERATION_FAILED',message:String(error.message).slice(0,1000)}})
    );
  }
});
process.stdin.on('end',async()=>{if(context)await context.close();});
process.stdin.on('error',()=>{process.exitCode=1;});
