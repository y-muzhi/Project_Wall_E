"""Each fixed Git verification reads current original bytes and rejects hidden aliases/streams."""

import base64
import hashlib
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.app.infrastructure import git_bundle as bundle
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.tests.code_tasks.test_git_bundle import archive_bytes, pe
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def fixed_package(tmp_path, monkeypatch):
    root = tmp_path / 'win-x64'
    root.mkdir()
    archive = archive_bytes(
        [
            ('cmd/git.exe', pe()),
            ('empty/', b''),
            ('data/raw', b'raw\r\n'),
        ]
    )
    (root / 'source.zip').write_bytes(archive)
    monkeypatch.setattr(bundle, 'BUNDLE_PARENT', tmp_path)
    monkeypatch.setattr(bundle, 'ARCHIVE_BYTES', len(archive))
    monkeypatch.setattr(bundle, 'ARCHIVE_SHA256', hashlib.sha256(archive).hexdigest())
    with ZipFile(BytesIO(archive)) as source:
        inventory, expanded = bundle._inventory(source, root)
        members = bundle._extract(source, root, inventory)
    encoded = (
        json.dumps(
            bundle._manifest(members), ensure_ascii=False, sort_keys=True, separators=(',', ':')
        )
        + '\n'
    ).encode()
    (root / 'manifest.json').write_bytes(encoded)
    expected = len(members), expanded, hashlib.sha256(encoded).hexdigest()
    assert bundle.verify_bundle_bytes() == expected
    return root, expected


def test_same_size_same_identity_same_mtime_content_is_rechecked_after_success(fixed_package):
    root, expected = fixed_package
    target = root / 'data/raw'
    original = target.stat()
    assert bundle.verify_bundle_bytes() == expected
    with target.open('r+b') as stream:
        stream.write(b'bad\r\n')
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    after = target.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        original.st_dev,
        original.st_ino,
        original.st_size,
        original.st_mtime_ns,
    )
    with pytest.raises(bundle.GitBundleError, match='MEMBER_BYTES_DIFFER'):
        bundle.verify_bundle_bytes()


@pytest.mark.parametrize(
    'kind', ['extra-file', 'extra-directory', 'missing-file', 'missing-directory']
)
def test_current_complete_inventory_is_required_on_every_call(fixed_package, kind):
    root, _ = fixed_package
    if kind == 'extra-file':
        (root / 'extra').write_bytes(b'')
    elif kind == 'extra-directory':
        (root / 'unexpected-empty').mkdir()
    elif kind == 'missing-file':
        (root / 'data/raw').unlink()
    else:
        (root / 'empty').rmdir()
    with pytest.raises(bundle.GitBundleError, match='OBJECTS_DIFFER'):
        bundle.verify_bundle_bytes()


@pytest.mark.parametrize('path', ['source.zip', 'manifest.json'])
def test_metadata_is_not_accepted_from_a_previous_success(fixed_package, path):
    root, _ = fixed_package
    target = root / path
    with target.open('r+b') as stream:
        old = stream.read(1)
        stream.seek(0)
        stream.write(bytes([old[0] ^ 1]))
    reason = 'ARCHIVE_DIGEST_DIFFERS' if path == 'source.zip' else 'MANIFEST_DIFFERS'
    with pytest.raises(bundle.GitBundleError, match=reason):
        bundle.verify_bundle_bytes()


@pytest.mark.parametrize('name', ['data/raw', 'empty', '.', 'source.zip', 'manifest.json'])
def test_named_stream_is_rejected_on_files_directories_and_metadata(fixed_package, name):
    root, expected = fixed_package
    target = root if name == '.' else root / name
    stream = target.with_name(target.name + ':fixture')
    with stream.open('xb') as output:
        output.write(b'owned hidden data')
    try:
        with pytest.raises(bundle.GitBundleError, match='ALTERNATE_STREAM_UNSUPPORTED'):
            bundle.verify_bundle_bytes()
    finally:
        stream.unlink()
    assert bundle.verify_bundle_bytes() == expected


def test_hard_link_alias_is_rejected_even_with_identical_bytes(fixed_package):
    root, expected = fixed_package
    target = root / 'data/raw'
    alias = root.parent / 'owned-alias'
    os.link(target, alias)
    try:
        with pytest.raises(PathBoundaryError, match='MULTIPLE_HARD_LINKS_REJECTED'):
            bundle.verify_bundle_bytes()
    finally:
        alias.unlink()
    assert bundle.verify_bundle_bytes() == expected


def test_expected_directory_cannot_be_replaced_by_junction(fixed_package):
    root, _ = fixed_package
    target = root.parent / 'owned-junction-target'
    target.mkdir()
    marker = target / 'never-read'
    marker.write_bytes(b'outside fixed package')
    alias = root / 'empty'
    alias.rmdir()
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = (
        'New-Item -ItemType Junction -Path '
        + quote(alias)
        + ' -Target '
        + quote(target)
        + ' -ErrorAction Stop | Out-Null'
    )
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        capture_output=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises((PathBoundaryError, bundle.GitBundleError)):
            bundle.verify_bundle_bytes()
    finally:
        assert alias.parent.resolve() == root.resolve() and alias.is_junction()
        alias.rmdir()
    assert marker.read_bytes() == b'outside fixed package'


def test_current_hash_uses_actual_read_only_data_lease(fixed_package, monkeypatch):
    root, expected = fixed_package
    target = root / 'data/raw'
    original_read = LockedFileSource._read
    observed = []

    def inspect(source, *args, **kwargs):
        snapshot = original_read(source, *args, **kwargs)
        if source._path == target:
            observed.append(snapshot.sha256)
            # Test the kernel sharing boundary while the exact hash source is held.
            with pytest.raises(PermissionError):
                with target.open('r+b'):
                    raise AssertionError('An active original hash source must deny writes')
        return snapshot

    monkeypatch.setattr(LockedFileSource, '_read', inspect)
    assert bundle.verify_bundle_bytes() == expected
    assert observed
