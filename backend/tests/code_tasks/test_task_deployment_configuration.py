"""Trusted TASK groups bind original binary/protocol/bundle types; no native execution."""

import hashlib
from copy import deepcopy
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.app.code_tasks import local_deployment as deployment
from backend.app.infrastructure import opencode_binary as binary
from backend.app.infrastructure import opencode_protocol_source as protocol
from backend.tests.code_tasks import test_local_deployment as base
from backend.tests.infrastructure import test_v20_opencode_runtime_bundle as runtime

tmp_path = base.tmp_path
local_source = base.local_source
runtime_bundle = runtime.runtime_bundle


def group(root, reference='opencode-bundle:sha256:' + 'a' * 64):
    return {
        'executor': {
            'archive': str(root / binary.ARCHIVE_NAME),
            'image': str(root / binary.IMAGE_NAME),
            'openapi': str(root / 'openapi.json'),
        },
        'runtime_bundle': {
            'manifest': str(root / 'bundle-manifest.json'),
            'root': str(root / 'bundle'),
            'reference': reference,
        },
        'execution': {
            'binary_ref': 'opencode-1.19.5',
            'version': binary.VERSION,
            'active_process_limit': 16,
            'job_memory_limit_bytes': 512 * 1024**2,
        },
        'network': {
            'model': [{'address': '127.0.0.1', 'port': 51001}],
            'forward': [],
            'control': [{'address': '127.0.0.1', 'port': 51002}],
            'application': [],
        },
        'configuration_sha256': 'c' * 64,
        'startup_timeout_ms': 30000,
        'max_diagnostic_output_bytes': 256 * 1024,
        'agent_ref': 'walle-code',
    }


def task_document(root):
    value = base.document(root)
    value['registration']['workspace_root'] = str(root / 'workspace')
    value['task'] = group(root)
    return value


