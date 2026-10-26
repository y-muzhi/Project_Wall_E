"""In-process V1.5 worker stages with explicit offline count/Chat fixtures."""
import asyncio
import json
import sqlite3

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts, update
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.commands import cancel_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.guide.collaboration_results import persist_collaboration_result
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.model_gateway import TransportResult
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.requirement_repository import RequirementRepository


PROFILE = ModelProfile('private-fixture-credential-not-in-input-786329', DEFAULT_PROFILE)


def output(context, **changes):
    return {'schema_version': 1, 'response_type': 'DISCUSSION', 'message': '已整理本轮讨论。',
        'basis_ref': context.input['current_request']['basis_ref'], 'progress_delta': None, 'cards': None,
        'document_result': None, 'suggestions': None, 'analysis': None, **changes}


class Gateway:
    def __init__(self, make=output, *, failed=False, hook=None):
        self.make, self.failed, self.hook = make, failed, hook;self.calls = []

    async def send(self, profile, context):
        self.calls.append(context)
        if self.hook:
            self.hook(context)
        value = self.make(context)
        raw = None if value is None else {'object': 'chat.completion', 'model': profile.model_name,
            'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 1200, 'completion_tokens': 100, 'total_tokens': 1300}}
        return TransportResult(not self.failed, 'TEMPORARY_SERVICE' if self.failed else None, self.failed, 500 if self.failed else 200,
            None, 1, None if raw is None else json.dumps(raw), 1200 if raw else None, 100 if raw else None, finish_reason='stop' if raw else None)


def execute(workspace, gateway, counter=None):
    from backend.app.guide import collaboration_execution
    original = collaboration_execution.persist_collaboration_result;failures = []
    def observed(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as error:
            failures.append(repr(error)+" cause="+repr(error.__cause__));raise
    collaboration_execution.persist_collaboration_result = observed
    try:
        result = asyncio.run(execute_guide_run(workspace[0], {'guide_run_id': 1}, process_lock=workspace[1].process_lock,
            catalog=workspace[2], profile=PROFILE, gateway=gateway, counting_counter=counter or Counter(['OK'])))
        return result if not failures else {**result, 'fixture_failure': failures}
    finally:
        collaboration_execution.persist_collaboration_result = original


def delta(context, *, invalid=False, indexed=True):
    return {'topic_changes': [], 'evidence_changes': [] if not indexed else [{'change': 'ADD', 'ref': 'new_e1', 'assertion': '本轮用户描述',
        'origin': 'USER_STATEMENT', 'nature': 'FACT', 'applies_to': 'GLOBAL', 'source_refs': ['missing' if invalid else context.input['current_request']['message_ref']], 'supersedes': [], 'topic_refs': []}],
        'focus_topic_ref': None, 'next_step': None, 'processed_user_message_ids': [context.input['current_request']['message_id']]}


def test_one_discussion_round_persists_exact_basis_count_usage_and_terminal_release(workspace, monkeypatch):
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    gateway = Gateway(lambda context: output(context, progress_delta=delta(context)))
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_FINISHED', result
    assert len(gateway.calls) == 1
    run = get_guide_run(workspace[0], 1)
    assert run['code'] == 'READ_OK', run
    assert run['data']['status'] == 'COMPLETED' and run['data']['progress_result'] == 'APPLIED'
    assert run['data']['application_result'] == 'NOT_REQUESTED' and run['data']['document_effect'] is None
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get(1)
        assert root['document_work_state'] == 'IDLE' and root['discussion_version'] == 3
        assert root['discussion_state_json']['pending_user_message_ids'] == []
        row = connection.execute('SELECT * FROM llm_uses').fetchone();snapshot = json.loads(row['request_snapshot_json'])
        assert snapshot['context_basis']['canonical']['authorization']['operation'] == 'DISCUSS'
        assert snapshot['request']['messages'][1]['content'] == gateway.calls[0].input_json
        assert row['call_no'] == row['attempt_no'] == 1 and row['input_tokens'] == 1200
        assert row['validation_status'] == 'SUCCEEDED'
        assert len(snapshot['counting']['count_attempts']) == 1
    assert counts(workspace[0])['requirement_documents'] == 0


@pytest.mark.parametrize('missing', [('document_result',), ('suggestions',), ('analysis',),
    ('document_result', 'suggestions', 'analysis')])
def test_missing_required_null_roots_remain_readable_but_are_never_invented_or_applied(workspace, monkeypatch, missing):
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    def incomplete(context):
        value = output(context, progress_delta=delta(context))
        for key in missing:del value[key]
        return value
    counter = Counter(['OK']);gateway = Gateway(incomplete)
    assert execute(workspace, gateway, counter)['code'] == 'AI_FINISHED'
    assert len(counter.calls) == len(gateway.calls) == 1
    with workspace[0].transaction() as connection:
        row = connection.execute('SELECT validation_status,parsed_output_json,trusted_output_json FROM llm_uses').fetchone()
        assert row['validation_status'] == 'FAILED' and row['trusted_output_json'] is None
        parsed = json.loads(row['parsed_output_json'])
        assert all(key not in parsed for key in missing)
        root = RequirementRepository(connection).get(1)
        assert root['document_work_state'] == 'IDLE' and root['discussion_version'] == 2
        assert root['discussion_state_json']['pending_user_message_ids']
        message = connection.execute("SELECT content,structured_content_json FROM conversation_messages WHERE role='ASSISTANT'").fetchone()
        displayed = json.loads(message['content'])
        assert displayed == parsed and all(key not in displayed for key in missing)
        assert message['structured_content_json'] is None
        assert connection.execute('SELECT count(*) FROM requirement_documents').fetchone()[0] == 0
    run = get_guide_run(workspace[0], 1)['data']
    assert run['status'] == 'COMPLETED' and run['progress_result'] == 'NOT_REQUESTED'
    assert run['application_result'] == 'NOT_REQUESTED'


@pytest.mark.parametrize('missing_payload', [False, True])
def test_clarification_null_payload_is_required_without_losing_valid_same_round_progress(workspace, monkeypatch, missing_payload):
    from backend.tests.guide.test_v15_cards import group
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    def returned(context):
        cards = group('CLARIFICATION')
        if missing_payload:del cards['action_payload']
        return output(context, cards=cards, progress_delta=delta(context))
    assert execute(workspace, Gateway(returned))['code'] == 'AI_FINISHED'
    with workspace[0].transaction() as connection:
        row = connection.execute('SELECT validation_status,parsed_output_json,trusted_output_json FROM llm_uses').fetchone()
        parsed = json.loads(row['parsed_output_json'])
        assert ('action_payload' not in parsed['cards']) is missing_payload
        assert row['validation_status'] == ('FAILED' if missing_payload else 'SUCCEEDED')
        assert (row['trusted_output_json'] is None) is missing_payload
        message = connection.execute("SELECT structured_content_json FROM conversation_messages WHERE role='ASSISTANT'").fetchone()
        assert (message['structured_content_json'] is None) is missing_payload
        root = RequirementRepository(connection).get(1)
        assert root['document_work_state'] == 'IDLE' and root['discussion_version'] == 3
        assert root['discussion_state_json']['pending_user_message_ids'] == []
    run = get_guide_run(workspace[0], 1)['data']
    assert run['progress_result'] == 'APPLIED' and run['application_result'] == 'NOT_REQUESTED'


@pytest.mark.parametrize('decision', ['HIGH', 'OK'])
def test_summary_count_evidence_rejects_budget_or_missing_raw_without_chat_and_releases_run(workspace, monkeypatch, decision):
    from backend.app.infrastructure.tokenization import restore_measurement, measurement_summary
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    class Summary(Counter):
        async def count(self, profile, texts):
            receipt = await super().count(profile, texts)
            return restore_measurement(measurement_summary(receipt.evidence), texts,
                raw_required=False, expected_model=profile.model_name)
    counter = Summary([decision]);gateway = Gateway()
    execute(workspace, gateway, counter)
    assert len(counter.calls) == 1 and gateway.calls == []
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT status,error_code FROM guide_runs WHERE id=1').fetchone()
        assert run['status'] == 'FAILED'
        assert run['error_code'] == ('CONTEXT_LIMIT_EXCEEDED' if decision == 'HIGH' else 'CONFIG_INVALID')
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        assert connection.execute('SELECT document_work_state FROM requirements').fetchone()[0] == 'IDLE'
    journal = workspace[0].path.with_name(workspace[0].path.name+'.count-audit')
    receipt = json.loads(next(journal.glob('*.finished.json')).read_text(encoding='utf-8'))
    assert receipt['phase'] == ('SUCCEEDED' if decision == 'HIGH' else 'FAILED')
    if decision == 'HIGH':
        assert receipt['raw_omitted_reason'] == 'AUDIT_CAPACITY'
        assert 'response_sha256' in receipt['measurement'] and 'response' not in receipt['measurement']


def test_review_accepts_actual_carried_section_reference_without_writing_document(workspace, monkeypatch):
    offline_gate(monkeypatch)
    created = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    heading = created['block_state_json']['blocks'][3]['block_id']
    assert accept(workspace, operation='REVIEW',
        target={'kind': 'EXISTING', 'document_id': created['id'], 'expected_content_version': 1},
        scope={'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': heading}})['code'] == 'GUIDE_ACCEPTED'
    before = counts(workspace[0])
    def reviewed(context):
        doc = context.input['documents'][0]
        ref = next(item['section_ref'] for item in doc['sections'] if item['heading_block_id'] == heading)
        return output(context, response_type='ANALYSIS', analysis={'conclusion': 'RESULT',
            'summary': '已检查实际携带的章节。', 'covered_refs': [ref], 'findings': [], 'unresolved': []})
    assert execute(workspace, Gateway(reviewed))['code'] == 'AI_FINISHED'
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT validation_status FROM llm_uses').fetchone()[0] == 'SUCCEEDED'
    after = counts(workspace[0])
    assert after['requirement_documents'] == before['requirement_documents']
    assert after['revisions'] == before['revisions']


@pytest.mark.parametrize('invalid_progress', ['unavailable_source', 'message_used_as_evidence_ref'])
def test_generate_directly_creates_one_current_revision_and_audit_without_second_adoption(workspace, monkeypatch, invalid_progress):
    offline_gate(monkeypatch)
    target = {'kind': 'NEW', 'name': '明确新稿', 'document_kind': 'brief', 'template_ref': None}
    assert accept(workspace, operation='GENERATE', target=target)['code'] == 'GUIDE_ACCEPTED'
    def generated(context):
        progress = delta(context, invalid=True)
        if invalid_progress == 'message_used_as_evidence_ref':
            from backend.tests.guide.test_v15_progress import delta as topic_delta
            progress = topic_delta()
            progress['topic_changes'][0]['evidence_refs'] = [context.input['current_request']['message_ref']]
        return output(context, response_type='DOCUMENT_RESULT', document_result={'name': '明确新稿', 'document_kind': 'brief', 'markdown_content': '# 目标\n\n正文已形成。\n', 'change_summary': '形成首稿'}, progress_delta=progress)
    result = execute(workspace, Gateway(generated))
    assert result['code'] == 'AI_FINISHED', result
    run = get_guide_run(workspace[0], 1)['data']
    assert run['application_result'] == 'APPLIED' and run['progress_result'] == 'REJECTED'
    assert run['document_effect']['result'] == 'CREATED' and run['document_effect']['after_content_version'] == 1
    assert run['returned_responses']
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM document_change_audits WHERE guide_run_id=1 AND event_type='CONTENT_COMMITTED'").fetchone()[0] == 1
        root = RequirementRepository(connection).get(1)
        assert root['discussion_state_json']['pending_user_message_ids'] == [2]
    with pytest.raises(Exception):
        persist_collaboration_result(workspace[0], 1, process_lock=workspace[1].process_lock, profile=PROFILE, catalog=workspace[2])
    assert counts(workspace[0])['revisions'] == 1


def test_revise_commits_target_only_and_preserves_independent_business_status(workspace, monkeypatch):
    offline_gate(monkeypatch);current = document(workspace)['data']['document'];other = document(workspace, name='参考稿')['data']['document']
    assert accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 1}, scope={'scope_type': 'DOCUMENT', 'scope_ref': None})['code'] == 'GUIDE_ACCEPTED'
    def revised(context):
        assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
        return output(context, response_type='DOCUMENT_RESULT', document_result={'name': current['name'], 'document_kind': 'brief', 'markdown_content': '只更新目标稿。', 'change_summary': '补齐正文'})
    result = execute(workspace, Gateway(revised))
    assert result['code'] == 'AI_FINISHED', result
    run = get_guide_run(workspace[0], 1)['data']
    assert run['application_result'] == 'APPLIED' and run['document_effect']['document_id'] == current['id']
    with workspace[0].transaction() as connection:
        assert DocumentRepository(connection).get_current(1, current['id'])['content_version'] == 2
        assert DocumentRepository(connection).get_current(1, other['id'])['markdown_content'] == ''
        assert RequirementRepository(connection).get(1)['status'] == 'CLOSED'


