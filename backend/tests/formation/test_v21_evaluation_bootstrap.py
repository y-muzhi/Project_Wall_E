"""The first frozen EV sample can use the existing bounded isolated observation."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from formation_evaluation import manifest_rows, row_for
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import samples

from backend.app.infrastructure.collaboration_observation import CollaborationObservation
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.model_profile import (
    DEFAULT_PROFILE,
    LONG_OUTPUT_PROFILE,
    ModelProfile,
)
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog


@pytest.mark.parametrize(
    'profile_id,manifest_name',
    (
        (DEFAULT_PROFILE, 'evaluation-inputs-default-2026-11-19-v6.md'),
        (LONG_OUTPUT_PROFILE, 'evaluation-inputs-long-2026-11-19-v6.md'),
    ),
)
def test_first_frozen_sample_checks_observation_without_count_chat_or_live_admission(
    tmp_path, profile_id, manifest_name
):
    profile = ModelProfile('explicit-offline-observation-check', profile_id)
    catalog = ResourceCatalog().for_formation_profile(profile.profile_id)
    first = samples()[0]
    context, facts = prepare_sample(tmp_path, catalog, first)
    frozen = manifest_rows(
        (ROOT / 'docs/verification/v2.1' / manifest_name).read_text(encoding='utf-8')
    )
    assert row_for(first, 'full', context, facts, profile) == frozen[0]
    database = FormationDatabase(tmp_path / 'input.sqlite', formation_release=load_release())
    with ProcessLock.for_database(database.path) as lock:
        capability = CollaborationObservation(
            database,
            1,
            catalog,
            profile,
            count_batches=2,
            chat_calls=1,
            total_tokens=catalog.collaboration.counting['total_limit'],
        )
        capability.check(database, 1, catalog, profile)
        assert capability.count_calls == capability.chat_calls == 0
        with pytest.raises(ConfigInvalid):
            capability.check(database, 2, catalog, profile)
        with pytest.raises(ConfigInvalid):
            catalog.collaboration.require_live(profile.snapshot)
        with database.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
            assert connection.execute('SELECT status FROM guide_runs').fetchone()[0] == 'RUNNING'
        lock.assert_owned()


@pytest.mark.parametrize(
    'defect',
    (
        'unbound_target',
        'writing_authority',
        'foreign_authorization',
        'wrong_content_basis',
        'missing_authorization',
        'boolean_content_basis',
        'float_content_basis',
        'float_document_basis',
        'existing_body',
    ),
)
def test_formation_observation_cannot_widen_read_only_bootstrap(tmp_path, defect):
    import json

    profile = ModelProfile('explicit-offline-observation-negative', DEFAULT_PROFILE)
    catalog = ResourceCatalog().for_formation_profile(profile.profile_id)
    sample = samples()[30] if defect == 'existing_body' else samples()[0]
    prepare_sample(tmp_path, catalog, sample)
    database = FormationDatabase(tmp_path / 'input.sqlite', formation_release=load_release())
    with ProcessLock.for_database(database.path):
        capability = CollaborationObservation(
            database,
            1,
            catalog,
            profile,
            count_batches=2,
            chat_calls=1,
            total_tokens=catalog.collaboration.counting['total_limit'],
        )
        if defect == 'existing_body':
            with pytest.raises(ConfigInvalid):
                capability.check(database, 1, catalog, profile)
        else:
            # Accepted run fields are immutable in SQLite. Inject only the
            # queried boundary value; never drop a trigger or rewrite a run.
            with database.transaction() as connection:
                original = dict(
                    connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone()
                )
                changed = dict(original)
                if defect == 'unbound_target':
                    changed['target_document_id'] = None
                else:
                    accepted = json.loads(original['execution_basis_json'])
                    if defect == 'writing_authority':
                        accepted['authorization']['allowed_targets'] = [{'document_id': 42}]
                    elif defect == 'foreign_authorization':
                        accepted['authorization']['target_document_id'] = 99
                    elif defect == 'wrong_content_basis':
                        accepted['authorization']['expected_content_version'] = 2
                    elif defect == 'boolean_content_basis':
                        accepted['authorization']['expected_content_version'] = True
                    elif defect == 'float_content_basis':
                        accepted['authorization']['expected_content_version'] = 1.0
                    elif defect == 'float_document_basis':
                        accepted['authorization']['target_document_id'] = 42.0
                    elif defect == 'missing_authorization':
                        accepted.pop('authorization')
                    changed['execution_basis_json'] = json.dumps(accepted)

                class QueryBoundary:
                    def execute(self, sql, parameters=()):
                        if sql == 'SELECT * FROM guide_runs WHERE id=?':
                            from types import SimpleNamespace

                            return SimpleNamespace(fetchone=lambda: changed)
                        return connection.execute(sql, parameters)

                with pytest.raises(ConfigInvalid):
                    capability.check_connection(QueryBoundary(), 1, catalog, profile)
                assert (
                    dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone())
                    == original
                )
        assert capability.count_calls == capability.chat_calls == 0
        with database.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_observation_c07_then_saved_schema210_evidence_supports_next_isolated_case(tmp_path):
    import asyncio
    import json

    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
    from backend.app.shared.command_execution import operation_time
    from backend.tests.guide.test_v15_counting import Counter
    from backend.tests.guide.test_v15_execution import Gateway

    profile = ModelProfile('explicit-offline-two-case-bootstrap', DEFAULT_PROFILE)
    catalog = ResourceCatalog().for_formation_profile(profile.profile_id)
    first_directory = tmp_path / 'first'
    first_directory.mkdir()
    first_context, _ = prepare_sample(first_directory, catalog, samples()[0])
    first = FormationDatabase(first_directory / 'input.sqlite', formation_release=load_release())
    counter, gateway = Counter(['OK']), Gateway()
    with ProcessLock.for_database(first.path) as first_lock:
        permit = CollaborationObservation(
            first,
            1,
            catalog,
            profile,
            count_batches=2,
            chat_calls=1,
            total_tokens=catalog.collaboration.counting['total_limit'],
        )
        outcome = asyncio.run(
            execute_guide_run(
                first,
                {'guide_run_id': 1},
                process_lock=first_lock,
                catalog=catalog,
                profile=profile,
                gateway=gateway,
                counting_counter=counter,
                observation=permit,
            )
        )
        assert outcome['code'] == 'AI_FINISHED', outcome
        assert (
            permit.count_calls == permit.chat_calls == len(gateway.calls) == len(counter.calls) == 1
        )
        with first.transaction() as connection:
            original = tuple(
                connection.execute(
                    'SELECT request_snapshot_json,raw_response_json FROM llm_uses WHERE id=1'
                ).fetchone()
            )
            snapshot = json.loads(original[0])
            assert snapshot['request']['messages'][1]['content'] == first_context.input_json
            assert snapshot['observation']['chat_calls'] == 1
            assert connection.execute(
                'SELECT content_version,markdown_content FROM requirement_documents WHERE id=42'
            ).fetchone()[:] == (1, '')
        # This is a Mock-only local test admission, automatically removed with tmp_path.
        # It does not modify the frozen release or permit a production provider call.
        proof = CollaborationAdmission(first, first_lock, catalog).approve_saved_call(
            first.path.resolve(), 1, operation_time(None)
        )
        assert proof['state'] == 'LIVE_VERIFIED'

        second_directory = tmp_path / 'second'
        second_directory.mkdir()
        second_context, _ = prepare_sample(second_directory, catalog, samples()[30])
        second = FormationDatabase(
            second_directory / 'input.sqlite', formation_release=load_release()
        )
        with ProcessLock.for_database(second.path) as second_lock:
            imported = CollaborationAdmission(second, second_lock, catalog).approve_saved_call(
                first.path.resolve(), 1, operation_time(None)
            )
            assert imported['state'] == 'LIVE_VERIFIED'
            next_counter, next_gateway = Counter(['OK']), Gateway()
            continued = asyncio.run(
                execute_guide_run(
                    second,
                    {'guide_run_id': 1},
                    process_lock=second_lock,
                    catalog=catalog,
                    profile=profile,
                    gateway=next_gateway,
                    counting_counter=next_counter,
                )
            )
            assert continued['code'] == 'AI_FINISHED', continued
            assert len(next_counter.calls) == len(next_gateway.calls) == 1
            with second.transaction() as connection:
                row = connection.execute(
                    'SELECT request_snapshot_json FROM llm_uses WHERE id=1'
                ).fetchone()
                actual = json.loads(row[0])
                assert actual['request']['messages'][1]['content'] == second_context.input_json
                assert 'observation' not in actual
                assert (
                    connection.execute(
                        'SELECT content_version FROM requirement_documents WHERE id=42'
                    ).fetchone()[0]
                    == 4
                )
        with first.transaction() as connection:
            assert (
                tuple(
                    connection.execute(
                        'SELECT request_snapshot_json,raw_response_json FROM llm_uses WHERE id=1'
                    ).fetchone()
                )
                == original
            )
    assert catalog.collaboration.release['admission']['state'] == 'OFFLINE_READY'
    with pytest.raises(ConfigInvalid):
        catalog.collaboration.require_live(profile.snapshot)