def test_task_group_uses_original_types_and_never_accepts_native_rules(tmp_path):
    value = task_document(tmp_path)
    installed = base.parse(value)
    assert installed.task_launch.plan.executor == {
        'version': binary.VERSION,
        'binary_ref': 'opencode-1.19.5',
        'runtime_bundle_ref': value['task']['runtime_bundle']['reference'],
    }
    assert installed.executor_binary.bundle.root == tmp_path / 'bundle'
    assert installed.executor_binary.openapi == tmp_path / 'openapi.json'
    assert installed.task_launch.coding.permission() == [
        {'permission': '*', 'pattern': '*', 'action': 'deny'}
    ]
    assert installed.coding_models is None and not installed.delivery_runtime_admitted
    changed = deepcopy(value)
    changed['task']['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    with pytest.raises(deployment.LocalDeploymentError):
        base.parse(changed)


@pytest.mark.parametrize(
    'defect',
    [
        'workspace',
        'version',
        'binary-ref',
        'bundle-ref',
        'manifest-inside',
        'relative-image',
        'extra-arguments',
        'extra-runtime',
        'port-bool',
        'external-network',
        'duplicate-endpoint',
        'ipv6-model',
        'timeout-bool',
        'timeout-too-long',
        'memory-bool',
        'agent-blank',
        'agent-control',
        'agent-type',
        'configuration-digest',
        'protocol-missing',
    ],
)
def test_task_groups_reject_incomplete_or_unbound_resources_before_io(tmp_path, defect):
    value = task_document(tmp_path)
    task = value['task']
    if defect == 'workspace':
        value['registration']['workspace_root'] = None
    elif defect == 'version':
        task['execution']['version'] = '1.19.4'
    elif defect == 'binary-ref':
        task['execution']['binary_ref'] = ' invalid '
    elif defect == 'bundle-ref':
        task['runtime_bundle']['reference'] = 'unregistered'
    elif defect == 'manifest-inside':
        task['runtime_bundle']['manifest'] = str(tmp_path / 'bundle' / 'manifest.json')
    elif defect == 'relative-image':
        task['executor']['image'] = 'opencode.exe'
    elif defect == 'extra-arguments':
        task['execution']['arguments'] = ['arbitrary']
    elif defect == 'extra-runtime':
        task['runtime_bundle']['ready'] = True
    elif defect == 'port-bool':
        task['network']['control'][0]['port'] = True
    elif defect == 'external-network':
        task['network']['model'][0]['address'] = '8.8.8.8'
    elif defect == 'duplicate-endpoint':
        task['network']['control'] = deepcopy(task['network']['model'])
    elif defect == 'ipv6-model':
        task['network']['model'][0]['address'] = '::1'
    elif defect == 'timeout-bool':
        task['startup_timeout_ms'] = True
    elif defect == 'timeout-too-long':
        task['startup_timeout_ms'] = 30001
    elif defect == 'memory-bool':
        task['execution']['job_memory_limit_bytes'] = True
    elif defect == 'agent-blank':
        task['agent_ref'] = ' '
    elif defect == 'agent-control':
        task['agent_ref'] = 'agent\n'
    elif defect == 'agent-type':
        task['agent_ref'] = True
    elif defect == 'configuration-digest':
        task['configuration_sha256'] = '0' * 64
    elif defect == 'protocol-missing':
        task['executor']['openapi'] = None
    with pytest.raises(deployment.LocalDeploymentError):
        base.parse(value)


@pytest.fixture
def task_source(local_source, runtime_bundle, tmp_path, monkeypatch):
    value, _, environment = local_source
    source, reference = runtime_bundle()
    resource = tmp_path / 'task-files'
    resource.mkdir()
    task = group(resource, reference)
    task['runtime_bundle'].update(manifest=str(source.manifest), root=str(source.root))
    image = base.image_bytes()
    with (resource / binary.IMAGE_NAME).open('xb') as stream:
        stream.write(image)
    archive = resource / binary.ARCHIVE_NAME
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as package:
        package.writestr(binary.IMAGE_NAME, image)
    monkeypatch.setattr(binary, 'RELEASE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    specification = {'info': {'version': '1.0.0'}, 'paths': {}}
    for route, method, status in protocol.REQUIRED_OPERATIONS:
        specification['paths'].setdefault(route, {})[method] = {'responses': {status: {}}}
    raw = base.encoded(specification)
    api = resource / 'openapi.json'
    with api.open('xb') as stream:
        stream.write(raw)
    monkeypatch.setattr(protocol, 'OPENAPI_BYTES', len(raw))
    monkeypatch.setattr(
        protocol, 'OPENAPI_BLOB', hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
    )
    value['task'] = task
    manifest = tmp_path / 'task-deployment.json'
    raw = base.encoded(value)
    with manifest.open('xb') as stream:
        stream.write(raw)
    environment = {
        **environment,
        deployment.MANIFEST_ENV: str(manifest),
        deployment.DIGEST_ENV: hashlib.sha256(raw).hexdigest(),
    }
    return value, manifest, environment, source


def test_actual_offline_preflight_pins_the_original_binary_and_bundle_manifest(task_source):
    value, _, environment, source = task_source
    with deployment.hold_configured_deployment(environment) as installed:
        assert installed.executor_binary.matches(installed.task_launch.plan.executor)
        image = installed.executor_binary.image
        with pytest.raises(PermissionError):
            image.rename(image.with_suffix('.changed'))
        with pytest.raises(PermissionError):
            source.manifest.rename(source.manifest.with_suffix('.changed'))
        assert installed.task_launch.configuration_sha256 == value['task']['configuration_sha256']
    image.rename(image.with_suffix('.released'))


@pytest.mark.parametrize('changed', ['image', 'archive', 'openapi', 'runtime'])
def test_changed_offline_resource_fails_before_any_application(task_source, changed):
    value, _, environment, source = task_source
    if changed == 'runtime':
        with (source.root / 'unexpected').open('xb') as stream:
            stream.write(b'not in fixed inventory')
    else:
        path = value['task']['executor'][changed]
        with open(path, 'ab') as stream:
            stream.write(b'changed')
    with (
        pytest.raises(deployment.LocalDeploymentError, match='SOURCE_UNVERIFIED'),
        deployment.hold_configured_deployment(environment),
    ):
        pytest.fail('Changed task resources reached the application')
