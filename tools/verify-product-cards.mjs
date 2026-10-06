import assert from 'node:assert/strict';

/** Actual production root and unchanged I14/I15/I36 transactions. Only the
 * named card-generation precondition uses the isolated CardsFixtureWorker.
 * Browser injection observes actual writes and loses a committed receipt;
 * it neither prepares commands nor replaces business owners or responses. */
export async function verifyProductCards(run,cli,api){
 const report={};
 await cli('snapshot');
 report.created=await run(`async(page)=>{
  await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'需求工作台',exact:true}).click();
  await page.locator('.workbench-controls').getByRole('button',{name:'新建需求',exact:true}).click();
  const drawer=page.locator('.create-drawer');await drawer.getByLabel('需求标题').fill('真实根卡片😀');await drawer.getByLabel('需求类型').selectOption('NEW');await drawer.getByLabel('初始想法').fill('初始化卡片前置夹具');await drawer.getByLabel('初始化模式').selectOption('DESIGN');await drawer.getByRole('button',{name:'创建需求',exact:true}).click();
  await page.waitForURL('**/requirements/1');await page.getByRole('button',{name:'完成初始化',exact:true}).waitFor();const toggle=page.getByRole('button',{name:'辅助面板',exact:true});if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true});await pane.locator('[data-card-key="optional"]').waitFor();
  if(await pane.locator('input:checked').count())throw Error('Recommendations became selections');if(await pane.locator('fieldset').count()!==4)throw Error('Root lost cards');
  const identity=await pane.evaluate(element=>Number(element.closest('[data-message-id]').dataset.messageId));if(!identity)throw Error('Actual message identity required');
  return {passed:true,identity,url:page.url()};
 }`);
 const id=report.created.identity,localKey=`walle:v1:cards:1:${id}`;
 report.current=(await api('/requirements/1/current-document')).data;
 report.original=(await api('/requirements/1/messages')).data.items.find(row=>row.id===id);
 assert.equal(report.original.card_state,'AVAILABLE');assert.equal(report.original.message_type,'INTERACTION_CARDS');
 await cli('snapshot');
 report.draft=await run(`async(page)=>{
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true});
  await pane.locator('[data-card-key="single"]').getByRole('textbox',{name:'自定义回答'}).fill(' 根页面本地😀\\n回答 ');
  await pane.locator('[data-card-key="multi"]').getByRole('checkbox',{name:/方案b/}).check();await pane.locator('[data-card-key="multi"]').getByRole('textbox',{name:'自定义回答'}).fill('多选补充');await pane.locator('[data-card-key="confirm"]').getByRole('radio',{name:/方案b/}).check();
  let sends=0;const observe=request=>{if(request.method()==='POST'&&/conversation-messages\\/\\d+\\/responses$/.test(new URL(request.url()).pathname))sends++;};page.on('request',observe);
  await pane.getByRole('button',{name:'提交整组答案',exact:true}).click();await pane.locator('[data-card-key="optional"]').getByRole('alert').waitFor();page.off('request',observe);
  if(sends||!await pane.locator('[data-card-key="optional"] input').first().evaluate(element=>element===document.activeElement))throw Error('Incomplete group sent or first error not focused');
  await pane.locator('[data-card-key="optional"]').getByRole('checkbox',{name:'明确跳过此问题'}).check();
  const local=await page.evaluate(key=>sessionStorage.getItem(key),${JSON.stringify(localKey)});if(!local)throw Error('Draft not persisted');return {passed:true,sends,local};
 }`);
 await cli('snapshot');
 report.restored=await run(`async(page)=>{
  await page.addInitScript(()=>{
   const send=window.fetch.bind(window);window.productCardFault={dropCard:true,dropText:false,failReads:0,wires:[]};
   window.fetch=async(input,options)=>{
    const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;
    if(window.productCardFault.failReads&&(!options?.method||options.method==='GET')&&path==='/api/v1/requirements/1'){window.productCardFault.failReads--;throw new TypeError('Explicit root card recovery read failure');}
    const card=options?.method==='POST'&&/conversation-messages\\/\\d+\\/responses$/.test(path),text=options?.method==='POST'&&/guide-runs(?:\\/\\d+\\/continue)?$/.test(path);
    const response=await send(input,options);if(card||text){window.productCardFault.wires.push({path,method:options.method,key:new Headers(options.headers).get('Idempotency-Key'),body:options.body,status:response.status});
     if(response.ok&&(card&&window.productCardFault.dropCard||text&&window.productCardFault.dropText)){if(card)window.productCardFault.dropCard=false;else window.productCardFault.dropText=false;throw new TypeError('Explicit root test actual committed receipt loss');}}
    return response;
   };
  });
  await page.reload();const pane=page.getByRole('region',{name:'决策卡片组',exact:true});await pane.locator('[data-card-key="single"] textarea').waitFor();
  const local=await page.evaluate(key=>sessionStorage.getItem(key),${JSON.stringify(localKey)}),encoded=await page.evaluate(key=>btoa(String.fromCharCode(...new TextEncoder().encode(sessionStorage.getItem(key)??''))),${JSON.stringify(localKey)});if(encoded!=='${Buffer.from(report.draft.local).toString('base64')}')throw Error('Reload changed local bytes');if(await pane.locator('[data-card-key="single"] textarea').inputValue()!==[' 根页面本地😀','回答 '].join(String.fromCharCode(10)))throw Error('Raw draft lost');
  await page.getByLabel('给 AI 的消息',{exact:true}).fill('卡片提交不得清空普通消息草稿');return {passed:true,local};
 }`);
 await cli('snapshot');
 report.unknown=await run(`async(page)=>{
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true});await pane.getByRole('button',{name:'提交整组答案',exact:true}).click();await pane.getByRole('button',{name:'重新确认整组提交结果',exact:true}).waitFor();
  if(await page.evaluate(()=>window.productCardFault.wires.length)!==1)throw Error('Original answer sent more than once');if(!await page.getByLabel('给 AI 的消息',{exact:true}).isDisabled())throw Error('Competing composer remains enabled');
  await page.getByRole('tab',{name:'评论',exact:true}).click();await page.getByRole('tab',{name:'AI 对话',exact:true}).click();await pane.getByRole('button',{name:'重新确认整组提交结果',exact:true}).waitFor();
  if(await page.evaluate(()=>window.productCardFault.wires.length)!==1||await page.getByLabel('给 AI 的消息',{exact:true}).inputValue()!=='卡片提交不得清空普通消息草稿')throw Error('Tab change replayed or discarded input');
  await page.evaluate(()=>window.productCardFault.failReads=1);await pane.getByRole('button',{name:'重新确认整组提交结果',exact:true}).click();await pane.getByRole('alert').filter({hasText:'未重发'}).waitFor();if(await page.evaluate(()=>window.productCardFault.wires.length)!==1)throw Error('Failed GET resent');
  await page.screenshot({path:'output/playwright/product-cards-unknown.png'});return {passed:true};
 }`);
 report.committed=(await api('/requirements/1/messages')).data.items;
 const formal=report.committed.filter(row=>row.reply_to_message_id===id);assert.equal(formal.length,1);assert.notEqual(formal[0].guide_run_id,report.original.guide_run_id);
 assert.deepEqual((await api('/requirements/1/current-document')).data,report.current);
 await cli('snapshot');
 report.initialization=await run(`async(page)=>{
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true});await pane.getByRole('button',{name:'重新确认整组提交结果',exact:true}).click();await pane.getByText('已回答 · 正式答案已保存',{exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.guide-composer textarea')?.disabled);
  if(await pane.locator('input:enabled,textarea:enabled').count())throw Error('Formal answers editable');if(await page.evaluate(key=>sessionStorage.getItem(key),${JSON.stringify(localKey)})!==null)throw Error('Answered local draft retained');if(await page.getByLabel('给 AI 的消息',{exact:true}).inputValue()!=='卡片提交不得清空普通消息草稿')throw Error('Card receiver cleared independent composer');
  await page.screenshot({path:'output/playwright/product-cards-answered.png'});return {passed:true};
 }`);
 // A fresh AVAILABLE initialization group replaced by a real ordinary I14.
 await cli('snapshot');
 report.initial_text=await run(`async(page)=>{
  const input=page.getByLabel('给 AI 的消息',{exact:true});await input.fill('初始化卡片前置夹具');await page.getByRole('button',{name:'发送消息',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.interaction-cards').length===2);const pane=page.getByRole('region',{name:'决策卡片组',exact:true}).last();await pane.locator('[data-card-key="single"] textarea').waitFor();await pane.locator('[data-card-key="single"] textarea').fill('初始化尚未提交答案');const identity=await pane.evaluate(element=>Number(element.closest('[data-message-id]').dataset.messageId));
  await input.fill('普通文字替代初始化卡片😀');await page.getByRole('button',{name:'发送消息',exact:true}).click();await pane.getByText('已失效 · 保留原问题供阅读',{exact:true}).waitFor();if(await pane.locator('input:enabled,textarea:enabled').count())throw Error('Expired initialization editable');if(await page.evaluate(key=>sessionStorage.getItem(key),'walle:v1:cards:1:'+identity)!==null)throw Error('Expired initialization local retained');
  let readRetries=0;for(;readRetries<3;readRetries++){await page.waitForFunction(()=>!document.querySelector('.guide-composer textarea')?.disabled||[...document.querySelectorAll('.guide-composer button')].some(button=>button.textContent==='重读已接受消息与运行'&&!button.disabled));if(!await input.isDisabled())break;await page.getByRole('button',{name:'重读已接受消息与运行',exact:true}).click();}await page.waitForFunction(()=>!document.querySelector('.guide-composer textarea')?.disabled);
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='完成初始化'&&!button.disabled));await page.getByRole('button',{name:'完成初始化',exact:true}).click();await page.getByRole('button',{name:'确认完成初始化',exact:true}).click();await page.getByRole('button',{name:'完成需求',exact:true}).waitFor();return {passed:true,identity,read_retries:readRetries};
 }`);
 assert.deepEqual((await api('/requirements/1/current-document')).data,report.current);
 const sendFixture=async()=>{
  await cli('snapshot');return await run(`async(page)=>{await page.getByLabel('AI 操作',{exact:true}).selectOption('ASK');await page.getByLabel('给 AI 的消息',{exact:true}).fill('等待卡片前置夹具');await page.getByRole('button',{name:'发送消息',exact:true}).click();await page.getByRole('button',{name:'发送补充说明',exact:true}).waitFor();const pane=page.getByRole('region',{name:'决策卡片组',exact:true}).last();await pane.locator('[data-card-key="single"] input:enabled').first().waitFor();return {passed:true,identity:await pane.evaluate(element=>Number(element.closest('[data-message-id]').dataset.messageId))};}`);
 };
 report.waiting_fixture=await sendFixture();
 const waitingMessage=(await api('/requirements/1/messages')).data.items.find(row=>row.id===report.waiting_fixture.identity);
 await cli('snapshot');
 report.waiting_answer=await run(`async(page)=>{
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true}).last();for(const key of ['single','confirm'])await pane.locator('[data-card-key="'+key+'"]').getByRole('radio',{name:/方案b/}).check();await pane.locator('[data-card-key="multi"]').getByRole('checkbox',{name:/方案a/}).check();await pane.locator('[data-card-key="optional"]').getByRole('checkbox',{name:'明确跳过此问题'}).check();await pane.getByRole('button',{name:'提交整组答案',exact:true}).click();await pane.getByText('已回答 · 正式答案已保存',{exact:true}).waitFor();
  let readRetries=0;for(;readRetries<3;readRetries++){await page.waitForFunction(()=>!document.querySelector('.guide-composer textarea')?.disabled||[...document.querySelectorAll('.interaction-cards button')].some(button=>button.textContent==='重读已保存答案与运行'&&!button.disabled));if(!await page.getByLabel('给 AI 的消息',{exact:true}).isDisabled())break;await pane.getByRole('button',{name:'重读已保存答案与运行',exact:true}).click();}
  await page.waitForFunction(()=>!document.querySelector('.guide-composer textarea')?.disabled);await page.getByRole('button',{name:'发送消息',exact:true}).waitFor();return {passed:true,read_retries:readRetries};
 }`);
 report.waiting_formal=(await api('/requirements/1/messages')).data.items.filter(row=>row.reply_to_message_id===waitingMessage.id);assert.equal(report.waiting_formal.length,1);assert.equal(report.waiting_formal[0].guide_run_id,waitingMessage.guide_run_id);
 report.text_fixture=await sendFixture();const textMessage=(await api('/requirements/1/messages')).data.items.find(row=>row.id===report.text_fixture.identity);
 await cli('snapshot');
 report.waiting_text=await run(`async(page)=>{
  const pane=page.getByRole('region',{name:'决策卡片组',exact:true}).last(),input=page.getByLabel('给 AI 的消息',{exact:true});await pane.locator('[data-card-key="single"] textarea').fill('等待时本地未提交😀');await input.fill('普通文字回复等待运行😀');await page.evaluate(()=>window.productCardFault.dropText=true);await page.getByRole('button',{name:'发送补充说明',exact:true}).click();await page.getByRole('button',{name:'重新确认消息发送结果',exact:true}).waitFor();const sends=await page.evaluate(()=>window.productCardFault.wires.length);
  await page.getByRole('tab',{name:'评论',exact:true}).click();await page.getByRole('tab',{name:'AI 对话',exact:true}).click();await page.getByRole('button',{name:'重新确认消息发送结果',exact:true}).waitFor();if(await input.inputValue()!=='普通文字回复等待运行😀'||await page.evaluate(()=>window.productCardFault.wires.length)!==sends)throw Error('Unknown ordinary input lost or replayed');
  await page.getByRole('button',{name:'重新确认消息发送结果',exact:true}).click();await pane.getByText('已失效 · 保留原问题供阅读',{exact:true}).waitFor();await page.getByRole('button',{name:'发送消息',exact:true}).waitFor();await page.waitForFunction(()=>document.querySelector('.guide-composer textarea')?.value==='');if(await page.evaluate(key=>sessionStorage.getItem(key),'walle:v1:cards:1:'+${textMessage.id})!==null)throw Error('Ordinary expiry did not clear local');if(await pane.locator('input:enabled,textarea:enabled').count())throw Error('Expired waiting remains editable');
  await page.screenshot({path:'output/playwright/product-cards-expired.png'});return {passed:true,sends};
 }`);
 report.messages=(await api('/requirements/1/messages')).data.items;report.runs=(await api('/requirements/1/guide-runs')).data.items;
 assert.equal(report.messages.find(row=>row.id===textMessage.id).card_state,'EXPIRED');assert.equal(report.messages.filter(row=>row.reply_to_message_id===textMessage.id).length,0);const ordinary=report.messages.filter(row=>row.content==='普通文字回复等待运行😀');assert.equal(ordinary.length,1);assert.equal(ordinary[0].message_type,'TEXT');assert.equal(ordinary[0].structured_content,null);assert.equal(ordinary[0].guide_run_id,textMessage.guide_run_id);assert.equal(report.runs.length,6);
 assert.deepEqual((await api('/requirements/1/current-document')).data,report.current);
 report.wires=await run(`async(page)=>await page.evaluate(()=>window.productCardFault.wires)`);const groups=new Map();for(const wire of report.wires){assert.equal(wire.status,202);assert(wire.key);const group=groups.get(wire.key)??[];group.push(wire);groups.set(wire.key,group);}const replayed=[...groups.values()].filter(group=>group.length>1);assert.equal(replayed.length,2);for(const pair of replayed){assert.equal(pair.length,2);assert.deepEqual(pair[0],pair[1]);}assert.equal(report.wires.length,9);assert.equal(groups.size,7);
 const response=JSON.parse(report.wires[0].body);assert.equal(response.responses.length,4);assert.equal(response.responses[0].custom_answer,'根页面本地😀\n回答');assert.deepEqual(response.responses[3],{card_key:'optional',selected_option_keys:[],custom_answer:null,skipped:true});
 for(const value of [report.created,report.draft,report.restored,report.unknown,report.initialization,report.initial_text,report.waiting_fixture,report.waiting_answer,report.text_fixture,report.waiting_text])assert.equal(value.passed,true);
 return {passed:true,...report};
}
