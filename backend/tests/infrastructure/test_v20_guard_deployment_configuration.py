"""Strict Guard startup metadata and actual owned NTFS/pipe composition; SYSTEM is explicit."""

import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_deployment_configuration as guard
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    current_operator_sid,
)
from backend.tests.code_tasks import test_local_deployment as local
from backend.tests.code_tasks import test_task_deployment_configuration as task

tmp_path = local.tmp_path
local_source = local.local_source
runtime_bundle = task.runtime_bundle
task_source = task.task_source


def document(root):
    return {
        'schema_version': 1,
        'protocol_version': guard.PROTOCOL,
        'installation_ref': 'a' * 64,
        'backend_sid': local.SID,
        'backend_program': {'root': str(root / 'program'), 'manifest_sha256': 'b' * 64},
        'journal_root': str(root / 'journal'),
        'task': None,
        'connection_timeout_ms': 500,
        'request_timeout_ms': 30000,
        'shutdown_timeout_ms': 30000,
    }


def identity(path, number):
    return {
        'canonical_path': str(path),
        'volume_serial': '1' * 16,
        'file_id': str(number) * 32,
        'is_directory': True,
        'filesystem': 'NTFS',
    }


def task_group(root):
    program = task.group(root)
    return {
        'program': {
            name: program[name] for name in ('executor', 'runtime_bundle', 'execution', 'network')
        },
        'source_parent': identity(root / 'source', 1),
        'runtime_base': identity(root / 'runtime-base', 2),
        'runtime_root': identity(root / 'runtime-base/task-runtime', 3),
        'network': {
            'provider': str(uuid4()),
            'sublayer': str(uuid4()),
            'model_listener': ['127.0.0.1', 51001],
            'forward_listeners': [],
            'admission': {
                'directory': identity(root / 'admission', 4),
                'evidence_sha256': 'c' * 64,
            },
        },
    }


def parse(value):
    return guard.decode_guard_deployment(_bytes(value))


def test_guard_group_has_no_business_database_model_or_arbitrary_command_fields(tmp_path):
    value = document(tmp_path)
    result = parse(value)
    assert result.task is None and result.backend_sid == local.SID
    assert result.connection_timeout_ms == 500
    for key in ('database', 'api_key', 'command', 'ready'):
        changed = deepcopy(value)
        changed[key] = 'secret-marker'
        with pytest.raises(guard.GuardDeploymentError) as failed:
            parse(changed)
        assert 'secret-marker' not in str(failed.value)


@pytest.mark.parametrize(
    'field,value',
    [
        ('schema_version', True),
        ('schema_version', 1.0),
        ('protocol_version', 'other'),
        ('backend_sid', 'S-1-5-18'),
        ('installation_ref', 'not-an-installation'),
        ('connection_timeout_ms', True),
        ('connection_timeout_ms', 5001),
        ('request_timeout_ms', 0),
        ('shutdown_timeout_ms', 300001),
    ],
)
def test_strict_guard_identity_version_and_bounded_lifecycle(tmp_path, field, value):
    source = document(tmp_path)
    source[field] = value
    with pytest.raises(guard.GuardDeploymentError):
        parse(source)


def test_task_resource_group_reuses_the_same_plan_and_source_types(tmp_path):
    source = document(tmp_path)
    source['task'] = task_group(tmp_path)
    decoded = parse(source)
    assert decoded.task.network.model_listener == decoded.task.sources.plan.network['model'][0]
    assert asdict(decoded.task.source_parent) == source['task']['source_parent']
    assert decoded.task.sources.binary.bundle.root == tmp_path / 'bundle'


