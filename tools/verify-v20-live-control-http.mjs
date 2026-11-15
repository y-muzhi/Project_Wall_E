/** CLI-first Chrome against the isolated actual HTTP application and SQLite. */
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir, writeFile} from 'node:fs/promises';
import {basename, join, resolve, relative, isAbsolute} from 'node:path';
import {randomUUID} from 'node:crypto';

const [workArg, entryArg, origin, task, profile, version, grant, nonce, checkVersion, outputLimit, invalidVersion, invalidGrant] = process.argv.slice(2);
const work = resolve(workArg), entry = resolve(entryArg);
const owned = resolve(process.env.WALLE_CHECK_TEMP || '');
const unknownStage = Number(process.env.WALLE_FIXTURE_UNKNOWN_STAGE || '3');
if (![3, 4].includes(unknownStage)) throw Error('Original configuration fixture stage required');
const inside = relative(owned, work);
if (!process.env.WALLE_CHECK_TEMP || inside.startsWith('..') || isAbsolute(inside) ||
    basename(entry) !== 'playwright-cli.js' || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/.test(origin) ||
    ![task, profile, version, grant, checkVersion, outputLimit].every(value => /^[1-9][0-9]*$/.test(value)) ||
    !/^[0-9a-f]{32}$/.test(nonce) ||
    (invalidVersion !== undefined && !['models', 'delivery', 'native-read'].includes(invalidVersion) && ![invalidVersion, invalidGrant].every(value => /^[1-9][0-9]*$/.test(value)))) throw Error('Exact owned HTTP browser fixture required');
await mkdir(join(work, 'temp'), {recursive: true});
const config = join(work, 'cli.config.json');
await writeFile(config, JSON.stringify({
  browser: {browserName: 'chromium', isolated: true,
    launchOptions: {executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
      headless: true, args: ['--disable-background-networking', '--disable-component-update', '--disable-sync']},
    contextOptions: {serviceWorkers: 'block', viewport: {width: 360, height: 800}}},
  outputDir: join(work, 'artifacts'), outputMode: 'stdout',
}), {flag: 'wx'});
const exec = promisify(execFile), session = 'w20-http-' + randomUUID().slice(0, 8);
const env = {...process.env, PWTEST_DAEMON_SESSION_DIR: join(work, 'daemon'),
  TEMP: join(work, 'temp'), TMP: join(work, 'temp')};
