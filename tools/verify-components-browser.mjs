import { spawn } from 'node:child_process';
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const root = resolve(import.meta.dirname, '..'), session = 'walle-components-' + Date.now() + '-' + crypto.randomUUID().replaceAll('-', '').slice(0,12);
const report = { timestamp: new Date().toISOString(), scope: 'Real React/components/native dialog/browser input/focus with explicit controlled parent events and Toast clock; no business HTTP/Provider/product-page/full acceptance', commands: [] };
const wrapper = process.env.WALLE_PLAYWRIGHT_WRAPPER ?? resolve(homedir(), '.codex/skills/playwright/scripts/playwright_cli.sh');
const bash = process.env.WALLE_BASH ?? (process.platform === 'win32' ? 'C:/Program Files/Git/bin/bash.exe' : 'bash');
await mkdir(resolve(root, 'output/playwright'), { recursive: true });
async function hashes() {
  const files = [];
  async function walk(directory) { for (const item of await readdir(directory, { withFileTypes: true })) {
    if (['node_modules','dist'].includes(item.name)) continue;
    const path = resolve(directory, item.name); if (item.isDirectory()) await walk(path); else if (/\.(ts|tsx|mjs|json|html|css)$/.test(item.name)) files.push(path);
  } }
  await walk(resolve(root, 'frontend')); files.push(resolve(root, 'tools/verify-components-browser.mjs'));
  return Object.fromEntries(await Promise.all(files.sort().map(async path => [path.slice(root.length + 1).replaceAll('\\','/'), createHash('sha256').update(await readFile(path)).digest('hex')])));
}
report.inputs_before = await hashes();
function run(command, args, cwd = root) {
  const child = spawn(command, args, { cwd, windowsHide: true, env: Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('WALLE_'))) }), record = { command, args, stdout: '', stderr: '', code: null };
  child.stdout.on('data', chunk => { record.stdout += chunk; }); child.stderr.on('data', chunk => { record.stderr += chunk; });
  const exited = new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', code => { record.code = code; resolve(code); }); });
  return { child, record, exited };
}
async function cli(...args) { const process = run(bash, [wrapper, '-s=' + session, ...args]); await process.exited; report.commands.push(process.record);
  if (process.record.code !== 0 || process.record.stdout.includes('### Error')) throw new Error(process.record.stdout + process.record.stderr); return process.record.stdout; }
