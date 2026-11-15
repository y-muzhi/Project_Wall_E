"""Strict startup source contracts and original backend type projections, with no IO."""

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

import pytest

from backend.app.code_tasks import local_deployment as backend
from backend.app.infrastructure import check_deployment_sources as checks
from backend.app.infrastructure import guard_deployment_configuration as guard
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.tests.code_tasks import test_local_deployment as local
from backend.tests.code_tasks import test_task_deployment_configuration as task
from backend.tests.infrastructure import test_v20_check_case_pack as cases
from backend.tests.infrastructure import test_v20_guard_deployment_configuration as guards

tmp_path = local.tmp_path


def identity(path, directory=True):
    return {
        'canonical_path': str(path),
        'volume_serial': '1' * 16,
        'file_id': sha256(str(path).encode()).hexdigest()[:32],
        'is_directory': directory,
        'filesystem': 'NTFS',
    }


def runner(root):
    return {
        'directory': identity(root),
        'manifest_sha256': 'a' * 64,
        'bundle_id': 'fixture:runner',
        'version': '1',
    }


def project(root, name='cli', owner='TESTING', purpose='CHECK'):
    return {
        'runner_ref': 'runner:' + name,
        'runner': runner(root / ('runner-' + name)),
        'command': {
            'command_id': 'command:' + name,
            'executable_ref': 'binary:' + name,
            'argument_template': ['{CHECK_HOST}', '{CHECK_PORT}'] if purpose == 'SERVICE' else [],
            'working_directory': '.',
            'purpose': purpose,
            'timeout_seconds': 30,
            'network_scope_ref': 'endpoint:' + name if purpose == 'SERVICE' else None,
        },
        'executable': {
            'reference': 'binary:' + name,
            'file': identity(root / (name + '.exe'), False),
            'sha256': 'b' * 64,
            'byte_count': 512,
        },
        'provider': str(uuid4()),
        'sublayer': str(uuid4()),
        'maximum': {
            'max_file_bytes': 4096,
            'max_snapshot_bytes': 40960,
            'max_snapshot_files': 32,
            'max_manifest_bytes': 8192,
        },
        'admission': {
            'directory': identity(root / ('admission-' + name)),
            'evidence_sha256': 'c' * 64,
        },
        'owner_kind': owner,
        'fixture': None,
        'evidence_ref': 'evidence:' + name,
        'runtime_refs': ['runtime:fixture'],
        'active_process_limit': 8,
        'job_memory_limit_bytes': 64 * 1024**2,
    }


def browser(root):
    return {
        'runner_ref': 'runner:browser',
        'driver': {
            'runner': runner(root / 'browser-runner'),
            'bootstrap_ref': 'driver.py',
            'chromium_ref': 'chrome.exe',
        },
        'provider': str(uuid4()),
        'sublayer': str(uuid4()),
        'admission': {
            'directory': identity(root / 'browser-admission'),
            'evidence_sha256': 'd' * 64,
        },
        'target_ref': 'target:integration',
        'evidence_ref': 'evidence:browser',
        'runtime_refs': ['runtime:fixture'],
        'command_id': 'command:browser',
        'active_process_limit': 8,
        'job_memory_limit_bytes': 64 * 1024**2,
        'applications': [
            {
                'role': 'FRONTEND',
                'origin_ref': 'origin:frontend',
                'prefix': '/',
                'service_ref': 'evidence:frontend',
            },
            {
                'role': 'BACKEND',
                'origin_ref': 'origin:backend',
                'prefix': '/api/',
                'service_ref': 'evidence:backend',
            },
        ],
    }


def case_pack(root):
    return {
        'case_pack_ref': 'cases:fixture',
        'directory': identity(root / 'case-pack'),
        'manifest_sha256': 'e' * 64,
        'bundle_id': 'fixture-pack',
        'version': '1.0.0',
        'limits': asdict(cases.LIMITS),
        'basis_refs': [asdict(cases.BASIS)],
        'command_ids': [cases.COMMAND],
        'endpoint_refs': [cases.ENDPOINT],
    }