async function cli(...commands) {
  let result;
  try {
    result = await exec(process.execPath, [entry, '-s=' + session, ...commands],
      {cwd: work, env, windowsHide: true, timeout: invalidVersion === 'native-read' ? 180000 : 60000, maxBuffer: 4 * 1024 * 1024, encoding: 'utf8'});
  } catch (error) {
    throw Error(error.stdout || error.stderr || error.message);
  }
  if (result.stdout.includes('### Error')) throw Error(result.stdout);
  return result.stdout;
}
try {
  await cli('open', origin + '/code-tasks/' + task, '--config', config, invalidVersion === 'native-read' ? '--idle-timeout=240000' : '--idle-timeout=30000');
  await cli('snapshot');
  const result = await cli('run-code', `async(page) => {
    page.setDefaultTimeout(12000);
    const base = ${JSON.stringify(origin)}, path = base + '/api/v1/code-tasks/' + ${JSON.stringify(task)};
    await page.reload();
    const originalResponse = await page.request.get(path);
    if (!originalResponse.ok()) throw Error(await originalResponse.text());
    const original = (await originalResponse.json()).data;
    let writes = 0, receipt = null, budgetWrites = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && request.url() === path + '/budget') budgetWrites++;
    });
    await page.route(path + '/configuration', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      writes++;
      const response = await route.fetch({maxRetries: 0});
      if (response.status() !== 202) throw Error(await response.text());
      receipt = (await response.json()).data;
      await route.abort('connectionreset');
    });
    const open = page.getByRole('button', {name: '更换任务配置', exact: true});
    try { await open.waitFor(); }
    catch (error) { throw Error(error.message + '\\nBODY: ' + await page.locator('body').innerText()); }
    await open.click();
    const form = page.getByRole('form', {name: '选择任务配置'});
    await form.getByLabel('新执行配置').selectOption(${JSON.stringify(profile)});
    if (${JSON.stringify(invalidVersion ?? null)} !== null && !['models', 'delivery', 'native-read'].includes(${JSON.stringify(invalidVersion ?? null)})) {
      await form.getByLabel('新配置版本').selectOption(${JSON.stringify(invalidVersion ?? '')});
      await form.getByLabel('新适用授权').selectOption(${JSON.stringify(invalidGrant ?? '')});
      await form.getByLabel('变更说明').fill('固定内容配置边界核对');
      await form.getByText('此版本更改了固定内容规则或容量，须使用新任务', {exact: true}).waitFor();
      if (!await form.getByRole('button', {name: '应用配置', exact: true}).isDisabled() || writes !== 0)
        throw Error('Fixed content configuration was submitted');
    }
    await form.getByLabel('新配置版本').selectOption(${JSON.stringify(version)});
    await form.getByLabel('新适用授权').selectOption(${JSON.stringify(grant)});
    const checkFacts = form.getByLabel('检查标准变更');
    await checkFacts.waitFor();
    if (!(await checkFacts.innerText()).includes('目标检查标准版本 #' + ${JSON.stringify(checkVersion)}))
      throw Error('Target check-set version was not displayed');
    const outputFacts = form.getByLabel('目标检查输出上限');
    await outputFacts.waitFor();
    if (!(await outputFacts.innerText()).replace(/\\s+/g, '').includes(
        '目标检查输出上限：' + ${JSON.stringify(outputLimit)} + '字节'))
      throw Error('Effective target output limit was not displayed');
    if (${invalidVersion === 'native-read'}) {
      const facts = form.getByLabel('待应用授权范围');
      const roots = await facts.locator('dt').filter({hasText: '目录读取'})
        .evaluate(element => element.nextElementSibling?.textContent);
      if (roots !== '任务工作区') throw Error('Managed read-root target was not shown in business terms');
    }
    if (${invalidVersion === 'models'})
      await form.getByLabel('模型调用授权提示').filter({hasText: '此授权不允许后续模型调用'}).waitFor();
    if (${invalidVersion === 'delivery'}) {
      const delivery = form.getByLabel('待应用授权范围');
      const approved = await delivery.locator('dt').filter({hasText: '本地交付'})
        .evaluate(element => element.nextElementSibling?.textContent);
      if (approved !== '未批准')
        throw Error('Revoked local delivery permission was not displayed');
    }
    await form.getByLabel('变更说明').fill('实际 HTTP 原会话控制配置');
    await form.getByRole('button', {name: '取消', exact: true}).click();
    await page.getByRole('button', {name: '更换任务配置', exact: true}).click();
    if (await form.getByLabel('变更说明').inputValue() !== '实际 HTTP 原会话控制配置')
      throw Error('Cancelled configuration draft was lost');
    await form.getByRole('button', {name: '应用配置', exact: true}).click();
    await page.getByRole('button', {name: '核对原配置请求', exact: true}).waitFor();
    await page.reload();
    await page.getByRole('button', {name: '核对原配置请求', exact: true}).click();
    await page.getByText(new RegExp('配置版本 #' + ${JSON.stringify(version)} + '.*待核对生效')).waitFor();
    const before = (await (await page.request.get(path)).json()).data;
    if (before.execution_profile_version_id !== original.execution_profile_version_id ||
        before.authorization_id !== original.authorization_id || before.status !== 'WAITING')
      throw Error('Pending HTTP configuration adopted unverified controls');
    await page.getByRole('button', {name: '增加预算', exact: true}).click();
    const budget = page.getByRole('form', {name: '追加任务预算'});
    await budget.getByLabel('新预算总额（元）').fill('0.200000');
    await budget.getByLabel('调整说明').fill('配置核对时提高预算总额');
    await budget.getByRole('button', {name: '保存新预算', exact: true}).click();
    await page.getByText('预算总额已更新。', {exact: true}).waitFor();
    const budgetView = (await (await page.request.get(path)).json()).data;
    if (budgetView.status !== 'WAITING' || budgetView.budget.limit_cny !== '0.200000' ||
        budgetView.configuration_application.status !== 'PENDING' ||
        budgetView.active_operations[0]?.id !== receipt.operation_id)
      throw Error('Budget adoption lost the original configuration wait');

    async function observe(outcome) {
      const response = await page.request.post(base + '/__v20_fixture/live-control/' + outcome,
        {headers: {'X-Fixture-Nonce': ${JSON.stringify(nonce)}}});
      if (!response.ok() || !(await response.json()).advanced) throw Error('Original fixture did not advance');
      await page.reload();
    }
    await observe('unknown');
    await page.getByText(new RegExp('配置版本 #' + ${JSON.stringify(version)} + '.*配置结果待核对')).waitFor();
    const unknown = (await (await page.request.get(path)).json()).data;
    if (unknown.execution_profile_version_id !== original.execution_profile_version_id ||
        unknown.configuration_application.status !== 'UNKNOWN') throw Error('Unknown controls became effective');
    const originalOperation = (await (await page.request.get(path + '/operations/' + receipt.operation_id)).json()).data;
    const unknownStates = ${unknownStage} === 3
      ? ['SUCCEEDED', 'SUCCEEDED', 'UNKNOWN', 'PENDING']
      : ['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED', 'UNKNOWN'];
    if (JSON.stringify(originalOperation.steps.map(step => step.status)) !==
          JSON.stringify(unknownStates) ||
        originalOperation.steps.some(step => step.external_identity !== null))
      throw Error('Third-step uncertainty lost its original stage or leaked a private identity');
    const progressResponse = page.waitForResponse(response =>
      response.url() === path + '/operations/' + receipt.operation_id &&
      response.request().method() === 'GET' && response.status() === 200);
    const readPending = page.getByRole('button', {name: '读取原应用进度', exact: true});
    await readPending.click();
    await progressResponse;
    await page.waitForFunction(() => {
      const panel = document.querySelector('section[aria-label="任务配置与授权"]');
      const button = [...(panel?.querySelectorAll('button') ?? [])].find(
        entry => entry.textContent?.trim() === '读取原应用进度');
      return button && !button.disabled && !panel.querySelector('[role="alert"]');
    });
    if (writes !== 1) throw Error('Reading third-step uncertainty replayed the original command');
    await observe('success');
    await page.getByText(new RegExp('配置版本 #' + ${JSON.stringify(version)} + '.*已核实生效')).waitFor();
    const current = (await (await page.request.get(path)).json()).data;
    if (current.status !== 'VERIFYING' || current.execution_profile_version_id !== Number(${JSON.stringify(version)}) ||
        current.authorization_id !== Number(${JSON.stringify(grant)}) ||
        current.current_candidate_id !== original.current_candidate_id ||
        current.control_generation !== original.control_generation ||
        current.active_session_id !== original.active_session_id) throw Error('HTTP adoption changed original scope');
    const readOriginal = page.getByRole('button', {name: '读取原应用进度', exact: true});
    if (await readOriginal.count()) await readOriginal.click();
    await page.getByRole('button', {name: '核对原配置请求', exact: true}).waitFor({state: 'detached'});
    await observe('unavailable');
    const disabled = page.getByRole('button', {name: '更换任务配置', exact: true});
    await page.getByText('运行配置核对服务尚未就绪', {exact: true}).waitFor();
    if (!await disabled.isDisabled() ||
        await disabled.getAttribute('title') !== '运行配置核对服务尚未就绪')
      throw Error('Unavailable worker was explained as active writing');
    await observe('ready');
    await page.getByRole('button', {name: '更换任务配置', exact: true}).waitFor();
    for (const width of [360, 1280]) {
      await page.setViewportSize({width, height: 800});
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1))
        throw Error('Actual HTTP configuration page overflows');
    }
    if (writes !== 1 || budgetWrites !== 1 || !receipt || receipt.task_status !== 'WAITING') throw Error('Original browser command was replayed');
    return {passed: true, writes, budgetWrites, originalOperation: receipt.operation_id, widths: [360, 1280]};
  }`);
  if (!/"passed"\s*:\s*true/.test(result)) throw Error(result);
  console.log('V20_LIVE_CONTROL_HTTP_BROWSER_PASSED');
} finally {
  await cli('close');
}
