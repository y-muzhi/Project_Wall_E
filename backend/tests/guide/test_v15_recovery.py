"""Recover durable return once; unknown sends never become automatic Chat."""
import asyncio
from datetime import datetime, timedelta
import json

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import Gateway, output, PROFILE
from backend.tests.guide.test_v15_counting import offline_gate, Counter
from backend.app.guide.collaboration_context import read_canonical
from backend.app.guide.collaboration_counting import compile_counted
from backend.app.guide.commands import recover_runs
from backend.app.guide.orchestrator import _transport, _parse
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.requirement_repository import RequirementRepository


def time_after(text, seconds=1): return datetime.fromisoformat(text[:-1]+'+00:00')+timedelta(seconds=seconds)
def timestamp(value): return value.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def prepare(workspace, monkeypatch, *, returned=True, parsed=True):
    offline_gate(monkeypatch)
    result = accept(workspace, operation='GENERATE', target={'kind': 'NEW', 'name': '恢复后新稿', 'document_kind': 'brief', 'template_ref': None})
    assert result['code'] == 'GUIDE_ACCEPTED', result
    with workspace[0].transaction() as connection:
        canonical = read_canonical(connection, 1, workspace[2]);at = time_after(connection.execute('SELECT updated_at FROM guide_runs').fetchone()[0])
    context = asyncio.run(compile_counted(canonical, workspace[2], PROFILE, counter=Counter(['OK'])))
    with workspace[0].transaction(write=True) as connection:
        AuditRepository(connection).prepare_collaboration(1, PROFILE, context, timestamp(at), catalog=workspace[2])
    if returned:
        gateway = Gateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
            'name': '恢复后新稿', 'document_kind': 'brief', 'markdown_content': '# 目标\n\n从真实保存响应恢复。', 'change_summary': '恢复已返回的新稿'}))
        wire = asyncio.run(gateway.send(PROFILE, context))
        _transport(workspace[0], 1, wire, PROFILE, lambda: at+timedelta(seconds=1))
        if parsed: _parse(workspace[0], 1, lambda: at+timedelta(seconds=2))
    return at


def recover(workspace, at, *, reason='STARTUP', live=frozenset()):
    return recover_runs(workspace[0], {'recovery_reason': reason, 'live_run_ids': live, 'operation_time': timestamp(at)}, process_lock=workspace[1].process_lock, catalog=workspace[2])


def test_saved_return_completes_one_real_document_once_with_no_dispatch_count_or_credentials(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch)
    def forbidden(*args, **kwargs): raise AssertionError('Recovery has no external action or credential dependency')
    monkeypatch.setattr(ModelProfile, 'from_environment', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway.send', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.tokenization.TokenizationGateway.count', forbidden)
    result = recover(workspace, at+timedelta(seconds=3));assert result['code'] == 'RECOVERED', result
    assert result['data']['recovered_run_ids'] == [1]
    before = counts(workspace[0]);assert before['requirement_documents'] == 1 and before['revisions'] == 1 and before['llm_uses'] == 1
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT status FROM guide_runs').fetchone()[0] == 'COMPLETED'
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'IDLE'
    assert recover(workspace, at+timedelta(seconds=4))['code'] == 'RECOVERY_NO_CHANGE'
    assert counts(workspace[0]) == before


def test_unknown_external_request_becomes_interrupted_without_document_and_keeps_pending_original(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch, returned=False)
    result = recover(workspace, at+timedelta(seconds=3));assert result['code'] == 'RECOVERED', result
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs').fetchone();row = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert run['status'] == 'FAILED' and run['error_code'] == 'INTERRUPTED'
        assert row['input_tokens'] is None and row['raw_response_json'] is None
        root = RequirementRepository(connection).get(1)
        assert root['document_work_state'] == 'IDLE' and root['discussion_state_json']['pending_user_message_ids'] == [run['trigger_message_id']]
    assert counts(workspace[0])['requirement_documents'] == 0


def test_unprovable_saved_basis_never_replays_a_content_commit(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch)
    with workspace[0].transaction(write=True) as connection:
        snapshot = json.loads(connection.execute('SELECT request_snapshot_json FROM llm_uses').fetchone()[0])
        snapshot['context_basis']['wire_sha256'] = '0'*64
        connection.execute('UPDATE llm_uses SET request_snapshot_json=?', (json.dumps(snapshot),))
    result = recover(workspace, at+timedelta(seconds=3));assert result['code'] == 'RECOVERED', result
    assert counts(workspace[0])['requirement_documents'] == 0
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT error_code FROM guide_runs').fetchone()[0] == 'INTERRUPTED'
        assert connection.execute('SELECT raw_response_json FROM llm_uses').fetchone()[0] is not None


def test_live_startup_run_and_fresh_progress_are_preserved_then_timeout_releases_without_resend(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch, returned=False)
    assert recover(workspace, at+timedelta(seconds=3), live={1})['code'] == 'RECOVERY_NO_CHANGE'
    assert recover(workspace, at+timedelta(minutes=14), reason='NO_PROGRESS', live={1})['code'] == 'RECOVERY_NO_CHANGE'
    result = recover(workspace, at+timedelta(minutes=15), reason='NO_PROGRESS', live={1});assert result['code'] == 'RECOVERED', result
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT error_code FROM guide_runs').fetchone()[0] == 'EXECUTION_TIMEOUT'
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'IDLE'
    assert counts(workspace[0])['llm_uses'] == 1


def test_durable_unparsed_response_is_parsed_and_committed_in_one_recovery_transaction(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch, parsed=False)
    result = recover(workspace, at+timedelta(minutes=16), reason='NO_PROGRESS');assert result['code'] == 'RECOVERED', result
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT parse_status FROM llm_uses').fetchone()[0] == 'SUCCEEDED'
        assert connection.execute('SELECT status FROM guide_runs').fetchone()[0] == 'COMPLETED'
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 1


def test_unparsed_recovery_storage_failure_rolls_back_parse_and_content_then_original_return_can_complete(workspace, monkeypatch):
    import sqlite3
    from backend.app.infrastructure.revision_repository import RevisionRepository
    at = prepare(workspace, monkeypatch, parsed=False)
    before = counts(workspace[0]);original = RevisionRepository.insert_content
    def unavailable(*args, **kwargs): raise sqlite3.OperationalError('private recovery storage failure')
    monkeypatch.setattr(RevisionRepository, 'insert_content', unavailable)
    result = recover(workspace, at+timedelta(seconds=3));assert result['code'] == 'STORAGE_UNAVAILABLE', result
    assert counts(workspace[0]) == before
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT parse_status FROM llm_uses').fetchone()[0] == 'NOT_STARTED'
        assert connection.execute('SELECT raw_response_json FROM llm_uses').fetchone()[0] is not None
        assert connection.execute('SELECT status FROM guide_runs').fetchone()[0] == 'RUNNING'
    monkeypatch.setattr(RevisionRepository, 'insert_content', original)
    assert recover(workspace, at+timedelta(seconds=4))['code'] == 'RECOVERED'
    assert counts(workspace[0])['llm_uses'] == 1 and counts(workspace[0])['revisions'] == 1