@pytest.mark.parametrize(
    'defect',
    [
        'source-type',
        'source-filesystem',
        'source-id',
        'runtime-identity',
        'provider',
        'provider-zero',
        'model-port',
        'forward-type',
        'admission-flag',
        'admission-digest',
    ],
)
def test_task_cannot_infer_os_evidence_or_widen_the_registered_network(tmp_path, defect):
    source = document(tmp_path)
    source['task'] = group = task_group(tmp_path)
    if defect == 'source-type':
        group['source_parent']['is_directory'] = 1
    elif defect == 'source-filesystem':
        group['source_parent']['filesystem'] = 'FAT32'
    elif defect == 'source-id':
        group['source_parent']['file_id'] = 1
    elif defect == 'runtime-identity':
        group['runtime_root']['canonical_path'] = '../runtime'
    elif defect == 'provider':
        group['network']['provider'] = True
    elif defect == 'provider-zero':
        group['network']['provider'] = str(__import__('uuid').UUID(int=0))
    elif defect == 'model-port':
        group['network']['model_listener'][1] = 51003
    elif defect == 'forward-type':
        group['network']['forward_listeners'] = 'arbitrary'
    elif defect == 'admission-flag':
        group['network']['admission']['ready'] = True
    else:
        group['network']['admission']['evidence_sha256'] = '0' * 64
    with pytest.raises(guard.GuardDeploymentError):
        parse(source)


@pytest.fixture
def guard_source(tmp_path, monkeypatch):
    # This fixture composes ordinary-user NTFS/pipe objects; it is not SYSTEM evidence.
    monkeypatch.setattr(guard, 'require_guard_identity', lambda: None)
    tmp_path = tmp_path / 'guard-source'
    tmp_path.mkdir()
    value = document(tmp_path)
    value['backend_sid'] = current_operator_sid()
    value['installation_ref'] = uuid4().hex + uuid4().hex
    program_root = tmp_path / 'program'
    program_root.mkdir()
    raw = local.image_bytes()
    with (program_root / 'walle-backend.exe').open('xb') as stream:
        stream.write(raw)
    program = _bytes(
        {
            'policy_version': 'BACKEND20-PROTECTED-1',
            'program_ref': 'FIXTURE-BACKEND-PROGRAM',
            'entry': 'walle-backend.exe',
            'files': [
                {
                    'path': 'walle-backend.exe',
                    'byte_count': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(),
                }
            ],
        }
    )
    with (program_root / 'backend-program.v1.json').open('xb') as stream:
        stream.write(program)
    value['backend_program']['manifest_sha256'] = hashlib.sha256(program).hexdigest()
    create_private_package(tmp_path / 'journal')
    manifest = tmp_path / 'guard-deployment.json'
    raw = _bytes(value)
    with manifest.open('xb') as stream:
        stream.write(raw)
    return value, manifest, hashlib.sha256(raw).hexdigest()


def test_actual_owned_host_is_composed_and_all_sources_are_fixed_until_close(guard_source):
    value, manifest, sha = guard_source
    owner = guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
    with pytest.raises(PermissionError):
        manifest.rename(manifest.with_suffix('.changed'))
    assert owner.host.name.endswith(value['installation_ref'])
    assert owner.host._server._task_runtime_root is None
    owner.serve(cancelled=lambda: True)
    owner.close()
    assert owner._closed and owner.host is None
    owner.close()
    manifest.rename(manifest.with_suffix('.released'))


def test_guard_rejects_wrong_source_before_creating_a_journal_or_pipe(guard_source, tmp_path):
    _, manifest, _ = guard_source
    with pytest.raises(guard.GuardDeploymentError, match='SOURCE_DIGEST_DIFFERS'):
        guard.GuardDeploymentOwner(str(manifest), 'c' * 64, cancelled=lambda: False)
    assert not (manifest.parent / 'journal/runtime-guard.lock').exists()


def test_normal_user_cannot_create_guard_resources_without_the_system_role(tmp_path, monkeypatch):
    if current_operator_sid() == 'S-1-5-18':
        pytest.skip('This case proves ordinary-user rejection')

    def forbidden(*args, **kwargs):
        raise AssertionError('SYSTEM identity must precede configuration/resource IO')

    monkeypatch.setattr(guard, 'LockedFileSource', forbidden)
    with pytest.raises(guard.GuardDeploymentError, match='SYSTEM_REQUIRED'):
        guard.GuardDeploymentOwner(str(tmp_path / 'absent.json'), 'a' * 64, cancelled=lambda: False)


