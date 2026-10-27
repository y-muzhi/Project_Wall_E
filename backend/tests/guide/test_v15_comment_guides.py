"""Actual comment-owned proposals and frozen source snapshot; no provider I/O."""
import json
from uuid import uuid4
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts, update
from backend.tests.documents.test_v15_documents import workspace, document, metadata
from backend.tests.comments.test_v15_comments import comment
from backend.tests.guide.test_v15_execution import execute, Gateway, output
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_context import compiled
from backend.app.guide.commands import modify_from_comment, retry_guide_run, fail_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.guide.api import guide_router
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.documents.markdown import parse_markdown
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.comments.commands import edit_comment


def source(workspace):
    current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    other = document(workspace, name='独立阅读稿')['data']['document']
    actual = comment(workspace, identity=current['id'])
    assert actual['code'] == 'COMMENT_CREATED', actual
    return current, other, actual['data']


def body(identity=1, **changes):
    return {'comment_id': identity, 'expected_content_version': 1, 'expected_discussion_version': 1, 'idempotency_key': str(uuid4()), **changes}


@pytest.mark.parametrize('mode,scope_type', [('COMMENT', 'SELECTION'), ('BLOCK', 'BLOCK'), ('SECTION', 'SECTION'), ('DOCUMENT', 'DOCUMENT')])
def test_comment_scope_is_derived_from_actual_anchor_and_frozen_without_changing_comment(workspace, mode, scope_type):
    current, other, _ = source(workspace)
    text = parse_markdown(current['markdown_content']).blocks[0].plain_text
    original = comment(workspace, identity=current['id'], anchor_type='SELECTION',
        selection={'selected_text': text, 'prefix_text': '', 'suffix_text': ''})['data']
    accepted = modify_from_comment(workspace[1], body(original['id'], scope_mode=mode), catalog=workspace[2])
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    context = compiled(workspace)
    authorization = context.canonical['authorization']
    assert authorization['target_document_id'] == current['id'] != other['id']
    assert authorization['scope']['scope_type'] == scope_type
    targets = authorization['allowed_targets']
    assert targets and (len(targets) == 1 if mode in ('COMMENT', 'BLOCK') else True)
    assert (targets[0]['selection_range'] is not None) == (mode == 'COMMENT')
    with workspace[0].transaction() as connection:
        basis = json.loads(connection.execute('SELECT execution_basis_json FROM guide_runs').fetchone()[0])
        assert basis['comment_source'] == original
        assert basis['request']['scope'] == authorization['scope']
        assert connection.execute('SELECT anchor_type FROM comments WHERE id=?', (original['id'],)).fetchone()[0] == 'SELECTION'
    assert counts(workspace[0])['llm_uses'] == 0


def test_omitted_mode_keeps_original_idempotent_identity_and_explicit_scope_cannot_reuse_key(workspace):
    from backend.app.infrastructure.idempotency import canonical_input
    _, _, original = source(workspace)
    request = body(original['id'])
    result = modify_from_comment(workspace[1], request, catalog=workspace[2])
    assert result['code'] == 'GUIDE_ACCEPTED'
    with workspace[0].transaction() as connection:
        saved = connection.execute("SELECT business_input_json FROM idempotency_records WHERE capability_id='APP-GUIDE-CMD-C05'").fetchone()[0]
    assert saved == canonical_input({key: value for key, value in request.items() if key != 'idempotency_key'})
    assert modify_from_comment(workspace[1], request, catalog=workspace[2]) == result
    assert modify_from_comment(workspace[1], {**request, 'scope_mode': 'COMMENT'}, catalog=workspace[2])['code'] == 'IDEMPOTENCY_CONFLICT'
    assert modify_from_comment(workspace[1], {**request, 'scope_mode': 'DOCUMENT'}, catalog=workspace[2])['code'] == 'IDEMPOTENCY_CONFLICT'


