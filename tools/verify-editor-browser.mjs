import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const session = `walle-source-${Date.now()}`;
const baselineOnly = process.argv.includes('--autolink-baseline');
const autolinkOnly = process.argv.includes('--autolink-check');
if (baselineOnly && autolinkOnly) throw new Error('基线采集和合规检查不能混用');
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
const inputFiles = ['shared/fixtures/markdown-v1.json', 'shared/fixtures/markdown-editor-v1.json', 'frontend/package-lock.json',
  'frontend/src/documents/selection.ts', 'frontend/src/documents/editor-source.ts', 'frontend/src/documents/source-nodes.ts',
  'frontend/src/documents/identity.ts', 'frontend/src/documents/contracts.ts', 'frontend/tests/browser/contracts.ts',
  'frontend/src/documents/edited-snapshot.ts', 'frontend/tests/browser/edited-snapshot.ts',
  'frontend/src/documents/autolink-lexemes.ts', 'frontend/src/documents/autolink-remark.ts',
  'backend/app/documents/autolinks.py', 'backend/app/documents/markdown.py', 'backend/requirements.lock',
  'backend/app/documents/snapshot.py', 'backend/app/shared/validation.py', 'backend/app/shared/time.py',
  'tools/verify-editor-output.py',
  'shared/fixtures/autolink-v1.json', 'frontend/tests/browser/autolink-baseline.ts', 'tools/autolink-baseline.py',
  'shared/fixtures/autolink-context-v1.json', 'frontend/tests/browser/autolink-conformance.ts',
  'frontend/tests/browser/probe.ts', 'frontend/tests/browser/editor.html',
  'frontend/tests/browser/vite.config.ts', 'tools/verify-editor-browser.mjs'];
async function inputHashes() {
  return Promise.all(inputFiles.map(async file => ({file,
    sha256: createHash('sha256').update(await readFile(resolve(root, file))).digest('hex')})));
}
const beforeHashes = await inputHashes();
const port = 5174;
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--config', 'tests/browser/vite.config.ts', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
  {cwd: resolve(root, 'frontend'), windowsHide: true});
