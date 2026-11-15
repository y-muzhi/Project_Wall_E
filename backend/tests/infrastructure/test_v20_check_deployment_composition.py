"""Actual NTFS/normal-app CHECK composition; privileged roles are explicit fixtures."""

import hashlib
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.app.code_tasks import local_deployment as backend
from backend.app.infrastructure import guard_deployment_configuration as guard
from backend.app.infrastructure import guard_project_check_deployment as admission
from backend.app.infrastructure.check_deployment_sources import decode_check_deployment_sources
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.schema_v20_release import load_release
from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_runtime_host_identity import windows_runtime_host_identity
from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot
from backend.tests.code_tasks import test_local_deployment as local
from backend.tests.infrastructure import test_v20_check_case_pack as cases
from backend.tests.infrastructure import test_v20_check_deployment_sources as metadata
from backend.tests.infrastructure import test_v20_guard_deployment_configuration as guards

tmp_path = local.tmp_path
local_source = local.local_source
guard_source = guards.guard_source
ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = b'# unexecuted fixture driver'


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def replace_data(path, raw):
    temporary = path.with_suffix('.next')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def identity(path, directory=True):
    with LocalPathGuard(path, directory=directory) as pinned:
        return asdict(pinned.verify())


@pytest.fixture
def check_source(local_source, tmp_path):
    value, manifest, environment = local_source
    value.update(
        schema_version=2, protocol_version=backend.PROTOCOL_V2, checks=metadata.group(tmp_path)
    )
    pack = value['checks']['case_packs'][0]
    path = create_private_package(tmp_path / 'case-pack')
    raw = cases.raw(cases.pack())
    write_new(path / 'manifest.json', raw)
    pack.update(directory=identity(path), manifest_sha256=hashlib.sha256(raw).hexdigest())
    raw = _bytes(value)
    replace_data(manifest, raw)
    environment[backend.DIGEST_ENV] = hashlib.sha256(raw).hexdigest()
    return value, manifest, environment


def test_backend_holds_only_its_data_case_pack_and_does_not_read_system_programs(
    check_source, monkeypatch
):
    value, _, environment = check_source

    def forbidden(*args, **kwargs):
        raise AssertionError('Backend must not read SYSTEM Guard resources/evidence')

    monkeypatch.setattr(guard, 'verify_guard_check_deployments', forbidden)
    path = Path(value['checks']['case_packs'][0]['directory']['canonical_path']) / 'manifest.json'
    with backend.hold_configured_deployment(environment) as installed:
        assert installed.task_launch is None and len(installed.testing_browser) == 1
        assert len(installed.case_packs) == 1 and not installed.delivery_runtime_admitted
        with pytest.raises(PermissionError):
            path.rename(path.with_suffix('.changed'))
    path.rename(path.with_suffix('.released'))


@pytest.mark.parametrize('defect', ['bytes', 'identity', 'scope'])
def test_changed_case_pack_is_rejected_before_app(check_source, defect):
    value, manifest, environment = check_source
    pack = value['checks']['case_packs'][0]
    if defect == 'bytes':
        replace_data(Path(pack['directory']['canonical_path']) / 'manifest.json', b'{}')
    elif defect == 'identity':
        pack['directory']['file_id'] = 'f' * 32
    else:
        pack['command_ids'] = ['unrelated-command']
    raw = _bytes(value)
    replace_data(manifest, raw)
    environment[backend.DIGEST_ENV] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(backend.LocalDeploymentError):
        with backend.hold_configured_deployment(environment):
            raise AssertionError('Changed data reached the application')


def test_normal_main_passes_independent_checks_to_the_original_app(check_source, tmp_path):
    _, _, environment = check_source
    database = Database(tmp_path / 'checks-startup.sqlite', schema_release=load_release())
    database.initialize()
    environment = {
        **os.environ,
        **environment,
        'WALLE_DATABASE_PATH': str(database.path),
        'WALLE_TEST_DEPLOYMENT_MODE': 'valid_checks',
    }
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-X',
            'utf8',
            str(ROOT / 'backend/tests/infrastructure/v20_local_deployment_startup_worker.py'),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LOCAL_DEPLOYMENT_STARTUP_PASSED' in result.stdout


