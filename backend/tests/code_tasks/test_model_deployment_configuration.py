"""Explicit fake credentials only; no normal .env, provider or token-count call."""

import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.code_tasks import local_deployment as deployment
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.model_profile import (
    BASE_URL,
    DEFAULT_PROFILE,
    DEEPSEEK_MODEL_ID,
    ModelProfile,
)
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.schema_v20_release import load_release
from backend.app.shared.json_canonical import canonical_input
from backend.tests.code_tasks import test_local_deployment as base
from backend.tests.code_tasks import test_task_deployment_configuration as task

tmp_path = base.tmp_path
local_source = base.local_source
runtime_bundle = task.runtime_bundle
task_source = task.task_source
CREDENTIAL = 'fixture-only-model-credential'


def environment():
    return {
        'WALLE_MODEL_API_KEY': CREDENTIAL,
        'WALLE_MODEL_PROFILE': DEFAULT_PROFILE,
        'WALLE_MODEL_ID': DEEPSEEK_MODEL_ID,
        'WALLE_MODEL_BASE_URL': BASE_URL,
    }


def group():
    profile = ModelProfile.from_environment(environment())
    return {
        'admissions': [
            {
                'evidence_ref': 'fixture-only-admission',
                'model_snapshot_ref': 'fixture-only-snapshot',
                'billing_scope_ref': 'fixture-only-billing',
                'price_sha256': 'd' * 64,
                'model_profile_ref': profile.profile_id,
                'model_snapshot_sha256': hashlib.sha256(
                    canonical_input(profile.snapshot).encode('utf-8')
                ).hexdigest(),
                'usage': {
                    'version': 'fixture-only-sse',
                    'final_source': 'USAGE_TRAILER',
                    'required_dimensions': ['input_tokens', 'output_tokens', 'cached_tokens'],
                    'cache_dimensions': ['cached_tokens'],
                    'cumulative_semantics': 'PER_DIMENSION_NONDECREASING',
                },
                'max_duration_seconds': 30,
                'input_cap': 1000,
                'context_cap': 2000,
                'output_cap': 100,
                'chunk_usage': False,
                'optional_fields': ['top_p'],
            }
        ]
    }


def document(root):
    value = task.task_document(root)
    value.update(
        schema_version=2, protocol_version=deployment.PROTOCOL_V2, checks=None, models=group()
    )
    return value


def parse(value, configured=None):
    return deployment.decode_local_deployment(
        _bytes(value),
        backend_sid=base.SID,
        environment=environment() if configured is None else configured,
    )


def test_model_metadata_reuses_original_profile_contract_and_does_not_publish_ready(tmp_path):
    installed = parse(document(tmp_path))
    (admission,) = installed.coding_models.admissions
    assert admission.model.profile_id == DEFAULT_PROFILE
    assert admission.model.api_key == CREDENTIAL
    assert admission.contract('walle-code', 100).permitted_output == 100
    assert admission.contract('walle-compaction', 100).alias == 'walle-compaction'
    assert admission.usage.cache_dimensions == ('cached_tokens',)
    assert not installed.delivery_runtime_admitted
    assert CREDENTIAL not in repr(installed)
    assert CREDENTIAL not in _bytes(document(tmp_path)).decode('utf-8')


