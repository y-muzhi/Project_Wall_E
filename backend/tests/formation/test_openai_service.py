"""Readiness and the single native observation CLI, isolated and offline."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tests.formation.test_openai_execution import adapters


def module():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        'openai_service_cli', root / 'tools/openai-service.py'
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_readiness_never_reads_credentials_or_constructs_provider(monkeypatch, capsys):
    service = module()

    def forbidden(*args, **kwargs):
        raise AssertionError('Readiness must not read credentials or construct HTTP')

    monkeypatch.setattr(
        'backend.app.infrastructure.local_credentials.read_local_credential', forbidden
    )
    monkeypatch.setattr('backend.app.infrastructure.openai_counting.OpenAIInputCounter', forbidden)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway', forbidden)
    assert service.main([]) == 0
    assert 'credentials_read=0; provider_calls=0; service_started=0' in capsys.readouterr().out


def test_cli_refuses_invalid_observation_without_user_database():
    service = module()
    with pytest.raises(SystemExit):
        service.main(['--observe'])
    with pytest.raises(SystemExit):
        service.main(['--start'])
    with pytest.raises(SystemExit):
        service.main(['--slot', 'unused'])
    for limit in ('0', '4'):
        with pytest.raises(SystemExit):
            service.main(['--observe', '--count-limit', limit])
    for limit in (0, 4, True):
        with pytest.raises(ValueError):
            service.observe(SimpleNamespace(), count_limit=limit)


def test_actual_cli_observation_uses_only_one_native_call_and_new_owned_slot(
    tmp_path_factory, monkeypatch
):
    service = module()
    root = tmp_path_factory.mktemp('os')
    (root / 'data').mkdir()
    (root / 'docs/verification/v2.1').mkdir(parents=True)
    key = root / 'key.env'
    key.write_bytes(b'OPENAI_API_KEY=offline-cli-key\n')
    monkeypatch.setattr(service, 'ROOT', root)
    from formation_evaluation_spec import samples

    counter, gateway, seen = adapters(samples()[0])
    monkeypatch.setattr(
        'backend.app.infrastructure.openai_counting.OpenAIInputCounter', lambda: counter
    )
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway', lambda: gateway)
    args = SimpleNamespace(
        slot=root / 'data/s', report=root / 'docs/verification/v2.1/live.md', credential_file=key
    )
    assert service.observe(args) == 0
    assert [kind for kind, _ in seen] == ['count', 'model']
    report = args.report.read_text(encoding='utf-8')
    assert 'TECHNICAL_COMPATIBLE' in report
    assert '实际计数尝试=1；实际模型尝试=1' in report
    assert 'offline-cli-key' not in report
    with pytest.raises(ValueError):
        service.observe(args)
    assert len(seen) == 2
    # A clean interpreter must activate fixed SQLite before catalog validation
    # imports document modules; a preactivated pytest process hides that order.
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            '-B',
            str(Path(__file__).resolve().parents[3] / 'tools/openai-service.py'),
            '--database',
            str(args.slot / 'input.sqlite'),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'admission=LIVE_VERIFIED' in result.stdout
    assert 'credentials_read=0; provider_calls=0; service_started=0' in result.stdout


def test_explicit_activation_requires_exact_release_and_keeps_actual_state(monkeypatch):
    from backend.app.infrastructure.collaboration_admission import AdmissionEvidence
    from backend.app.infrastructure.resources import ConfigInvalid

    profile, catalog = module().profile_and_catalog()
    resource = catalog.collaboration
    offline = AdmissionEvidence(resource.release['admission'])
    key = 'WALLE_ACTIVATED_OPENAI_RELEASE_SHA256'
    for digest in ('', '0' * 64):
        monkeypatch.setenv(key, digest)
        with pytest.raises(ConfigInvalid):
            resource.require_live(profile.snapshot, admission=offline)
    monkeypatch.setenv(key, resource.release_sha256)
    resource.require_live(profile.snapshot, admission=offline)
    assert offline.value['state'] == 'OFFLINE_READY'
    with pytest.raises(ConfigInvalid):
        resource.require_live(profile.snapshot)
    with pytest.raises(ConfigInvalid):
        resource.require_live(
            profile.snapshot, admission=AdmissionEvidence({**offline.value, 'state': 'SUSPENDED'})
        )