def materialize_runner(spec, *, browser=False, capability='CLI', lpac_capability_names=()):
    root = create_private_package(spec['directory']['canonical_path'])
    members = {'entry.exe': local.image_bytes()}
    if browser:
        members.update({'driver.py': BOOTSTRAP, 'chrome.exe': local.image_bytes()})
        if lpac_capability_names:
            from backend.app.infrastructure.browser_driver_lpac_policy import POLICY_FILE

            members[POLICY_FILE] = _bytes(
                {
                    'schema_version': 1,
                    'capability_names': list(lpac_capability_names),
                }
            )
    for name, raw in members.items():
        write_new(root / name, raw)
    manifest = {
        'schema_version': 1,
        'protocol_version': 'CHECK20-CONTROL-1',
        'bundle_id': spec['bundle_id'],
        'version': spec['version'],
        'entry_ref': 'entry.exe',
        'runtime_refs': ['runtime:fixture'],
        'file_entries': [
            {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'byte_count': len(raw)}
            for name, raw in sorted(members.items())
        ],
        'capabilities': ['CONTENT_INTEGRITY', 'BROWSER' if browser else capability],
        'platform_refs': ['windows-x64'],
        'admission_evidence_refs': ['fixture:unproved'],
    }
    raw = _bytes(manifest)
    write_new(root / 'manifest.json', raw)
    spec.update(directory=identity(root), manifest_sha256=hashlib.sha256(raw).hexdigest())


def prepare_guard_checks(value, installation_ref, *, lpac_capability_names=()):
    for row in value['projects']:
        capability = 'HTTP' if row['command']['purpose'] == 'SERVICE' else 'CLI'
        materialize_runner(row['runner'], capability=capability)
        executable = row['executable']
        raw = local.image_bytes()
        path = Path(executable['file']['canonical_path'])
        write_new(path, raw)
        executable.update(
            file=identity(path, False), sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw)
        )
    for row in value['browsers']:
        materialize_runner(
            row['driver']['runner'],
            browser=True,
            lpac_capability_names=lpac_capability_names,
        )
    for row in (*value['projects'], *value['browsers']):
        path = create_private_package(row['admission']['directory']['canonical_path'])
        row['admission']['directory'] = identity(path)
    group = decode_check_deployment_sources(value)
    for source in (*group.projects, *group.browsers):
        deployed = source.deployment
        expected = {
            'installation_ref': installation_ref,
            'backend_program_ref': 'FIXTURE-BACKEND-PROGRAM',
            'host': windows_runtime_host_identity(),
            'runner_ref': deployed.runner_ref,
            'runner_manifest_sha256': deployed.runner.manifest_sha256,
            'wfp_provider': str(deployed.provider),
            'wfp_sublayer': str(deployed.sublayer),
        }
        if type(deployed) is admission.GuardProjectCheckDeployment:
            expected.update(
                command_definition_sha256=deployed.command.definition_sha256,
                executable_sha256=deployed.executable.sha256,
                owner_kind='TESTING',
            )
            http = deployed.command.purpose == 'SERVICE'
            if http:
                expected['application_mode'] = 'OWNED_LOOPBACK_HTTP'
            required = admission._HTTP_REQUIRED_CHECKS if http else admission._REQUIRED_CHECKS
            filename = 'check-runtime-admission.json'
        else:
            image = hashlib.sha256(local.image_bytes()).hexdigest()
            expected.update(
                owner_kind='TESTING',
                run_kind='CHECK_DRIVER',
                executable_sha256=image,
                bootstrap_sha256=hashlib.sha256(BOOTSTRAP).hexdigest(),
                chromium_sha256=image,
            )
            required = admission._BROWSER_REQUIRED_CHECKS
            if lpac_capability_names:
                expected['lpac_capability_names'] = list(lpac_capability_names)
                required = required | {'lpac_capability_identity_and_denied_boundaries'}
            filename = 'browser-runtime-admission.json'
        raw = _bytes(
            {
                'schema_version': 1,
                'deployment': expected,
                'checks': {check: 'f' * 64 for check in required},
            }
        )
        write_new(Path(deployed.admission_directory.canonical_path) / filename, raw)
        row = next(
            row
            for row in (*value['projects'], *value['browsers'])
            if row['evidence_ref'] == source.evidence_ref
        )
        row['admission']['evidence_sha256'] = hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    'defect',
    [None, 'runner-extra', 'runtime-reference', 'admission-digest', 'driver-closure', 'executable'],
)
def test_guard_opens_independent_check_runtime_and_never_executes(
    guard_source, tmp_path, monkeypatch, defect
):
    value, manifest, _ = guard_source
    # These role gates are fixtures. Original validators and actual NTFS
    # runtime roots/first pipe are used. No formal SYSTEM/WFP proof is claimed.
    monkeypatch.setattr(admission, 'current_operator_sid', lambda: 'S-1-5-18')
    group = metadata.group(tmp_path)
    group['case_packs'] = []
    prepare_guard_checks(group, value['installation_ref'])
    base_path = manifest.parent / 'independent-base'
    base_path.mkdir()
    source = create_private_package(manifest.parent / 'independent-source')
    with LocalDirectoryPin(base_path) as base:
        with TaskRuntimeRoot.create(base, value['backend_sid']) as root:
            runtime = {
                'source_parent': identity(source),
                'runtime_base': asdict(base.verify()),
                'runtime_root': asdict(root.verify()),
            }
    value.update(
        schema_version=2, protocol_version=guard.PROTOCOL_V2, runtime=runtime, checks=group
    )
    if defect == 'runner-extra':
        write_new(
            Path(group['projects'][0]['runner']['directory']['canonical_path']) / 'extra', b'bad'
        )
    elif defect == 'runtime-reference':
        group['projects'][0]['runtime_refs'] = ['unrelated-runtime']
    elif defect == 'admission-digest':
        group['browsers'][0]['admission']['evidence_sha256'] = 'e' * 64
    elif defect == 'driver-closure':
        group['browsers'][0]['driver']['chromium_ref'] = 'absent.exe'
    elif defect == 'executable':
        replace_data(Path(group['projects'][0]['executable']['file']['canonical_path']), b'changed')
    raw = _bytes(value)
    replace_data(manifest, raw)
    if defect:
        with pytest.raises(guard.GuardDeploymentError):
            guard.GuardDeploymentOwner(
                str(manifest), hashlib.sha256(raw).hexdigest(), cancelled=lambda: False
            )
        manifest.rename(manifest.with_suffix('.rejected'))
        return
    owner = guard.GuardDeploymentOwner(
        str(manifest), hashlib.sha256(raw).hexdigest(), cancelled=lambda: False
    )
    try:
        assert owner.spec.task is None and owner.spec.runtime is not None
        server = owner.host._server
        assert len(server._project_checks) == 4
        assert server._task_program is server._task_runtime_bundle is server._task_network is None
        assert not server._owners and not server._retained
    finally:
        owner.close()
    assert owner._closed


