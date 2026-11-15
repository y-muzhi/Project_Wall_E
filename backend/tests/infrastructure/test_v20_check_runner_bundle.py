"""CHECK20 manifests use installed NTFS bytes, not catalogue labels."""

from dataclasses import replace
from hashlib import sha256
from time import monotonic

import pytest

from backend.app.infrastructure.check_runner_bundle import (
    CHECK_PROTOCOL,
    CheckResourceError,
    RegisteredCheckRunner,
    decode_runner_manifest,
    hold_check_runner_bundle,
)
from backend.app.infrastructure.content_paths import ContentPathError
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, PathBoundaryError
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
from backend.app.shared.validation import InvalidInput


def member(path, raw):
    return {'path': path, 'byte_count': len(raw), 'sha256': sha256(raw).hexdigest()}


def document(**changes):
    return {
        'schema_version': 1,
        'protocol_version': CHECK_PROTOCOL,
        'bundle_id': 'native-check-runner',
        'version': '1.0.0',
        'entry_ref': 'bin/entry',
        'runtime_refs': ['fixed-runtime:1'],
        'file_entries': [member('bin/entry', b'runner'), member('zero', b'')],
        'capabilities': ['CLI', 'CONTENT_INTEGRITY'],
        'platform_refs': ['windows-x64'],
        'admission_evidence_refs': ['lpac:sha256:' + 'b' * 64],
        **changes,
    }


@pytest.mark.parametrize(
    'changes',
    [
        {'ready': True},
        {'schema_version': True},
        {'protocol_version': 'latest'},
        {'entry_ref': 'C:/external.exe'},
        {'entry_ref': 'BIN/entry'},
        {'runtime_refs': ['same', 'same']},
        {'admission_evidence_refs': []},
        {'capabilities': ['PROJECT_COMMAND']},
        {'file_entries': [member('manifest.json', b'x')]},
        {'file_entries': [member('../entry', b'x')]},
        {'file_entries': [member('bin/entry', b'x'), member('BIN/new', b'y')]},
        {'file_entries': [{**member('bin/entry', b'x'), 'byte_count': True}]},
    ],
)
def test_runner_manifest_requires_bounded_exact_registered_inventory(changes):
    with pytest.raises((CheckResourceError, ContentPathError, InvalidInput)):
        decode_runner_manifest(canonical_input(document(**changes)).encode('utf-8'))


@pytest.fixture
def bundle(tmp_path):
    root = create_private_package(tmp_path / 'runner')
    (root / 'bin').mkdir()
    (root / 'bin/entry').write_bytes(b'runner')
    (root / 'zero').write_bytes(b'')
    manifest = document()
    raw = canonical_input(manifest).encode('utf-8')
    (root / 'manifest.json').write_bytes(raw)
    with PrivatePackageGuard(root) as held:
        directory = held.verify()
    return root, RegisteredCheckRunner(
        directory, sha256(raw).hexdigest(), 'native-check-runner', '1.0.0'
    )


def inspect(registration, cancelled=lambda: False):
    return hold_check_runner_bundle(registration, deadline=monotonic() + 20, cancelled=cancelled)


def test_runner_reads_exact_original_bytes_and_distinguishes_admission(bundle):
    root, registration = bundle
    with inspect(registration) as closure:
        assert closure.registration == registration
        assert closure.manifest.capabilities == ('CLI', 'CONTENT_INTEGRITY')
        assert not hasattr(closure, 'ready')
        with LocalPathGuard(root / 'bin/entry', directory=False) as native:
            assert closure.entry == native.verify()
        with pytest.raises(OSError), (root / 'manifest.json').open('ab'):
            raise AssertionError('The registered manifest must remain write-locked')
    with inspect(registration) as recovered:
        assert recovered == closure


@pytest.mark.parametrize(
    'fault', ['digest', 'identity', 'bytes', 'file', 'directory', 'links', 'stream']
)
def test_runner_declines_drift_extra_objects_and_aliases(bundle, fault):
    root, registration = bundle
    if fault == 'digest':
        registration = replace(registration, manifest_sha256='c' * 64)
    elif fault == 'identity':
        registration = replace(registration, bundle_id='different-runner')
    elif fault == 'bytes':
        (root / 'bin/entry').write_bytes(b'Runner')
    elif fault == 'file':
        (root / 'extra').write_bytes(b'extra')
    elif fault == 'directory':
        (root / 'extra').mkdir()
    elif fault == 'links':
        (root / 'other').hardlink_to(root / 'bin/entry')
    else:
        (root / 'bin/entry:hidden').write_bytes(b'extra stream')
    with (
        pytest.raises((CheckResourceError, PathBoundaryError, WorkspaceWriteError)),
        inspect(registration),
    ):
        raise AssertionError('Changed or ambiguous bundle was accepted')


def test_runner_rechecks_original_members_after_use(bundle):
    root, registration = bundle
    with pytest.raises(CheckResourceError, match='TREE_DIFFERS'), inspect(registration):
        (root / 'bin/entry').write_bytes(b'changed')
    with (
        pytest.raises(CheckResourceError, match='INTERRUPTED'),
        inspect(registration, cancelled=lambda: True),
    ):
        raise AssertionError('Cancelled bundle was accepted')
