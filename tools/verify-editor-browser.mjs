import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const session = `walle-source-${Date.now()}`;
const wrapper = process.env.WALLE_PLAYWRIGHT_WRAPPER ?? resolve(homedir(), '.codex/skills/playwright/scripts/playwright_cli.sh');
const bash = process.env.WALLE_BASH ?? (process.platform === 'win32' ? 'C:/Program Files/Git/bin/bash.exe' : 'bash');
const commands = [];
async function cli(...args) {
  const start = Date.now();
  const child = spawn(bash, [wrapper, `-s=${session}`, ...args], {cwd: root, windowsHide: true});
  let stdout = '', stderr = '';
  child.stdout.on('data', data => { stdout += data; });
  child.stderr.on('data', data => { stderr += data; });
  const code = await new Promise((accept, reject) => {
    child.once('error', reject);
    child.once('exit', accept);
  });
  commands.push({args, code, elapsed_ms: Date.now() - start, stdout, stderr});
  if (code !== 0 || stdout.includes('### Error')) throw new Error(`浏览器命令失败: ${args[0]}\n${stdout}\n${stderr}`);
  return stdout;
}

const artifacts = resolve(root, 'output/playwright');
await mkdir(artifacts, {recursive: true});
const port = 5174;
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
  {cwd: resolve(root, 'frontend'), windowsHide: true});
let serverLog = '';
vite.stdout.on('data', data => { serverLog += data; });
vite.stderr.on('data', data => { serverLog += data; });
const report = {timestamp: new Date().toISOString(), scope: 'Initial source/projection and Crepe identity keyboard integration; no complete edited snapshot, product pages or HTTP acceptance', commands};
function resultFrom(output) {
  const match = /### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output);
  if (!match) throw new Error('浏览器未返回结构化结果');
  return JSON.parse(match[1]);
}
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (vite.exitCode !== null) throw new Error(`Vite启动失败\n${serverLog}`);
    try { ready = (await fetch(`http://127.0.0.1:${port}/tests/browser/editor.html`)).ok; } catch {}
    if (ready) break;
    await new Promise(accept => setTimeout(accept, 100));
  }
  if (!ready) throw new Error('Vite启动超时');
  await cli('open', `http://127.0.0.1:${port}/tests/browser/editor.html`);
  await cli('snapshot');
  const output = await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verify())');
  report.result = resultFrom(output);
  if (report.result.cases.length !== 15 || report.result.cases.some(entry => !entry.raw_equal || !entry.projection_equal || !entry.changed_rejected)) throw new Error('浏览器断言不完整');
  await cli('snapshot');
  await cli('screenshot', '--filename=output/playwright/editor-source.png');
  report.identity_types = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyIdentityTypes())'));
  if (report.identity_types.length !== 15) throw new Error('身份节点逐类型检查不完整');
  await cli('snapshot');
  await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.prepareIdentity())');
  const identitySnapshot = await cli('snapshot');
  const editorRef = /textbox \[ref=([^\]]+)\]/.exec(identitySnapshot)?.[1];
  if (!editorRef) throw new Error('真实编辑器没有textbox引用');
  await cli('click', editorRef);
  report.identity_checks = [];
  async function checkIdentity(name, ids, next, position) {
    await cli('snapshot');
    const actual = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.identityReport())'));
    assert.deepEqual(actual.ids, ids, name);
    assert.deepEqual(actual.dom_ids, ids.map(String), `${name}: DOM身份`);
    assert.equal(actual.next, next, `${name}: 高水位`);
    if (position !== undefined) assert.equal(actual.position, position, `${name}: 光标`);
    assert.equal(actual.serialized.includes('walle_block_id'), false, `${name}: 元数据泄漏`);
    report.identity_checks.push({name, ...actual});
  }
  await checkIdentity('initial-bind', [10,20], 30);
  await cli('press', 'Control+Home');
  await cli('press', 'ArrowRight');
  await cli('press', 'Enter');
  await checkIdentity('keyboard-split', [10,30,20], 31, 4);
  await cli('press', 'Control+z');
  await checkIdentity('keyboard-undo', [10,20], 31);
  await cli('press', 'Control+Shift+z');
  await checkIdentity('keyboard-redo', [10,30,20], 31, 4);
  await cli('press', 'Backspace');
  await checkIdentity('keyboard-join', [10,20], 31, 2);
  await cli('press', 'Enter');
  await checkIdentity('keyboard-second-split', [10,31,20], 32, 4);
  await cli('press', 'Control+Home');
  await cli('press', 'Enter');
  await checkIdentity('keyboard-empty-first-split', [10,32,31,20], 33, 3);
  await cli('press', 'Backspace');
  await checkIdentity('keyboard-empty-first-join', [10,31,20], 33, 1);
  await cli('screenshot', '--filename=output/playwright/editor-identity.png');
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = String(error);
  process.exitCode = 1;
} finally {
  try { await cli('close'); } catch (error) { report.close_error = String(error); process.exitCode = 1; }
  vite.kill();
  report.server_log = serverLog;
  report.fixtures = [];
  for (const file of ['shared/fixtures/markdown-v1.json', 'shared/fixtures/markdown-editor-v1.json', 'frontend/package-lock.json']) {
    report.fixtures.push({file, sha256: createHash('sha256').update(await readFile(resolve(root, file))).digest('hex')});
  }
  const path = resolve(root, 'docs/verification', `editor-browser-${report.timestamp.replace(/[:.]/g, '-')}.json`);
  await writeFile(path, JSON.stringify(report, null, 2) + '\n');
  console.log(`${report.passed ? 'PASS' : 'FAIL'} ${path}`);
  if (report.error) console.error(report.error);
}
