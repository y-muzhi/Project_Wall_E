"""Isolated capability/tool tests: private delegates only, no provider I/O."""
import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import Counter
from backend.tests.guide.test_v15_execution import Gateway, PROFILE
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.infrastructure.collaboration_observation import CollaborationObservation
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid


def tool():
    path = Path(__file__).resolve().parents[3]/'tools/observe-v15-once.py'
    spec = importlib.util.spec_from_file_location('walle_private_observation_tool', path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def observe(directory, **changes):
    return tool().observe_once(directory, profile=PROFILE, catalog=ResourceCatalog(),
        count_batches=1, chat_calls=1, total_tokens=139264, **changes)


def test_successful_isolated_observation_uses_normal_audit_and_cannot_repeat_slot(tmp_path):
    directory = tmp_path/'slot';counter = Counter(['OK']);gateway = Gateway()
    result = observe(directory, counter=counter, gateway=gateway)
    assert result['result'] == 'AI_FINISHED' and result['admission'] == 'LIVE_VERIFIED', result
    assert result['count_batches_sent'] == result['chat_calls_sent'] == 1
    database = Database(directory/'observation.sqlite')
    with database.transaction() as connection:
        row = connection.execute('SELECT * FROM llm_uses').fetchone()
        snapshot = json.loads(row['request_snapshot_json'])
        assert row['call_status'] == row['validation_status'] == 'SUCCEEDED'
        assert snapshot['admission']['state'] == 'OFFLINE_READY'
        assert snapshot['observation'] == {'count_batches': 1, 'chat_calls': 1, 'input_tokens': 131072,
            'output_tokens': 8192, 'total_tokens': 139264, 'framing_reserve': 1024, 'transport_retries': 0}
        assert 'observation' not in json.loads(snapshot['request']['messages'][1]['content'])
    assert counts(database)['requirement_documents'] == counts(database)['revisions'] == 0
    assert ResourceCatalog().collaboration.release['admission']['state'] == 'OFFLINE_READY'
    with pytest.raises(FileExistsError): observe(directory, counter=counter, gateway=gateway)
    assert len(counter.calls) == len(gateway.calls) == 1


@pytest.mark.parametrize('failure', ['count', 'usage'])
def test_failure_keeps_actual_audit_and_slot_without_retry(tmp_path, failure):
    class BadUsage(Gateway):
        async def send(self, profile, context):
            wire = await super().send(profile, context);raw = wire.raw_response;raw['usage']['total_tokens'] = 9999
            return replace(wire, raw_response_json=json.dumps(raw))
    counter = Counter(['FAIL' if failure == 'count' else 'OK'])
    gateway = BadUsage();directory = tmp_path/'failed'
    result = observe(directory, counter=counter, gateway=gateway)
    assert result['admission'] == ('SUSPENDED' if failure == 'usage' else 'OFFLINE_READY'), result
    assert result['count_batches_sent'] == 1 and result['chat_calls_sent'] == (failure == 'usage')
    database = Database(directory/'observation.sqlite')
    assert counts(database)['revisions'] == counts(database)['requirement_documents'] == 0
    with pytest.raises(FileExistsError): observe(directory, counter=counter, gateway=gateway)
    assert len(counter.calls) == 1 and len(gateway.calls) == (failure == 'usage')


def test_capability_rechecks_real_connection_run_profile_and_single_workspace(workspace, tmp_path):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    database, executor, catalog = workspace
    permit = CollaborationObservation(database, 1, catalog, PROFILE, count_batches=1, chat_calls=1, total_tokens=139264)
    assert permit.check(database, 1, catalog, PROFILE).value['state'] == 'OFFLINE_READY'
    before = counts(database)
    for identity, profile in [(2, PROFILE), (1, ModelProfile('offline-other-profile'))]:
        with pytest.raises(ConfigInvalid): permit.check(database, identity, catalog, profile)
    other = Database(tmp_path/'other.sqlite');other.initialize()
    with pytest.raises(ConfigInvalid): permit.check(other, 1, catalog, PROFILE)
    with other.transaction() as connection:
        with pytest.raises(ConfigInvalid): permit.check_connection(connection, 1, catalog, PROFILE)
    assert counts(database) == before
    from backend.tests.requirements.test_v15_foundation import create
    assert create(executor, title='第二个需求')['code'] == 'CREATED'
    with pytest.raises(ConfigInvalid): permit.check(database, 1, catalog, PROFILE)


def test_budget_debits_before_io_and_cannot_retry_unknown_failure(workspace):
    database, executor, catalog = workspace
    permit = CollaborationObservation(database, 1, catalog, PROFILE, count_batches=1, chat_calls=1, total_tokens=139264)
    class Delegate:
        def __init__(self): self.count_calls = self.chat_calls = 0
        async def count(self, *args): self.count_calls += 1;raise TimeoutError()
        async def send(self, *args): self.chat_calls += 1;raise TimeoutError()
    delegate = Delegate();counter = permit.counter(delegate);gateway = permit.gateway(delegate)
    async def run():
        with pytest.raises(TimeoutError): await counter.count(PROFILE, [])
        with pytest.raises(ConfigInvalid): await counter.count(PROFILE, [])
        with pytest.raises(TimeoutError): await gateway.send(PROFILE, None)
        with pytest.raises(ConfigInvalid): await gateway.send(PROFILE, None)
    asyncio.run(run())
    assert delegate.count_calls == delegate.chat_calls == permit.count_calls == permit.chat_calls == 1


def test_preview_never_reads_credentials_or_calls_providers_and_budgets_are_explicit(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs): raise AssertionError('Preview or invalid command must not access credentials/providers')
    monkeypatch.setattr(ModelProfile, 'from_environment', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway.send', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.tokenization.TokenizationGateway.count', forbidden)
    module = tool()
    assert module.main([]) == 0
    output = capsys.readouterr().out
    assert 'mode=OFFLINE_PREVIEW' in output and 'count_batches_sent=0' in output and 'chat_calls_sent=0' in output
    for argv in [['--execute'], ['--allow-chat-calls', '1'], ['--execute', '--allow-count-batches', '4']]:
        with pytest.raises(SystemExit): module.main(argv)
    for counts_limit in [True, 0, 4]:
        with pytest.raises(ConfigInvalid): module.observe_once(tmp_path/'invalid', profile=PROFILE, catalog=ResourceCatalog(),
            count_batches=counts_limit, chat_calls=1, total_tokens=139264)
    assert not (tmp_path/'invalid').exists()


def test_ordinary_worker_and_command_cannot_install_observation(workspace):
    from backend.app.guide.worker import GuideWorker
    from backend.app.guide.commands import create_guide_run
    from backend.tests.guide.test_v15_acceptance import body
    with pytest.raises(ValueError): GuideWorker(workspace[0], catalog=workspace[2], orchestrator_options={'observation': object()})
    result = create_guide_run(workspace[1], body(observation={'chat_calls': 1}), catalog=workspace[2])
    assert result['code'] == 'INVALID_INPUT'
    assert counts(workspace[0])['guide_runs'] == counts(workspace[0])['llm_uses'] == 0
