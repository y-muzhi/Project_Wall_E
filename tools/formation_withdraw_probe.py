"""Actual ADJUST_WRITE model failure, explicit withdraw and original-request recovery."""

import importlib.util
import json
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def register_state(app, db, catalog):
    from backend.app.formation.proposal_sources import read_reference
    from backend.app.infrastructure.requirement_repository import RequirementRepository

    def facts():
        with db.transaction() as connection:
            row = connection.execute(
                'SELECT message_id,card_key FROM formation_proposal_index WHERE document_id=1'
            ).fetchone()
            proposal = read_reference(
                connection,
                RequirementRepository(connection).get_for_document(1, 1),
                dict(row),
                purpose='STAGED_WRITE',
            )
            run = connection.execute(
                'SELECT status,error_code FROM guide_runs ORDER BY id DESC LIMIT 1'
            ).fetchone()
            return {
                'binding': proposal.binding,
                'payload': proposal.payload,
                'needs_revision': proposal.needs_revision,
                'run': dict(run),
                'content_version': connection.execute(
                    'SELECT content_version FROM requirement_documents WHERE id=1'
                ).fetchone()[0],
                'run_count': connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],
                'llm_count': connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],
                'formal_count': connection.execute(
                    "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
                ).fetchone()[0],
                'proofs': [
                    json.loads(row[0])
                    for row in connection.execute(
                        "SELECT after_json FROM formation_event_changes WHERE entity_kind='PROPOSAL_CHECK' ORDER BY event_id"
                    )
                ],
            }

    initial = facts()

    @app.get('/__fixture/withdraw-state')
    def state():
        return {'initial': initial, 'actual': facts()}


def browser(run, temporary, mode):
    result = run(
        """async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY');
 await page.getByText(/文档提案 · 待处理/).click();
 await page.getByRole('button',{name:'请 AI 继续调整',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('继续调整原精确提案，失败后由用户决定是否撤回');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'讨论',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status==='FAILED');
 const failed=await (await page.request.get('http://127.0.0.1:8217/__fixture/withdraw-state')).json();
 if(failed.actual.run.error_code!=='MODEL_ERROR'||failed.actual.needs_revision!==true)throw Error('Not actual failed adjustment '+JSON.stringify({run:failed.actual.run,needs_revision:failed.actual.needs_revision}));
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('撤回核实期间新写的输入');
 await page.getByRole('tab',{name:'进展',exact:true}).click();
 await page.getByRole('button',{name:'刷新主线',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().reads.page.phase==='READY'&&!window.formationProduct.state().formation.loading);
 const summary=page.getByText(/文档提案 · 待处理/);
 if(!(await summary.evaluate(node=>node.parentElement.open)))await summary.click();
 const withdraw=page.getByRole('button',{name:'撤回调整',exact:true});
 await withdraw.waitFor();
 if(CASE_VARIANT==='unknown')await page.evaluate(()=>window.formationProduct.losePatch());
 else await page.evaluate(()=>window.formationProduct.failRead('/api/v1/requirements/1?'));
 await withdraw.click();
 await page.waitForFunction(mode=>window.formationProduct.state().formation.phase===(mode==='unknown'?'UNKNOWN':'CONFIRMED'),CASE_VARIANT);
 const committed=await (await page.request.get('http://127.0.0.1:8217/__fixture/withdraw-state')).json();
 if(committed.actual.needs_revision!==false||committed.actual.proofs.length!==1)throw Error('Withdraw was not actually committed '+JSON.stringify(committed.actual));
 if(CASE_VARIANT==='unknown')await page.getByRole('button',{name:'按原请求核实',exact:true}).click();
 else await page.getByRole('button',{name:'刷新已确认结果',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().formation.phase==='IDLE'&&window.formationProduct.state().formation.pending.length===0);
 const actual=await (await page.request.get('http://127.0.0.1:8217/__fixture/withdraw-state')).json();
 if(JSON.stringify(actual.initial.binding)!==JSON.stringify(actual.actual.binding)||JSON.stringify(actual.initial.payload)!==JSON.stringify(actual.actual.payload))throw Error('Withdraw replaced original authority');
 if(actual.actual.run_count!==2||actual.actual.llm_count!==2||actual.actual.formal_count!==0||actual.actual.content_version!==2||actual.actual.proofs.length!==1)throw Error('Recovery repeated effect '+JSON.stringify(actual.actual));
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 if(await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).inputValue()!=='撤回核实期间新写的输入')throw Error('Withdraw recovery cleared newer input');
 const writes=await page.evaluate(()=>window.formationProduct.requests().filter(row=>row.method==='PATCH'&&JSON.parse(row.body).discussion_command?.action==='WITHDRAW_PROPOSAL_ADJUSTMENT'));
 if(writes.length!==(CASE_VARIANT==='unknown'?2:1))throw Error('Wrong explicit recovery '+JSON.stringify(writes));
 if(writes.length===2&&(writes[0].body!==writes[1].body||writes[0].key!==writes[1].key))throw Error('Unknown withdraw changed frozen request');
 const events=actual.actual.proofs[0];
 if(events.expected_semantic_digest!==events.observed_semantic_digest)throw Error('Withdraw proof not actual matched digest');
 return {mode:CASE_VARIANT,modelError:'MODEL_ERROR',withdrawProofs:1,contentVersion:2,originalBindingKept:true,runCount:2,llmCount:2,newInputKept:true,patches:writes.length};
}""".replace('CASE_VARIANT', json.dumps(mode))
    )
    print('WITHDRAW_RECOVERY_PASS', json.dumps(result), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location(
        'formation_base_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    for mode in ('refresh', 'unknown'):
        case = 'withdraw-' + mode
        base.CASES[case] = partial(browser, mode=mode)
        base.probe(case, production=True)