def test_section_uses_comment_block_identity_with_duplicate_headings_and_never_falls_back_to_document(workspace):
    from backend.tests.documents.test_v15_editing import start, candidate, save, finish
    current = document(workspace)['data']['document']
    draft = start(workspace)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '开场文字。\n\n# 同名标题\n\n重复文字。\n\n# 同名标题\n\n重复文字。\n'))
    assert saved['code'] == 'DRAFT_SAVED', saved
    assert finish(workspace, saved['data'])['code'] == 'DRAFT_COMPLETED'
    first = comment(workspace, expected_content_version=2)['data']
    before = counts(workspace[0])
    assert modify_from_comment(workspace[1], body(first['id'], expected_content_version=2, scope_mode='SECTION'), catalog=workspace[2])['code'] == 'SCOPE_INVALID'
    assert counts(workspace[0]) == before
    last = comment(workspace, expected_content_version=2, block_id=5, anchor_type='SELECTION',
        selection={'selected_text': '重复文字', 'prefix_text': '', 'suffix_text': '。'})['data']
    accepted = modify_from_comment(workspace[1], body(last['id'], expected_content_version=2, scope_mode='SECTION'), catalog=workspace[2])
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    authority = compiled(workspace).canonical['authorization']
    assert authority['scope'] == {'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': 4}}
    assert [target['block_id'] for target in authority['allowed_targets']] == [4, 5]


@pytest.mark.parametrize('state,code', [('RESOLVED', 'STATE_CONFLICT'), ('DELETED', 'STATE_CONFLICT'), ('ORPHANED', 'COMMENT_ORPHANED')])
def test_expanded_modes_keep_comment_lifecycle_guards(workspace, state, code):
    from backend.app.comments.commands import resolve_comment, delete_comment
    _, _, original = source(workspace)
    if state == 'ORPHANED':
        with workspace[0].transaction(write=True) as connection:
            connection.execute("UPDATE comments SET anchor_status='ORPHANED' WHERE id=?", (original['id'],))
    else:
        command = resolve_comment if state == 'RESOLVED' else delete_comment
        assert command(workspace[1], {'comment_id': original['id'], 'idempotency_key': str(uuid4())})['code'] in ('COMMENT_UPDATED', 'COMMENT_DELETED')
    before = counts(workspace[0])
    for mode in ('BLOCK', 'SECTION', 'DOCUMENT'):
        assert modify_from_comment(workspace[1], body(original['id'], scope_mode=mode), catalog=workspace[2])['code'] == code
        assert counts(workspace[0]) == before


@pytest.mark.parametrize('mode,applied', [('COMMENT', False), ('DOCUMENT', True)])
def test_same_outside_selection_patch_requires_explicit_document_authority(workspace, monkeypatch, mode, applied):
    offline_gate(monkeypatch);current, _, _ = source(workspace)
    block = parse_markdown(current['markdown_content']).blocks[0]
    text = block.plain_text
    original = comment(workspace, identity=current['id'], anchor_type='SELECTION',
        selection={'selected_text': text[:1], 'prefix_text': '', 'suffix_text': text[1:]})['data']
    accepted = modify_from_comment(workspace[1], body(original['id'], scope_mode=mode), catalog=workspace[2])
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    patch = {'title': '调整章节', 'explanation': '按评论处理', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': 1}, 'selector_json': None, 'original_content': block.markdown,
        'proposed_markdown': '# 全新的章节名称', 'proposed_data_json': None}
    gateway = Gateway(lambda context: output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch]))
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    actual = get_guide_run(workspace[0], accepted['data']['guide_run_id'])['data']
    assert actual['application_result'] == ('APPLIED' if applied else 'NOT_APPLIED')
    assert (actual['suggestion_batch_id'] is not None) == applied
    with workspace[0].transaction() as connection:
        saved = connection.execute('SELECT markdown_content,content_version FROM requirement_documents WHERE id=?', (current['id'],)).fetchone()
        assert tuple(saved) == (current['markdown_content'], 1)
        assert connection.execute('SELECT status FROM comments WHERE id=?', (original['id'],)).fetchone()[0] == 'OPEN'
    if applied:
        from backend.tests.suggestions.test_v15_batches import decide, complete
        with workspace[0].transaction() as connection:
            suggestion_id = connection.execute('SELECT id FROM suggestions WHERE batch_id=?', (actual['suggestion_batch_id'],)).fetchone()[0]
        before = counts(workspace[0])['llm_uses']
        assert decide(workspace, suggestion_id)['code'] == 'SUGGESTION_DECIDED'
        assert complete(workspace)['code'] == 'BATCH_APPLIED'
        assert counts(workspace[0])['llm_uses'] == before == 1


