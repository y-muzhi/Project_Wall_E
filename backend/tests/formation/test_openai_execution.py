"""OpenAI native HTTP -> original C01/C07 -> normal audit, strictly offline."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from formation_evaluation_execution import protected_facts
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import Sample, samples

from backend.app.guide.collaboration_counting import restore_counted
from backend.app.guide.model_calls import get_model_call, list_model_calls
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.collaboration_observation import CollaborationObservation
from backend.app.infrastructure.collaboration_provider import admission_for
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_counting import OpenAIInputCounter
from backend.app.infrastructure.openai_protocol import COUNT_ENDPOINT, ENDPOINT, MODEL
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import operation_time
from backend.tests.formation.test_v21_live_fix_examples import task_output

PROFILE = ModelProfile('offline-openai-c07-only', OPENAI_PROFILE)


def adapters(sample, *, defect=None, make=None, output_tokens=100, input_tokens=2000):
    seen = []

    def count(req):
        assert str(req.url) == COUNT_ENDPOINT
        body = json.loads(req.content)
        assert 'input' in body and body['text']['format']['strict'] is True
        seen.append(('count', body))
        return httpx.Response(
            200,
            json={'object': 'response.input_tokens', 'input_tokens': input_tokens},
            headers={'x-request-id': 'offline_count'},
        )

    def chat(req):
        assert str(req.url) == ENDPOINT
        body = json.loads(req.content)
        seen.append(('model', body))
        assert 'messages' not in body and body['store'] is False
        assert req.extensions['timeout']['read'] == (
            1800 if body['max_output_tokens'] == 100_000 else 180
        )
        from types import SimpleNamespace

        ctx = SimpleNamespace(input=json.loads(body['input'][1]['content']))
        value = task_output(sample, ctx) if make is None else make(ctx)
        if defect == 'wrong-block':
            value['progress_delta']['formation_delta']['changes'][0]['document_refs'] = ['d42v4']
        if defect == 'protocol':
            del value['basis_ref']
        raw = {
            'object': 'response',
            'id': 'resp_offline_c07',
            'model': MODEL,
            'status': 'completed',
            'output': [
                {
                    'type': 'message',
                    'role': 'assistant',
                    'status': 'completed',
                    'content': [
                        {
                            'type': 'output_text',
                            'text': json.dumps(value, ensure_ascii=False),
                            'annotations': [],
                        }
                    ],
                }
            ],
            'usage': {
                'input_tokens': input_tokens + (1 if defect == 'usage' else 0),
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + (1 if defect == 'usage' else 0) + output_tokens,
                'input_tokens_details': {'cached_tokens': 0},
                'output_tokens_details': {'reasoning_tokens': 20},
            },
        }
        if defect == 'refusal':
            raw['output'][0]['content'] = [
                {'type': 'refusal', 'refusal': 'offline explicit refusal'}
            ]
        if defect == 'incomplete':
            raw['status'] = 'incomplete'
            raw['incomplete_details'] = {'reason': 'max_output_tokens'}
            raw['output'][0]['status'] = 'incomplete'
        if defect == 'http':
            return httpx.Response(
                500, json={'error': {'code': 'server_error', 'message': 'offline'}}
            )
        return httpx.Response(200, json=raw)

    return (
        OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(count)),
        ModelGateway(transport_factory=lambda: httpx.MockTransport(chat)),
        seen,
    )


@pytest.fixture(scope='module')
def technical_source(tmp_path_factory):
    path = tmp_path_factory.mktemp('oa-source')
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    sample = samples()[0]
    prepare_sample(path, catalog, sample)
    db = FormationDatabase(path / 'input.sqlite', formation_release=load_release())
    counter, gateway, seen = adapters(sample)
    with ProcessLock.for_database(db.path) as lock:
        permit = CollaborationObservation(
            db, 1, catalog, PROFILE, count_batches=2, chat_calls=1, total_tokens=139264
        )
        result = asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': 1},
                process_lock=lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=counter,
                gateway=gateway,
                observation=permit,
            )
        )
        assert result['code'] == 'AI_FINISHED', result
        with db.transaction() as connection:
            row = dict(connection.execute('SELECT * FROM llm_uses').fetchone())
            assert (
                row['provider'] == 'openai'
                and row['parse_status'] == 'SUCCEEDED'
                and row['validation_status'] == 'SUCCEEDED'
            ), row['validation_error']
            snapshot = json.loads(row['request_snapshot_json'])
            restored = restore_counted(snapshot, catalog, PROFILE)
            assert PROFILE.request(restored) == snapshot['request']
        proof = admission_for(db, lock, catalog).approve_saved_call(
            db.path.resolve(), 1, operation_time(None)
        )
        assert proof['state'] == 'LIVE_VERIFIED'
        assert proof['request_input_tokens'] == 2000 and proof['count_gap'] == 0
    assert [kind for kind, _ in seen] == ['count', 'model']
    return db.path.resolve()


@pytest.mark.parametrize('body', ('blank', 'fbase'))
@pytest.mark.parametrize('task', ('discuss', 'write', 'path', 'associate', 'assess'))
def test_native_openai_output_uses_existing_five_c07_tasks(tmp_path, technical_source, body, task):
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    sample = Sample(body, 3, task)
    original, _ = prepare_sample(tmp_path, catalog, sample)
    db = FormationDatabase(tmp_path / 'input.sqlite', formation_release=load_release())
    counter, gateway, seen = adapters(sample)
    with ProcessLock.for_database(db.path) as lock:
        before = protected_facts(db)
        admission_for(db, lock, catalog).approve_saved_call(
            technical_source, 1, operation_time(None)
        )
        result = asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': 1},
                process_lock=lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=counter,
                gateway=gateway,
            )
        )
        assert result['code'] == 'AI_FINISHED', result
        assert protected_facts(db) == before
        with db.transaction() as connection:
            row = dict(connection.execute('SELECT * FROM llm_uses').fetchone())
            assert row['provider'] == 'openai'
            assert row['validation_status'] == 'SUCCEEDED', row['validation_error']
            snapshot = json.loads(row['request_snapshot_json'])
            assert snapshot['request']['input'][1]['content'] == original.input_json
            assert json.loads(row['raw_response_json'])['object'] == 'response'
        detail = get_model_call(db, 1, catalog=catalog)
        assert detail['code'] == 'READ_OK', detail
        assert detail['data']['preflight']['counts'] == [2000]
        assert detail['data']['preflight']['budget']['counting'] == 'openai_exact_request_v1'
        assert (
            json.loads(detail['data']['raw_request_json'])['input'][1]['content']
            == original.input_json
        )
        calls = list_model_calls(db, 1, include_input_limit=True, catalog=catalog)
        assert calls['code'] == 'READ_OK'
        assert calls['data']['items'][0]['user_message_id'] is not None
        assert calls['data']['items'][0]['total_tokens'] == 2100
        assert (
            calls['data']['items'][0]['input_token_limit']
            == detail['data']['preflight']['budget']['input_tokens']
            == 131072
        )
    assert [kind for kind, _ in seen] == ['count', 'model']


@pytest.mark.parametrize(
    'defect', ('wrong-block', 'protocol', 'usage', 'refusal', 'incomplete', 'http')
)
def test_native_failure_never_changes_protected_business_content(
    tmp_path, technical_source, defect
):
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    sample = Sample('fbase', 3, 'assess')
    prepare_sample(tmp_path, catalog, sample)
    db = FormationDatabase(tmp_path / 'input.sqlite', formation_release=load_release())
    counter, gateway, seen = adapters(sample, defect=defect)
    with ProcessLock.for_database(db.path) as lock:
        before = protected_facts(db)
        admission_for(db, lock, catalog).approve_saved_call(
            technical_source, 1, operation_time(None)
        )
        result = asyncio.run(
            execute_guide_run(
                db,
                {'guide_run_id': 1},
                process_lock=lock,
                catalog=catalog,
                profile=PROFILE,
                counting_counter=counter,
                gateway=gateway,
            )
        )
        assert protected_facts(db) == before
        with db.transaction() as connection:
            row = dict(connection.execute('SELECT * FROM llm_uses').fetchone())
            assert row['validation_status'] != 'SUCCEEDED'
            assert row['provider'] == 'openai'
        assert result['code'] in ('AI_FINISHED', 'AI_FAILED')
    assert [kind for kind, _ in seen] == ['count', 'model']
