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
  assert.equal(report.browser.recovery.passed, true); assert.equal(report.browser.recovery.capacity_records, 20);
  assert.equal(report.browser.recovery.checks.length, 7);
  assert.equal(report.browser.autosave.passed, true); assert.equal(report.browser.autosave.writes.length, 3);
  assert.equal(report.browser.autosave.peak_inflight, 1); assert.equal(report.browser.autosave.confirmed_draft_version, 4);
  assert.equal(report.browser.autosave.native_cohort.final_version, 6); assert.equal(report.browser.autosave.native_cohort.retired_proof_refused, true);
  report.editor_host = result(await cli('run-code', 'async (page) => { await page.evaluate(() => window.apiProbe.hostProbe.prepare()); const editor = page.locator("#native-editor-host .ProseMirror"); await editor.click(); await editor.press("Control+End"); await page.keyboard.press("Enter"); await page.keyboard.insertText("真实浏览器输入😀"); await page.waitForFunction(() => { const state = window.apiProbe.hostProbe.status(); return state.valid && state.status === "SAVED" && state.confirmed_version >= 2 && state.markdown.includes("真实浏览器输入😀"); }, null, {timeout:15000}); return await page.evaluate(() => window.apiProbe.hostProbe.inspect()); }'));
  assert.equal(report.editor_host.passed, true);
  report.editor_readonly = result(await cli('run-code', 'async (page) => { const before = await page.evaluate(() => window.apiProbe.hostProbe.readonly(true)); await page.keyboard.insertText("不应进入只读内容"); return await page.evaluate(before => { const state = window.apiProbe.hostProbe.status(); return {passed: state.markdown === before.markdown, state}; }, before); }'));
  assert.equal(report.editor_readonly.passed, true);
  report.editor_composition = result(await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.hostProbe.composition())'));
  assert.equal(report.editor_composition.passed, true);
  report.editor_host_closed = result(await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.hostProbe.close())'));
  assert.equal(report.editor_host_closed.closed, true);
  report.read_limits = result(await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.readLimits())'));
  assert.equal(report.read_limits.passed, true); assert.equal(report.read_limits.revision_codepoints, 1000);
  assert.equal(report.read_limits.prefix_codepoints, 100); assert.equal(report.read_limits.suffix_codepoints, 100);
  await cli('run-code', 'async (page) => { await page.evaluate(() => window.apiProbe.mountCreate()); await page.waitForFunction(() => !!window.createProbe?.state().state); return true; }');
  await cli('snapshot');
  report.create_drawer = result(await cli('run-code', `async (page) => {
    const trigger=page.getByRole('button',{name:'打开新建诊断'}); await trigger.click();await page.evaluate(()=>window.createStage='initial');
    const drawer=page.locator('.create-drawer'), title=drawer.getByLabel('需求标题'), type=drawer.getByLabel('需求类型'), template=drawer.getByLabel('需求模板'), mode=drawer.getByLabel('初始化模式');
    if(!await title.evaluate(element=>element===document.activeElement)||!await template.isDisabled()||await mode.inputValue()!=='')throw new Error('Initial controlled fields');
    await drawer.getByRole('button',{name:'创建需求',exact:true}).click();
    if(await drawer.locator('[aria-invalid=true]').count()!==5||!await title.evaluate(element=>element===document.activeElement))throw new Error('Five errors or first focus missing');
    await page.evaluate(()=>window.createStage='discard');await page.mouse.click(5,5);if(!await drawer.isVisible())throw new Error('Mask closed create');
    await title.fill('未提交输入');await drawer.getByRole('button',{name:'取消',exact:true}).click();
    const confirm=page.locator('.confirmation');await confirm.waitFor();
    if(await page.locator('dialog').count()!==2||await page.evaluate(()=>document.body.style.overflow)!=='hidden')throw new Error('Nested modal/scroll lock');
    await page.keyboard.press('Escape');if(await confirm.count()||!await drawer.isVisible()||await page.evaluate(()=>document.body.style.overflow)!=='hidden')throw new Error('Nested Escape released drawer');
    await drawer.getByRole('button',{name:'取消',exact:true}).click();await confirm.getByRole('button',{name:'放弃输入'}).click();
    if(await page.locator('dialog').count()||await page.evaluate(()=>document.body.style.overflow)!=='')throw new Error('Discard modal cleanup');
    await page.evaluate(()=>window.createStage='linked-fields');await trigger.click();await type.selectOption('NEW');if(await template.inputValue()!=='0'||!await template.getByRole('option',{name:'需求新增规格'}).count())throw new Error('NEW linked template');
    await type.selectOption('CHANGE');if(!await template.getByRole('option',{name:'需求改造规格'}).count())throw new Error('CHANGE linked template');await type.selectOption('NEW');
    await title.fill('😀'.repeat(21));await drawer.getByLabel('初始想法').fill('  正式初始想法\\n保留第二行  ');await mode.selectOption('DESIGN');
    await drawer.getByRole('button',{name:'创建需求',exact:true}).click();if(await title.inputValue()!=='😀'.repeat(21)||!await title.evaluate(element=>element===document.activeElement))throw new Error('Long title truncated/focus lost');
    if((await page.evaluate(()=>window.createProbe.state())).prepared!==0)throw new Error('Invalid form submitted');
    await page.evaluate(()=>window.createStage='composition');await title.fill('真实抽屉😀');await title.evaluate(element=>element.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true})));await title.press('Enter');
    await title.evaluate(element=>element.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'😀'})));if((await page.evaluate(()=>window.createProbe.state())).prepared!==0)throw new Error('Composition submitted');
    await page.evaluate(()=>window.createStage='submit');await drawer.getByRole('button',{name:'创建需求',exact:true}).click();await page.waitForFunction(()=>window.createProbe.state().state.unknown);
    if(await drawer.locator('[data-field]:disabled').count()!==5||!await drawer.getByRole('button',{name:'取消',exact:true}).isDisabled())throw new Error('Unknown original inputs unlocked');
    const feedback=await drawer.getByRole('alert').boundingBox(); if(!feedback||feedback.y<0||feedback.y+feedback.height>await page.evaluate(()=>window.innerHeight))throw new Error('Unknown feedback outside viewport');
    await page.keyboard.press('Escape');if(!await drawer.isVisible())throw new Error('Unknown dismissed');await page.screenshot({path:'output/playwright/create-unknown.png'});
    await drawer.getByRole('button',{name:'核实创建结果'}).click();await page.waitForFunction(()=>!!window.createProbe.state().state.result&&!document.querySelector('.create-drawer'));
    if(await page.evaluate(()=>document.body.style.overflow)!=='')throw new Error('Successful create retained lock');
    const native=await page.evaluate(()=>window.createProbe.inspect()),wires=await page.evaluate(()=>window.apiProbe.creationWires());
    if(wires.length!==2||wires[0].key!==wires[1].key||wires[0].body!==wires[1].body||wires.some(wire=>wire.status!==201))throw new Error('Original action not replayed');
    await page.evaluate(()=>window.createProbe.destroy());return {...native,wires,ordered_five_errors:true,nested_modal_cleanup:true,synthetic_composition_guard:true};
  }`.replace(/\r?\n/g,' ')));
  assert.equal(report.create_drawer.passed, true); assert.equal(report.create_drawer.actual_list_count, 1);
  await cli('screenshot', '--filename=output/playwright/api-native-probe.png');
  await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.destroy())');
  report.passed = true;
} catch (error) { report.passed = false; report.error = String(error); globalThis.process.exitCode = 1;
  if (opened) try {
    report.failure_wires = result(await cli('run-code','async (page) => await page.evaluate(() => window.apiProbe?.wireFacts() ?? [])'));
    report.failure_transport = result(await cli('run-code','async (page) => await page.evaluate(() => window.apiProbe?.transportFacts() ?? [])'));
    report.failure_ui = result(await cli('run-code','async (page) => await page.evaluate(() => ({stage:window.createStage,state:window.createProbe?.state(),dialogs:[...document.querySelectorAll("dialog")].map(element=>element.outerHTML)}))'));
    await cli('snapshot'); await cli('screenshot','--filename=output/playwright/api-failure.png');
  } catch (diagnostic) { report.diagnostic_error = String(diagnostic); }
}
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
      if (closed.facts.llm_uses !== 0 || closed.facts.guide_runs !== 7 || closed.facts.requirements !== 3 || closed.facts.revisions !== 4 || closed.facts.comments !== 2 || native.record.code !== 0) { report.passed = false; report.error ??= 'Native persisted facts/closure differ'; globalThis.process.exitCode = 1; }
    } else { report.passed = false; report.error ??= 'Native closure/facts missing'; globalThis.process.exitCode = 1; }
  }
  report.inputs_after = await hashes();
  report.changed_inputs = [...new Set([...Object.keys(report.inputs_before), ...Object.keys(report.inputs_after)])].filter(key => report.inputs_before[key] !== report.inputs_after[key]);
  if (report.changed_inputs.length) { report.passed = false; report.error ??= 'Inputs changed during verification'; globalThis.process.exitCode = 1; }
  const path = resolve(root, 'docs/verification', `api-browser-${report.timestamp.replace(/[:.]/g, '-')}.json`);
  await writeFile(path, JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify({ passed: report.passed, evidence: path, error: report.error }));
}
