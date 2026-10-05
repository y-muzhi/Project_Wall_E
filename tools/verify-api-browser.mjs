import { spawn } from 'node:child_process';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const root = resolve(import.meta.dirname, '..'), session = `walle-api-${Date.now()}`;
const wrapper = process.env.WALLE_PLAYWRIGHT_WRAPPER ?? resolve(homedir(), '.codex/skills/playwright/scripts/playwright_cli.sh');
const bash = process.env.WALLE_BASH ?? (process.platform === 'win32' ? 'C:/Program Files/Git/bin/bash.exe' : 'bash');
const report = { timestamp: new Date().toISOString(), scope: 'Actual browser same-origin proxy, production API/isolated SQLite, all 37 bindings reached with explicit positive/failure cases and real Crepe documents; no Provider/paid request/effects/product-page or whole acceptance', commands: [] };
const directory = resolve(root, 'output/playwright'); await mkdir(directory, { recursive: true });
const database = resolve(directory, `api-${session}.sqlite`);
async function hashes() {
  const files = [];
  async function walk(path) {
    for (const entry of await readdir(path, { withFileTypes: true })) {
      if (['node_modules', 'dist', '__pycache__'].includes(entry.name)) continue;
      const child = resolve(path, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (/\.(py|sql|json|lock|ts|tsx|mjs|html|css)$/.test(entry.name)) files.push(child);
    }
  }
  for (const name of ['backend', 'frontend', 'shared']) await walk(resolve(root, name));
  files.push(resolve(root, 'tools/api-browser-service.py'), resolve(root, 'tools/verify-api-browser.mjs'));
  return Object.fromEntries(await Promise.all(files.sort().map(async file => [file.slice(root.length + 1).replaceAll('\\', '/'), createHash('sha256').update(await readFile(file)).digest('hex')])));
}
report.inputs_before = await hashes();
function subprocess(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, windowsHide: true, ...options });
  const record = { command, args, stdout: '', stderr: '', code: null };
  child.stdout.on('data', data => { record.stdout += data; }); child.stderr.on('data', data => { record.stderr += data; });
  const exited = new Promise((accept, reject) => { child.once('error', reject); child.once('exit', code => { record.code = code; accept(code); }); });
  return { child, record, exited };
}
async function cli(...args) {
  const process = subprocess(bash, [wrapper, `-s=${session}`, ...args]);
  await process.exited; report.commands.push(process.record);
  if (process.record.code !== 0 || process.record.stdout.includes('### Error')) throw new Error(`CLI ${args[0]} failed: ${process.record.stdout}\n${process.record.stderr}`);
  return process.record.stdout;
}
function result(output) { const match = /### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output); assert(match, 'Structured browser result required'); return JSON.parse(match[1]); }
let native, vite, opened = false;
async function killOwned(process) {
  if (process.child.exitCode !== null || process.child.signalCode !== null) return;
  if (globalThis.process.platform === 'win32') {
    const killer = subprocess('taskkill', ['/PID', String(process.child.pid), '/T', '/F']); await killer.exited;
  } else process.child.kill();
  await process.exited;
}
const wait = delay => new Promise(resolve => setTimeout(resolve, delay));
try {
  const npx = subprocess(globalThis.process.execPath, [resolve(globalThis.process.execPath, '../node_modules/npm/bin/npx-cli.js'), '--version']);
  await npx.exited; report.npx = npx.record; assert.equal(npx.record.code, 0);
  const source = subprocess(globalThis.process.execPath, ['tools/spec-audit.mjs', 'check']); await source.exited; report.source = source.record; assert.equal(source.record.code, 0);
  const env = Object.fromEntries(Object.entries(globalThis.process.env).filter(([key]) => !key.startsWith('WALLE_MODEL_')));
  native = subprocess(resolve(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'tools/api-browser-service.py', '--database', database], { env });
  let ready;
  for (let index = 0; index < 100; index++) {
    const line = native.record.stdout.split('\n').find(line => line.startsWith('{'));
    if (line) { ready = JSON.parse(line); break; }
    if (native.child.exitCode !== null) throw new Error(native.record.stderr);
    await wait(100);
  }
  assert.equal(ready?.ready, true); assert.match(ready.url, /^http:\/\/127\.0\.0\.1:[0-9]+$/);
  vite = subprocess(globalThis.process.execPath, ['node_modules/vite/bin/vite.js', '--config', 'tests/browser/api-vite.config.ts', '--host', '127.0.0.1', '--port', '5175', '--strictPort'],
    { cwd: resolve(root, 'frontend'), env: { ...env, WALLE_PROBE_API_URL: ready.url } });
  let live = false;
  for (let index = 0; index < 100; index++) {
    try { const response = await fetch('http://127.0.0.1:5175/tests/browser/api.html'); if (response.ok) { live = true; break; } } catch { /* server not ready */ }
    if (vite.child.exitCode !== null) throw new Error(vite.record.stderr); await wait(100);
  }
  assert(live); await cli('open', 'http://127.0.0.1:5175/tests/browser/api.html'); opened = true;
  await cli('snapshot');
  await cli('run-code', 'async (page) => { await page.waitForFunction(() => document.querySelector("#status")?.textContent === "READY", null, {timeout: 15000}); return true; }');
  report.browser = result(await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.run())'));
  assert.equal(report.browser.passed, true);
  const reached = new Set(report.browser.records.map(record => record.name)); assert.equal(reached.size, 37);
  assert.equal(report.browser.current_version, 2); assert.equal(report.browser.draft_version, 4);
  assert.equal(report.browser.pairs.length, 7); assert.equal(report.browser.history.source_content_version, 2);
  await cli('screenshot', '--filename=output/playwright/api-native-probe.png');
  await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.destroy())');
  report.passed = true;
} catch (error) { report.passed = false; report.error = String(error); globalThis.process.exitCode = 1; }
finally {
  if (opened) try { await cli('close'); } catch (error) { report.close_error = String(error); report.passed = false; globalThis.process.exitCode = 1; }
  if (vite) { await killOwned(vite); report.vite = vite.record; }
  if (native) {
    if (native.child.exitCode === null && native.child.signalCode === null) {
      native.child.stdin.end('shutdown\n');
      let timer;
      try { await Promise.race([native.exited, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Actual service shutdown exceeded verification wait')), 20000); })]); }
      catch (error) { report.shutdown_error = String(error); report.passed = false; globalThis.process.exitCode = 1; await killOwned(native); }
      finally { clearTimeout(timer); }
    }
    report.native = native.record;
    const lines = native.record.stdout.trim().split('\n').filter(line => line.startsWith('{'));
    const closed = lines.length > 1 ? JSON.parse(lines.at(-1)) : null;
    if (closed?.closed === true) { report.native_facts = closed.facts; report.database = { path: database, sha256: createHash('sha256').update(await readFile(database)).digest('hex') };
      if (closed.facts.llm_uses !== 0 || closed.facts.guide_runs !== 4 || native.record.code !== 0) { report.passed = false; report.error ??= 'Native persisted facts/closure differ'; globalThis.process.exitCode = 1; }
    } else { report.passed = false; report.error ??= 'Native closure/facts missing'; globalThis.process.exitCode = 1; }
  }
  report.inputs_after = await hashes();
  report.changed_inputs = [...new Set([...Object.keys(report.inputs_before), ...Object.keys(report.inputs_after)])].filter(key => report.inputs_before[key] !== report.inputs_after[key]);
  if (report.changed_inputs.length) { report.passed = false; report.error ??= 'Inputs changed during verification'; globalThis.process.exitCode = 1; }
  const path = resolve(root, 'docs/verification', `api-browser-${report.timestamp.replace(/[:.]/g, '-')}.json`);
  await writeFile(path, JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify({ passed: report.passed, evidence: path, error: report.error }));
}
