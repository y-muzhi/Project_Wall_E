"""Actual NTFS program inventory/lease boundaries; synthetic PE fixtures never execute."""

import os
from hashlib import sha256
from pathlib import Path

import pytest

from backend.app.infrastructure.program_manifest import (
    BACKEND_PROGRAM_POLICY,
    GUARD_PROGRAM_POLICY,
    ProgramManifestError,
    decode_program_manifest,
)
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.tests.code_tasks.test_local_deployment import image_bytes
from backend.tests.requirements.test_v15_foundation import tmp_path
from tools.windows_program_package import package_manifest, validate_program_destination


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / 'guard-program'
    root.mkdir()
    entry = root / GUARD_PROGRAM_POLICY.entry_name
    with entry.open('xb') as stream:
        stream.write(image_bytes())
    internal = root / '_internal'
    internal.mkdir()
    with (internal / 'runtime.dat').open('xb') as stream:
        stream.write(b'fixed actual fixture')
    raw, digest, count, size = package_manifest(
        root, 'WALLE-GUARD-PACKAGE-FIXTURE', policy=GUARD_PROGRAM_POLICY
    )
    with (root / GUARD_PROGRAM_POLICY.manifest_name).open('xb') as stream:
        stream.write(raw)
    assert count == 2 and size > 0
    return root, digest


def lease(prepared, **kwargs):
    root, digest = prepared
    return ProgramPackageLease(root, expected_sha256=digest, policy=GUARD_PROGRAM_POLICY, **kwargs)


@pytest.mark.parametrize('policy', [BACKEND_PROGRAM_POLICY, GUARD_PROGRAM_POLICY])
def test_original_policy_requires_its_actual_dedicated_entry_and_canonical_bytes(policy):
    data = {
        'policy_version': policy.version,
        'program_ref': 'WALLE-PROGRAM-POLICY-FIXTURE',
        'entry': policy.entry_name,
        'files': [{'path': policy.entry_name, 'byte_count': 8, 'sha256': 'a' * 64}],
    }
    raw = _bytes(data)
    decoded = decode_program_manifest(raw, expected_sha256=sha256(raw).hexdigest(), policy=policy)
    assert decoded.entry == policy.entry_name and not hasattr(decoded, 'ready')
    other = GUARD_PROGRAM_POLICY if policy == BACKEND_PROGRAM_POLICY else BACKEND_PROGRAM_POLICY
    with pytest.raises(ProgramManifestError, match='MANIFEST_REQUIRED'):
        decode_program_manifest(raw, expected_sha256=sha256(raw).hexdigest(), policy=other)
    data['entry'] = 'python.exe'
    altered = _bytes(data)
    with pytest.raises(ProgramManifestError, match='DEDICATED_REGISTERED'):
        decode_program_manifest(altered, expected_sha256=sha256(altered).hexdigest(), policy=policy)


def test_guard_entry_must_be_the_original_root_executable():
    data = {
        'policy_version': GUARD_PROGRAM_POLICY.version,
        'program_ref': 'WALLE-GUARD-ROOT-FIXTURE',
        'entry': 'nested/' + GUARD_PROGRAM_POLICY.entry_name,
        'files': [
            {
                'path': 'nested/' + GUARD_PROGRAM_POLICY.entry_name,
                'byte_count': 8,
                'sha256': 'a' * 64,
            }
        ],
    }
    raw = _bytes(data)
    with pytest.raises(ProgramManifestError, match='DEDICATED_REGISTERED_GUARD'):
        decode_program_manifest(
            raw, expected_sha256=sha256(raw).hexdigest(), policy=GUARD_PROGRAM_POLICY
        )


def test_actual_original_files_cannot_be_overwritten_or_renamed_until_release(prepared):
    root, _ = prepared
    target = root / '_internal/runtime.dat'
    before = target.read_bytes()
    with lease(prepared) as held:
        assert held.verify().program_ref == 'WALLE-GUARD-PACKAGE-FIXTURE'
        held.verify_running_entry(root / GUARD_PROGRAM_POLICY.entry_name)
        with pytest.raises(ProgramManifestError, match='RUNNING_ENTRY_DIFFERS'):
            held.verify_running_entry(Path(os.sys.executable))
        with pytest.raises(PermissionError):
            with target.open('r+b'):
                pytest.fail('Original native read-sharing lease must deny a writer')
        with pytest.raises(PermissionError):
            target.rename(target.with_suffix('.moved'))
        assert target.read_bytes() == before
    target.rename(target.with_suffix('.released'))
    held.close()
    with pytest.raises(ProgramManifestError, match='LEASE_CLOSED'):
        held.verify()


