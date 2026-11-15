from unittest.mock import patch
import pytest

from backend.app.infrastructure.content_secret_policy import (
    REFERENCE,
    load_secret_policy,
    inspect_registered_fixed_tree,
    SecretRestricted,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.content_manifest import ContentLimits
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.tests.code_tasks.test_git_commit_closure import Store, SOURCE


def inspect(data, commit, **changes):
    args = dict(
        format=data.format,
        read_object=data.read,
        source_fingerprint=SOURCE,
        verify_source=lambda: data.source,
        check_active=lambda: None,
        read_limits=ClosureLimits(100, 100, 100000, 1000000, 100),
        content_limits=ContentLimits(100000, 1000000, 100, 1),
        materialization_root=r'C:\owned',
        started_at=0,
        clock=lambda: data.now,
    )
    args.update(changes)
    return inspect_registered_fixed_tree(commit, secret_policy_ref=REFERENCE, **args)


@pytest.mark.parametrize(
    'path',
    [
        '.env',
        'src/.ENV.test',
        'docs/.env.example',
        '.netrc',
        'key/id_rsa',
        '.aws/credentials',
        'x/.AWS/CREDENTIALS',
    ],
)
def test_registered_paths_are_rejected_before_blob_read(path):
    data = Store()
    blob = data.put('blob', b'never open')
    # basename fixture tests one-component files; nested names tested on policy directly.
    with pytest.raises(SecretRestricted):
        load_secret_policy(REFERENCE).check_path(path)
    if '/' not in path:
        commit = data.commit(data.tree(path.encode(), blob))
        with pytest.raises(SecretRestricted):
            inspect(data, commit)
        assert all(request.object_type != 'blob' for request in data.calls)


@pytest.mark.parametrize(
    'marker',
    [
        b'-----BEGIN PRIVATE KEY-----',
        b'-----BEGIN RSA PRIVATE KEY-----',
        b'-----BEGIN EC PRIVATE KEY-----',
        b'-----BEGIN OPENSSH PRIVATE KEY-----',
        b'-----BEGIN ENCRYPTED PRIVATE KEY-----',
    ],
)
def test_registered_byte_markers_fail_entire_tree_and_hide_diagnostics(marker):
    data = Store()
    blob = data.put('blob', b'prefix\0' + marker + b'\nprivate fixture')
    commit = data.commit(data.tree(b'file.txt', blob))
    with pytest.raises(SecretRestricted) as error:
        inspect(data, commit)
    assert str(error.value) == 'SECRET_RESTRICTED'
    assert b'private fixture'.decode() not in repr(error.value)


def test_registered_policy_preserves_safe_binary_bytes():
    data = Store('sha256')
    body = b'\0\xffnormal public bytes\r\n'
    blob = data.put('blob', body)
    commit = data.commit(data.tree(b'source.bin', blob))
    result = inspect(data, commit)
    assert result.entries[0].byte_count == len(body)


@pytest.mark.parametrize('override', [{'check_file': lambda p, b: None}, {'check_path': None}])
def test_callbacks_cannot_be_overridden(override):
    data = Store()
    commit = data.commit(data.put('tree', b''))
    with pytest.raises(ConfigInvalid):
        inspect(data, commit, **override)
    assert data.calls == []


def test_unknown_or_tampered_policy_is_not_empty_allow(tmp_path):
    with pytest.raises(ConfigInvalid):
        load_secret_policy('../unknown')
    from backend.app.infrastructure import content_secret_policy as module

    path = tmp_path / 'changed-policy'
    with path.open('xb') as stream:
        stream.write(b'{}')
    with patch.object(module, 'RESOURCE', path):
        with pytest.raises(ConfigInvalid):
            load_secret_policy(REFERENCE)
    with patch.object(module, 'RESOURCE', tmp_path / 'missing'):
        with pytest.raises(ConfigInvalid):
            load_secret_policy(REFERENCE)
