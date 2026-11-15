"""Archive and source boundaries for the actual browser package preparer."""

import io
import json
import stat
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZipInfo
import pytest
from tools import windows_browser_package as package
from backend.app.infrastructure.content_paths import ContentPathError
from backend.tests.requirements.test_v15_foundation import tmp_path


def archive(entries):
    data = io.BytesIO()
    with ZipFile(data, 'w') as stream:
        for name, value in entries:
            stream.writestr(name, value)
    return data.getvalue()


@pytest.mark.parametrize(
    'names',
    [
        ('../outside.py',),
        ('drive:stream',),
        ('alias.py', 'ALIAS.py'),
        ('same.py', 'same.py'),
        ('file', 'file/child'),
    ],
)
def test_bad_archive_namespace_rejects_before_output(tmp_path, names):
    raw = archive([(name, b'value') for name in names])
    with pytest.raises(ContentPathError):
        package.extract_archive(raw, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_symbolic_archive_member_and_size_limit_refuse_before_output(tmp_path, monkeypatch):
    link = ZipInfo('link')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match='TYPE_UNSUPPORTED'):
        package.extract_archive(archive([(link, b'target')]), tmp_path / 'link-output')
    monkeypatch.setattr(package, 'MAX_TOTAL_BYTES', 2)
    with pytest.raises(ValueError, match='SIZE_LIMIT'):
        package.extract_archive(archive([('value', b'123')]), tmp_path / 'size-output')
    assert not (tmp_path / 'size-output').exists()


def test_archive_materializes_only_declared_original_file_bytes(tmp_path):
    raw = archive([('directory/', b''), ('directory/value.bin', b'\x00\xff')])
    package.extract_archive(raw, tmp_path / 'output')
    assert (tmp_path / 'output/directory/value.bin').read_bytes() == b'\x00\xff'


def test_fixed_archive_checks_hash_and_hidden_stream(tmp_path):
    path = tmp_path / 'archive.zip'
    path.write_bytes(b'archive bytes')
    expected = sha256(path.read_bytes()).hexdigest()
    assert package.fixed_archive(path, expected) == b'archive bytes'
    with pytest.raises(ValueError, match='SHA256_DIFFERS'):
        package.fixed_archive(path, '0' * 64)
    stream = tmp_path / 'archive.zip:hidden'
    stream.write_bytes(b'unregistered')
    try:
        with pytest.raises(RuntimeError, match='ALTERNATE_STREAM_UNSUPPORTED'):
            package.fixed_archive(path, expected)
    finally:
        stream.unlink()


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'path', 'url', 'version', 'boolean'])
def test_source_lock_rejects_unfixed_or_ambiguous_input(change):
    path = Path(__file__).resolve().parents[2] / 'browser-headless-runtime.lock.json'
    value = json.loads(path.read_bytes())
    package.decode_browser_lock(json.dumps(value).encode())
    if change == 'unknown':
        value['ready'] = True
    elif change == 'duplicate':
        value['archives'][1] = value['archives'][0]
    elif change == 'path':
        value['archives'][0]['filename'] = '../package.whl'
    elif change == 'url':
        value['archives'][0]['url'] = 'https://example.invalid/package.whl'
    elif change == 'version':
        value['chromium'] = 'latest'
    else:
        value['schema_version'] = True
    with pytest.raises(ValueError):
        package.decode_browser_lock(json.dumps(value).encode())


def test_full_prepared_tree_rejects_extra_empty_directory_and_same_size_tamper(tmp_path):
    from backend.tests.code_tasks.test_local_deployment import image_bytes

    root = tmp_path / 'package'
    root.mkdir()
    (root / 'python.exe').write_bytes(image_bytes())
    (root / 'driver.py').write_bytes(b'fixed bootstrap')
    (root / 'chrome-headless-shell-win64').mkdir()
    (root / 'chrome-headless-shell-win64/chrome-headless-shell.exe').write_bytes(image_bytes())
    raw = package.runner_manifest(root, 'a' * 64)
    (root / 'manifest.json').write_bytes(raw)
    digest, count, total = package.verify_prepared_package(root)
    assert digest == sha256(raw).hexdigest() and count == 4 and total > 0

    extra = root / 'unexpected'
    extra.mkdir()
    with pytest.raises(ValueError, match='TREE_DIFFERS'):
        package.verify_prepared_package(root)
    extra.rmdir()
    target = root / 'driver.py'
    original = target.read_bytes()
    target.write_bytes(b'X' * len(original))
    with pytest.raises(ValueError, match='TREE_DIFFERS'):
        package.verify_prepared_package(root)


@pytest.mark.parametrize('limit', [False, 0, -1, 32769])
def test_launch_read_budget_rejects_invalid_override_without_file_leases(tmp_path, limit):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_task_workspace_tree import hold_task_workspace_tree
    from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError

    path = tmp_path / 'runtime'
    path.mkdir()
    (path / 'input').write_bytes(b'input')
    with LocalPathGuard(path, directory=True) as guard:
        with pytest.raises(WorkspaceWriteError, match='HANDLE_LIMIT_INVALID'):
            with hold_task_workspace_tree(
                path, guard.verify(), '0' * 64, lambda: None, launch_handle_limit=limit
            ):
                raise AssertionError('invalid budget admitted')
    # Failure must leave no leaked original file lease.
    (path / 'input').write_bytes(b'updated')


def test_sdk_subtree_keeps_only_runtime_but_still_validates_other_names(tmp_path):
    raw = archive(
        [
            ('playwright/driver/node.exe', b'fixed SDK runtime'),
            ('playwright/sync_api/__init__.py', b'old Python wrapper'),
        ]
    )
    package.extract_archive(raw, tmp_path / 'runtime', prefix='playwright/driver/')
    assert (tmp_path / 'runtime/playwright/driver/node.exe').read_bytes() == b'fixed SDK runtime'
    assert not (tmp_path / 'runtime/playwright/sync_api').exists()
    raw = archive(
        [
            ('playwright/driver/node.exe', b'fixed SDK runtime'),
            ('not-selected/../../outside', b'invalid path'),
        ]
    )
    with pytest.raises(ContentPathError):
        package.extract_archive(raw, tmp_path / 'refused', prefix='playwright/driver/')
    assert not (tmp_path / 'refused').exists()