def group(root):
    return {
        'projects': [
            project(root),
            project(root, 'frontend', purpose='SERVICE'),
            project(root, 'backend', purpose='SERVICE'),
        ],
        'browsers': [browser(root)],
        'case_packs': [case_pack(root)],
    }


def backend_document(root, *, coding=False):
    value = local.document(root)
    value.update(schema_version=2, protocol_version=backend.PROTOCOL_V2, checks=group(root))
    value['registration']['workspace_root'] = str(root / 'workspace')
    if coding:
        value['task'] = task.group(root)
        value['checks']['projects'].append(project(root, 'coding', owner='CODING'))
    return value


def guard_document(root):
    value = guards.document(root)
    value.update(
        schema_version=2,
        protocol_version=guard.PROTOCOL_V2,
        checks=group(root),
        runtime={
            name: identity(root / path)
            for name, path in (
                ('source_parent', 'source'),
                ('runtime_base', 'base'),
                ('runtime_root', 'base/task-runtime'),
            )
        },
    )
    return value


def test_independent_testing_projects_browser_and_cases_use_original_types(tmp_path):
    value = backend_document(tmp_path)
    installed = backend.decode_local_deployment(_bytes(value), backend_sid=local.SID)
    assert installed.task_launch is None and installed.coding_models is None
    assert (
        len(installed.testing_cli)
        == len(installed.testing_browser)
        == len(installed.case_packs)
        == 1
    )
    assert not installed.project_checks and not installed.delivery_runtime_admitted
    browser = installed.testing_browser[0]
    assert {item.role for item in browser.applications} == {'FRONTEND', 'BACKEND'}
    assert {item.service.command.network_scope_ref for item in browser.applications} == {
        'endpoint:frontend',
        'endpoint:backend',
    }
    assert all(item.service.command.purpose == 'SERVICE' for item in browser.applications)
    assert installed.case_packs[0].basis_refs == (cases.BASIS,)
    assert not (tmp_path / 'source').exists()


def test_coding_and_testing_deployments_keep_distinct_owners(tmp_path):
    installed = backend.decode_local_deployment(
        _bytes(backend_document(tmp_path, coding=True)), backend_sid=local.SID
    )
    assert len(installed.project_checks) == 1 and installed.task_launch is not None
    assert installed.project_checks[0].command.command_id == 'command:coding'
    assert installed.testing_cli[0].command.command_id == 'command:cli'


def test_independent_guard_check_runtime_requires_no_opencode_or_model(tmp_path):
    deployed = guard.decode_guard_deployment(_bytes(guard_document(tmp_path)))
    assert deployed.task is None and deployed.runtime is not None
    assert len(deployed.checks.guard_deployments) == 4
    assert deployed.runtime.source_parent.canonical_path == str(tmp_path / 'source')


