"""Production Closure evidence paging over 1001 real associations, then actual manual edit."""

import hashlib
import json
import urllib.request


def seed(workspace, document, link):
    from backend.app.formation.commands import complete_step
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.tests.formation.test_v21_completion_commands import request
    from backend.tests.formation.test_v21_real_growth_continuation import route

    for _batch in range(50):
        route(workspace, document, [{'type': 'LINK_CONTENT', **link} for _ in range(20)])
        if _batch % 10 == 9:
            print('HISTORY_LINKS', 1 + 20 * (_batch + 1), flush=True)
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document)
    body = request(workspace)
    body.update(document_id=document, expected_discussion_version=root['discussion_version'])
    print('HISTORY_COMPLETION_START', flush=True)
    result = complete_step(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    print('HISTORY_COMPLETION_READY', flush=True)


def fingerprint(connection, document):
    event = connection.execute(
        'SELECT event_id FROM formation_closures WHERE document_id=? ORDER BY event_id DESC LIMIT 1',
        (document,),
    ).fetchone()[0]
    digests = {}
    counts = {}
    orders = {
        'formation_closures': 'event_id',
        'formation_closure_items': 'ordinal',
        'formation_closure_evidence': 'owner_kind,item_ref,ordinal',
    }
    for table, order in orders.items():
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(
            'SELECT * FROM ' + table + ' WHERE event_id=? ORDER BY ' + order, (event,)
        ):
            encoded = json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode(
                'utf-8'
            )
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(encoded)
            count += 1
        digests[table] = digest.hexdigest()
        counts[table] = count
    return {'event': event, 'digests': digests, 'counts': counts}


def browser(run):
    first = run("""async(page)=>{
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const summary=page.getByText('查看完整结束记录',{exact:true});
 await summary.click();
 const evidenceSummary=page.getByText('查看结束时的证据',{exact:true});
 const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/evidence'));
 await evidenceSummary.click();
 const data=await (await response).json();
 const box=evidenceSummary.locator('..').locator(':scope > .formation-page');
 await box.locator(':scope > ul > li').first().waitFor();
 const state={total:data.data.total,ordinals:data.data.items.map(row=>row.ordinal),pages:1,maxRows:await box.locator(':scope > ul > li').count(),oldPage:null};
 if(!Number.isInteger(state.total)||state.total<5005)throw Error('Unexpected full evidence count '+JSON.stringify(data));
 await page.evaluate(value=>{window.w21History=value;},state);
 return {total:state.total};
}""")
    while True:
        state = run("""async(page)=>{
 const box=page.getByText('查看结束时的证据',{exact:true}).locator('..').locator(':scope > .formation-page');
 const next=box.getByRole('button',{name:'下一页',exact:true});
 const state=await page.evaluate(()=>window.w21History);
 for(let index=0;index<25&&!(await next.isDisabled());index++){
  const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/evidence'));
  await next.click();
  const responseValue=await response;const data=await responseValue.json();
  if(state.oldPage===null)state.oldPage=responseValue.url();
  if(data.data.total!==state.total||data.data.items.length>20)throw Error('Evidence paging truncated or unbounded');
  state.ordinals.push(...data.data.items.map(row=>row.ordinal));state.pages++;
  await page.waitForFunction(()=>!document.querySelector('details:has(> summary) .formation-page[aria-busy="true"]'));
  state.maxRows=Math.max(state.maxRows,await box.locator(':scope > ul > li').count());
 }
 await page.evaluate(value=>{window.w21History=value;},state);
 return {count:state.ordinals.length,total:state.total,pages:state.pages,done:await next.isDisabled()};
}""")
        print('IMMUTABLE_EVIDENCE_PAGE', state['pages'], state['count'], flush=True)
        if state['done']:
            break
    assert state['count'] == first['total'], state
    result = run("""async(page)=>{
 const evidence=await page.evaluate(()=>window.w21History);
 if(new Set(evidence.ordinals).size!==evidence.total||Math.max(...evidence.ordinals)!==evidence.total||evidence.maxRows>20)throw Error('History members lost or accumulated in DOM');
 if((await page.evaluate(()=>window.formationProduct.requests())).length!==0)throw Error('Viewing history sent command');
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const editor=page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
 await editor.waitFor();await editor.click();await page.keyboard.press('Control+Home');await page.keyboard.insertText('历史完成后继续修改');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 const detail=await page.evaluate(()=>window.formationProduct.state().reads.detail.data);
 if(detail.status!=='COMPLETED')throw Error('Manual edit reopened completed step');
 const closure=page.getByText('查看完整结束记录',{exact:true});
 if(!(await closure.evaluate(node=>node.parentElement.open)))await closure.click();
 const summary=page.getByText('查看结束时的证据',{exact:true});
 const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/evidence'));
 if(await summary.evaluate(node=>node.parentElement.open)){
  await summary.locator('..').locator(':scope > .formation-page').getByRole('button',{name:'刷新',exact:true}).click();
 }else await summary.click();
 const data=await (await response).json();
 const firstUrl=new URL(evidence.oldPage);firstUrl.searchParams.delete('cursor');
 const originalFirst=(await (await page.request.get(firstUrl.toString())).json()).data;
 if(data.data.total!==evidence.total||originalFirst.items.some(row=>row.kind==='ARTIFACT'&&row.freshness!=='CURRENT'))throw Error('Old closure changed after current edit');
 const oldPage=await (await page.request.get(evidence.oldPage)).json();
 if(oldPage.data.total!==evidence.total||oldPage.data.items[0].ordinal!==21)throw Error('Immutable cursor invalidated by current F');
 return {total:evidence.total,pages:evidence.pages,maxDom:evidence.maxRows,oldCursorKept:true,status:detail.status};
}""")
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/content-state', timeout=10
    ) as response:
        facts = json.load(response)
    assert facts['initial']['closure'] == facts['actual']['closure'], facts['actual']['closure']
    print('REAL_CLOSURE_HISTORY_PASS', json.dumps(result), flush=True)
