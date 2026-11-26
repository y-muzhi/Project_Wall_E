"""Isolation evidence binding and actual native Windows host facts."""

from hashlib import sha256
from platform import win32_ver
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.guard_task_actions import TaskNetworkDeployment
from backend.app.infrastructure.guard_task_deployment import (
    _EVIDENCE_NAME,
    _REQUIRED_CHECKS,
    TaskRuntimeAdmission,
    _verify_deployment_record,
)
from backend.app.infrastructure.opencode_binary import VERSION
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_runtime_host_identity import windows_runtime_host_identity
from backend.tests.requirements.test_v15_foundation import tmp_path


def test_current_windows_identity_reads_native_build():
    actual = windows_runtime_host_identity()
    assert actual['architecture'] == 'AMD64'
    assert actual['windows_version'][:2] == [10, 0]
    assert actual['windows_version'][2] >= 22000
    assert actual['windows_version'] == [int(part) for part in win32_ver()[1].split('.')[:3]]


@pytest.mark.parametrize(
    'outcome',
    [
        'complete',
        'wrong_host',
        'wrong_capabilities',
        'missing_capabilities',
        'missing_probe',
        'truthy_probe',
    ],
)
def test_fixed_deployment_evidence_requires_exact_binding_and_all_native_probes(outcome):
    expected = {
        'host': windows_runtime_host_identity(),
        'opencode_version': VERSION,
        'lpac_capability_names': ['registryRead'],
    }
    record = {
        'schema_version': 1,
        'deployment': {**expected},
        'checks': {name: sha256(name.encode()).hexdigest() for name in _REQUIRED_CHECKS},
    }
    if outcome == 'complete':
        assert _verify_deployment_record(_bytes(record), expected) is None
    elif outcome in ('wrong_host', 'wrong_capabilities', 'missing_capabilities'):
        if outcome == 'wrong_host':
            record['deployment']['host'] = {
                'architecture': 'ARM64',
                'windows_version': [10, 0, 22000],
            }
        elif outcome == 'wrong_capabilities':
            record['deployment']['lpac_capability_names'] = ['registryRead', 'lpacCom']
        else:
            del record['deployment']['lpac_capability_names']
        with pytest.raises(LaunchOutcomeUnknown, match='BINDING_DIFFERS'):
            _verify_deployment_record(_bytes(record), expected)
    else:
        name = next(iter(_REQUIRED_CHECKS))
        if outcome == 'missing_probe':
            del record['checks'][name]
        else:
            record['checks'][name] = True
        with pytest.raises(LaunchOutcomeUnknown, match='NATIVE_EVIDENCE_REQUIRED'):
            _verify_deployment_record(_bytes(record), expected)


def test_ordinary_native_account_cannot_admit_even_pinned_evidence(tmp_path):
    root = create_private_package(tmp_path / 'guard-admission')
    with PrivatePackageGuard(root) as package:
        raw = b'{}'
        (root / _EVIDENCE_NAME).write_bytes(raw)
        admission = TaskRuntimeAdmission(package.verify(), sha256(raw).hexdigest())
        network = TaskNetworkDeployment(uuid4(), uuid4(), ('127.0.0.1', 41001), admission=admission)
        with pytest.raises(LaunchOutcomeUnknown, match='DEPLOYMENT_SYSTEM_REQUIRED'):
            admission.verify(
                installation_ref='a' * 64,
                backend_program_ref='backend-fixture',
                plan=SimpleNamespace(runtime_bundle_ref='fixed', binary_ref='fixture'),
                program_sha256='b' * 64,
                network=network,
                checkpoint=lambda: None,
            )


def test_deployment_pins_actual_private_ntfs_file_and_refuses_changed_bytes(tmp_path, monkeypatch):
    from backend.app.infrastructure import guard_task_deployment as deployment

    root = create_private_package(tmp_path / 'fixed-admission')
    provider, sublayer = uuid4(), uuid4()
    expected = {
        'installation_ref': 'a' * 64,
        'backend_program_ref': 'backend-fixture',
        'runtime_bundle_ref': 'fixed',
        'binary_ref': 'fixture',
        'program_sha256': 'b' * 64,
        'opencode_version': VERSION,
        'lpac_capability_names': ['registryRead'],
        'host': windows_runtime_host_identity(),
        'wfp_provider': str(provider),
        'wfp_sublayer': str(sublayer),
        'model_listener': ['127.0.0.1', 41001],
        'forward_listeners': [],
    }
    raw = _bytes(
        {
            'schema_version': 1,
            'deployment': expected,
            'checks': {name: sha256(name.encode()).hexdigest() for name in _REQUIRED_CHECKS},
        }
    )
    path = root / _EVIDENCE_NAME
    path.write_bytes(raw)
    with PrivatePackageGuard(root) as package:
        monkeypatch.setattr(deployment, '_SYSTEM', package.operator_sid)
        admission = TaskRuntimeAdmission(package.verify(), sha256(raw).hexdigest())
        network = TaskNetworkDeployment(
            provider, sublayer, ('127.0.0.1', 41001), admission=admission
        )

        def verify(actual_network):
            return admission.verify(
                installation_ref=expected['installation_ref'],
                backend_program_ref=expected['backend_program_ref'],
                plan=SimpleNamespace(runtime_bundle_ref='fixed', binary_ref='fixture'),
                program_sha256=expected['program_sha256'],
                network=actual_network,
                checkpoint=lambda: None,
            )

        assert verify(network) == admission.evidence_sha256
        different_port = TaskNetworkDeployment(
            provider, sublayer, ('127.0.0.1', 41002), admission=admission
        )
        with pytest.raises(LaunchOutcomeUnknown, match='BINDING_DIFFERS'):
            verify(different_port)
        path.write_bytes(raw + b' ')
        with pytest.raises(LaunchOutcomeUnknown, match='BYTES_DIFFER'):
            verify(network)
