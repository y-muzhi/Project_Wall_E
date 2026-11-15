"""Actual NTFS inventory and atomic publication; no installed native executor."""

import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from backend.app.infrastructure import opencode_runtime_preparation as preparation
from backend.app.infrastructure.opencode_runtime_bundle import (
    OpenCodeRuntimeBundle,
    verify_opencode_runtime_bundle,
)
from backend.tests.infrastructure import test_v20_opencode_runtime_bundle as original

runtime_bundle = original.runtime_bundle
tmp_path = original.tmp_path


def publish(source, destination, cancelled=lambda: False):
    return preparation.publish_runtime_manifest(
        source.root, destination, deadline=monotonic() + 15, cancelled=cancelled
    )


def test_preparation_is_deterministic_reuses_original_verifier_and_changes_no_source(
    runtime_bundle, tmp_path
):
    source, _ = runtime_bundle()
    before = {
        str(p.relative_to(source.root)): p.read_bytes()
        for p in source.root.rglob('*')
        if p.is_file()
    }
    first = preparation.prepare_runtime_manifest(
        source.root, deadline=monotonic() + 15, cancelled=lambda: False
    )
    second = preparation.prepare_runtime_manifest(
        source.root, deadline=monotonic() + 15, cancelled=lambda: False
    )
    assert first == second and first.file_count == 6
    assert first.raw.endswith(b'\n')
    destination = tmp_path / 'prepared.json'
    assert publish(source, destination) == first
    assert (
        verify_opencode_runtime_bundle(
            OpenCodeRuntimeBundle(destination, source.root),
            first.reference,
            deadline=monotonic() + 15,
            cancelled=lambda: False,
        )
        == 6
    )
    assert before == {
        str(p.relative_to(source.root)): p.read_bytes()
        for p in source.root.rglob('*')
        if p.is_file()
    }
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


@pytest.mark.parametrize('damage', ['lsp', 'plugin', 'lock', 'missing-dependency'])
def test_invalid_prepared_bytes_do_not_publish_a_manifest(runtime_bundle, tmp_path, damage):
    source, _ = runtime_bundle(damage)
    destination = tmp_path / 'rejected.json'
    with pytest.raises((preparation.bundle.OpenCodeRuntimeBundleError, ValueError)):
        publish(source, destination)
    assert not destination.exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_an_existing_manifest_is_rejected_before_reading_or_replacing_any_source(
    runtime_bundle, monkeypatch
):
    source, _ = runtime_bundle()
    original = source.manifest.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('Existing destination must fail before inventory')

    monkeypatch.setattr(preparation, 'prepare_runtime_manifest', forbidden)
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='ALREADY_EXISTS'):
        publish(source, source.manifest)
    assert source.manifest.read_bytes() == original


def test_manifest_cannot_be_written_inside_the_runtime_tree(runtime_bundle):
    source, _ = runtime_bundle()
    destination = source.root / 'new-manifest.json'
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='OUTSIDE_TREE'):
        publish(source, destination)
    assert not destination.exists()


def test_empty_or_added_directory_is_not_silently_dropped_from_the_inventory(
    runtime_bundle, tmp_path
):
    source, _ = runtime_bundle()
    (source.root / 'empty').mkdir()
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='TREE_DIFFERS'):
        publish(source, tmp_path / 'rejected.json')


def test_source_change_between_inventory_and_full_verification_is_rejected(
    runtime_bundle, tmp_path, monkeypatch
):
    source, _ = runtime_bundle()
    original = preparation.bundle._verify_tree

    def changed(*args, **kwargs):
        (source.root / '.gitignore').write_bytes(b'changed bytes')
        return original(*args, **kwargs)

    monkeypatch.setattr(preparation.bundle, '_verify_tree', changed)
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='MEMBER_DIFFERS'):
        publish(source, tmp_path / 'rejected.json')
    assert not (tmp_path / 'rejected.json').exists()


def test_competing_destination_is_never_overwritten_and_temporary_name_is_cleaned(
    runtime_bundle, tmp_path, monkeypatch
):
    source, _ = runtime_bundle()
    destination = tmp_path / 'competing.json'
    original = os.link

    def raced(temporary, target):
        with open(target, 'xb') as stream:
            stream.write(b'other original manifest')
        return original(temporary, target)

    monkeypatch.setattr(preparation.os, 'link', raced)
    with pytest.raises(FileExistsError):
        publish(source, destination)
    assert destination.read_bytes() == b'other original manifest'
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


