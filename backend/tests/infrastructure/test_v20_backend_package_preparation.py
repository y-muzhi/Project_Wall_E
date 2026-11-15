"""Actual NTFS source copies and original protected-program manifests; no fake build success."""

from hashlib import sha256

import pytest

from backend.app.infrastructure.guard_backend_program import decode_backend_program_manifest
from backend.tests.code_tasks.test_local_deployment import image_bytes
from backend.tests.requirements.test_v15_foundation import tmp_path
from tools import windows_backend_package as preparation


def test_source_snapshot_copies_actual_original_bytes_and_later_drift_changes_input(
    tmp_path, monkeypatch
):
    source = tmp_path / 'source.dat'
    raw = b'original\r\n\x00'
    source.write_bytes(raw)
    monkeypatch.setattr(preparation, 'input_files', lambda *args: {'backend/input.dat': source})
    target = tmp_path / 'snapshot'
    target.mkdir()
    original = preparation.snapshot_sources(tmp_path, None, target)
    assert (target / 'backend/input.dat').read_bytes() == raw
    assert preparation.snapshot_sources(tmp_path, None) == original
    assert original['backend/input.dat'][1:] == (len(raw), sha256(raw).hexdigest())
    with source.open('ab') as stream:
        stream.write(b'changed')
    after = preparation.snapshot_sources(tmp_path, None)
    assert after != original and preparation.source_digest(after) != preparation.source_digest(
        original
    )


def package(tmp_path):
    root = tmp_path / 'new-package'
    root.mkdir()
    # Synthetic valid PE only exercises preparation validation, never executes.
    (root / 'walle-backend.exe').write_bytes(image_bytes())
    (root / 'data').mkdir()
    (root / 'data/value.dat').write_bytes(b'fixed data')
    return root


def test_manifest_is_original_canonical_policy_and_does_not_self_admit(tmp_path):
    root = package(tmp_path)
    raw, digest, count, total = preparation.package_manifest(root, 'WALLE-BACKEND-PREPARED-FIXTURE')
    spec = decode_backend_program_manifest(raw, expected_sha256=digest)
    assert spec.entry == 'walle-backend.exe' and count == 2 and total > 0
    assert not hasattr(spec, 'ready') and not (root / 'backend-program.v1.json').exists()


def test_preparation_refuses_unrepresentable_empty_directory(tmp_path):
    root = package(tmp_path)
    (root / 'extra-empty').mkdir()
    with pytest.raises(preparation.BackendBuildError, match='EMPTY_OR_EXTRA_DIRECTORY'):
        preparation.package_manifest(root, 'WALLE-BACKEND-PREPARED-FIXTURE')


def test_actual_preparation_refuses_unregistered_alternate_stream(tmp_path):
    root = package(tmp_path)
    stream = root / 'data/value.dat:fixture'
    stream.write_bytes(b'hidden input')
    try:
        with pytest.raises(RuntimeError, match='ALTERNATE_STREAM_UNSUPPORTED'):
            preparation.package_manifest(root, 'WALLE-BACKEND-PREPARED-FIXTURE')
    finally:
        stream.unlink()


def test_frontend_input_detects_identity_and_inventory_drift_but_ignores_old_dist(tmp_path):
    import os

    frontend = tmp_path / 'frontend'
    source = frontend / 'src'
    source.mkdir(parents=True)
    entry = frontend / 'index.html'
    entry.write_bytes(b'<main></main>')
    module = source / 'feature.ts'
    module.write_bytes(b'export const version = 1;')
    before = preparation.frontend_sources(tmp_path)
    assert 'frontend-source/src/feature.ts' in before

    stale = frontend / 'dist'
    stale.mkdir()
    (stale / 'index.html').write_bytes(b'old output')
    assert preparation.frontend_sources(tmp_path) == before

    # Same byte content with a different original NTFS object must fail source CAS.
    candidate = source / 'owned-replacement.tmp'
    candidate.write_bytes(module.read_bytes())
    os.replace(candidate, module)
    changed_identity = preparation.frontend_sources(tmp_path)
    assert changed_identity != before
    assert (
        changed_identity['frontend-source/src/feature.ts'][1:]
        == before['frontend-source/src/feature.ts'][1:]
    )

    addition = source / 'new-feature.ts'
    addition.write_bytes(b'export const added = true;')
    added = preparation.frontend_sources(tmp_path)
    assert added != changed_identity
    assert preparation.source_digest(added) != preparation.source_digest(changed_identity)
    addition.unlink()
    assert preparation.frontend_sources(tmp_path) == changed_identity


def test_frontend_input_refuses_actual_source_alternate_stream(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    entry = frontend / 'index.html'
    entry.write_bytes(b'<main></main>')
    stream = frontend / 'index.html:fixture'
    stream.write_bytes(b'not a registered source')
    try:
        with pytest.raises(RuntimeError, match='ALTERNATE_STREAM_UNSUPPORTED'):
            preparation.frontend_sources(tmp_path)
    finally:
        stream.unlink()