async function code(source) { const output = await cli('run-code', source.replace(/\r?\n/g, ' ')), match = /### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output); assert(match); return JSON.parse(match[1]); }
let vite, opened = false;
try {
  const npx = run(process.execPath, [resolve(process.execPath, '../node_modules/npm/bin/npx-cli.js'), '--version']); await npx.exited; report.npx = npx.record; assert.equal(npx.record.code, 0);
  const source = run(process.execPath, ['tools/spec-audit.mjs','check']); await source.exited; report.source = source.record; assert.equal(source.record.code, 0);
  vite = run(process.execPath, ['node_modules/vite/bin/vite.js', '--config','tests/browser/vite.config.ts','--host','127.0.0.1','--port','5177','--strictPort'], resolve(root,'frontend'));
  let ready = false;
  for (let index = 0; index < 100; index++) { try { if ((await fetch('http://127.0.0.1:5177/tests/browser/components.html')).ok) { ready = true; break; } } catch {} if (vite.child.exitCode !== null) throw new Error(vite.record.stderr); await new Promise(resolve => setTimeout(resolve,100)); }
  assert(ready); await cli('open','http://127.0.0.1:5177/tests/browser/components.html'); opened = true; await cli('snapshot');
  report.confirmation = await code(`async (page) => {
    await page.waitForFunction(() => !!window.componentsProbe);
    const open = page.getByRole('button', {name:'打开确认'}), cancel = page.getByRole('button', {name:'取消',exact:true});
    await open.click(); if (!await cancel.evaluate(element => element === document.activeElement)) throw new Error('Initial cancel focus');
    await page.mouse.click(5,5); if (!await page.locator('dialog').isVisible()) throw new Error('Mask closed dialog');
    for (let index=0;index<12;index++) { await page.keyboard.press('Tab'); if (!await page.evaluate(() => document.querySelector('dialog')?.contains(document.activeElement))) throw new Error('Focus escaped modal'); }
    for (let index=0;index<12;index++) { await page.keyboard.press('Shift+Tab'); if (!await page.evaluate(() => document.querySelector('dialog')?.contains(document.activeElement))) throw new Error('Reverse focus escaped modal'); }
    await cancel.focus(); await page.keyboard.press('Enter'); if (await page.locator('dialog').count()) throw new Error('Cancel Enter did not close');
    if (!await open.evaluate(element => element === document.activeElement)) throw new Error('Original focus not restored');
    await open.click(); await page.getByRole('button',{name:'执行诊断'}).dblclick(); await page.keyboard.press('Escape');
    if (!await page.locator('dialog').isVisible() || !await cancel.isDisabled()) throw new Error('Busy closed');
    await page.evaluate(() => window.componentsProbe.complete('诊断拒绝')); await page.getByRole('alert').filter({hasText:'诊断拒绝'}).waitFor();
    if (await cancel.isDisabled()) throw new Error('Failure did not restore controls');
    await page.screenshot({path:'output/playwright/${session}-confirmation.png'});
    await page.getByRole('button',{name:'执行诊断',exact:true}).click();
    if(!await cancel.isDisabled())throw Error('Retry did not enter actual busy state');
    await page.getByRole('button',{name:'执行诊断',exact:true}).click({force:true});
    if((await page.evaluate(()=>window.componentsProbe.state())).events.filter(event=>event.kind==='confirm').length!==2)throw Error('Retry emitted duplicate intent');
    await page.evaluate(()=>window.componentsProbe.complete('诊断再次拒绝'));
    await page.getByRole('alert').filter({hasText:'诊断再次拒绝'}).waitFor();
    if(!await cancel.isEnabled())throw Error('Second failure did not restore cancellation');
    await cancel.click(); const state = await page.evaluate(() => window.componentsProbe.state());
    if (state.events.filter(event=>event.kind==='confirm').length!==2 || state.toasts.length) throw new Error('Duplicate action/error toast');
    for(const method of ['ESC','CLOSE']){
      await open.click();if(method==='ESC')await page.keyboard.press('Escape');else await page.getByRole('button',{name:'关闭确认弹窗',exact:true}).click();
      if(await page.locator('dialog').count()||!await open.evaluate(el=>el===document.activeElement))throw Error('Unsubmitted close/focus failed');
    }
    return {passed:true,events:state.events,known_failure_retry:true,escape_and_close_restored_focus:true,scope:'Native shared Confirmation with explicitly controlled parent events; no business HTTP retry claim'};
  }`); assert.equal(report.confirmation.passed,true);
  report.filters = await code(`async (page) => {
    await page.getByRole('button',{name:'数字类型：全部'}).click(); await page.getByLabel('一',{exact:true}).uncheck();
    if (!await page.getByLabel('零',{exact:true}).isDisabled()) throw new Error('Last item not protected');
    let state = await page.evaluate(()=>window.componentsProbe.state()); if (state.values.length!==1 || state.values[0]!==0 || typeof state.values[0]!=='number') throw new Error('Numeric zero lost');
    await page.getByRole('button',{name:'一键全选'}).click(); if (!await page.getByRole('button',{name:'一键全选'}).isDisabled()) throw new Error('Repeated all allowed');
    await page.evaluate(()=>window.componentsProbe.restoreFilters([0])); await page.waitForFunction(()=>window.componentsProbe.state().values.length===1);
    await page.mouse.click(5,5); if (await page.locator('.filter-menu').count()) throw new Error('Outside did not close');
    await page.getByRole('button',{name:'清除',exact:true}).click(); const input=page.getByRole('textbox',{name:'诊断搜索'});
    await input.fill('  新关键词  '); await input.press('Enter'); await input.fill('');
    state=await page.evaluate(()=>window.componentsProbe.state()); if(state.submitted!=='新关键词'||state.events.filter(event=>event.kind==='search').length!==2) throw new Error('Draft empty submitted');
    await input.fill('组合搜索'); await input.evaluate(element=>element.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true})));
    await input.press('Enter'); await input.evaluate(element=>element.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'组合搜索'})));
    state=await page.evaluate(()=>window.componentsProbe.state()); if(state.events.filter(event=>event.kind==='search').length!==2) throw new Error('Composition submitted');
    await input.press('Enter'); state=await page.evaluate(()=>window.componentsProbe.state());
    if(state.events.filter(event=>event.kind==='filter').length!==2 || state.events.filter(event=>event.kind==='search').length!==3) throw new Error('Controlled input duplicate');
    return {passed:true,events:state.events};
  }`); assert.equal(report.filters.passed,true);
  report.pagination = await code(`async(page)=>{
    await page.getByRole('button',{name:'第 7 页',exact:true}).click();
    await page.evaluate(()=>window.componentsProbe.restorePagination({page:99,page_size:20,total:21,total_pages:2}));
    await page.getByRole('button',{name:'返回有效页'}).click();
    await page.evaluate(()=>window.componentsProbe.restorePagination({page:1,page_size:20,total:0,total_pages:0}));
    await page.waitForFunction(()=>window.componentsProbe.state().pagination.total===0);
    if(!await page.getByRole('button',{name:'上一页'}).isDisabled()||!await page.getByRole('button',{name:'下一页'}).isDisabled())throw new Error('Empty invalid direction');
    const events=(await page.evaluate(()=>window.componentsProbe.state())).events.filter(event=>event.kind==='page');
    if(JSON.stringify(events.map(event=>event.value))!=='[7,2]')throw new Error('Invalid or duplicate pagination');return {passed:true,events};
  }`); assert.equal(report.pagination.passed,true);
  report.toast = await code(`async(page)=>{
    await page.evaluate(()=>window.componentsProbe.toast('info','暂停诊断')); const toast=page.locator('.toast').filter({hasText:'暂停诊断'}); await toast.hover();
    await page.evaluate(()=>window.componentsProbe.advance(4000)); if(!await toast.isVisible())throw new Error('Hover expired');
    await toast.getByRole('button',{name:'关闭提示'}).focus(); await page.mouse.move(5,5); await page.evaluate(()=>window.componentsProbe.advance(4000));
    if(!await toast.isVisible())throw new Error('Focus expired'); await page.getByRole('button',{name:'打开确认'}).focus();
    await page.evaluate(()=>window.componentsProbe.advance(2999));if(!await toast.isVisible())throw new Error('Remaining time lost');
    await page.evaluate(()=>window.componentsProbe.advance(1)); if(await toast.count())throw new Error('Remaining expiry failed');
    await page.evaluate(()=>{window.componentsProbe.toast('success','同一诊断');window.componentsProbe.toast('success','同一诊断');});
    if(await page.locator('.toast').count()!==1)throw new Error('Duplicate toast');
    await page.getByRole('button',{name:'打开确认'}).click();
    if(!await page.locator('dialog .toast').isVisible())throw new Error('Toast below native modal layer');await page.getByRole('button',{name:'取消',exact:true}).click();
    await page.evaluate(()=>{for(const text of ['二','三','四'])window.componentsProbe.toast('info',text);});
    const state=await page.evaluate(()=>window.componentsProbe.state());if(JSON.stringify(state.toasts.map(toast=>toast.message))!=='["四","三","二"]')throw new Error('Queue order/limit');
    const trigger=page.getByRole('button',{name:'打开确认'});await trigger.click();await trigger.evaluate(element=>element.remove());await page.getByRole('button',{name:'取消',exact:true}).click();
    if (!await page.getByRole('button',{name:'返回入口'}).evaluate(element=>element===document.activeElement)) throw new Error('Removed trigger fallback missing');
    return {passed:true,scope:'Real pointer/focus and explicit controlled Toast clock, no wall-clock duration claim',toasts:state.toasts,removed_trigger_focus_fallback:true};
  }`); assert.equal(report.toast.passed,true);
  await cli('screenshot',`--filename=output/playwright/${session}-native.png`);
  await code('async(page)=>{await page.evaluate(()=>window.componentsProbe.destroy());return true;}'); report.passed=true;
} catch(error) {report.passed=false;report.error=String(error);process.exitCode=1;}
finally {
  if(opened)try{await cli('close');}catch(error){report.close_error=String(error);report.passed=false;process.exitCode=1;}
  if(vite){if(vite.child.exitCode===null){if(process.platform==='win32'){const kill=run('taskkill',['/PID',String(vite.child.pid),'/T','/F']);await kill.exited;}else vite.child.kill();await vite.exited;}report.vite=vite.record;}
  report.inputs_after=await hashes();report.changed_inputs=[...new Set([...Object.keys(report.inputs_before),...Object.keys(report.inputs_after)])].filter(key=>report.inputs_before[key]!==report.inputs_after[key]);
  if(report.changed_inputs.length){report.passed=false;report.error??='Inputs changed';process.exitCode=1;}
  const path=resolve(root,'docs/verification', 'components-browser-'+report.timestamp.replace(/[:.]/g,'-')+'.json');await writeFile(path,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:report.passed,evidence:path,error:report.error}));
}
