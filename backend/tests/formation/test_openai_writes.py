"""Native OpenAI generation/revision over real Schema210 commands, no external I/O."""

import asyncio
import json

import pytest

from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.model_profile import (
    OPENAI_DOCUMENT_PROFILE,
    OPENAI_PROFILE,
    ModelProfile,
)
from backend.tests.formation.test_openai_execution import PROFILE, adapters, technical_source
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import output

__all__ = ['database', 'released', 'workspace', 'technical_source']


@pytest.mark.parametrize('failure', ('size', 'truncated', 'read_timeout', 'response_capacity'))
def test_document_limit_rejection_or_truncation_never_creates_a_document(
    workspace, monkeypatch, failure
):
    from backend.app.infrastructure.model_gateway import ModelGateway
    from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
    from backend.app.messages.queries import list_messages

    db, commands, original_catalog = workspace
    catalog = original_catalog.for_formation_profile(OPENAI_PROFILE)
    resources = catalog.for_document_operation('GENERATE').collaboration
    monkeypatch.setenv('WALLE_ACTIVATED_OPENAI_DOCUMENT_RELEASE_SHA256', resources.release_sha256)
    accepted = accept(
        (db, commands, catalog),
        operation='GENERATE',
        target={
            'kind': 'NEW',
            'name': '未完成文档',
            'document_kind': 'design',
            'template_ref': None,
        },
    )
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    run_id = accepted['data']['guide_run_id']

    def written(context):
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            message='模拟截断。',
            document_result={
                'name': '未完成文档',
                'document_kind': 'design',
                'markdown_content': '# 模拟内容\n',
                'change_summary': '模拟输出',
            },
        )

    model_requests = []

    def fail_response(request):
        import httpx

        model_requests.append(request)
        if failure == 'read_timeout':
            raise httpx.ReadTimeout('isolated timeout', request=request)
        return httpx.Response(200, content=b' ' * (MAX_AUDIT_BYTES + 1))

    counter, gateway, seen = adapters(
        None,
        make=written,
        input_tokens=131_073 if failure == 'size' else 2_000,
        output_tokens=100_000,
        defect=None if failure == 'size' else 'incomplete',
    )
    if failure in ('read_timeout', 'response_capacity'):
        import httpx

        gateway = ModelGateway(transport_factory=lambda: httpx.MockTransport(fail_response))
    result = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': run_id},
            process_lock=commands.process_lock,
            catalog=catalog,
            profile=PROFILE,
            counting_counter=counter,
            gateway=gateway,
        )
    )
    assert result['code'] == 'AI_FAILED', result
    kinds = [kind for kind, _ in seen]
    expected, reason = {
        'size': ('CONTEXT_LIMIT_EXCEEDED', None),
        'truncated': ('OUTPUT_INVALID', '达到本次上限'),
        'read_timeout': ('MODEL_ERROR', '等待模型响应超时'),
        'response_capacity': ('MODEL_ERROR', '模型响应超过当前读取容量'),
    }[failure]
    assert result['details']['error_code'] == expected, result
    if failure == 'size':
        assert 1 <= len(kinds) <= 3 and set(kinds) == {'count'}
    else:
        if failure == 'truncated':
            assert kinds == ['count', 'model']
        else:
            assert kinds == ['count'] and len(model_requests) == 1
        receipts = list_messages(
            db, {'requirement_id': 1, 'document_id': 1}, catalog=catalog, include_operations=True
        )
        trigger = next(
            item
            for item in receipts['data']['items']
            if item['id'] == accepted['data']['user_message_id']
        )
        assert trigger['guide_operations'][0]['state'] == 'FAILED'
        assert reason in trigger['guide_operations'][0]['reason']
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM requirement_documents WHERE name='未完成文档'"
            ).fetchone()[0]
            == 0
        )
        count = connection.execute(
            'SELECT count(*) FROM llm_uses WHERE guide_run_id=?', (run_id,)
        ).fetchone()[0]
        assert count == (0 if failure == 'size' else 1)
        if failure == 'truncated':
            status = connection.execute(
                'SELECT finish_reason,parse_status,raw_response_json FROM llm_uses WHERE guide_run_id=?',
                (run_id,),
            ).fetchone()
            assert tuple(status)[:2] == ('length', 'FAILED')
            assert json.loads(status['raw_response_json'])['status'] == 'incomplete'