def test_invalid_main_result_still_commits_valid_progress_and_preserves_complete_return(workspace, monkeypatch):
    offline_gate(monkeypatch);target = {'kind': 'NEW', 'name': '新稿', 'document_kind': 'brief', 'template_ref': None}
    assert accept(workspace, operation='GENERATE', target=target)['code'] == 'GUIDE_ACCEPTED'
    gateway = Gateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={'bad': 'not a document'}, progress_delta=delta(context)))
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    run = get_guide_run(workspace[0], 1)['data']
    assert run['progress_result'] == 'APPLIED' and run['application_result'] == 'NOT_APPLIED'
    assert counts(workspace[0])['requirement_documents'] == 0
    assert run['returned_responses'] and 'not a document' in run['returned_responses'][0]['content']


def test_bad_json_delivers_raw_once_without_removing_pending(workspace, monkeypatch):
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    gateway = Gateway(lambda _: '```json\n不是可解析协议\n```')
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    assert len(gateway.calls) == 1
    with workspace[0].transaction() as connection:
        assert connection.execute("SELECT content FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0].startswith('```json')
        assert RequirementRepository(connection).get(1)['discussion_state_json']['pending_user_message_ids'] == [2]


def test_retryable_transport_failure_is_one_chat_and_no_automatic_count_or_transport_retry(workspace, monkeypatch):
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    gateway = Gateway(lambda _: None, failed=True);counter = Counter(['OK'])
    result = execute(workspace, gateway, counter)
    assert result['code'] == 'AI_FAILED' and result['details']['error_code'] == 'MODEL_ERROR'
    assert len(gateway.calls) == len(counter.calls) == 1
    assert counts(workspace[0])['llm_uses'] == 1


def test_document_storage_failure_rolls_back_progress_content_assistant_and_revision_but_keeps_call(workspace, monkeypatch):
    from backend.app.infrastructure.revision_repository import RevisionRepository
    offline_gate(monkeypatch);target = {'kind': 'NEW', 'name': '新稿', 'document_kind': 'brief', 'template_ref': None}
    assert accept(workspace, operation='GENERATE', target=target)['code'] == 'GUIDE_ACCEPTED'
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('Injected real storage failure')
    monkeypatch.setattr(RevisionRepository, 'insert_content', fail)
    gateway = Gateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
        'name': '新稿', 'document_kind': 'brief', 'markdown_content': '正文。', 'change_summary': '首稿'}, progress_delta=delta(context)))
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_FAILED' and result['details']['error_code'] == 'STORAGE_UNAVAILABLE', result
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get(1)
        assert root['discussion_version'] == 2 and root['discussion_state_json']['pending_user_message_ids'] == [2]
        assert root['discussion_state_json']['evidence'] == [] and root['document_work_state'] == 'IDLE'
        assert connection.execute('SELECT count(*) FROM requirement_documents').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0] == 0
        row = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert row['raw_response_json'] is not None and row['input_tokens'] == 1200 and row['call_status'] == 'SUCCEEDED'