@pytest.mark.parametrize('extra_kind', ['file', 'empty-directory'])
def test_added_inventory_members_are_rejected_during_original_lease(prepared, extra_kind):
    root, _ = prepared
    with lease(prepared) as held:
        extra = root / 'unregistered'
        if extra_kind == 'file':
            with extra.open('xb') as stream:
                stream.write(b'unregistered original')
        else:
            extra.mkdir()
        with pytest.raises(ProgramManifestError, match='MEMBERS_DIFFER'):
            held.verify()
    root.rename(root.with_name('released-extra-inventory'))


@pytest.mark.parametrize('change', ['missing', 'changed-bytes', 'wrong-digest', 'hardlink'])
def test_initial_resource_mismatch_is_rejected_and_original_owners_close(
    prepared, tmp_path, change
):
    root, digest = prepared
    target = root / '_internal/runtime.dat'
    if change == 'missing':
        target.unlink()
    elif change == 'changed-bytes':
        with target.open('ab') as stream:
            stream.write(b'changed')
    elif change == 'wrong-digest':
        digest = 'b' * 64
    else:
        os.link(target, tmp_path / 'second-hardlink')
    with pytest.raises((RuntimeError, ValueError)):
        ProgramPackageLease(root, expected_sha256=digest, policy=GUARD_PROGRAM_POLICY)
    root.rename(root.with_name('released-rejected-package'))


@pytest.mark.parametrize('relative', ['_internal/runtime.dat', '_internal'])
def test_alternate_streams_are_rejected_in_the_actual_package(prepared, relative):
    root, _ = prepared
    stream_path = root / (relative + ':unregistered')
    with stream_path.open('xb') as stream:
        stream.write(b'hidden actual fixture')
    try:
        with pytest.raises(RuntimeError, match='ALTERNATE_STREAM'):
            lease(prepared)
    finally:
        stream_path.unlink()
    root.rename(root.with_name('released-alternate-stream'))


def test_cancellation_never_claims_a_verified_package(prepared):
    with pytest.raises(ProgramManifestError, match='CANCELLED_OR_EXPIRED'):
        lease(prepared, cancelled=lambda: True)
    root, _ = prepared
    root.rename(root.with_name('released-cancelled-package'))


def test_unknown_close_retains_original_owner_and_is_never_retried(prepared, monkeypatch):
    held = lease(prepared)
    calls = []
    original = held._entry.close

    def unknown_after_close():
        original()
        calls.append('close')
        raise RuntimeError('Explicit unknown-close fixture')

    monkeypatch.setattr(held._entry, 'close', unknown_after_close)
    with pytest.raises(ProgramManifestError, match='CLOSE_UNVERIFIED') as first:
        held.close()
    assert first.value.retained_owner is held and calls == ['close']
    with pytest.raises(ProgramManifestError, match='CLOSE_PREVIOUSLY_UNVERIFIED') as second:
        held.close()
    assert second.value.retained_owner is held and calls == ['close']


def test_final_destination_limits_are_checked_before_any_publish(prepared, tmp_path):
    root, digest = prepared
    raw = (root / GUARD_PROGRAM_POLICY.manifest_name).read_bytes()
    destination = tmp_path / ('original-destination-' * 10)
    assert not destination.exists()
    with pytest.raises(ValueError, match='CONTENT_FULL_PATH_TOO_LONG'):
        validate_program_destination(destination, raw, digest, policy=GUARD_PROGRAM_POLICY)
    assert not destination.exists()
    spec = validate_program_destination(
        tmp_path / 'valid-final-location', raw, digest, policy=GUARD_PROGRAM_POLICY
    )
    assert spec.manifest_sha256 == digest


def test_backend_cli_preserves_actual_unknown_package_close_owner(prepared, monkeypatch):
    from tools import windows_backend_package as backend

    held = lease(prepared)
    original_close = held._entry.close
    calls = []

    def unknown_after_native_close():
        original_close()
        calls.append('close')
        raise RuntimeError('Owned native close outcome is unknown')

    monkeypatch.setattr(held._entry, 'close', unknown_after_native_close)
    with pytest.raises(ProgramManifestError, match='CLOSE_UNVERIFIED') as failure:
        held.close()
    original_error = failure.value

    def failed_build(*arguments, **options):
        raise original_error

    monkeypatch.setattr(backend, 'build_backend', failed_build)
    with pytest.raises(ProgramManifestError, match='CLOSE_UNVERIFIED') as propagated:
        backend.main(
            [
                '--output',
                str(prepared[0].with_name('not-published')),
                '--program-ref',
                'WALLE-BACKEND-UNKNOWN-CLOSE-FIXTURE',
            ]
        )
    assert propagated.value is original_error
    assert propagated.value.retained_owner is held and calls == ['close']
    with pytest.raises(ProgramManifestError, match='CLOSE_PREVIOUSLY_UNVERIFIED'):
        held.close()
    assert calls == ['close']
    assert not prepared[0].with_name('not-published').exists()
