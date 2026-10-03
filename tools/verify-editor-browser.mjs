import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';

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
const report = {timestamp: new Date().toISOString(), scope: 'Initial source parsing/projection in real Crepe; no identity edits, product pages or HTTP acceptance', commands};
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
  const match = /### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output);
  if (!match) throw new Error('浏览器未返回结构化结果');
  report.result = JSON.parse(match[1]);
  if (report.result.cases.length !== 15 || report.result.cases.some(entry => !entry.raw_equal || !entry.projection_equal || !entry.changed_rejected)) throw new Error('浏览器断言不完整');
  await cli('snapshot');
  await cli('screenshot', '--filename=output/playwright/editor-source.png');
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
