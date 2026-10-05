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
const strikethroughOnly = process.argv.includes('--strikethrough-check');
const rawSourceOnly = process.argv.includes('--raw-source-check');
const selectionOnly = process.argv.includes('--selection-check');
const normalizationOnly = process.argv.includes('--normalization-check');
const receiptsOnly = process.argv.includes('--receipts-check');
if ([baselineOnly, autolinkOnly, strikethroughOnly, rawSourceOnly, selectionOnly, normalizationOnly, receiptsOnly].filter(Boolean).length > 1) throw new Error('独立检查模式不能混用');
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
  'frontend/src/documents/recovery-store.ts', 'frontend/src/api/client.ts', 'frontend/src/api/decoding.ts',
  'frontend/src/documents/autolink-lexemes.ts', 'frontend/src/documents/autolink-remark.ts',
  'frontend/src/documents/inline-marks.ts',
  'frontend/src/documents/raw-source-remark.ts', 'backend/app/documents/raw_source.py',
  'shared/fixtures/raw-source-containers-v1.json', 'frontend/tests/browser/raw-source.ts',
  'frontend/src/documents/editor-selection.ts', 'frontend/tests/browser/editor-selection.ts',
  'frontend/src/documents/source-normalization.ts', 'frontend/tests/browser/source-normalization.ts',
  'shared/fixtures/editor-selection-v1.json', 'backend/app/documents/anchors.py',
  'frontend/src/documents/url-domain-unicode.ts', 'shared/markdown/url-domain-unicode-v1.json',
  'backend/app/documents/autolinks.py', 'backend/app/documents/markdown.py', 'backend/requirements.lock',
  'backend/app/documents/snapshot.py', 'backend/app/shared/validation.py', 'backend/app/shared/time.py',
  'backend/app/documents/strikethrough.py', 'shared/fixtures/strikethrough-v1.json', 'frontend/tests/browser/strikethrough.ts',
  'tools/verify-editor-output.py',
  'shared/fixtures/autolink-v1.json', 'frontend/tests/browser/autolink-baseline.ts', 'tools/autolink-baseline.py',
  'shared/fixtures/autolink-context-v1.json', 'frontend/tests/browser/autolink-conformance.ts',
  'shared/fixtures/autolink-unicode-v1.json',
  'frontend/tests/browser/probe.ts', 'frontend/tests/browser/editor.html',
  'frontend/tests/browser/vite.config.ts', 'tools/verify-editor-browser.mjs',
  'frontend/tests/browser/save-receipts.ts', 'tools/editor-save-roundtrip.py',
  'backend/app/documents/commands.py', 'backend/app/documents/contracts.py', 'backend/app/documents/manual_identity.py',
  'backend/app/documents/sources.py', 'backend/app/documents/guards.py', 'backend/app/documents/queries.py',
  'backend/app/infrastructure/document_repository.py', 'backend/app/infrastructure/requirement_repository.py',
  'backend/app/infrastructure/database.py', 'backend/app/infrastructure/idempotency.py',
  'backend/app/infrastructure/process_lock.py', 'backend/app/infrastructure/resources.py',
  'backend/app/infrastructure/identifiers.py', 'backend/app/shared/command_execution.py',
  'backend/app/infrastructure/migrations/001_initial.sql', 'backend/app/infrastructure/migrations/002_idempotency_guards.sql',
  'backend/app/infrastructure/migrations/003_manual_edit_sources.sql', 'backend/app/infrastructure/migrations/004_manual_identity_proofs.sql',
  'backend/tests/infrastructure/test_database.py'];
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
const report = {timestamp: new Date().toISOString(), scope: 'Source/projection, local pairs, Crepe identity/history and actual SQLite save receipts via isolated diagnostic subprocess bridge; no product pages or HTTP acceptance', commands};
function resultFrom(output) {
  const match = /### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output);
  if (!match) throw new Error('浏览器未返回结构化结果');
  return JSON.parse(match[1]);
}
async function verifyReceipts() {
  const database = resolve(artifacts, `receipt-${session}.sqlite`);
  const calls = [];
  async function native(operation, request) {
    const child = spawn(resolve(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'tools/editor-save-roundtrip.py', operation, '--database', database], {cwd: root, windowsHide: true});
    let stdout = '', stderr = '';
    child.stdout.on('data', data => { stdout += data; });
    child.stderr.on('data', data => { stderr += data; });
    const exited = new Promise((accept, reject) => { child.once('error', reject); child.once('exit', accept); });
    child.stdin.end(request ? JSON.stringify(request) : undefined);
    const status = await exited;
    if (status !== 0) throw new Error(`实际保存探针失败: ${stderr}`);
    const result = JSON.parse(stdout);
    calls.push({operation, request, result, status, stderr});
    assert.equal(result.code, operation === 'init' ? 'DRAFT_STARTED' : operation === 'save' ? 'DRAFT_SAVED' : 'READ_OK');
    return operation === 'init' ? result.data.manual_draft : result.data;
  }
  const initial = await native('init');
  async function phase(name, document) {
    await cli('snapshot');
    return resultFrom(await cli('run-code', `async (page) => await page.evaluate(document => window.editorProbe.receipts.${name}(document), ${JSON.stringify(document)})`));
  }
  let value = await phase('start', initial);
  for (const name of ['first', 'second', 'third', 'fourth']) {
    const receipt = await native('save', value.request);
    value = await phase(name, receipt);
  }
  assert.equal(value.checks.length, 11);
  assert.equal(value.outputs.length, 16);
  assert.deepEqual(value.ids, [1,4,2,5]);
  assert.equal(value.next, 6);
  const persisted = await native('read');
  assert.equal(persisted.content_version, 5);
  assert.deepEqual(persisted.block_state_json, value.outputs.at(-1).pair.block_state_json);
  return {...value, database_path: database, requirement_id: initial.requirement_id, native_calls: calls,
    database_sha256: createHash('sha256').update(await readFile(database)).digest('hex'),
    scope: 'Actual Crepe/history and real SQLite application save roundtrips; diagnostic subprocess bridge, no HTTP/product UI acceptance'};
}
async function verifySelection() {
  const result = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyEditorSelection())'));
  assert.equal(result.records.length, 14);
  assert.deepEqual(result.rejected, ['cross-block', 'surrogate-interior', 'partial-html-atom', 'outside-editor', 'stale-dom-state', 'collapsed-no-event',
    'old-document', 'old-version', 'changed-text', 'missing-block', 'inverse-partial-image-alt', 'inverse-partial-synthetic-tail', '2001-not-truncated']);
  assert.ok(result.records.every(entry => entry.inverse_equal === true));
  await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.prepareSelection())');
  const snapshot = await cli('snapshot');
  const ref = /textbox \[ref=([^\]]+)\]/.exec(snapshot)?.[1];
  if (!ref) throw new Error('选区键盘检查缺少真实编辑器引用');
  await cli('click', ref);
  await cli('press', 'Control+Home');
  await cli('press', 'ArrowRight');
  await cli('press', 'Shift+ArrowRight');
  const keyboard = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.keyboardSelection())'));
  assert.deepEqual(keyboard.event, {document_id: 90, content_version: 3, block_id: 10, start_offset: 1, end_offset: 2,
    selected_text: '😀', prefix_text: '甲', suffix_text: '乙'});
  result.records.push(keyboard);
  return result;
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
  } else if (autolinkOnly || strikethroughOnly || rawSourceOnly || selectionOnly || normalizationOnly || receiptsOnly) {
    report.scope = receiptsOnly ? 'Actual Crepe/history and isolated SQLite save receipt roundtrips, no product/HTTP acceptance' : 'Independent syntax/context cases and edited output; fixture provenance, not product/HTTP acceptance';
    if (autolinkOnly) {
      report.autolink_conformance = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.autolinkConformance())'));
      assert.equal(report.autolink_conformance.records.length, 56);
      assert.deepEqual(report.autolink_conformance.mismatches, []);
      assert.equal(report.autolink_conformance.outputs.length, 61);
    } else if (strikethroughOnly) {
      report.strikethrough = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyStrikethrough())'));
      assert.equal(report.strikethrough.records.length, 18);
      assert.equal(report.strikethrough.outputs.length, 21);
    } else if (rawSourceOnly) {
      report.raw_source = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyRawSource())'));
      assert.equal(report.raw_source.records.length, 18);
      assert.equal(report.raw_source.outputs.length, 22);
    } else if (selectionOnly) {
      report.editor_selection = await verifySelection();
    } else if (receiptsOnly) {
      report.receipts = await verifyReceipts();
    } else {
      report.source_normalization = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifySourceNormalization())'));
      assert.equal(report.source_normalization.checks.length, 51);
      assert.equal(report.source_normalization.outputs.length, 114);
    }
    const backend = spawn(resolve(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'tools/verify-editor-output.py'], {cwd: root, windowsHide: true});
    let stdout = '', stderr = '';
    backend.stdout.on('data', data => { stdout += data; });
    backend.stderr.on('data', data => { stderr += data; });
    const exited = new Promise((accept, reject) => { backend.once('error', reject); backend.once('exit', accept); });
    backend.stdin.end(JSON.stringify({...report, identity_types: [], edited_snapshots: {outputs: []}, identity_checks: []}));
    const code = await exited;
    report.backend_command = {status: code, stdout, stderr};
    if (code !== 0) throw new Error(`后端拒绝方言快照\n${stderr}`);
    report.backend_output = JSON.parse(stdout);
    assert.equal(report.backend_output.pairs_checked, selectionOnly ? report.editor_selection.records.length :
      (report.autolink_conformance ?? report.strikethrough ?? report.raw_source ?? report.source_normalization ?? report.receipts).outputs.length);
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
  assert.equal(report.autolink_conformance.records.length, 56);
  assert.deepEqual(report.autolink_conformance.mismatches, [], '独立自动链接/容器预期');
  assert.equal(report.autolink_conformance.outputs.length, 61);
  report.strikethrough = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyStrikethrough())'));
  assert.equal(report.strikethrough.records.length, 18);
  assert.equal(report.strikethrough.outputs.length, 21);
  report.raw_source = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifyRawSource())'));
  assert.equal(report.raw_source.records.length, 18);
  assert.equal(report.raw_source.outputs.length, 22);
  report.editor_selection = await verifySelection();
  report.source_normalization = resultFrom(await cli('run-code', 'async (page) => await page.evaluate(() => window.editorProbe.verifySourceNormalization())'));
  assert.equal(report.source_normalization.checks.length, 51);
  assert.equal(report.source_normalization.outputs.length, 114);
  report.receipts = await verifyReceipts();
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
  assert.equal(report.backend_output.pairs_checked, report.identity_types.length + report.edited_snapshots.outputs.length + report.identity_checks.length + report.autolink_conformance.outputs.length + report.strikethrough.outputs.length + report.raw_source.outputs.length + report.editor_selection.records.length + report.source_normalization.outputs.length + report.receipts.outputs.length);
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
