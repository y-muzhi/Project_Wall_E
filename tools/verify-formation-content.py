"""Actual six content entry probes with isolated production HTTP and offline providers."""

import argparse
import importlib.util
import json
import os
import sys
import threading
import urllib.request
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def original_probe():
    specification = importlib.util.spec_from_file_location(
        'formation_browser_probe', ROOT / 'tools/verify-formation-concurrency.py'
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def serve():
    from backend.app.infrastructure.sqlite_runtime import activate

    activate()
    from tools.quality_python import install_guards

    temporary = Path(os.environ['WALLE_CHECK_TEMP'])
    install_guards(ROOT, temporary)
    import pytest
    import uvicorn

    from backend.app.formation.commands import update_path
    from backend.app.guide.worker import GuideWorker
    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.formation_schema_release import load_release
    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
    from backend.app.service import create_app
    from backend.tests.formation.test_v21_artifact_links import link_input, material
    from backend.tests.formation.test_v21_content_maintenance import state
    from backend.tests.formation.test_v21_discuss_acceptance import accepted, request
    from backend.tests.formation.test_v21_model_publication import write_group
    from backend.tests.formation.test_v21_path_commands import request as path_request
    from backend.tests.formation.test_v21_proposal_adjustment import run_round
    from backend.tests.formation.test_v21_schema import workspace as fixture
    from backend.tests.guide.test_v15_acceptance import accept
    from backend.tests.guide.test_v15_cards import group
    from backend.tests.guide.test_v15_counting import Counter, offline_gate
    from backend.tests.guide.test_v15_execution import PROFILE, Gateway, execute, output

    entry, relation = os.environ['W21_BROWSER_CASE'].rsplit('-', 1)
    entry = 'review' if entry == 'review480' else entry
    related = relation in ('related', 'sufficient')
    patcher = pytest.MonkeyPatch()
    offline_gate(patcher)
    db = FormationDatabase(temporary / 'content.sqlite', formation_release=load_release())
    db.initialize()
    generation = fixture.__wrapped__(db)
    base = next(generation)
    workspace = (base[0], base[1], base[2].for_formation_profile(DEFAULT_PROFILE))
    document, revision = material(workspace)
    assert document == 3

    if entry == 'restore':
        with db.transaction() as connection:
            original = connection.execute(
                'SELECT markdown_content FROM requirement_documents WHERE id=?', (document,)
            ).fetchone()[0]

        def change(blocks, identities):
            target = blocks[0 if related else -1]
            updated = target.markdown.rstrip('\r\n') + ' 恢复前的差异\n'
            return (
                original[: target.start_offset] + updated + original[target.end_offset :],
                identities,
            )

        from backend.app.documents.markdown import parse_markdown
        from backend.tests.documents.test_v15_editing import candidate, finish, save, start

        started = start(workspace, identity=document, version=1)
        assert started['code'] == 'DRAFT_STARTED', started
        draft = started['data']['manual_draft']
        baseline = parse_markdown(draft['markdown_content']).blocks
        identity_values = [row['block_id'] for row in draft['block_state_json']['blocks']]
        markdown, identity_values = change(baseline, identity_values)
        saved = save(workspace, draft, candidate(workspace, draft, markdown, identity_values))
        assert saved['code'] == 'DRAFT_SAVED', saved
        result = finish(workspace, saved['data'])
        assert result['code'] == 'DRAFT_COMPLETED', result
        with db.transaction() as connection:
            revision = connection.execute(
                'SELECT id FROM revisions WHERE document_id=? AND source_content_version=2',
                (document,),
            ).fetchone()[0]

    with db.transaction() as connection:
        link = link_input(connection, document, revision)
    result = update_path(
        workspace[1],
        path_request(workspace, [{'type': 'LINK_CONTENT', **link}], document_id=document),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    before = state(workspace, document)
    current = before[4]
    from backend.app.documents.markdown import parse_markdown

    blocks = parse_markdown(current['markdown_content']).blocks
    identities = [block['block_id'] for block in json.loads(current['block_state_json'])['blocks']]
    index = 0 if related else len(blocks) - 1
    target = blocks[index]
    changed = target.markdown.rstrip('\r\n') + ' 实际入口补充\n'
    proposed = (
        current['markdown_content'][: target.start_offset]
        + changed
        + current['markdown_content'][target.end_offset :]
    )
    precise = {
        'title': '核实范围',
        'explanation': '只修改选定区块',
        'impact': None,
        'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': identities[index]},
        'selector_json': None,
        'original_content': target.markdown,
        'proposed_markdown': changed,
        'proposed_data_json': None,
    }

    if entry in ('review', 'remove'):
        from tools.formation_review_probe import seed

        seed(workspace, document)
    elif entry == 'history':
        from tools.formation_history_probe import seed

        seed(workspace, document, link)
    elif entry in ('fact', 'suggestion'):
        accepted_result = accept(
            base,
            document_id=document,
            operation='DISCUSS' if entry == 'fact' else 'PROPOSE_CHANGES',
            expected_discussion_version=before[0]['discussion_version'],
            target={'kind': 'EXISTING', 'document_id': document, 'expected_content_version': 1},
            scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': identities[index]}},
        )
        assert accepted_result['code'] == 'GUIDE_ACCEPTED', accepted_result

        def returned(context):
            if entry == 'fact':
                payload = {
                    'confirmed_fact_patches': [
                        {
                            'patch': precise,
                            'evidence': [
                                {
                                    'message_id': context.input['current_request']['message_id'],
                                    'quoted_text': '用户原话',
                                }
                            ],
                        }
                    ]
                }
                return output(context, cards=group('FACT_CONFIRMATION', payload))
            return output(context, response_type='CHANGE_PROPOSALS', suggestions=[precise])

        completed = execute(base, Gateway(returned))
        assert completed['code'] == 'AI_FINISHED', completed
    elif entry == 'staged':
        body = request(
            workspace,
            target={
                'discussion_step_ref': 's1',
                'discussion_branch_ref': None,
                'branch_intent': None,
                'branch_resume_basis': None,
            },
        )
        body.update(
            document_id=document, expected_discussion_version=before[0]['discussion_version']
        )
        initial = accepted(workspace, body)

        def staged_reply(context):
            cards = write_group(context)
            cards['action_payload'].update(
                write_mode='PATCH_EXISTING',
                markdown_content=None,
                patches=[precise],
                scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': identities[index]}},
            )
            return output(context, cards=cards)

        completed = run_round(workspace, initial['data']['guide_run_id'], Gateway(staged_reply))
        assert completed['code'] == 'AI_FINISHED', completed

    def revision_reply(context):
        if entry == 'review':
            from tools.formation_review_probe import reply

            return reply(context, related)
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': current['name'],
                'document_kind': 'brief',
                'markdown_content': proposed,
                'change_summary': '只修改目标范围',
            },
        )

    def worker(database, catalog):
        return GuideWorker(
            database,
            catalog=catalog,
            orchestrator_options={
                'profile': PROFILE,
                'gateway': Gateway(revision_reply),
                'counting_counter': Counter(['OK']),
            },
        )

    try:
        next(generation)
    except StopIteration:
        pass
    app = create_app(database=db, catalog=workspace[2], worker_factory=worker, schema_version=210)

    def facts():
        with db.transaction() as connection:
            doc = dict(
                connection.execute(
                    'SELECT * FROM requirement_documents WHERE id=?', (document,)
                ).fetchone()
            )
            head = dict(
                connection.execute(
                    'SELECT * FROM formation_heads WHERE document_id=?', (document,)
                ).fetchone()
            )
            artifact = dict(
                connection.execute(
                    "SELECT * FROM formation_artifacts WHERE document_id=? AND artifact_ref='a1'",
                    (document,),
                ).fetchone()
            )
            ranges = [
                tuple(row)
                for row in connection.execute(
                    'SELECT role,ordinal,block_id,block_digest FROM formation_artifact_ranges '
                    "WHERE document_id=? AND artifact_ref='a1' ORDER BY role,ordinal",
                    (document,),
                )
            ]
            value = {
                'content_version': doc['content_version'],
                'markdown': doc['markdown_content'],
                'formation_version': head['version'],
                'artifact': artifact,
                'ranges': ranges,
                'run_count': connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],
                'llm_count': connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],
                'revision_count': connection.execute('SELECT count(*) FROM revisions').fetchone()[
                    0
                ],
            }
            if entry in ('history', 'review', 'remove'):
                from tools.formation_history_probe import fingerprint

                value['closure'] = fingerprint(connection, document)
            if entry == 'review':
                from tools.formation_review_probe import facts as review_facts

                value.update(review_facts(connection, document))
            return value

    initial_facts = facts()

    @app.get('/__fixture/content-state')
    def content_state():
        return {'initial': initial_facts, 'actual': facts()}

    server = uvicorn.Server(
        uvicorn.Config(app, host='127.0.0.1', port=8217, log_level='error', access_log=False)
    )

    def stop():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop, daemon=True).start()
    try:
        server.run()
    finally:
        patcher.undo()