def test_comment_document_scope_stops_on_full_required_input_over_budget_without_chat(workspace, monkeypatch):
    from backend.tests.guide.test_v15_counting import Counter
    offline_gate(monkeypatch);_, _, original = source(workspace)
    assert modify_from_comment(workspace[1], body(original['id'], scope_mode='DOCUMENT'), catalog=workspace[2])['code'] == 'GUIDE_ACCEPTED'
    counter = Counter(['HIGH', 'HIGH', 'HIGH']);gateway = Gateway()
    result = execute(workspace, gateway, counter=counter)
    assert result['code'] == 'AI_FAILED', result
    assert result['details']['error_code'] == 'CONTEXT_LIMIT_EXCEEDED'
    assert not gateway.calls and 1 <= len(counter.calls) <= 3
    for texts in counter.calls:
        wire = json.loads(texts[1])
        assert wire['current_request']['scope']['scope_type'] == 'DOCUMENT'
        assert all(block['writable'] for block in wire['documents'][0]['blocks'])


def test_comment_acceptance_has_two_versions_actual_owner_and_frozen_original_source(workspace):
    current, other, original = source(workspace)
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    request = body(original['id']);result = modify_from_comment(workspace[1], request, catalog=workspace[2])
    assert result['code'] == 'GUIDE_ACCEPTED', result
    assert result['data']['processing'] == 'MODEL'
    assert modify_from_comment(workspace[1], request, catalog=workspace[2]) == result
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs').fetchone();basis = json.loads(run['execution_basis_json'])
        assert run['operation'] == 'PROPOSE_CHANGES' and run['source_type'] == 'COMMENT' and run['source_id'] == original['id']
        assert run['target_document_id'] == current['id'] != other['id']
        assert basis['comment_source'] == original and basis['request']['instruction'] == original['content']
        assert RequirementRepository(connection).get(1)['status'] == 'CLOSED'
    context = compiled(workspace)
    assert context.input['current_request']['operation'] == 'PROPOSE_CHANGES'
    assert context.input_json.count(original['content']) == 1
    assert context.input['documents'][0]['document_id'] == current['id']
    anchor = next(item for item in context.basis['selected'] if item['ref'] == 'r1:comment_anchor')
    assert anchor['kind'] == 'RUN_MATERIAL' and anchor['source_refs'][0]['guide_run_id'] == result['data']['guide_run_id']
    assert counts(workspace[0])['llm_uses'] == 0


def test_comment_proposal_uses_existing_batch_without_writing_or_resolving_source(workspace, monkeypatch):
    offline_gate(monkeypatch);current, other, original = source(workspace)
    accepted = modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2]);assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    patch = {'title': '落实评论', 'explanation': '调整本条评论的目标', 'impact': '当前目标章节', 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': 1}, 'selector_json': None, 'original_content': parse_markdown(current['markdown_content']).blocks[0].markdown,
        'proposed_markdown': '# 评论建议的新目标', 'proposed_data_json': None}
    result = execute(workspace, Gateway(lambda context: output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])))
    assert result['code'] == 'AI_FINISHED', result
    run = get_guide_run(workspace[0], accepted['data']['guide_run_id']);assert run['code'] == 'READ_OK', run
    assert run['data']['application_result'] == 'APPLIED' and run['data']['suggestion_batch_id'] is not None
    with workspace[0].transaction() as connection:
        batch = connection.execute('SELECT * FROM suggestion_batches').fetchone()
        assert batch['target_document_id'] == current['id'] and batch['source_type'] == 'COMMENT' and batch['source_id'] == original['id']
        assert connection.execute('SELECT status FROM comments WHERE id=?', (original['id'],)).fetchone()[0] == 'OPEN'
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'SUGGESTION_REVIEWING'
        assert all(row['content_version'] == 1 for row in connection.execute("SELECT content_version FROM requirement_documents WHERE document_type='CURRENT'"))