def test_guard_imports_no_business_database_or_model_configuration():
    root = Path(__file__).resolve().parents[3]
    code = (
        'import sys;import backend.app.infrastructure.guard_deployment_configuration;'
        "assert 'backend.app.infrastructure.database' not in sys.modules;"
        "assert 'backend.app.infrastructure.model_profile' not in sys.modules;"
        "print('GUARD_NO_DATABASE_OR_MODEL_IMPORT')"
    )
    result = subprocess.run(
        [sys.executable, '-B', '-c', code],
        cwd=root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'GUARD_NO_DATABASE_OR_MODEL_IMPORT' in result.stdout


@pytest.mark.parametrize('defect', [None, 'source-id', 'runtime-id', 'admission'])
def test_actual_guard_full_task_group_and_failed_admission_hold_no_execution(
    guard_source, task_source, tmp_path, monkeypatch, defect
):
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot

    value, manifest, _ = guard_source
    backend_value, _, _, source = task_source
    group = task_group(tmp_path)
    group['program'] = {
        name: backend_value['task'][name]
        for name in ('executor', 'runtime_bundle', 'execution', 'network')
    }
    with LocalPathGuard(tmp_path / 'workspace', directory=True) as parent:
        group['source_parent'] = asdict(parent.verify())
    base_path = manifest.parent / 'runtime-base'
    base_path.mkdir()
    with LocalDirectoryPin(base_path) as base:
        group['runtime_base'] = asdict(base.verify())
        with TaskRuntimeRoot.create(base, value['backend_sid']) as root:
            group['runtime_root'] = asdict(root.verify())
    create_private_package(manifest.parent / 'task-admission')
    with LocalPathGuard(manifest.parent / 'task-admission', directory=True) as admission:
        group['network']['admission']['directory'] = asdict(admission.verify())
    checked = []

    def admission_port(admission, **bound):
        # This named port proves composition/binding, not SYSTEM/WFP admission.
        bound['checkpoint']()
        checked.append(bound)
        assert bound['installation_ref'] == value['installation_ref']
        assert bound['backend_program_ref'] == 'FIXTURE-BACKEND-PROGRAM'
        assert bound['program_sha256'] == hashlib.sha256(local.image_bytes()).hexdigest()
        assert (
            bound['plan'].runtime_bundle_ref == backend_value['task']['runtime_bundle']['reference']
        )
        assert bound['network'].admission is admission
        if defect == 'admission':
            raise guard.GuardDeploymentError('FIXTURE_ADMISSION_REJECTED')
        return admission.evidence_sha256

    monkeypatch.setattr(guard.TaskRuntimeAdmission, 'verify', admission_port)

    def namespace_port(installation_ref, provider, sublayer, checkpoint):
        checkpoint()
        assert len(checked) == 1
        assert installation_ref == value['installation_ref']
        assert str(provider) == group['network']['provider']
        assert str(sublayer) == group['network']['sublayer']

    monkeypatch.setattr(guard, 'ensure_admitted_task_wfp_namespace', namespace_port)
    if defect == 'source-id':
        group['source_parent']['file_id'] = 'f' * 32
    elif defect == 'runtime-id':
        group['runtime_root']['file_id'] = 'f' * 32
    value['task'] = group
    raw = _bytes(value)
    temporary = manifest.with_suffix('.new')
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, manifest)
    sha = hashlib.sha256(raw).hexdigest()
    if defect:
        with pytest.raises(guard.GuardDeploymentError):
            guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
        assert len(checked) == (1 if defect == 'admission' else 0)
        # The deployment source remains releasable after pre-host rejection.
        manifest.rename(manifest.with_suffix('.rejected'))
        source.manifest.rename(source.manifest.with_suffix('.released'))
        return
    owner = guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
    try:
        server = owner.host._server
        assert asdict(server._task_source_parent) == group['source_parent']
        assert asdict(server._task_runtime_root.verify()) == group['runtime_root']
        assert (
            server._task_runtime_bundle.reference
            == backend_value['task']['runtime_bundle']['reference']
        )
        assert len(checked) == 1 and not server._owners
        for pinned in (manifest, source.manifest):
            with pytest.raises(PermissionError):
                pinned.rename(pinned.with_suffix('.changed'))
    finally:
        owner.close()
    assert owner._closed
    source.manifest.rename(source.manifest.with_suffix('.released'))