@pytest.mark.parametrize('operation', ('GENERATE', 'REVISE'))
def test_native_write_uses_original_single_commit_and_leaves_other_document_unchanged(
    workspace, monkeypatch, operation
):
    db, commands, original_catalog = workspace
    catalog = original_catalog.for_formation_profile(OPENAI_PROFILE)
    document_resources = catalog.for_document_operation(operation).collaboration
    monkeypatch.setenv(
        'WALLE_ACTIVATED_OPENAI_DOCUMENT_RELEASE_SHA256', document_resources.release_sha256
    )
    active = db, commands, catalog
    target = (
        {'kind': 'NEW', 'name': 'OpenAI新稿', 'document_kind': 'design', 'template_ref': None}
        if operation == 'GENERATE'
        else {'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 1}
    )
    with db.transaction() as connection:
        untouched = dict(
            connection.execute('SELECT * FROM requirement_documents WHERE id=2').fetchone()
        )
        before_revisions = connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
    result = accept(
        active,
        operation=operation,
        target=target,
        scope=None if operation == 'GENERATE' else {'scope_type': 'DOCUMENT', 'scope_ref': None},
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result

    long_paragraphs = '\n\n'.join(
        f'第 {number} 节。' + '完整返回正文。' * 390 for number in range(40)
    )
    markdown = (
        '# 目标\n\n' + long_paragraphs + '\n'
        if operation == 'GENERATE'
        else '# 目标\n\n通过原生接口形成的离线夹具正文。\n\n另一段。\n'
    )
    input_tokens = 131_072 if operation == 'GENERATE' else 2_000

    def written(context):
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            message='只在模型审计中保留的返回内容。' * 240,
            document_result={
                'name': 'OpenAI新稿' if operation == 'GENERATE' else '需求',
                'document_kind': 'design',
                'markdown_content': markdown,
                'change_summary': '生成或修订明确目标',
            },
        )

    counter, gateway, seen = adapters(
        None, make=written, output_tokens=100_000, input_tokens=input_tokens
    )
    finished = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': 1},
            process_lock=commands.process_lock,
            catalog=catalog,
            profile=PROFILE,
            counting_counter=counter,
            gateway=gateway,
        )
    )
    assert finished['code'] == 'AI_FINISHED', finished
    run = get_guide_run(db, 1)['data']
    assert run['status'] == 'COMPLETED' and run['application_result'] == 'APPLIED', run
    assert run['document_effect']['result'] == ('CREATED' if operation == 'GENERATE' else 'UPDATED')
    expected_summary = f'文档已保存为 V{run["document_effect"]["after_content_version"]}。'
    assert run['final_result']['summary'] == expected_summary
    with db.transaction() as connection:
        message = connection.execute(
            'SELECT content FROM conversation_messages WHERE id=?',
            (run['latest_assistant_message_id'],),
        ).fetchone()
        assert message[0] == expected_summary
        assert (
            dict(connection.execute('SELECT * FROM requirement_documents WHERE id=2').fetchone())
            == untouched
        )
        assert (
            connection.execute('SELECT count(*) FROM revisions').fetchone()[0]
            == before_revisions + 1
        )
        use = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert use['provider'] == 'openai' and use['validation_status'] == 'SUCCEEDED'
        assert use['input_tokens'] == input_tokens and use['output_tokens'] == 100_000
        stored = connection.execute(
            'SELECT markdown_content FROM requirement_documents WHERE id=?',
            (run['document_effect']['document_id'],),
        ).fetchone()[0]
        assert stored == markdown
        if operation == 'GENERATE':
            assert len(use['raw_response_json'].encode('utf-8')) > 300_000
        assert json.loads(use['raw_response_json'])['object'] == 'response'
        assert '只在模型审计中保留的返回内容。' in use['raw_response_json']
        snapshot = json.loads(use['request_snapshot_json'])
        assert snapshot['request']['max_output_tokens'] == 100000
        assert snapshot['protocol']['release'] == document_resources.reference(
            'collaboration.release'
        )
        assert snapshot['counting']['output_tokens_limit'] == 100000
        assert ModelProfile.from_snapshot(snapshot['profile']).profile_id == OPENAI_DOCUMENT_PROFILE
        assert document_resources.counting['input_limit'] == 131072
        assert document_resources.counting['total_limit'] == 231072
        assert (
            catalog.for_document_operation('DISCUSS').collaboration.counting['output_limit'] == 8192
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM document_change_audits WHERE guide_run_id=1 AND event_type='CONTENT_COMMITTED'"
            ).fetchone()[0]
            == 1
        )
    assert [kind for kind, _ in seen] == ['count', 'model']

    if operation == 'REVISE':
        verify_review_after_first_write(active, document_resources)


