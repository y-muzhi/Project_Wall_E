"""Private offline admission evidence only; never promote a real release here."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_recovery import prepare, timestamp
from backend.tests.guide.test_v15_execution import Gateway, PROFILE
from backend.app.guide.collaboration_counting import restore_counted
from backend.app.guide.orchestrator import _transport
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.collaboration_resources import CollaborationResources

REAL_ADMISSION = CollaborationResources.require_live


def ledger(workspace):
    return CollaborationAdmission(workspace[0], workspace[1].process_lock, workspace[2])


def test_saved_observation_import_rechecks_original_bytes_counts_and_usage_without_provider_or_database_writes(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch);store = ledger(workspace);before = counts(workspace[0])
    assert store.current(PROFILE.snapshot).value['state'] == 'OFFLINE_READY'
    def forbidden(*args, **kwargs): raise AssertionError('Admission import never calls a provider or reads credentials')
    monkeypatch.setattr('backend.app.infrastructure.model_profile.ModelProfile.from_environment', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway.send', forbidden)
    value = store.approve_saved_call(workspace[0].path, 1, timestamp(at+timedelta(seconds=3)))
    assert value['state'] == 'LIVE_VERIFIED' and value['actual_input_tokens'] == 1200 and value['framing_gap'] == 200
    assert ledger(workspace).current(PROFILE.snapshot).value == value
    assert store.approve_saved_call(workspace[0].path, 1, timestamp(at+timedelta(seconds=4))) == value
    assert counts(workspace[0]) == before and workspace[2].collaboration.release['admission']['state'] == 'OFFLINE_READY'


def test_durable_actual_usage_anomaly_suspends_even_without_config_and_cannot_be_reapproved_for_same_release(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch, returned=False)
    with workspace[0].transaction() as connection:
        snapshot = json.loads(connection.execute('SELECT request_snapshot_json FROM llm_uses').fetchone()[0])
    context = restore_counted(snapshot, workspace[2], PROFILE)
    wire = asyncio.run(Gateway().send(PROFILE, context));raw = wire.raw_response;raw['usage']['total_tokens'] = 9999
    _transport(workspace[0], 1, replace(wire, raw_response_json=json.dumps(raw)), PROFILE, lambda: at+timedelta(seconds=1))
    store = ledger(workspace)
    assert store.current(PROFILE.snapshot).value['state'] == ledger(workspace).current(PROFILE.snapshot).value['state'] == 'SUSPENDED'
    assert not store.path.exists()
    with pytest.raises(ConfigInvalid): store.approve_saved_call(workspace[0].path, 1, timestamp(at+timedelta(seconds=3)))
    assert counts(workspace[0])['llm_uses'] == 1


def test_modified_config_never_substitutes_for_original_evidence(workspace, monkeypatch):
    at = prepare(workspace, monkeypatch);store = ledger(workspace)
    store.approve_saved_call(workspace[0].path, 1, timestamp(at+timedelta(seconds=3)))
    record = json.loads(store.path.read_text(encoding='utf-8'));record['admission']['chat_request_sha256'] = '0'*64
    store.path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ConfigInvalid): store.current(PROFILE.snapshot)


def test_actual_dispatch_uses_imported_evidence_then_durable_suspension_blocks_before_new_count_or_chat(workspace, monkeypatch):
    from backend.tests.guide.test_v15_acceptance import accept
    from backend.tests.guide.test_v15_execution import execute
    from backend.tests.guide.test_v15_counting import offline_gate, Counter
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.shared.command_execution import operation_time
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    assert execute(workspace, Gateway())['code'] == 'AI_FINISHED'
    store = ledger(workspace);store.approve_saved_call(workspace[0].path, 1, operation_time(None))
    monkeypatch.setattr(CollaborationResources, 'require_live', REAL_ADMISSION)
    class BadUsage(Gateway):
        async def send(self, profile, context):
            result = await super().send(profile, context);raw = result.raw_response;raw['usage']['total_tokens'] = 9999
            return replace(result, raw_response_json=json.dumps(raw))
    assert accept(workspace, expected_discussion_version=2)['code'] == 'GUIDE_ACCEPTED'
    gateway = BadUsage();counter = Counter(['OK'])
    result = asyncio.run(execute_guide_run(workspace[0], {'guide_run_id': 2}, process_lock=workspace[1].process_lock,
        catalog=workspace[2], profile=PROFILE, gateway=gateway, counting_counter=counter))
    assert result['code'] == 'AI_FINISHED' and len(gateway.calls) == len(counter.calls) == 1
    with workspace[0].transaction() as connection:
        assert json.loads(connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE guide_run_id=2').fetchone()[0])['admission']['state'] == 'LIVE_VERIFIED'
    assert ledger(workspace).current(PROFILE.snapshot).value['state'] == 'SUSPENDED'
    assert accept(workspace, expected_discussion_version=3)['code'] == 'GUIDE_ACCEPTED'
    never_gateway = Gateway();never_counter = Counter([])
    result = asyncio.run(execute_guide_run(workspace[0], {'guide_run_id': 3}, process_lock=workspace[1].process_lock,
        catalog=workspace[2], profile=PROFILE, gateway=never_gateway, counting_counter=never_counter))
    assert result['code'] == 'AI_FAILED' and result['details']['error_code'] == 'CONFIG_INVALID'
    assert not never_gateway.calls and not never_counter.calls and counts(workspace[0])['llm_uses'] == 2
