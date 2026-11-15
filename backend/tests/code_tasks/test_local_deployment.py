"""Strict local startup source and actual NTFS pins; no Guard installation."""

import hashlib
import json

import pytest

from backend.app.code_tasks import local_deployment as deployment
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.tests.infrastructure.test_v20_windows_executable_pin import image_bytes
from backend.tests.requirements import test_v15_foundation as foundation

tmp_path = foundation.tmp_path

SID = 'S-1-5-21-1-2-3-1001'


def document(root, sid=SID):
    return {
        'schema_version': 1,
        'protocol_version': deployment.PROTOCOL,
        'registration': {
            'installation_ref': 'a' * 64,
            'backend_sid': sid,
            'guard_image': {
                'path': str(root / 'guard.exe'),
                'byte_count': 4096,
                'sha256': 'b' * 64,
            },
            'journal_root': str(root / 'journal'),
            'private_roots': [str(root / 'private')],
            'limits': {
                'max_file_bytes': 4096,
                'max_metadata_entries': 4096,
                'max_open_handles': 256,
                'max_metadata_bytes': 32768,
                'max_git_output_bytes': 4096,
                'max_git_seconds': 5,
            },
            'workspace_root': None,
        },
        'task': None,
    }


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def parse(value):
    return deployment.decode_local_deployment(encoded(value), backend_sid=SID)


@pytest.fixture
def local_source(tmp_path):
    value = document(tmp_path, current_operator_sid())
    for root in ('journal', 'private', 'workspace'):
        (tmp_path / root).mkdir()
    value['registration']['workspace_root'] = str(tmp_path / 'workspace')
    image = image_bytes()
    with (tmp_path / 'guard.exe').open('xb') as stream:
        stream.write(image)
    value['registration']['guard_image'].update(
        byte_count=len(image), sha256=hashlib.sha256(image).hexdigest()
    )
    manifest = tmp_path / 'deployment.json'
    raw = encoded(value)
    with manifest.open('xb') as stream:
        stream.write(raw)
    environment = {
        deployment.MANIFEST_ENV: str(manifest),
        deployment.DIGEST_ENV: hashlib.sha256(raw).hexdigest(),
    }
    return value, manifest, environment


def test_exact_registration_uses_existing_private_types_and_does_not_create_roots(tmp_path):
    value = document(tmp_path)
    result = parse(value)
    assert result.installation_ref == 'a' * 64
    assert result.backend_sid == SID and result.task_launch is None
    assert result.coding_models is None and not result.delivery_runtime_admitted
    assert result.private_roots == (tmp_path / 'private',)
    assert not result.guard_image.exists() and not result.journal_root.exists()


@pytest.mark.parametrize('where', ['root', 'registration', 'guard_image', 'limits'])
def test_unknown_fields_cannot_supply_runtime_or_privilege_flags(tmp_path, where):
    value = document(tmp_path)
    target = (
        value
        if where == 'root'
        else value['registration']
        if where == 'registration'
        else value['registration'][where]
    )
    target['ready'] = True
    with pytest.raises(deployment.LocalDeploymentError):
        parse(value)


@pytest.mark.parametrize(
    'field,value',
    [
        ('schema_version', True),
        ('schema_version', 1.0),
        ('schema_version', 2),
        ('protocol_version', 'other'),
        ('task', {'ready': True}),
    ],
)
def test_other_versions_and_incomplete_groups_fail_explicitly(tmp_path, field, value):
    source = document(tmp_path)
    source[field] = value
    with pytest.raises(deployment.LocalDeploymentError):
        parse(source)


@pytest.mark.parametrize('value', [True, 1.0, 0, -1, '4096', 2**53])
def test_guard_image_size_keeps_exact_integer_and_bounds(tmp_path, value):
    source = document(tmp_path)
    source['registration']['guard_image']['byte_count'] = value
    with pytest.raises(deployment.LocalDeploymentError):
        parse(source)


