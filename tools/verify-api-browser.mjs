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
const nativeDiagnostics=resolve(directory,`vite-native-${session}`);await mkdir(nativeDiagnostics,{recursive:true});
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
  vite = subprocess(globalThis.process.execPath, ['--report-on-fatalerror','--report-exclude-env',`--report-directory=${nativeDiagnostics}`,'node_modules/vite/bin/vite.js', '--config', 'tests/browser/api-vite.config.ts', '--host', '127.0.0.1', '--port', '5175', '--strictPort'],
    { cwd: resolve(root, 'frontend'), env: { ...env, WALLE_PROBE_API_URL: ready.url } });
  let live = false;
  for (let index = 0; index < 100; index++) {
    try { const response = await fetch('http://127.0.0.1:5175/tests/browser/api.html'); if (response.ok) { live = true; break; } } catch { /* server not ready */ }
    if (vite.child.exitCode !== null) throw new Error(vite.record.stderr); await wait(100);
  }
  assert(live); await cli('open', 'http://127.0.0.1:5175/tests/browser/api.html'); opened = true;
  await cli('snapshot');
  await cli('run-code', 'async (page) => { await page.waitForFunction(() => document.querySelector("#status")?.textContent === "READY", null, {timeout: 15000}); return true; }');
  report.workbench_empty = result(await cli('run-code','async (page) => { await page.evaluate(() => window.apiProbe.mountWorkbench(false)); await page.waitForFunction(() => window.workbenchProbe?.state().phase === "EMPTY"); const value=await page.evaluate(() => window.workbenchProbe.state()); if(value.state.result.pagination.total!==0||await page.getByText("暂无需求",{exact:true}).count()!==1)throw new Error("Native empty workbench missing"); await page.evaluate(() => window.workbenchProbe.destroy()); return {passed:true,total:0}; }'));
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
  await cli('run-code','async (page) => { await page.evaluate(() => window.apiProbe.mountWorkbench(true)); await page.waitForFunction(() => window.workbenchProbe.state().phase === "READY"); return true; }');
  await cli('snapshot');
  report.workbench_queries=result(await cli('run-code',`async(page)=>{
    const input=page.getByRole('textbox',{name:'请输入需求编号或需求标题'});await input.fill('未提交草稿');
    let state=await page.evaluate(()=>window.workbenchProbe.state());if(state.reads.length!==1||state.state.result.pagination.total!==24)throw new Error('Input caused query or wrong native total');
    await page.getByRole('button',{name:'需求状态：全部'}).click();await page.getByLabel('已完成',{exact:true}).uncheck();await page.mouse.click(5,5);
    await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().reads.length===2);
    state=await page.evaluate(()=>window.workbenchProbe.state());if(state.reads[1].keyword!==undefined||state.state.requested.keyword!=='')throw new Error('Filter submitted draft');
    await input.fill('工作台条目');await input.press('Enter');await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().state.result.pagination.total===21);
    await page.getByRole('button',{name:'第 2 页',exact:true}).click();await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().state.result.pagination.page===2);
    if(await page.locator('.workbench-table tbody tr').count()!==1)throw new Error('Native page2 wrong count');await input.fill('另一个未提交草稿');
    await page.getByRole('button',{name:'第 1 页',exact:true}).click();await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().state.result.pagination.page===1);
    state=await page.evaluate(()=>window.workbenchProbe.state());if(state.reads.at(-1).keyword!=='工作台条目'||state.state.result.items.length!==20)throw new Error('Paging submitted draft');
    await page.screenshot({path:'output/playwright/workbench-native.png'});return {passed:true,reads:state.reads,requested:state.state.requested,total:state.state.result.pagination.total};
  }`.replace(/\r?\n/g,' ')));
  report.workbench_return=result(await cli('run-code',`async(page)=>{
    await page.evaluate(()=>window.scrollTo(0,500));const title=page.locator('.workbench-table tbody tr').nth(10).locator('a'),box=await title.boundingBox();if(!box)throw new Error('Visible native row missing');
    await page.mouse.move(box.x+3,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+55,box.y+box.height/2,{steps:8});await page.mouse.up();
    let state=await page.evaluate(()=>window.workbenchProbe.state());if(state.opened.length||!await page.evaluate(()=>window.getSelection()?.toString()))throw new Error('Drag navigated or no actual selection');
    await title.click();await page.waitForSelector('[data-native-detail]');state=await page.evaluate(()=>window.workbenchProbe.state());const saved=state.entry;
    if(state.opened.length!==1||saved.query.keyword!=='工作台条目'||saved.query.page!==1||saved.scroll<=0)throw new Error('Native detail entry not saved');
    const updated=await page.evaluate(()=>window.workbenchProbe.updateOpened());await page.evaluate(()=>window.workbenchProbe.holdNext());await page.goBack();await page.waitForFunction(()=>window.workbenchProbe.state().held&&window.workbenchProbe.state().phase==='REFRESHING');
    if(await page.locator('.workbench-table tbody tr').count()!==20||await page.evaluate(()=>window.scrollY)!==0)throw new Error('Return lost old rows or restored before fresh response');
    await page.evaluate(()=>window.workbenchProbe.release());await page.waitForFunction(saved=>window.workbenchProbe.state().phase==='READY'&&Math.abs(window.scrollY-saved.scroll)<=1,saved);
    state=await page.evaluate(()=>window.workbenchProbe.state());const session=await page.evaluate(()=>window.workbenchProbe.sessionSnapshot());
    if(!state.state.result.items.some(row=>row.id===updated.id&&row.title===updated.title))throw new Error('Return did not show actual intervening native title update');
    if(state.entry.entry_id!==saved.entry_id||session.query.keyword!=='工作台条目'||session.scroll!==saved.scroll)throw new Error('Wrong session/history entry restored');
    return {passed:true,entry:saved,restored_scroll:state.scroll,session,scope:'Real browser Back/native API refresh held after actual read; same entry restored after render, no whole-page reload claim'};
  }`.replace(/\r?\n/g,' ')));
  report.workbench_states=result(await cli('run-code',`async(page)=>{
    await page.evaluate(()=>window.workbenchProbe.outOfRange());await page.waitForFunction(()=>window.workbenchProbe.state().phase==='OUT_OF_RANGE');
    await page.getByRole('button',{name:'返回有效页'}).click();await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().state.requested.page===2);
    await page.evaluate(()=>window.workbenchProbe.dropNextRead());const input=page.getByRole('textbox',{name:'请输入需求编号或需求标题'});await input.fill('不存在工作台文本');await input.press('Enter');
    await page.waitForFunction(()=>window.workbenchProbe.state().phase==='REFRESH_ERROR');let state=await page.evaluate(()=>window.workbenchProbe.state());
    if(state.state.confirmed.keyword!=='工作台条目'||state.state.requested.keyword!=='不存在工作台文本'||await page.locator('.workbench-table tbody tr').count()!==1)throw new Error('Refresh loss discarded successful condition/row');
    if(await page.getByText('没有符合条件的需求',{exact:true}).count())throw new Error('Failed refresh claimed empty result');
    await page.getByRole('button',{name:'重试查询'}).click();await page.waitForFunction(()=>window.workbenchProbe.state().phase==='NO_MATCH');
    await input.fill('😀'.repeat(101));const before=(await page.evaluate(()=>window.workbenchProbe.state())).reads.length;await input.press('Enter');
    if((await page.evaluate(()=>window.workbenchProbe.state())).reads.length!==before||!await page.getByRole('alert').filter({hasText:'100'}).count())throw new Error('Invalid keyword submitted or error absent');
    await page.evaluate(()=>window.workbenchProbe.mainNavigation());await page.waitForFunction(()=>window.workbenchProbe.state().phase==='READY'&&window.workbenchProbe.state().state.requested.keyword==='');
    state=await page.evaluate(()=>window.workbenchProbe.state());if(state.state.requested.status.length!==3||state.state.requested.requirement_type.length!==2||state.state.requested.page!==1)throw new Error('Main navigation did not reset');
    await page.evaluate(()=>window.workbenchProbe.destroy());return {passed:true,main_query:state.state.requested,states:['EMPTY','READY','REFRESHING','OUT_OF_RANGE','REFRESH_ERROR','NO_MATCH'],scope:'Refresh error is explicit local discard after actual native successful GET, not real offline TCP or full navigation product acceptance'};
  }`.replace(/\r?\n/g,' ')));
  report.detail_layout_geometry=result(await cli('run-code',`async(page)=>{
    await page.setViewportSize({width:1600,height:900});await page.evaluate(()=>window.apiProbe.mountDetailFrame());
    await page.waitForSelector('#detail-frame-editor .ProseMirror');await page.locator('#native-detail-frame .detail-header').scrollIntoViewIfNeeded();
    const frame=page.locator('#native-detail-frame');
    if(await frame.getByRole('complementary',{name:'辅助面板'}).isVisible())throw Error('Actual ACTIVE default panel should be closed');
    await frame.getByRole('button',{name:/^辅助面板/}).click();const resize=frame.getByRole('separator',{name:'调整辅助面板宽度'});
    const handle=await resize.boundingBox();if(!handle)throw Error('Resize handle geometry missing');
    await page.mouse.move(handle.x+handle.width/2,handle.y+20);await page.mouse.down();await page.mouse.move(handle.x+handle.width/2-100,handle.y+20,{steps:10});await page.mouse.up();
    if(Math.abs((await page.evaluate(()=>window.detailFrameProbe.state())).geometry.preferences.right_width-520)>1)throw Error('Native drag width not stored');
    await resize.focus();for(let i=0;i<4;i++)await page.keyboard.press('ArrowLeft');
    let state=await page.evaluate(()=>window.detailFrameProbe.state());if(state.geometry.preferences.right_width!==600)throw Error('Keyboard width not stored');
    await page.setViewportSize({width:1280,height:900});await page.waitForFunction(()=>{
      const s=window.detailFrameProbe.state().geometry,region=document.querySelector('#native-detail-frame .detail-document-region'),panel=document.querySelector('#native-detail-frame .detail-panel');
      return s.mode==='DESKTOP'&&s.right_width<600&&s.document_width>=640&&region?.getBoundingClientRect().width>=639.9&&Math.abs(panel?.getBoundingClientRect().width-s.right_width)<0.1;
    });
    state=await page.evaluate(()=>window.detailFrameProbe.state());const doc=await frame.locator('.detail-document-region').boundingBox();if(doc.width<639.9||state.geometry.preferences.right_width!==600||state.geometry.right_width>=600)throw Error('Desktop clamp lost minimum/preference '+JSON.stringify({geometry:state.geometry,doc}));
    await page.setViewportSize({width:1024,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().geometry.mode==='COMPACT');
    if(await frame.getByRole('complementary',{name:'文档大纲'}).isVisible()||!await frame.getByRole('complementary',{name:'辅助面板'}).isVisible())throw Error('Compact did not prioritize right panel');
    await frame.getByRole('button',{name:'大纲',exact:true}).click();if(!await frame.getByRole('complementary',{name:'文档大纲'}).isVisible()||await frame.getByRole('complementary',{name:'辅助面板'}).isVisible())throw Error('Compact outline mutual exclusion');
    await frame.getByRole('button',{name:/^辅助面板/}).click();await frame.getByRole('tab',{name:'评论',exact:true}).click();
    await page.waitForFunction(()=>window.detailFrameProbe.state().panelReads.includes('COMMENTS'));
    state=await page.evaluate(()=>window.detailFrameProbe.state());if(!state.geometry.preferences.left_open||state.geometry.preferences.right_tab!=='COMMENTS')throw Error('Auto collapse persisted');
    return {passed:true,preferences:state.geometry.preferences,document_minimum:doc.width,native_drag:true,keyboard_resize:true};
  }`.replace(/\r?\n/g,' ')));
  report.detail_layout=result(await cli('run-code',`async(page)=>{
    const frame=page.locator('#native-detail-frame');let state;
    const editor=frame.getByRole('textbox',{name:'人工编辑草稿'});await editor.click();await editor.press('Control+Home');await editor.press('End');await editor.press('Enter');await editor.pressSequentially('窄屏保存真实输入😀');
    await page.setViewportSize({width:1000,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().guard.phase==='BLOCKED'&&!window.detailFrameProbe.state().guard.saving);
    state=await page.evaluate(()=>window.detailFrameProbe.state());if(!state.readonly||state.save.confirmed_version!==2||state.save.status!=='SAVED'||await frame.getByRole('textbox').count()||await frame.getByRole('tab').count())throw Error('Narrow failed actual save/input block');
    const actual=await page.evaluate(()=>window.detailFrameProbe.inspect());if(!actual.markdown.includes('窄屏保存真实输入😀'))throw Error('Narrow content not native persisted');
    await frame.getByText('当前窗口过窄，请将窗口调整至至少 1024px',{exact:true}).waitFor();await page.screenshot({path:'output/playwright/detail-narrow.png'});
    await page.evaluate(()=>window.detailFrameProbe.holdNextRead());await page.setViewportSize({width:1280,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().held);
    if(await frame.getByRole('textbox').count()||await frame.getByRole('button',{name:'布局诊断操作'}).count())throw Error('Restoration opened before actual read');
    await page.setViewportSize({width:900,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().guard.phase==='BLOCKED');await page.evaluate(()=>window.detailFrameProbe.release());
    await page.evaluate(()=>window.detailFrameProbe.dropNextRead());await page.setViewportSize({width:1280,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().guard.phase==='RESTORE_FAILED');
    if(await frame.getByRole('textbox').count())throw Error('Failed read opened operations');await frame.getByRole('button',{name:'重新读取',exact:true}).click();
    await page.waitForFunction(()=>window.detailFrameProbe.state().guard.phase==='SUPPORTED');state=await page.evaluate(()=>window.detailFrameProbe.state());
    if(state.readonly||!state.editor_connected||state.restoreReads!==3||state.errors.length||state.geometry.preferences.right_width!==600)throw Error('Restore lost instance/preferences or state');
    await page.setViewportSize({width:1600,height:900});await page.waitForFunction(()=>window.detailFrameProbe.state().geometry.right_width===600);
    await frame.getByRole('tab',{name:'版本记录',exact:true}).click();await page.waitForFunction(()=>window.detailFrameProbe.state().panelReads.includes('REVISIONS'));
    await frame.locator('.detail-header').scrollIntoViewIfNeeded();await page.screenshot({path:'output/playwright/detail-desktop.png'});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Detail produced page overflow');
    const final=await page.evaluate(()=>window.detailFrameProbe.state());await page.evaluate(()=>window.detailFrameProbe.destroy());await page.setViewportSize({width:1280,height:720});
    return {passed:true,native_draft_version:actual.version,restore_reads:final.restoreReads,panel_reads:final.panelReads,preferences:final.geometry.preferences,
      scope:'Real layout/keyboard/native viewport, actual editor draft I11/I03/I08/I10 and panel reads; held and discarded actual re-read for race/failure. Parent is explicit diagnostic, not complete detail product or Windows IME'};
  }`.replace(/\r?\n/g,' ')));
  report.detail_read=result(await cli('run-code','async(page)=>await page.evaluate(()=>window.apiProbe.detailRead())'));
  assert.equal(report.detail_read.passed,true);
  report.manual_end=result(await cli('run-code',`async(page)=>{
    const before=await page.evaluate(()=>window.apiProbe.wireFacts().length),probe=await page.evaluate(()=>window.apiProbe.manualEnd());
    const wires=(await page.evaluate(()=>window.apiProbe.wireFacts())).slice(before);
    const complete=wires.filter(wire=>wire.path==='/api/v1/requirements/2/manual-draft/complete'),cancel=wires.filter(wire=>wire.path==='/api/v1/requirements/2/manual-draft'&&wire.method==='DELETE');
    for(const pair of [complete,cancel])if(pair.length!==2||pair.some(wire=>wire.status!==200||typeof wire.body!=='string'||typeof wire.key!=='string'||!wire.key)||pair[0].key!==pair[1].key||pair[0].body!==pair[1].body)throw Error('Ending replay differs from original native action');
    if(JSON.parse(complete[0].body).expected_version!==3||JSON.parse(cancel[0].body).expected_version!==2)throw Error('Ending used wrong independent draft version');
    return {...probe,replay_wires:[...complete,...cancel]};
  }`.replace(/\r?\n/g,' ')));
  assert.equal(report.manual_end.passed,true);
  report.manual_start=result(await cli('run-code',`async(page)=>{
    const before=await page.evaluate(()=>window.apiProbe.wireFacts().length),probe=await page.evaluate(()=>window.apiProbe.manualStart());
    const wires=(await page.evaluate(()=>window.apiProbe.wireFacts())).slice(before),starts=wires.filter(wire=>wire.method==='POST'&&wire.path==='/api/v1/requirements/2/manual-draft');
    if(starts.length!==2||starts.some(wire=>wire.status!==201||typeof wire.body!=='string'||typeof wire.key!=='string'||!wire.key)||starts[0].key!==starts[1].key||starts[0].body!==starts[1].body||JSON.parse(starts[0].body).expected_version!==3)throw Error('Draft start replay differs from original native intention');
    return {...probe,replay_wires:starts};
  }`.replace(/\r?\n/g,' ')));
  assert.equal(report.manual_start.passed,true);
  report.recovery_adoption_prepare=result(await cli('run-code','async(page)=>await page.evaluate(()=>window.apiProbe.recoveryAdoptionPrepare())'));
  assert.equal(report.recovery_adoption_prepare.passed,true);
  await cli('run-code','async(page)=>{ await page.reload(); await page.waitForFunction(()=>document.querySelector("#status")?.textContent==="READY",null,{timeout:15000});return true;}');
  await cli('snapshot');
  report.recovery_adoption=result(await cli('run-code','async(page)=>await page.evaluate(()=>window.apiProbe.recoveryAdoptionResume())'));
  assert.equal(report.recovery_adoption.passed,true);
  report.manual_controls=[];
  for(const [operation,localMode] of [['COMPLETE','AVAILABLE'],['CANCEL','COMPARE'],['CANCEL','NONE']]){
    const before=result(await cli('run-code',`async(page)=>{const before=await page.evaluate(()=>window.apiProbe.wireFacts().length);await page.evaluate(args=>window.apiProbe.mountManualControls(...args),${JSON.stringify([operation,localMode])});return before;}`));
    await cli('snapshot');
    await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls');await scope.getByRole('button',{name:'人工编辑',exact:true}).click();
      await page.waitForFunction(()=>window.manualControlsProbe.state().start.phase==='UNKNOWN');await scope.getByRole('button',{name:'重新确认开始编辑',exact:true}).click();
      await page.waitForFunction(()=>window.manualControlsProbe.state().recovery?.phase===${JSON.stringify(localMode==='NONE'?'NONE':localMode)}&&!window.manualControlsProbe.state().recovery.checking);
      const state=await page.evaluate(()=>window.manualControlsProbe.state());if(!state.readonly||state.startPrepares!==1||state.startSubmits!==2)throw Error('Start control fabricated edit readiness');
      if(${JSON.stringify(localMode)}==='NONE'){await scope.getByRole('button',{name:'继续后端草稿',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().serverReads===1);}
      else{await scope.getByRole('button',{name:'对照内容',exact:true}).click();const compare=scope.getByLabel('草稿内容对照');await compare.waitFor();if(!await compare.locator('pre').first().textContent().then(value=>value.includes('实际本地待恢复内容😀'))||await compare.locator('pre').count()!==2)throw Error('Actual paired comparison missing');await page.screenshot({path:'output/playwright/manual-recovery-${localMode.toLowerCase()}.png'});}
      return true;
    }`.replace(/\r?\n/g,' '));
    if(localMode==='AVAILABLE')await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls');await scope.getByRole('button',{name:'恢复本地内容',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().recovery.phase==='RESTORED');
      if(!await scope.getByRole('button',{name:'完成编辑',exact:true}).isDisabled())throw Error('Unsaved restored content enabled complete');await page.evaluate(()=>window.manualControlsProbe.flush());
      await page.waitForFunction(()=>window.manualControlsProbe.state().save.status==='SAVED');await page.evaluate(()=>window.manualControlsProbe.composition(true));
      await page.waitForFunction(()=>!window.manualControlsProbe.state().valid);if(!await scope.getByRole('button',{name:'完成编辑',exact:true}).isDisabled())throw Error('Composition left complete enabled');
      await page.evaluate(()=>window.manualControlsProbe.composition(false));await page.waitForFunction(()=>window.manualControlsProbe.state().valid);return true;
    }`.replace(/\r?\n/g,' '));
    if(localMode==='COMPARE')await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls');if(await scope.getByRole('button',{name:'恢复本地内容',exact:true}).count())throw Error('Divergent content can restore');
      await scope.getByRole('button',{name:'使用后端草稿',exact:true}).click();const dialog=page.getByRole('dialog',{name:'放弃本地未同步内容？',exact:true});await dialog.waitFor();
      if(!await dialog.getByRole('button',{name:'继续编辑',exact:true}).evaluate(element=>element===document.activeElement))throw Error('Discard confirmation lacks safe focus');
      await dialog.getByRole('button',{name:'继续编辑',exact:true}).click();if((await page.evaluate(()=>window.manualControlsProbe.state())).recovery.phase!=='COMPARE')throw Error('Dismissal discarded content');
      await scope.getByRole('button',{name:'使用后端草稿',exact:true}).click();await dialog.getByRole('button',{name:'确认放弃',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().serverReads===1);return true;
    }`.replace(/\r?\n/g,' '));
    await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls'),editor=scope.getByRole('textbox',{name:'人工编辑草稿',exact:true});await editor.click();await editor.press('Control+End');await page.keyboard.press('Enter');await page.keyboard.insertText('控件真实浏览器编辑😀');
      await page.waitForFunction(()=>window.manualControlsProbe.state().save.status==='DIRTY');if(!await scope.getByRole('button',{name:'完成编辑',exact:true}).isDisabled())throw Error('Dirty control claims saved');
      await page.evaluate(()=>window.manualControlsProbe.flush());await page.waitForFunction(()=>window.manualControlsProbe.state().save.status==='SAVED');
      if(await scope.getByRole('button',{name:'完成编辑',exact:true}).isDisabled()||!await scope.getByRole('status').textContent().then(value=>/^已保存 · /.test(value)))throw Error('Confirmed save not rendered');return true;
    }`.replace(/\r?\n/g,' '));
    if(operation==='CANCEL')await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls');await scope.getByRole('button',{name:'取消编辑',exact:true}).click();const dialog=page.getByRole('dialog',{name:'放弃人工编辑？',exact:true});await dialog.waitFor();
      if(!await dialog.getByRole('button',{name:'继续编辑',exact:true}).evaluate(element=>element===document.activeElement))throw Error('Cancel lacks safe focus');
      await dialog.getByRole('button',{name:'继续编辑',exact:true}).click();if((await page.evaluate(()=>window.manualControlsProbe.state())).endPrepares!==0)throw Error('Dismissal issued I13');
      await scope.getByRole('button',{name:'取消编辑',exact:true}).click();await dialog.getByRole('button',{name:'确认放弃',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().end.phase==='UNKNOWN');
      await page.screenshot({path:'output/playwright/manual-cancel-unknown.png'});await dialog.getByRole('button',{name:'保留请求并关闭弹窗',exact:true}).click();return true;
    }`.replace(/\r?\n/g,' '));
    else await cli('run-code',`async(page)=>{await page.locator('#native-manual-controls').getByRole('button',{name:'完成编辑',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().end.phase==='UNKNOWN');return true;}`);
    const verified=result(await cli('run-code',`async(page)=>{
      const scope=page.locator('#native-manual-controls');if(!(await page.evaluate(()=>window.manualControlsProbe.state())).readonly)throw Error('Unknown result opened editor');
      await page.evaluate(()=>window.manualControlsProbe.dropNextRead());await scope.getByRole('button',{name:'重新确认结束操作',exact:true}).click();
      await scope.getByRole('button',{name:'重新读取实际详情',exact:true}).waitFor();const confirmed=await page.evaluate(()=>window.manualControlsProbe.state());if(confirmed.end.phase!=='CLOSED'||confirmed.endSubmits!==2||confirmed.endedReads!==0)throw Error('Failed detail callback lost native receipt');
      await scope.getByRole('button',{name:'重新读取实际详情',exact:true}).click();await page.waitForFunction(()=>window.manualControlsProbe.state().endedReads===1);
      const probe=await page.evaluate(()=>window.manualControlsProbe.inspect());const wires=(await page.evaluate(()=>window.apiProbe.wireFacts())).slice(${before});
      const starts=wires.filter(wire=>wire.method==='POST'&&wire.path==='/api/v1/requirements/2/manual-draft'),ends=wires.filter(wire=>wire.path==='/api/v1/requirements/2/manual-draft/complete'||wire.method==='DELETE'&&wire.path==='/api/v1/requirements/2/manual-draft');
      for(const [pair,status] of [[starts,201],[ends,200]])if(pair.length!==2||pair.some(wire=>wire.status!==status||!wire.key||typeof wire.body!=='string')||pair[0].key!==pair[1].key||pair[0].body!==pair[1].body)throw Error('UI replay or read retry mutated original command');
      await page.evaluate(()=>window.manualControlsProbe.destroy());return {...probe,replay_wires:[...starts,...ends],scope:'Actual controls/native clicks, editor keyboard input, explicit flush/IndexedDB, native receipts deliberately lost and exact replay, real I37 loss plus read-only retry; synthetic composition events are not Windows IME acceptance'};
    }`.replace(/\r?\n/g,' ')));report.manual_controls.push(verified);assert.equal(verified.passed,true);
  }
  await cli('screenshot', '--filename=output/playwright/api-native-probe.png');
  await cli('run-code', 'async (page) => await page.evaluate(() => window.apiProbe.destroy())');
  report.development_alive_before_close=vite.child.exitCode===null&&vite.child.signalCode===null;assert.equal(report.development_alive_before_close,true);
  const health=await fetch('http://127.0.0.1:5175/api/v1/requirements?page=1');assert.equal(health.status,200);const checked=await health.json();assert.equal(checked.meta.pagination.total,24);
  report.passed = true;
} catch (error) { report.passed = false; report.error = String(error); globalThis.process.exitCode = 1;
  report.development_exit_before_cleanup={code:vite?.child.exitCode??null,signal:vite?.child.signalCode??null};
  if (opened) try {
    report.failure_wires = result(await cli('run-code','async (page) => await page.evaluate(() => window.apiProbe?.wireFacts() ?? [])'));
    report.failure_transport = result(await cli('run-code','async (page) => await page.evaluate(() => window.apiProbe?.transportFacts() ?? [])'));
    report.failure_ui = result(await cli('run-code','async (page) => await page.evaluate(() => ({stage:window.createStage,state:window.createProbe?.state(),workbench:window.workbenchProbe?.state(),detail:window.detailFrameProbe?.state(),manual:window.manualControlsProbe?.state(),dialogs:[...document.querySelectorAll("dialog")].map(element=>element.outerHTML)}))'));
    await cli('snapshot'); await cli('screenshot','--filename=output/playwright/api-failure.png');
  } catch (diagnostic) { report.diagnostic_error = String(diagnostic); }
}
finally {
  if (opened) try { await cli('close'); } catch (error) { report.close_error = String(error); report.passed = false; globalThis.process.exitCode = 1; }
  if (vite) { await killOwned(vite); report.vite = vite.record; }
  report.native_diagnostic_files=await Promise.all((await readdir(nativeDiagnostics)).map(async name=>{const path=resolve(nativeDiagnostics,name);return {path,sha256:createHash('sha256').update(await readFile(path)).digest('hex')};}));
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
      if (closed.facts.llm_uses !== 0 || closed.facts.guide_runs !== 28 || closed.facts.requirements !== 24 || closed.facts.requirement_documents !== 24 || closed.facts.revisions !== 4 || closed.facts.comments !== 2 || native.record.code !== 0) { report.passed = false; report.error ??= 'Native persisted facts/closure differ'; globalThis.process.exitCode = 1; }
    } else { report.passed = false; report.error ??= 'Native closure/facts missing'; globalThis.process.exitCode = 1; }
  }
  report.inputs_after = await hashes();
  report.changed_inputs = [...new Set([...Object.keys(report.inputs_before), ...Object.keys(report.inputs_after)])].filter(key => report.inputs_before[key] !== report.inputs_after[key]);
  if (report.changed_inputs.length) { report.passed = false; report.error ??= 'Inputs changed during verification'; globalThis.process.exitCode = 1; }
  const path = resolve(root, 'docs/verification', `api-browser-${report.timestamp.replace(/[:.]/g, '-')}.json`);
  await writeFile(path, JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify({ passed: report.passed, evidence: path, error: report.error }));
}