@pytest.mark.parametrize(
    'defect',
    [
        'extra',
        'too-many',
        'ready',
        'system-flag',
        'runner-bool',
        'runner-sha',
        'executable-directory',
        'byte-count-bool',
        'service-coding',
        'fixture-coding',
        'runtime-duplicate',
        'process-bool',
        'memory-bool',
        'duplicate-evidence',
        'browser-evidence-collision',
        'duplicate-target',
        'wrong-service',
        'non-service',
        'wrong-owner',
        'same-role',
        'same-endpoint',
        'same-origin',
        'same-service',
        'prefix-query',
        'prefix-escape',
        'bootstrap',
        'chromium',
        'case-extra',
        'case-limit-bool',
        'case-no-basis',
        'case-duplicate',
        'resource-conflict',
    ],
)
def test_strict_resource_groups_reject_ambiguous_or_untrusted_authority(tmp_path, defect):
    value = group(tmp_path)
    p, front, back = value['projects']
    b = value['browsers'][0]
    if defect == 'extra':
        value['command'] = 'arbitrary'
    elif defect == 'too-many':
        value['projects'] *= 12
    elif defect == 'ready':
        p['ready'] = True
    elif defect == 'system-flag':
        b['admission']['system'] = True
    elif defect == 'runner-bool':
        p['runner']['directory']['is_directory'] = 1
    elif defect == 'runner-sha':
        p['runner']['manifest_sha256'] = '0' * 64
    elif defect == 'executable-directory':
        p['executable']['file']['is_directory'] = True
    elif defect == 'byte-count-bool':
        p['executable']['byte_count'] = True
    elif defect == 'service-coding':
        front['owner_kind'] = 'CODING'
    elif defect == 'fixture-coding':
        p['owner_kind'] = 'CODING'
        p['fixture'] = {
            'reference': 'fixture',
            'sha256': 'f' * 64,
            'directory': identity(tmp_path / 'fixture'),
        }
    elif defect == 'runtime-duplicate':
        p['runtime_refs'] *= 2
    elif defect == 'process-bool':
        p['active_process_limit'] = True
    elif defect == 'memory-bool':
        p['job_memory_limit_bytes'] = True
    elif defect == 'duplicate-evidence':
        back['evidence_ref'] = front['evidence_ref']
    elif defect == 'browser-evidence-collision':
        b['evidence_ref'] = p['evidence_ref']
    elif defect == 'duplicate-target':
        value['browsers'].append({**deepcopy(b), 'evidence_ref': 'different'})
    elif defect == 'wrong-service':
        b['applications'][0]['service_ref'] = 'missing'
    elif defect == 'non-service':
        b['applications'][0]['service_ref'] = p['evidence_ref']
    elif defect == 'wrong-owner':
        front['owner_kind'] = 'UNTRUSTED'
    elif defect == 'same-role':
        b['applications'][0]['role'] = 'BACKEND'
    elif defect == 'same-endpoint':
        back['command']['network_scope_ref'] = front['command']['network_scope_ref']
    elif defect == 'same-origin':
        b['applications'][1].update(origin_ref='origin:frontend', prefix='/')
    elif defect == 'same-service':
        b['applications'][1]['service_ref'] = 'evidence:frontend'
    elif defect == 'prefix-query':
        b['applications'][0]['prefix'] = '/?redirect/'
    elif defect == 'prefix-escape':
        b['applications'][0]['prefix'] = '/../'
    elif defect == 'bootstrap':
        b['driver']['bootstrap_ref'] = '../driver.py'
    elif defect == 'chromium':
        b['driver']['chromium_ref'] = 'chrome.sh'
    elif defect == 'case-extra':
        value['case_packs'][0]['source'] = 'arbitrary'
    elif defect == 'case-limit-bool':
        value['case_packs'][0]['limits']['max_check_cases'] = True
    elif defect == 'case-no-basis':
        value['case_packs'][0]['basis_refs'] = []
    elif defect == 'case-duplicate':
        value['case_packs'] *= 2
    else:
        extra = deepcopy(p)
        extra['evidence_ref'] = 'other'
        extra['executable']['sha256'] = 'f' * 64
        value['projects'].append(extra)
    with pytest.raises((RuntimeError, ValueError, TypeError)):
        checks.decode_check_deployment_sources(value)


@pytest.mark.parametrize('side', ['backend', 'guard'])
@pytest.mark.parametrize('defect', ['old-extra', 'protocol', 'bool-version', 'missing-runtime'])
def test_versions_are_explicit_and_incomplete_groups_do_not_gain_runtime(tmp_path, side, defect):
    value = backend_document(tmp_path) if side == 'backend' else guard_document(tmp_path)
    if defect == 'old-extra':
        value.update(
            schema_version=1,
            protocol_version=backend.PROTOCOL if side == 'backend' else guard.PROTOCOL,
        )
    elif defect == 'protocol':
        value['protocol_version'] = 'latest'
    elif defect == 'bool-version':
        value['schema_version'] = True
    elif side == 'backend':
        value['registration']['workspace_root'] = None
    else:
        value['runtime'] = None
    with pytest.raises(RuntimeError):
        if side == 'backend':
            backend.decode_local_deployment(_bytes(value), backend_sid=local.SID)
        else:
            guard.decode_guard_deployment(_bytes(value))