let serverLog = '';
vite.stdout.on('data', data => { serverLog += data; });
vite.stderr.on('data', data => { serverLog += data; });
const report = {timestamp: new Date().toISOString(), scope: 'Source/projection, local edited pairs and Crepe identity keyboard integration; no product pages or HTTP/DB save acceptance', commands};
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
  if (baselineOnly) {
    report.scope = 'Autolink baseline observation only; passed means collection completed, not GFM conformance';
    report.frontend_baseline = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.autolinkBaseline())'));
    const backend = spawn(resolve(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'tools/autolink-baseline.py'], {cwd: root, windowsHide: true});
    let stdout = '', stderr = '';
    backend.stdout.on('data', data => { stdout += data; });
    backend.stderr.on('data', data => { stderr += data; });
    const code = await new Promise((accept, reject) => { backend.once('error', reject); backend.once('exit', accept); });
    report.backend_command = {status: code, stdout, stderr};
    if (code !== 0) throw new Error(`后端基线收集失败\n${stderr}`);
    report.backend_baseline = JSON.parse(stdout);
    assert.equal(report.frontend_baseline.records.length, 22);
    assert.equal(report.backend_baseline.records.length, 22);
    report.conforms = !report.frontend_baseline.mismatches.length && !report.backend_baseline.mismatches.length;
  } else if (autolinkOnly) {
    report.scope = '48 independent literal/context cases and edited output; fixture provenance, not product/HTTP acceptance';
    report.autolink_conformance = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.autolinkConformance())'));
    assert.equal(report.autolink_conformance.records.length, 48);
    assert.deepEqual(report.autolink_conformance.mismatches, []);
    assert.equal(report.autolink_conformance.outputs.length, 51);
    const backend = spawn(resolve(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'tools/verify-editor-output.py'], {cwd: root, windowsHide: true});
    let stdout = '', stderr = '';
    backend.stdout.on('data', data => { stdout += data; });
    backend.stderr.on('data', data => { stderr += data; });
    const exited = new Promise((accept, reject) => { backend.once('error', reject); backend.once('exit', accept); });
    backend.stdin.end(JSON.stringify({...report, identity_types: [], edited_snapshots: {outputs: []}, identity_checks: []}));
    const code = await exited;
    report.backend_command = {status: code, stdout, stderr};
    if (code !== 0) throw new Error(`后端拒绝自动链接快照\n${stderr}`);
    report.backend_output = JSON.parse(stdout);
    assert.equal(report.backend_output.pairs_checked, report.autolink_conformance.outputs.length);
  } else {
  const output = await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verify())');
  report.result = resultFrom(output);
  if (report.result.cases.length !== 15 || report.result.cases.some(entry => !entry.raw_equal || !entry.projection_equal || !entry.changed_rejected)) throw new Error('浏览器断言不完整');
  await cli('snapshot');
  await cli('screenshot', '--filename=output/playwright/editor-source.png');
  report.snapshot_contract = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyContracts())'));
  if (report.snapshot_contract.positive_fixtures.length !== 15 || report.snapshot_contract.rejected_variants.length !== 31 || !report.snapshot_contract.metadata_capacity_rejected) throw new Error('完整快照门禁断言不完整');
  report.identity_types = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyIdentityTypes())'));
  if (report.identity_types.length !== 15) throw new Error('身份节点逐类型检查不完整');
  await cli('snapshot');
  report.edited_snapshots = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyEditedSnapshots())'));
  if (report.edited_snapshots.checks.length !== 19) throw new Error('编辑快照检查不完整');
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
    assert.deepEqual(actual.dom_ids, ids.filter(id => id !== null).map(String), `${name}: DOM身份`);
    assert.equal(actual.next, next, `${name}: 高水位`);
    assert.equal(actual.pair.block_state_json.next_block_id, next, `${name}: 输出高水位`);
    assert.deepEqual(actual.pair.block_state_json.blocks.map(block => block.block_id), ids.filter((id, index) => id !== null &&
      !(name === 'keyboard-empty-first-split' && index === 0)), `${name}: 输出业务区块身份`);
    if (position !== undefined) assert.equal(actual.position, position, `${name}: 光标`);
    assert.equal(actual.serialized.includes('walle_block_id'), false, `${name}: 元数据泄漏`);
    const exactMarkdown = {
      'initial-bind': '甲乙\n\n尾\n',
      'keyboard-split': '甲\n\n乙\n\n尾\n',
      'keyboard-undo': '甲乙\n\n尾\n',
      'keyboard-redo': '甲\n\n乙\n\n尾\n',
      'keyboard-join': '甲乙\n\n尾\n',
      'keyboard-second-split': '甲\n\n乙\n\n尾\n',
      'keyboard-empty-first-split': '甲\n\n乙\n\n尾\n',
      'keyboard-empty-first-join': '甲\n\n乙\n\n尾\n',
      'keyboard-empty-new-gap': '甲\n\n乙\n\n尾\n',
      'keyboard-gap-becomes-block': '甲\n\n乙\n\n尾\n\n新\n',
    };
    assert.equal(actual.pair.markdown_content, exactMarkdown[name], `${name}: 完整源码及撤销恢复`);
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
  await cli('press', 'Control+End');
  await cli('press', 'Enter');
  await checkIdentity('keyboard-empty-new-gap', [10,31,20,null], 33, 10);
  await cli('type', '新');
  await checkIdentity('keyboard-gap-becomes-block', [10,31,20,33], 34, 11);
  await cli('screenshot', '--filename=output/playwright/editor-identity.png');
  report.autolink_conformance = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.autolinkConformance())'));
  assert.equal(report.autolink_conformance.records.length, 48);
  assert.deepEqual(report.autolink_conformance.mismatches, [], '独立自动链接/容器预期');
  assert.equal(report.autolink_conformance.outputs.length, 51);
  const backendCommand = [resolve(root, '.venv/Scripts/python.exe'), '-X', 'utf8', 'tools/verify-editor-output.py'];
  const backend = spawn(backendCommand[0], backendCommand.slice(1), {cwd: root, windowsHide: true});
  let backendStdout = '', backendStderr = '';
  backend.stdout.on('data', data => { backendStdout += data; });
  backend.stderr.on('data', data => { backendStderr += data; });
  const backendExited = new Promise((accept, reject) => { backend.once('error', reject); backend.once('exit', accept); });
  backend.stdin.end(JSON.stringify(report));
  const backendStatus = await backendExited;
  report.backend_command = {command: backendCommand, status: backendStatus, stdout: backendStdout, stderr: backendStderr};
  if (backendStatus !== 0) throw new Error(`后端拒绝真实编辑器快照\n${backendStderr}`);
  report.backend_output = JSON.parse(backendStdout);
  assert.equal(report.backend_output.passed, true);
  assert.equal(report.backend_output.pairs_checked, report.identity_types.length + report.edited_snapshots.outputs.length + report.identity_checks.length + report.autolink_conformance.outputs.length);
  }
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = String(error);
  process.exitCode = 1;
} finally {
  try { await cli('close'); } catch (error) { report.close_error = String(error); process.exitCode = 1; }
  vite.kill();
  report.server_log = serverLog;
  report.inputs_before = beforeHashes;
  report.inputs_after = await inputHashes();
  if (JSON.stringify(report.inputs_before) !== JSON.stringify(report.inputs_after)) {
    report.passed = false;
    report.error = '验证期间源码或夹具发生变化，结果不能用于该版本验收';
    process.exitCode = 1;
  }
  const path = resolve(root, 'docs/verification', `editor-browser-${report.timestamp.replace(/[:.]/g, '-')}.json`);
  await writeFile(path, JSON.stringify(report, null, 2) + '\n');
  console.log(`${report.passed ? baselineOnly ? 'BASELINE COLLECTED' : 'PASS' : 'FAIL'} ${path}`);
  if (report.error) console.error(report.error);
}