@pytest.mark.parametrize('outside', [False, True])
def test_local_return_uses_frozen_scope_and_full_or_outside_return_is_not_guessed(workspace, monkeypatch, outside):
    offline_gate(monkeypatch);current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    block = current['block_state_json']['blocks'][3]['block_id']
    assert accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 1},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': block}})['code'] == 'GUIDE_ACCEPTED'
    from backend.app.documents.markdown import parse_markdown
    blocks = parse_markdown(current['markdown_content']).blocks
    changed = '# 修改后的章节\n'
    if outside:
        changed = current['markdown_content'].replace(blocks[0].markdown, '# 越权改动\n')
    gateway = Gateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
        'name': current['name'], 'document_kind': 'brief', 'markdown_content': changed, 'change_summary': '局部修订'}))
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    run = get_guide_run(workspace[0], 1)['data']
    assert run['application_result'] == ('NOT_APPLIED' if outside else 'APPLIED')
    with workspace[0].transaction() as connection:
        actual = DocumentRepository(connection).get_current(1, current['id'])
        assert actual['content_version'] == (1 if outside else 2)
        assert [item['block_id'] for item in json.loads(actual['block_state_json'])['blocks']] == [item['block_id'] for item in current['block_state_json']['blocks']]


def test_cancellation_wins_before_late_transport_business_commit(workspace, monkeypatch):
    from uuid import uuid4
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    def cancel(_):
        assert cancel_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': str(uuid4())})['code'] == 'GUIDE_CANCELLED'
    gateway = Gateway(hook=cancel)
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_STOPPED', result
    with workspace[0].transaction() as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0] == 0
        row = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert row['call_status'] == 'CANCELLED' and row['raw_response_json'] is not None and row['input_tokens'] == 1200
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'IDLE'