@pytest.mark.parametrize(
    'defect',
    [
        'key',
        'url',
        'ready',
        'empty',
        'too-many',
        'duplicate',
        'profile',
        'snapshot',
        'price',
        'duration-bool',
        'duration-too-large',
        'input-bool',
        'context-bool',
        'output-bool',
        'context-too-small',
        'output-profile-limit',
        'usage-nonstream',
        'usage-unknown-dimension',
        'usage-missing-output',
        'usage-cache-output',
        'usage-semantics',
        'usage-duplicate',
        'chunk-bool',
        'optional-unknown',
        'optional-duplicate',
        'reference-control',
        'reference-too-long',
        'no-task',
    ],
)
def test_metadata_cannot_supply_secrets_or_invent_runtime_and_protocol_authority(tmp_path, defect):
    value = document(tmp_path)
    row = value['models']['admissions'][0]
    if defect == 'key':
        row['api_key'] = CREDENTIAL
    elif defect == 'url':
        value['models']['base_url'] = 'https://unapproved.invalid'
    elif defect == 'ready':
        row['ready'] = True
    elif defect == 'empty':
        value['models']['admissions'] = []
    elif defect == 'too-many':
        value['models']['admissions'] *= 17
    elif defect == 'duplicate':
        value['models']['admissions'].append(deepcopy(row))
    elif defect == 'profile':
        row['model_profile_ref'] = 'deepseek-long-v3'
    elif defect == 'snapshot':
        row['model_snapshot_sha256'] = 'e' * 64
    elif defect == 'price':
        row['price_sha256'] = '0' * 64
    elif defect == 'duration-bool':
        row['max_duration_seconds'] = True
    elif defect == 'duration-too-large':
        row['max_duration_seconds'] = 181
    elif defect == 'input-bool':
        row['input_cap'] = True
    elif defect == 'context-bool':
        row['context_cap'] = True
    elif defect == 'output-bool':
        row['output_cap'] = True
    elif defect == 'context-too-small':
        row['context_cap'] = 1000
    elif defect == 'output-profile-limit':
        row['output_cap'] = 8193
    elif defect == 'usage-nonstream':
        row['usage']['final_source'] = 'COMPLETE_BODY'
    elif defect == 'usage-unknown-dimension':
        row['usage']['required_dimensions'].append('unproved_tokens')
    elif defect == 'usage-missing-output':
        row['usage']['required_dimensions'].remove('output_tokens')
    elif defect == 'usage-cache-output':
        row['usage']['cache_dimensions'] = ['output_tokens']
    elif defect == 'usage-semantics':
        row['usage']['cumulative_semantics'] = 'SUM_FRAMES'
    elif defect == 'usage-duplicate':
        row['usage']['required_dimensions'] *= 2
    elif defect == 'chunk-bool':
        row['chunk_usage'] = 1
    elif defect == 'optional-unknown':
        row['optional_fields'] = ['base_url']
    elif defect == 'optional-duplicate':
        row['optional_fields'] *= 2
    elif defect == 'reference-control':
        row['evidence_ref'] = 'bad\nreference'
    elif defect == 'reference-too-long':
        row['evidence_ref'] = 'a' * 257
    else:
        value['task'] = None
    with pytest.raises(deployment.LocalDeploymentError) as failure:
        parse(value)
    assert CREDENTIAL not in str(failure.value)


@pytest.mark.parametrize(
    'defect', ['missing-key', 'endpoint', 'profile-environment', 'not-provided']
)
def test_only_original_explicit_profile_environment_can_supply_credentials(tmp_path, defect):
    configured = environment()
    if defect == 'missing-key':
        del configured['WALLE_MODEL_API_KEY']
    elif defect == 'endpoint':
        configured['WALLE_MODEL_BASE_URL'] = 'https://unapproved.invalid'
    elif defect == 'profile-environment':
        configured['WALLE_MODEL_PROFILE'] = 'deepseek-long-v3'
    else:
        with pytest.raises(deployment.LocalDeploymentError, match='ENVIRONMENT_REQUIRED'):
            deployment.decode_local_deployment(_bytes(document(tmp_path)), backend_sid=base.SID)
        return
    with pytest.raises(deployment.LocalDeploymentError) as failed:
        parse(document(tmp_path), configured)
    assert CREDENTIAL not in str(failed.value)


@pytest.mark.parametrize('omitted', [False, True])
def test_absent_models_do_not_load_any_model_environment(tmp_path, monkeypatch, omitted):
    value = document(tmp_path)
    if omitted:
        del value['models']
    else:
        value['models'] = None

    def forbidden(*args, **kwargs):
        raise AssertionError('Unconfigured model must not read environment')

    monkeypatch.setattr(ModelProfile, 'from_environment', forbidden)
    assert parse(value).coding_models is None


@pytest.fixture
def model_source(task_source):
    value, manifest, configured, source = task_source
    value.update(
        schema_version=2, protocol_version=deployment.PROTOCOL_V2, checks=None, models=group()
    )
    raw = _bytes(value)
    temporary = manifest.with_suffix('.next')
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, manifest)
    configured = {
        **configured,
        **environment(),
        deployment.DIGEST_ENV: hashlib.sha256(raw).hexdigest(),
    }
    return value, manifest, configured, source


def test_real_ntfs_preflight_constructs_original_model_group_without_any_api(model_source):
    _, _, configured, _ = model_source
    with deployment.hold_configured_deployment(configured) as installation:
        (admission,) = installation.coding_models.admissions
        assert admission.model.api_key == CREDENTIAL
        assert installation.task_launch.coding.agent == 'walle-code'


def test_real_main_binds_model_group_in_original_app_without_calls(model_source, tmp_path):
    _, _, configured, _ = model_source
    database = Database(tmp_path / 'models-startup.sqlite', schema_release=load_release())
    database.initialize()
    configured = {
        **os.environ,
        **configured,
        'WALLE_DATABASE_PATH': str(database.path),
        'WALLE_TEST_DEPLOYMENT_MODE': 'valid_models',
    }
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-X',
            'utf8',
            str(root / 'backend/tests/infrastructure/v20_local_deployment_startup_worker.py'),
        ],
        env=configured,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LOCAL_DEPLOYMENT_STARTUP_PASSED' in result.stdout
