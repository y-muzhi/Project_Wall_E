"""Actual removal and historical restoration do not revive an old content association."""

import json
import urllib.request


def facts():
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/content-state', timeout=10
    ) as response:
        return json.load(response)


def browser(run, temporary):
    run("""async(page)=>{
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const editor=page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
 await editor.waitFor();await editor.click();
 await page.keyboard.press('Control+A');
 let selected=await page.evaluate(()=>window.getSelection()?.toString()??'');
 if(!selected.includes('待定事项')){await page.keyboard.press('Control+A');selected=await page.evaluate(()=>window.getSelection()?.toString()??'');}
 if(!selected.includes('待定事项')||selected.length<40)throw Error('Keyboard did not select actual document '+JSON.stringify(selected));

 await page.keyboard.press('Backspace');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open&&window.formationProduct.state().layout.right_tab!=='REVISIONS')))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 if((await page.evaluate(()=>window.formationProduct.state().reads.detail.data.status))!=='COMPLETED')throw Error('Removal reopened completed step');
 await page.getByRole('tab',{name:'成果',exact:true}).click();
 try{await page.getByText('内容已移除',{exact:true}).waitFor({timeout:10000});}
 catch(error){
  const facts=await (await page.request.get('http://127.0.0.1:8217/__fixture/content-state')).json();
  throw Error('Actual removal state '+JSON.stringify({freshness:facts.actual.artifact.freshness,markdown:facts.actual.markdown,ranges:facts.actual.ranges}));
 }
 await page.getByText('查看关联范围与替代历史',{exact:true}).click();
 await page.getByRole('tab',{name:'当前核实范围',exact:true}).click();
 await page.getByText('暂无当前核实范围',{exact:true}).waitFor();
 return true;
}""")
    removed = facts()
    initial, current = removed['initial'], removed['actual']
    assert current['content_version'] == 2 and current['artifact']['freshness'] == 'REMOVED'
    assert current['artifact']['origin_revision_id'] == initial['artifact']['origin_revision_id']
    assert current['closure'] == initial['closure']
    assert not [row for row in current['ranges'] if row[0] == 'CURRENT']
    assert current['run_count'] == current['llm_count'] == 0
    run("""async(page)=>{
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'文档记录',exact:true}).click();
 await page.getByRole('button',{name:'查看 V1',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='HISTORY');
 await page.getByRole('button',{name:'恢复到编辑草稿',exact:true}).click();
 await page.getByRole('dialog',{name:'恢复到编辑草稿',exact:true}).getByRole('button',{name:'恢复草稿',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='MANUAL');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 if(!(await page.evaluate(()=>window.formationProduct.state().layout.right_open&&window.formationProduct.state().layout.right_tab!=='REVISIONS')))await page.getByRole('button',{name:'Ai助手',exact:true}).click();
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 await page.locator('[data-step-ref="s1"] .formation-node').click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.detail.phase==='READY');
 await page.getByRole('tab',{name:'成果',exact:true}).click();
 await page.getByText('内容已移除',{exact:true}).waitFor();
 return true;
}""")
    restored = facts()['actual']
    assert restored['content_version'] == 3
    assert restored['markdown'] == initial['markdown']
    assert restored['artifact']['freshness'] == 'REMOVED'
    assert restored['artifact'] == current['artifact']
    assert restored['ranges'] == current['ranges']
    assert restored['closure'] == initial['closure']
    assert restored['formation_version'] == current['formation_version']
    assert restored['run_count'] == restored['llm_count'] == 0
    print(
        'REMOVED_RESTORED_PAGE_PASS',
        json.dumps(
            {
                'version': 3,
                'freshness': 'REMOVED',
                'restoredText': True,
                'currentRanges': 0,
                'closureKept': True,
                'runCount': 0,
            }
        ),
        flush=True,
    )