def test_stale_discussion_or_content_and_archived_comment_target_cannot_save_a_run(workspace):
    current, _, original = source(workspace);before = counts(workspace[0])
    for changes, code in [({'expected_discussion_version': 99}, 'DISCUSSION_VERSION_CONFLICT'), ({'expected_content_version': 99}, 'CONTENT_VERSION_CONFLICT')]:
        assert modify_from_comment(workspace[1], body(original['id'], **changes), catalog=workspace[2])['code'] == code
        assert counts(workspace[0]) == before
    assert metadata(workspace, current['id'], 1, {'type': 'ARCHIVE'})['code'] == 'UPDATED'
    assert modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2])['code'] == 'STATE_CONFLICT'


def test_failed_comment_retry_keeps_source_and_rejects_changed_comment_without_another_input(workspace):
    _, _, original = source(workspace);assert modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2])['code'] == 'GUIDE_ACCEPTED'
    assert fail_guide_run(workspace[0], {'guide_run_id': 1, 'error_code': 'CONFIG_INVALID', 'safe_message': '离线准入未完成'}, process_lock=workspace[1].process_lock)['code'] == 'RUN_FAILED'
    changed = edit_comment(workspace[1], {'comment_id': original['id'], 'content': '修改后的评论', 'idempotency_key': str(uuid4())})
    assert changed['code'] == 'COMMENT_UPDATED', changed
    before = counts(workspace[0]);result = retry_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': str(uuid4())}, catalog=workspace[2])
    assert result['code'] == 'SOURCE_INVALID', result
    assert counts(workspace[0]) == before