def browser_case(run, temporary, entry, related):
    run("""async(page)=>{
 await page.setViewportSize({width:1440,height:900});
 await page.waitForFunction(()=>window.formationProduct.state().current===3);
 return true;
}""")
    if entry == 'manual':
        run(
            """async(page)=>{
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('button',{name:'人工编辑',exact:true}).click();
 const editor=page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror[contenteditable="true"]');
 await editor.waitFor();await editor.click();
 await page.keyboard.press(RELATED?'Control+Home':'Control+End');
 await page.keyboard.insertText('人工入口的实际补充');
 await page.getByRole('button',{name:'完成编辑',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.state().phase==='CURRENT');
 return true;
}""".replace('RELATED', json.dumps(related))
        )
    elif entry == 'restore':
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
 return true;
}""")
    elif entry == 'remove':
        from tools.formation_removed_probe import browser

        browser(run, temporary)
        return
    elif entry in ('review', 'review480'):
        from tools.formation_review_probe import browser

        browser(run, temporary, related, width=480 if entry == 'review480' else 1440)
        return
    elif entry == 'history':
        from tools.formation_history_probe import browser

        browser(run)
    elif entry == 'revise':
        run("""async(page)=>{
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 await page.getByRole('button',{name:'操作设置',exact:true}).click();
 await page.getByRole('combobox',{name:'AI 操作',exact:true}).click();
 await page.getByRole('option',{name:'修订并保存',exact:true}).click();
 await page.getByRole('button',{name:'操作设置',exact:true}).click();
 await page.getByRole('textbox',{name:'给 AI 的消息',exact:true}).fill('仅修改已指定的范围');
 await page.getByRole('region',{name:'AI 消息输入',exact:true}).getByRole('button',{name:'修订并保存',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.read.getSnapshot().run?.status==='COMPLETED');
 return true;
}""")
    elif entry in ('fact', 'staged'):
        run(
            """async(page)=>{
 await page.getByRole('tab',{name:'Ai对话',exact:true}).click();
 const cards=page.getByRole('region',{name:'决策卡片组',exact:true});
 await cards.getByRole('radio',{name:OPTION,exact:true}).check();
 await cards.getByRole('button',{name:SUBMIT,exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().regions.conversation.cards.getSnapshot().slots.some(slot=>slot.owner?.getSnapshot().phase==='RESOLVED'));
 return true;
}""".replace('OPTION', json.dumps('确认以上事实和变更' if entry == 'fact' else 'apply')).replace(
                'SUBMIT', json.dumps('确认并写入' if entry == 'fact' else '按提案写入')
            )
        )
    else:
        run("""async(page)=>{
 await page.getByRole('tab',{name:'修改建议',exact:true}).click();
 await page.getByRole('button',{name:/接受全部待处理/}).click();
 await page.getByRole('dialog').getByRole('button',{name:'确认批量接受',exact:true}).click();
 await page.getByRole('button',{name:'完成本批修改',exact:true}).click();
 await page.getByRole('dialog',{name:'完成本批修改',exact:true}).getByRole('button',{name:'确认应用',exact:true}).click();
 await page.waitForFunction(()=>window.formationProduct.owner().documents.getSnapshot().detail?.current?.content_version===2);
 return true;
}""")
    with urllib.request.urlopen(
        'http://127.0.0.1:8217/__fixture/content-state', timeout=10
    ) as response:
        data = json.load(response)
    before, actual = data['initial'], data['actual']
    assert actual['content_version'] == before['content_version'] + 1, data
    assert actual['formation_version'] == before['formation_version'] + int(
        related or entry == 'staged'
    ), data
    assert actual['artifact']['origin_revision_id'] == before['artifact']['origin_revision_id']
    if related:
        assert actual['artifact']['freshness'] == 'NEEDS_REVIEW', data
    else:
        assert actual['artifact'] == before['artifact'], data
        assert actual['ranges'] == before['ranges'], data
    assert actual['run_count'] == before['run_count'] + int(entry == 'revise'), data
    assert actual['llm_count'] == before['llm_count'] + int(entry == 'revise'), data
    print(
        'CONTENT_ENTRY_PASS',
        entry,
        related,
        json.dumps(
            {
                key: actual[key]
                for key in ['content_version', 'formation_version', 'run_count', 'llm_count']
            }
        ),
        flush=True,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--production', action='store_true')
    cases = [
        entry + '-' + relation
        for entry in ('manual', 'restore', 'revise', 'fact', 'suggestion', 'staged')
        for relation in ('related', 'unrelated')
    ]
    cases.extend(
        (
            'history-related',
            'review-sufficient',
            'review-missing',
            'review480-sufficient',
            'remove-related',
        )
    )
    parser.add_argument('--case', choices=[*cases, 'all'], default='all')
    args = parser.parse_args()
    if args.serve:
        serve()
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        base_probe = original_probe()
        for selected in cases if args.case == 'all' else [args.case]:
            entry, relation = selected.rsplit('-', 1)
            base_probe.CASES[selected] = partial(
                browser_case, entry=entry, related=relation in ('related', 'sufficient')
            )
            print('CASE', selected, flush=True)
            base_probe.probe(
                selected,
                serve_script=Path(__file__).resolve(),
                document_id=3,
                startup_timeout=300 if entry == 'history' else 60,
                production=args.production,
            )