@pytest.mark.parametrize('limit', ['entries', 'files', 'bytes'])
def test_preparation_limits_fail_before_publication(runtime_bundle, tmp_path, monkeypatch, limit):
    source, _ = runtime_bundle()
    if limit == 'entries':
        monkeypatch.setattr(preparation, 'MAX_ENTRIES', 1)
    elif limit == 'files':
        monkeypatch.setattr(preparation.bundle, 'MAX_FILES', 1)
    else:
        monkeypatch.setattr(preparation.bundle, 'MAX_BYTES', 1)
    with pytest.raises(RuntimeError):
        publish(source, tmp_path / 'rejected.json')
    assert not (tmp_path / 'rejected.json').exists()


def test_cancellation_during_inventory_leaves_no_publication(runtime_bundle, tmp_path):
    source, _ = runtime_bundle()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 3

    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='INTERRUPTED'):
        publish(source, tmp_path / 'cancelled.json', cancelled)
    assert not (tmp_path / 'cancelled.json').exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_actual_cli_only_publishes_verified_offline_metadata(runtime_bundle, tmp_path):
    source, _ = runtime_bundle()
    root = Path(__file__).resolve().parents[3]
    destination = tmp_path / 'cli-prepared.json'
    command = [
        sys.executable,
        '-B',
        str(root / 'tools/prepare-opencode-runtime.py'),
        '--bundle-root',
        str(source.root),
        '--manifest',
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert 'runtime admission unchanged' in result.stdout
    assert destination.exists()
    original = destination.read_bytes()
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert repeated.returncode != 0
    assert destination.read_bytes() == original
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_final_temporary_manifest_verification_failure_cleans_only_own_file(
    runtime_bundle, tmp_path, monkeypatch
):
    source, _ = runtime_bundle()
    destination = tmp_path / 'final-rejected.json'
    verify = preparation.bundle.verify_opencode_runtime_bundle

    def changed(*args, **kwargs):
        target = source.root / '.gitignore'
        original_bytes = target.read_bytes()
        target.write_bytes(b'X' + original_bytes[1:])
        return verify(*args, **kwargs)

    monkeypatch.setattr(preparation.bundle, 'verify_opencode_runtime_bundle', changed)
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='MEMBER_DIFFERS'):
        publish(source, destination)
    assert not destination.exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_cancel_after_verified_temporary_manifest_never_publishes(
    runtime_bundle, tmp_path, monkeypatch
):
    source, _ = runtime_bundle()
    destination = tmp_path / 'cancelled-after-verify.json'
    cancelled = False
    verify = preparation.bundle.verify_opencode_runtime_bundle

    def checked(*args, **kwargs):
        nonlocal cancelled
        result = verify(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(preparation.bundle, 'verify_opencode_runtime_bundle', checked)
    with pytest.raises(preparation.bundle.OpenCodeRuntimeBundleError, match='INTERRUPTED'):
        publish(source, destination, lambda: cancelled)
    assert not destination.exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_two_real_publishers_keep_one_complete_original_manifest(runtime_bundle, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    source, _ = runtime_bundle()
    destination = tmp_path / 'one-original.json'

    def attempt(_):
        try:
            return publish(source, destination)
        except (FileExistsError, preparation.bundle.OpenCodeRuntimeBundleError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    successful = [item for item in results if isinstance(item, preparation.PreparedRuntimeManifest)]
    assert len(successful) == 1, results
    assert destination.read_bytes() == successful[0].raw
    assert (
        verify_opencode_runtime_bundle(
            OpenCodeRuntimeBundle(destination, source.root),
            successful[0].reference,
            deadline=monotonic() + 15,
            cancelled=lambda: False,
        )
        == 6
    )
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_replaced_source_with_identical_bytes_cannot_borrow_original_file_identity(
    runtime_bundle, tmp_path, monkeypatch
):
    from backend.app.infrastructure.windows_config_source import ConfigReadError

    source, _ = runtime_bundle()
    verify = preparation.bundle._verify_tree

    def replaced(*args, **kwargs):
        target = source.root / '.gitignore'
        before = target.read_bytes()
        target.rename(tmp_path / 'retained-original-input')
        with target.open('xb') as stream:
            stream.write(before)
        return verify(*args, **kwargs)

    monkeypatch.setattr(preparation.bundle, '_verify_tree', replaced)
    destination = tmp_path / 'identity-rejected.json'
    with pytest.raises(ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
        publish(source, destination)
    assert not destination.exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []


def test_hardlinked_runtime_file_is_not_treated_as_an_independent_source(runtime_bundle, tmp_path):
    from backend.app.infrastructure.windows_local_paths import PathBoundaryError

    source, _ = runtime_bundle()
    target = source.root / '.gitignore'
    os.link(target, tmp_path / 'external-alias')
    destination = tmp_path / 'alias-rejected.json'
    with pytest.raises(PathBoundaryError, match='MULTIPLE_HARD_LINKS_REJECTED'):
        publish(source, destination)
    assert not destination.exists()
    assert list(tmp_path.glob('.opencode-manifest-*')) == []