@pytest.mark.parametrize('mode', [None, 'DOCUMENT'])
def test_comment_route_returns_only_new_receipt_and_requires_both_versions(workspace, mode):
    _, _, original = source(workspace)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(guide_router)
    with TestClient(app) as client:
        path = '/api/v1/comments/'+str(original['id'])+'/guide-runs'
        assert client.post(path, json={'expected_content_version': 1}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
        for invalid_mode in (None, 'SELECTION', 'document', 1):
            assert client.post(path, json={'expected_content_version': 1, 'expected_discussion_version': 1, 'scope_mode': invalid_mode}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
        result = client.post(path, json={'expected_content_version': 1, 'expected_discussion_version': 1, **({} if mode is None else {'scope_mode': mode})}, headers={'Idempotency-Key': str(uuid4())})
        assert result.status_code == 202, result.text
        assert set(result.json()['data']) == {'processing', 'guide_run_id', 'user_message_id'}
        actual = get_guide_run(workspace[0], result.json()['data']['guide_run_id'])['data']
        assert actual['scope']['scope_type'] == ('BLOCK' if mode is None else 'DOCUMENT')


@pytest.mark.parametrize('next_action', ['COMMENT', 'DISCUSS'])
def test_saved_comment_evidence_can_be_reused_by_the_next_actual_http_command(workspace, monkeypatch, next_action):
    from backend.app.suggestions.commands import discard_batch
    from backend.tests.guide.test_v15_progress import delta, evidence
    from backend.app.requirements.source_refs import verify_source_refs
    from backend.app.guide.accepted_context import capture_source
    from backend.app.shared.command_execution import Rejected
    from copy import deepcopy

    offline_gate(monkeypatch);current, _, original = source(workspace)
    accepted = modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2])
    assert accepted['code'] == 'GUIDE_ACCEPTED'
    patch = {'title': '落实评论', 'explanation': '调整本条评论的目标', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': 1}, 'selector_json': None, 'original_content': parse_markdown(current['markdown_content']).blocks[0].markdown,
        'proposed_markdown': '# 评论建议的新目标', 'proposed_data_json': None}
    def returned(context):
        request = context.input['current_request']
        anchor = next(item['ref'] for item in context.basis['selected'] if item['kind'] == 'RUN_MATERIAL')
        progress = delta(evidence_changes=[evidence(source_refs=[request['message_ref'], anchor])],
            processed_user_message_ids=[request['message_id']])
        return output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch], progress_delta=progress)
    gateway = Gateway(returned);result = execute(workspace, gateway)
    assert result['code'] == 'AI_FINISHED', result
    run = get_guide_run(workspace[0], 1)['data'];assert run['progress_result'] == 'APPLIED', run
    assert discard_batch(workspace[1], {'batch_id': run['suggestion_batch_id'], 'idempotency_key': str(uuid4())})['code'] == 'BATCH_DISCARDED'
    source_ref = {'kind': 'RUN_MATERIAL', 'guide_run_id': 1, 'material_ref': 'comment_anchor'}
    with workspace[0].transaction() as connection:
        saved = connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE guide_run_id=1').fetchone()[0]
        selected = next(item for item in json.loads(saved)['context_basis']['selected'] if item['ref'] == 'r1:comment_anchor')
        assert selected['source_refs'] == [source_ref]
        assert verify_source_refs(connection, 1, [source_ref], resources=workspace[2].collaboration) == [source_ref]
        captured = capture_source(connection, 1, source_ref, workspace[2].collaboration)
        assert 'comment_anchor' in json.dumps(captured['value'])
        qualified = {**source_ref, 'material_ref': selected['ref']}
        assert verify_source_refs(connection, 1, [qualified], resources=workspace[2].collaboration) == [qualified]
        for owner, invalid in [(2, source_ref), (1, {**source_ref, 'guide_run_id': 999}),
                (1, {**source_ref, 'material_ref': 'r999:comment_anchor'}), (1, {**source_ref, 'material_ref': 'not_selected'})]:
            with pytest.raises(Rejected, match='SOURCE_INVALID'):
                verify_source_refs(connection, owner, [invalid], resources=workspace[2].collaboration)
            with pytest.raises(Rejected, match='SOURCE_INVALID'):
                capture_source(connection, owner, invalid, workspace[2].collaboration)
        version = RequirementRepository(connection).get(1)['discussion_version']
    if next_action == 'COMMENT':
        snapshot = json.loads(saved)
        for problem in ('missing_selection', 'ambiguous_selection', 'alias_mismatch', 'foreign_basis'):
            damaged = deepcopy(snapshot);basis = damaged['context_basis']
            if problem == 'missing_selection':
                basis['selected'] = [item for item in basis['selected'] if item['ref'] != selected['ref']]
            elif problem == 'ambiguous_selection':
                basis['selected'].append({**selected, 'ref': 'another_saved_ref'})
            elif problem == 'alias_mismatch':
                next(item for item in basis['aliases'] if item['ref'] == selected['ref'])['source_refs'] = [{'kind': 'MESSAGE', 'message_id': 1}]
            else:
                basis['canonical']['requirement']['id'] = 2
            with workspace[0].transaction(write=True) as connection:
                connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE guide_run_id=1', (json.dumps(damaged),))
            try:
                with workspace[0].transaction() as connection:
                    for read in (lambda: verify_source_refs(connection, 1, [source_ref], resources=workspace[2].collaboration),
                            lambda: capture_source(connection, 1, source_ref, workspace[2].collaboration)):
                        with pytest.raises(Rejected, match='SOURCE_INVALID'):
                            read()
            finally:
                with workspace[0].transaction(write=True) as connection:
                    connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE guide_run_id=1', (saved,))
    second = comment(workspace, identity=current['id'], content='继续核对这项。')['data']
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(guide_router)
    with TestClient(app) as client:
        if next_action == 'COMMENT':
            path = '/api/v1/comments/'+str(second['id'])+'/guide-runs'
            payload = {'expected_content_version': 1, 'expected_discussion_version': version}
        else:
            path = '/api/v1/requirements/1/guide-runs'
            payload = {'expected_discussion_version': version, 'operation': 'DISCUSS', 'instruction': '继续讨论。',
                'target': None, 'scope': None, 'source_refs': [], 'proposal_ref': None, 'acknowledge_source_changes': False}
        response = client.post(path, json=payload, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 202, response.text
        next_id = response.json()['data']['guide_run_id']
    context = compiled(workspace, next_id)
    assert any(item['source_ref'] == source_ref for item in context.canonical['run_materials'])
    assert 'comment_anchor' in context.input_json
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE guide_run_id=1').fetchone()[0] == saved
    assert len(gateway.calls) == counts(workspace[0])['llm_uses'] == 1