def verify_review_after_first_write(workspace, document_resources):
    from uuid import uuid4

    from backend.app.documents.commands import (
        cancel_manual_draft,
        complete_manual_draft,
        create_document,
        start_manual_draft,
    )
    from backend.app.guide.commands import cancel_guide_run
    from backend.app.messages.queries import list_messages
    from backend.app.requirements.queries import get_requirement
    from backend.app.documents.markdown import parse_markdown
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.app.suggestions.commands import decide_group, decide_suggestion, complete_batch
    from backend.app.suggestions.queries import get_batch

    db, commands, catalog = workspace
    with db.transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        root = RequirementRepository(connection).get_for_document(1, 1)
        base_revision = connection.execute(
            'SELECT id FROM revisions WHERE document_id=1 AND source_content_version=2'
        ).fetchone()[0]
    metadata = json.loads(current['block_state_json'])['blocks']
    blocks = parse_markdown(current['markdown_content']).blocks
    result = accept(
        workspace,
        operation='REVISE',
        expected_discussion_version=root['discussion_version'],
        target={'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 2},
        scope={'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': metadata[0]['block_id']}},
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result
    run_id = result['data']['guide_run_id']
    with db.transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs WHERE id=?', (run_id,)).fetchone()
        assert run['operation'] == 'PROPOSE_CHANGES'
        assert json.loads(run['execution_basis_json'])['resources'][
            'release'
        ] == document_resources.reference('collaboration.release')

    selected = {'requirement_id': 1, 'document_id': 1}
    messages = list_messages(db, selected, catalog=catalog, include_operations=True)
    assert messages['code'] == 'READ_OK', messages
    trigger = next(
        item
        for item in messages['data']['items']
        if item['id'] == result['data']['user_message_id']
    )
    assert trigger['guide_operations'][0]['state'] == 'RUNNING'
    assert trigger['guide_operations'][0]['base_content_version'] == 2
    assert trigger['guide_operations'][0]['scope_label'] == '目标'
    assert (
        accept(
            workspace,
            operation='REVISE',
            expected_discussion_version=root['discussion_version'] + 1,
            target={'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 2},
            scope={'scope_type': 'DOCUMENT', 'scope_ref': None},
        )['code']
        == 'WORK_STATE_CONFLICT'
    )

    other = create_document(
        commands,
        {
            'requirement_id': 1,
            'name': '运行中独立创建',
            'document_kind': 'DESIGN',
            'template_ref': None,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert other['code'] == 'CREATED', other
    third = other['data']['document']['id']
    draft = start_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 2,
            'expected_version': 1,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert draft['code'] == 'DRAFT_STARTED', draft
    parallel = accept(
        workspace,
        document_id=third,
        operation='GENERATE',
        target={
            'kind': 'NEW',
            'name': '独立模型轮次',
            'document_kind': 'design',
            'template_ref': None,
        },
    )
    assert parallel['code'] == 'GUIDE_ACCEPTED', parallel
    other_run = parallel['data']['guide_run_id']
    detail = get_requirement(db, 1, include_document_runs=True)
    assert detail['code'] == 'READ_OK', detail
    assert detail['data']['active_operation']['target_document_id'] == 2
    assert {(item['document_id'], item['id']) for item in detail['data']['document_runs']} == {
        (1, run_id),
        (third, other_run),
    }
    cancelled = cancel_guide_run(
        commands, {'guide_run_id': other_run, 'idempotency_key': str(uuid4())}
    )
    assert cancelled['code'] == 'GUIDE_CANCELLED', cancelled

    def proposed(context):
        return output(
            context,
            response_type='CHANGE_PROPOSALS',
            suggestions=[
                {
                    'title': '更新目标',
                    'explanation': '修订属于当前章节',
                    'impact': None,
                    'patch_operation': 'REPLACE_BLOCK',
                    'target_ref': {'block_id': entry['block_id']},
                    'selector_json': None,
                    'original_content': block.markdown,
                    'proposed_markdown': proposed,
                    'proposed_data_json': None,
                }
                for entry, block, proposed in zip(
                    metadata,
                    blocks,
                    ('# 新目标\n', '已接受段落。\n', '应保留原句。\n'),
                    strict=True,
                )
            ],
            suggestion_groups=[
                {
                    'title': '更新目标与说明',
                    'reason': '两个位置保持一致',
                    'suggestion_orders': [1, 2],
                },
                {'title': '另行调整', 'reason': '可独立处理', 'suggestion_orders': [3]},
            ],
        )

    counter, gateway, seen = adapters(None, make=proposed)
    finished = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': run_id},
            process_lock=commands.process_lock,
            catalog=catalog,
            profile=PROFILE,
            counting_counter=counter,
            gateway=gateway,
        )
    )
    assert finished['code'] == 'AI_FINISHED', finished
    run = get_guide_run(db, run_id)['data']
    batch_id = run['suggestion_batch_id']
    assert batch_id is not None, run
    with db.transaction() as connection:
        root = RequirementRepository(connection).get(1)
        assert root['document_work_state'] == 'MANUAL_EDITING'
        assert root['active_operation_id'] == draft['data']['manual_draft']['id']
        assert (
            connection.execute(
                'SELECT content_version FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
            == 2
        )
    messages = list_messages(db, selected, catalog=catalog, include_operations=True)
    assert messages['code'] == 'READ_OK', messages
    trigger = next(
        item
        for item in messages['data']['items']
        if item['id'] == result['data']['user_message_id']
    )
    assert trigger['guide_operations'][0]['state'] == 'PENDING_REVIEW'
    assert trigger['guide_operations'][0]['batch_id'] == batch_id
    assert any(item.get('audited_document_output') for item in messages['data']['items'])
    with db.transaction() as connection:
        discussion_version = RequirementRepository(connection).get_for_document(1, 1)[
            'discussion_version'
        ]
    repeated = accept(
        workspace,
        operation='REVISE',
        expected_discussion_version=discussion_version,
        target={'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 2},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None},
    )
    assert repeated['code'] == 'BATCH_PENDING', repeated
    ended_draft = cancel_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 2,
            'draft_id': draft['data']['manual_draft']['id'],
            'expected_version': 1,
            'idempotency_key': str(uuid4()),
        },
    )
    assert ended_draft['code'] == 'DRAFT_CANCELLED', ended_draft
    new_document = create_document(
        commands,
        {
            'requirement_id': 1,
            'name': '并行操作文档',
            'document_kind': 'DESIGN',
            'template_ref': None,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert new_document['code'] == 'CREATED', new_document
    batch = get_batch(db, batch_id, catalog=catalog)['data']
    assert batch['status'] == 'PENDING' and batch['base_content_version'] == 2
    decision = decide_suggestion(
        commands,
        {
            'suggestion_id': batch['suggestions'][0]['id'],
            'decision': 'ACCEPTED',
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert decision['code'] == 'STATE_CONFLICT', decision
    review = get_batch(db, batch_id, catalog=catalog, include_review=True)['data']['review']
    assert review['base_revision_id'] == base_revision
    assert review['grouped'] and review['independent'] and review['decision_version'] == 1
    assert [len(group['suggestion_ids']) for group in review['groups']] == [2, 1]
    first = {
        'batch_id': batch_id,
        'group_id': 1,
        'expected_decision_version': 1,
        'decision': 'ACCEPTED',
        'idempotency_key': str(uuid4()),
    }
    accepted = decide_group(commands, first, catalog=catalog)
    assert accepted['code'] == 'GROUP_DECIDED', accepted
    assert accepted['data']['decision_version'] == 2
    assert decide_group(commands, first, catalog=catalog) == accepted
    second = {**first, 'group_id': 2, 'decision': 'REJECTED', 'idempotency_key': str(uuid4())}
    conflict = decide_group(commands, second, catalog=catalog)
    assert (
        conflict['code'] == 'DECISION_VERSION_CONFLICT'
        and conflict['details']['actual_version'] == 2
    )
    assert (
        decide_group(commands, {**second, 'expected_decision_version': 2}, catalog=catalog)['code']
        == 'GROUP_DECIDED'
    )
    stale = complete_batch(
        commands,
        {
            'batch_id': batch_id,
            'expected_content_version': 2,
            'expected_decision_version': 2,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert stale['code'] == 'DECISION_VERSION_CONFLICT'
    old_draft = start_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 1,
            'expected_version': 2,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert old_draft['code'] == 'DRAFT_STARTED', old_draft
    draft_before = old_draft['data']['manual_draft']
    application = complete_batch(
        commands,
        {
            'batch_id': batch_id,
            'expected_content_version': 2,
            'expected_decision_version': 3,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert application['code'] == 'BATCH_APPLIED', application
    from backend.app.documents.queries import get_manual_draft

    submitted = {
        'requirement_id': 1,
        'document_id': 1,
        'draft_id': draft_before['id'],
        'expected_version': draft_before['content_version'],
        'idempotency_key': str(uuid4()),
    }
    conflicting = complete_manual_draft(commands, submitted, catalog=catalog)
    assert conflicting['code'] == 'CONTENT_VERSION_CONFLICT', conflicting
    assert get_manual_draft(db, 1, 1, catalog=catalog)['data'] == draft_before
    assert (
        cancel_manual_draft(commands, {**submitted, 'idempotency_key': str(uuid4())})['code']
        == 'DRAFT_CANCELLED'
    )
    with db.transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        assert current['content_version'] == 3
        assert current['markdown_content'].startswith('# 新目标\n')
        assert (
            '已接受段落。' in current['markdown_content']
            and '另一段。' in current['markdown_content']
        )
        applied_revision = connection.execute(
            'SELECT id FROM revisions WHERE document_id=1 AND source_content_version=3'
        ).fetchone()[0]
    messages = list_messages(db, selected, catalog=catalog, include_operations=True)
    assert messages['code'] == 'READ_OK', messages
    trigger = next(
        item
        for item in messages['data']['items']
        if item['id'] == result['data']['user_message_id']
    )
    assert trigger['guide_operations'][0]['state'] == 'APPLIED'
    assert trigger['guide_operations'][0]['saved_content_version'] == 3
    final = get_batch(db, batch_id, catalog=catalog, include_review=True)['data']['review']
    assert final['decision_version'] == 3 and final['applied_revision_id'] == applied_revision
    assert [kind for kind, _ in seen] == ['count', 'model']


def test_restored_framework_remains_reviewable_when_model_finishes_after_manual_commit(
    workspace, monkeypatch
):
    from uuid import uuid4

    from backend.app.documents.commands import create_document
    from backend.app.documents.markdown import parse_markdown
    from backend.app.documents.queries import get_current_document
    from backend.app.messages.queries import list_messages
    from backend.app.suggestions.commands import complete_batch, decide_group, discard_batch
    from backend.app.suggestions.queries import get_batch
    from backend.tests.documents.test_v15_editing import candidate, finish, save, start

    db, commands, original_catalog = workspace
    catalog = original_catalog.for_formation_profile(OPENAI_PROFILE)
    active = (db, commands, catalog)
    resources = catalog.for_document_operation('REVISE').collaboration
    monkeypatch.setenv('WALLE_ACTIVATED_OPENAI_DOCUMENT_RELEASE_SHA256', resources.release_sha256)
    created = create_document(
        commands,
        {
            'requirement_id': 1,
            'name': '前端设计',
            'document_kind': 'FRONTEND_DESIGN',
            'initial_content': 'FRAMEWORK',
            'template_ref': None,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert created['code'] == 'CREATED', created
    template = created['data']['document']
    document_id = template['id']

    def current():
        return get_current_document(db, 1, document_id, catalog=catalog)['data']

    def request(document):
        with db.transaction() as connection:
            version = connection.execute(
                'SELECT discussion_version FROM requirement_documents WHERE id=?', (document_id,)
            ).fetchone()[0]
        result = accept(
            active,
            operation='REVISE',
            expected_discussion_version=version,
            target={
                'kind': 'EXISTING',
                'document_id': document_id,
                'expected_content_version': document['content_version'],
            },
            scope={'scope_type': 'DOCUMENT', 'scope_ref': None},
        )
        assert result['code'] == 'GUIDE_ACCEPTED', result
        return result['data']

    def run(result, make):
        counter, gateway, seen = adapters(None, make=make)
        finished = asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': result['guide_run_id']},
                process_lock=commands.process_lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=counter,
                gateway=gateway,
            )
        )
        assert finished['code'] == 'AI_FINISHED', finished
        assert [kind for kind, _ in seen] == ['count', 'model']
        return get_guide_run(db, result['guide_run_id'])['data']

    first = run(
        request(template),
        lambda context: output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': '前端设计',
                'document_kind': 'design',
                'markdown_content': '# 咖啡助手前端\n\n这是业务设计首稿。\n',
                'change_summary': '完成首稿',
            },
        ),
    )
    assert first['operation'] == 'REVISE' and first['suggestion_batch_id'] is None
    assert first['application_result'] == 'APPLIED', first
    assert first['document_effect']['after_content_version'] == 2
    assert '业务设计首稿' in current()['markdown_content']

    restoring = start(
        active, identity=document_id, version=2, restore=template['current_revision_id']
    )
    assert restoring['code'] == 'DRAFT_STARTED', restoring
    restore = finish(active, restoring['data']['manual_draft'])
    assert restore['code'] == 'DRAFT_COMPLETED', restore
    frozen = current()
    assert (
        frozen['content_version'] == 3
        and frozen['markdown_content'] == template['markdown_content']
    )

    def proposed(context):
        editing = start(active, identity=document_id, version=3)
        assert editing['code'] == 'DRAFT_STARTED', editing
        draft = editing['data']['manual_draft']
        saved = save(active, draft, candidate(active, draft, '# 人工更新\n\n后保存的版本。\n'))
        assert saved['code'] == 'DRAFT_SAVED', saved
        committed = finish(active, saved['data'])
        assert committed['code'] == 'DRAFT_COMPLETED', committed

        block = parse_markdown(frozen['markdown_content']).blocks[0]
        return output(
            context,
            response_type='CHANGE_PROPOSALS',
            suggestions=[
                {
                    'title': '调整首块',
                    'explanation': '使用冻结的旧正文',
                    'impact': None,
                    'patch_operation': 'REPLACE_BLOCK',
                    'target_ref': {'block_id': frozen['block_state_json']['blocks'][0]['block_id']},
                    'selector_json': None,
                    'original_content': block.markdown,
                    'proposed_markdown': '这是建议中的说明。\n',
                    'proposed_data_json': None,
                }
            ],
            suggestion_groups=[
                {'title': '说明', 'reason': '按旧版本审阅', 'suggestion_orders': [1]}
            ],
        )

    submitted = request(frozen)
    proposal = run(submitted, proposed)
    assert proposal['operation'] == 'PROPOSE_CHANGES'
    batch_id = proposal['suggestion_batch_id']
    assert batch_id is not None
    read = get_batch(db, batch_id, catalog=catalog, include_review=True)['data']
    assert read['batch']['base_content_version'] == 3
    assert read['review']['base_revision_id'] == frozen['current_revision_id']
    assert read['review']['applied_revision_id'] is None
    receipt = list_messages(
        db,
        {'requirement_id': 1, 'document_id': document_id},
        catalog=catalog,
        include_operations=True,
    )
    trigger = next(
        message
        for message in receipt['data']['items']
        if message['id'] == submitted['user_message_id']
    )
    assert trigger['guide_operations'][0]['state'] == 'OUTDATED'

    mutation = {'batch_id': batch_id, 'idempotency_key': str(uuid4())}
    assert discard_batch(commands, mutation)['code'] == 'CONTENT_VERSION_CONFLICT'
    decision = {
        'batch_id': batch_id,
        'idempotency_key': str(uuid4()),
        'expected_decision_version': 1,
    }
    assert (
        decide_group(
            commands,
            {**decision, 'group_id': 1, 'decision': 'ACCEPTED'},
            catalog=catalog,
        )['code']
        == 'CONTENT_VERSION_CONFLICT'
    )
    assert (
        complete_batch(
            commands,
            {**decision, 'idempotency_key': str(uuid4()), 'expected_content_version': 3},
            catalog=catalog,
        )['code']
        == 'CONTENT_VERSION_CONFLICT'
    )
    assert get_batch(db, batch_id, catalog=catalog, include_review=True)['data'] == read
    latest = current()
    assert latest['content_version'] == 4 and '后保存的版本。' in latest['markdown_content']
    request(latest)


def test_review_only_on_empty_document_does_not_use_first_draft_permission(workspace, monkeypatch):
    from backend.app.documents.queries import get_current_document

    db, commands, original_catalog = workspace
    catalog = original_catalog.for_formation_profile(OPENAI_PROFILE)
    resources = catalog.for_document_operation('PROPOSE_CHANGES').collaboration
    monkeypatch.setenv('WALLE_ACTIVATED_OPENAI_DOCUMENT_RELEASE_SHA256', resources.release_sha256)
    blank = get_current_document(db, 1, 1, catalog=catalog)['data']
    assert blank['content_version'] == 1 and blank['markdown_content'] == ''
    accepted = accept(
        (db, commands, catalog),
        operation='PROPOSE_CHANGES',
        instruction='仅提出建议',
        target={'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': 1},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None},
    )
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    run_id = accepted['data']['guide_run_id']
    counter, gateway, seen = adapters(
        None,
        make=lambda context: output(
            context,
            response_type='ANALYSIS',
            suggestion_groups=None,
            analysis={
                'conclusion': 'NO_CHANGE',
                'summary': '正文暂无可修订区块。',
                'findings': [],
                'covered_refs': [],
                'unresolved': [],
            },
        ),
    )
    finished = asyncio.run(
        execute_guide_run(
            db,
            {'guide_run_id': run_id},
            process_lock=commands.process_lock,
            catalog=catalog,
            profile=PROFILE,
            counting_counter=counter,
            gateway=gateway,
        )
    )
    assert finished['code'] == 'AI_FINISHED', finished
    run = get_guide_run(db, run_id)['data']
    assert run['operation'] == 'PROPOSE_CHANGES' and run['application_result'] == 'NO_CHANGE', run
    assert run['document_effect'] is None and run['suggestion_batch_id'] is None
    assert [kind for kind, _ in seen] == ['count', 'model']
    assert (
        get_current_document(db, 1, 1, catalog=catalog)['data']['current_revision_id']
        == blank['current_revision_id']
    )