@pytest.mark.parametrize('value', [None, '', 'A' * 64, '0' * 64, 'a' * 63])
def test_guard_image_digest_cannot_be_forged_by_format_coercion(tmp_path, value):
    source = document(tmp_path)
    source['registration']['guard_image']['sha256'] = value
    with pytest.raises(deployment.LocalDeploymentError):
        parse(source)


@pytest.mark.parametrize(
    'value',
    ['relative', '../private', '//server/share/private', 'C:/private/../other', ' C:/private'],
)
def test_paths_are_explicit_local_absolute_without_normalizing_an_alias(tmp_path, value):
    source = document(tmp_path)
    source['registration']['journal_root'] = value
    with pytest.raises(deployment.LocalDeploymentError):
        parse(source)


@pytest.mark.parametrize(
    'defect', ['backend', 'duplicate-root', 'root-type', 'limit-bool', 'limit-too-long']
)
def test_scope_identity_and_original_limit_constraints_are_preserved(tmp_path, defect):
    source = document(tmp_path)
    registration = source['registration']
    if defect == 'backend':
        registration['backend_sid'] = SID + '2'
    elif defect == 'duplicate-root':
        registration['private_roots'] *= 2
    elif defect == 'root-type':
        registration['private_roots'] = 'C:/private'
    elif defect == 'limit-bool':
        registration['limits']['max_git_seconds'] = True
    else:
        registration['limits']['max_git_seconds'] = 301
    with pytest.raises(deployment.LocalDeploymentError):
        parse(source)


def test_absent_configuration_probes_nothing_and_bad_pair_never_opens_a_file(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No source IO without an explicit complete pair')

    monkeypatch.setattr(deployment, 'LockedFileSource', forbidden)
    with deployment.hold_configured_deployment({}) as result:
        assert result is None
    for source in ({deployment.MANIFEST_ENV: 'C:/private'}, {deployment.DIGEST_ENV: 'a' * 64}):
        with (
            pytest.raises(deployment.LocalDeploymentError, match='SOURCE_PAIR'),
            deployment.hold_configured_deployment(source),
        ):
            pytest.fail('Incomplete source pair was accepted')


def test_real_source_and_guard_are_held_until_application_exits(local_source):
    _, manifest, environment = local_source
    with deployment.hold_configured_deployment(environment) as installation:
        assert installation.workspace_root is not None
        with pytest.raises(PermissionError):
            manifest.rename(manifest.with_suffix('.moved'))
        with pytest.raises(PermissionError):
            installation.guard_image.rename(installation.guard_image.with_suffix('.moved'))
    manifest.rename(manifest.with_suffix('.moved'))
    installation.guard_image.rename(installation.guard_image.with_suffix('.moved'))


def test_wrong_digest_fails_before_current_identity_or_guard_checks(local_source, monkeypatch):
    _, _, environment = local_source
    environment[deployment.DIGEST_ENV] = 'c' * 64

    def forbidden():
        raise AssertionError('Digest must be checked before identity/resources')

    monkeypatch.setattr(deployment, '_current_backend_sid', forbidden)
    with (
        pytest.raises(deployment.LocalDeploymentError, match='SOURCE_DIGEST_DIFFERS'),
        deployment.hold_configured_deployment(environment),
    ):
        pytest.fail('Changed source was accepted')


def test_application_error_is_not_reclassified_as_a_deployment_error(local_source):
    _, manifest, environment = local_source
    with (
        pytest.raises(ValueError, match='original application failure'),
        deployment.hold_configured_deployment(environment),
    ):
        raise ValueError('original application failure')
    manifest.rename(manifest.with_suffix('.moved'))


def test_failure_messages_do_not_echo_configuration_or_source_paths(tmp_path):
    value = document(tmp_path)
    value['registration']['backend_sid'] = 'secret-marker'
    with pytest.raises(deployment.LocalDeploymentError) as failure:
        parse(value)
    assert 'secret-marker' not in str(failure.value)
    assert str(tmp_path) not in str(failure.value)