@pytest.mark.parametrize(
    'defect',
    [
        None,
        'old-admission',
        'wrong-capability',
        'missing-boundary-proof',
        'missing-logon-proof',
        'missing-gui-proof',
    ],
)
@pytest.mark.parametrize('capabilities', [('registryRead',), ('registryRead', 'lpacCom')])
def test_browser_explicit_os_policy_requires_exact_new_admission(
    tmp_path, monkeypatch, defect, capabilities
):
    import json
    from dataclasses import replace
    from time import monotonic

    monkeypatch.setattr(admission, 'current_operator_sid', lambda: 'S-1-5-18')
    value = metadata.group(tmp_path)
    value['case_packs'] = []
    prepare_guard_checks(value, 'fixed-installation', lpac_capability_names=capabilities)
    source = decode_check_deployment_sources(value).browsers[0]
    deployed = source.deployment
    path = Path(deployed.admission_directory.canonical_path) / 'browser-runtime-admission.json'
    evidence = json.loads(path.read_bytes())
    if defect == 'old-admission':
        del evidence['deployment']['lpac_capability_names']
        del evidence['checks']['lpac_capability_identity_and_denied_boundaries']
    elif defect == 'wrong-capability':
        evidence['deployment']['lpac_capability_names'] = ['internetClient']
    elif defect == 'missing-boundary-proof':
        del evidence['checks']['lpac_capability_identity_and_denied_boundaries']
    if defect == 'missing-logon-proof':
        del evidence['checks']['original_controller_private_logon_source']
    elif defect == 'missing-gui-proof':
        del evidence['checks']['private_gui_namespace_and_owned_cleanup']
    if defect:
        raw = _bytes(evidence)
        replace_data(path, raw)
        deployed = replace(deployed, admission_sha256=hashlib.sha256(raw).hexdigest())

    def verify():
        return deployed.verify(
            'fixed-installation',
            'FIXTURE-BACKEND-PROGRAM',
            deadline=monotonic() + 20,
            cancelled=lambda: False,
        )

    if defect:
        with pytest.raises(admission.CheckResourceError, match='NATIVE_EVIDENCE_REQUIRED'):
            verify()
    else:
        assert verify() == deployed.admission_sha256