def test_explicit_saved_material_reads_only_actual_transmitted_units_and_deduplicates_current_evidence(workspace, monkeypatch):
    from backend.app.guide.commands import create_guide_run
    from backend.tests.guide.test_v15_acceptance import body
    from backend.tests.guide.test_v15_context import compiled
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    assert execute(workspace, Gateway(lambda context: output(context, progress_delta=delta(context))))['code'] == 'AI_FINISHED'
    private = create_guide_run(workspace[1], body(expected_discussion_version=3, instruction='复核保留材料',
        source_refs=[{'kind': 'RUN_MATERIAL', 'guide_run_id': 1, 'material_ref': 'authorization'}]), catalog=workspace[2])
    assert private['code'] == 'SOURCE_INVALID'
    result = create_guide_run(workspace[1], body(expected_discussion_version=3, instruction='复核保留材料',
        source_refs=[{'kind': 'RUN_MATERIAL', 'guide_run_id': 1, 'material_ref': 'm2'}]), catalog=workspace[2])
    assert result['code'] == 'GUIDE_ACCEPTED', result
    context = compiled(workspace, result['data']['guide_run_id'])
    assert context.input_json.count('用户原话') == 1
    assert 'allowed_targets' not in context.input_json and 'authorization' not in context.input_json
    material = next(item for item in context.basis['selected'] if item['ref'] == 'r1:m2')
    assert material['message_ids'] == [2]
    assert material['source_refs'] == [{'kind': 'RUN_MATERIAL', 'guide_run_id': 1, 'material_ref': 'm2'}]