def test_constructor_retained_child_is_never_blindly_closed_again(guard_source, monkeypatch):
    _, manifest, sha = guard_source
    calls = []

    class RetainedChild:
        def close(self):
            calls.append('close')
            raise AssertionError('Unknown child close must not be retried')

    child = RetainedChild()

    def failed_host(*args, **kwargs):
        error = RuntimeError('Owned constructor boundary')
        error.retained_owner = child
        raise error

    monkeypatch.setattr(guard, 'GuardControlGitHost', failed_host)
    with pytest.raises(guard.GuardDeploymentError, match='CHILD_OWNER_UNVERIFIED') as failure:
        guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
    retained = failure.value.retained_owner
    try:
        assert retained._orphans == [child] and calls == []
        with pytest.raises(guard.GuardDeploymentError, match='REQUIRES_OBSERVATION'):
            retained.close()
        assert calls == []
        with pytest.raises(PermissionError):
            manifest.rename(manifest.with_suffix('.changed'))
    finally:
        # This test port owns no native resource. Its removal is explicit
        # fixture reconciliation, not a product retry of an uncertain close.
        retained._orphans.clear()
        retained.close()
    assert retained._closed


def test_unknown_owner_close_is_latched_and_does_not_repeat_native_stop(guard_source, monkeypatch):
    _, manifest, sha = guard_source
    owner = guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
    original = owner.host.stop_owned
    calls = []

    def unknown_stop(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('Owned shutdown failure')

    monkeypatch.setattr(owner.host, 'stop_owned', unknown_stop)
    try:
        with pytest.raises(RuntimeError, match='shutdown failure') as failed:
            owner.close()
        assert failed.value.retained_owner is owner
        with pytest.raises(guard.GuardDeploymentError, match='REQUIRES_OBSERVATION'):
            owner.close()
        assert len(calls) == 1
    finally:
        # The port failed before invoking any native operation; restore only
        # after proving that fact, then clean this fixture's known empty Host.
        monkeypatch.setattr(owner.host, 'stop_owned', original)
        owner._close_failed = False
        owner.close()


@pytest.mark.parametrize(
    'boundary,expected',
    [
        ('identity', 'SYSTEM_IDENTITY'),
        ('deployment-source', 'DEPLOYMENT_SOURCE'),
        ('deployment-contract', 'DEPLOYMENT_CONTRACT'),
        ('backend-source', 'BACKEND_SOURCE'),
        ('backend-contract', 'BACKEND_CONTRACT'),
        ('journal', 'PRIVATE_JOURNAL'),
        ('records', 'CONTROLLER_RECORDS'),
        ('host', 'CONTROL_HOST'),
    ],
)
def test_actual_constructor_preserves_failed_stage_without_disclosing_exception(
    guard_source, monkeypatch, boundary, expected
):
    from backend.app.infrastructure.guard_service_diagnostics import GuardFailureStage

    _, manifest, sha = guard_source

    def failed(*args, **kwargs):
        error = RuntimeError('private path and provider secret')
        error.native_error = 5
        raise error

    if boundary in ('deployment-source', 'backend-source'):
        original = guard.LockedFileSource
        calls = 0

        def source(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (1 if boundary == 'deployment-source' else 2):
                return failed()
            return original(*args, **kwargs)

        monkeypatch.setattr(guard, 'LockedFileSource', source)
    else:
        name = {
            'identity': 'require_guard_identity',
            'deployment-contract': 'decode_guard_deployment',
            'backend-contract': 'decode_backend_program_manifest',
            'journal': 'LaunchJournal',
            'records': 'GuardControllerRecords',
            'host': 'GuardControlGitHost',
        }[boundary]
        monkeypatch.setattr(guard, name, failed)
    with pytest.raises(guard.GuardDeploymentError) as failure:
        guard.GuardDeploymentOwner(str(manifest), sha, cancelled=lambda: False)
    diagnostic = failure.value.guard_diagnostic
    assert diagnostic.stage is GuardFailureStage[expected] and diagnostic.native_error == 5
    assert 'private' not in str(failure.value)
    assert failure.value.__cause__.args == ('private path and provider secret',)
    # Actual source locks from the failed constructor were released exactly once.
    manifest.rename(manifest.with_suffix('.released'))
