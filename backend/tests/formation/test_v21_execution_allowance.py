"""New allowance wraps real C01/C07 and Schema210 receipts, with offline adapters."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from formation_evaluation import manifest_rows
from formation_evaluation_execution import Allowance, append, outcome, protected_facts
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import samples

from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
from backend.app.infrastructure.collaboration_observation import CollaborationObservation
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import operation_time
from backend.tests.guide.test_v15_counting import Counter
from backend.tests.guide.test_v15_execution import Gateway


@pytest.mark.parametrize('transport_fails', [False, True])
def test_real_observation_audit_then_normal_case_stays_offline_and_bounded(
    tmp_path, transport_fails
):
    profile = ModelProfile('offline-only-execution-fixture', 'deepseek-v2')
    catalog = ResourceCatalog().for_formation_profile('deepseek-v2', discussion_routes=False)
    manifest = Path('docs/verification/v2.1/evaluation-inputs-default-2026-11-19-v6.md')
    frozen = manifest_rows(manifest.read_text(encoding='utf-8'))
    report = tmp_path / 'events.md'
    report.touch()

    def event(*values):
        append(report, ' '.join(values) + '\n')

    allowance = Allowance(profile, event, lambda: None)
    source = None
    for sample in (samples()[0], samples()[30]):
        directory = tmp_path / sample.sample_id
        directory.mkdir()
        original, facts = prepare_sample(directory, catalog, sample)
        database = FormationDatabase(directory / 'input.sqlite', formation_release=load_release())
        expected = [row for row in frozen if row[0] == sample.sample_id]
        case = allowance.case(sample, expected, facts)
        case.catalog = catalog
        with ProcessLock.for_database(database.path) as lock:
            before = protected_facts(database)
            store = CollaborationAdmission(database, lock, catalog)
            permit = None
            if source is None:
                permit = CollaborationObservation(
                    database,
                    1,
                    catalog,
                    profile,
                    count_batches=2,
                    chat_calls=1,
                    total_tokens=139264,
                )
            else:
                store.approve_saved_call(source, 1, operation_time(None))
            counter = Counter(['OK'])
            gateway = Gateway(failed=transport_fails)
            result = asyncio.run(
                execute_guide_run(
                    database,
                    {'guide_run_id': 1},
                    process_lock=lock,
                    catalog=catalog,
                    profile=profile,
                    counting_counter=case.counter(counter),
                    gateway=case.gateway(gateway),
                    observation=permit,
                )
            )
            data = outcome(database, case)
            assert data['chat'] == data['count'] == '1'
            assert protected_facts(database) == before
            assert data['request'] == expected[0][9]
            assert len(counter.calls) == len(gateway.calls) == 1
            assert gateway.calls[0].input_json == original.input_json
            if transport_fails:
                assert allowance.stopped
                assert data['status'] == 'TRANSPORT_ERROR'
                assert result['code'] != 'AI_FINISHED'
                break
            assert result['code'] == 'AI_FINISHED', result
            assert data['status'] == 'LIVE_RETURNED', data
            if source is None:
                store.approve_saved_call(database.path, 1, operation_time(None))
                source = database.path
    assert allowance.counts == allowance.chats == (1 if transport_fails else 2)
    assert catalog.collaboration.release['admission']['state'] == 'OFFLINE_READY'
    assert 'CHAT_INTENT' in report.read_text(encoding='utf-8')
