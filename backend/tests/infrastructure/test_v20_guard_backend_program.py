"""Protected backend package codec/ports and actual writable-package rejection.

Port success is deliberately not SYSTEM/cross-user/package deployment evidence.
"""

from backend.app.infrastructure import program_manifest

import hashlib
import sys
from dataclasses import replace
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import guard_backend_program as program
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_access_check import ControllerAccess, NativeAccessError
from backend.app.infrastructure.windows_executable_pin import ExecutablePinError
from backend.app.infrastructure.windows_local_paths import FileIdentity, LocalPathGuard
from backend.app.infrastructure.windows_pipe_peer import PipePeerError
from backend.tests.infrastructure.test_v20_windows_pipe_peer import connection, peer
from backend.tests.requirements.test_v15_foundation import tmp_path


def manifest(**changed):
    return {
        'policy_version': program.POLICY_VERSION,
        'program_ref': 'WALLE-BACKEND-PACKAGE-TEST20',
        'entry': 'walle-backend.exe',
        'files': [
            {'path': 'lib/python.dll', 'byte_count': 4, 'sha256': 'b' * 64},
            {'path': 'walle-backend.exe', 'byte_count': 16, 'sha256': 'a' * 64},
        ],
        **changed,
    }


def decode(value):
    raw = _bytes(value)
    return program.decode_backend_program_manifest(
        raw, expected_sha256=hashlib.sha256(raw).hexdigest()
    )


def test_complete_canonical_manifest_keeps_fixed_entry_and_implied_directories():
    spec = decode(manifest())
    assert spec.entry == 'walle-backend.exe'
    assert spec.directories == {'lib'}
    assert [member.path for member in spec.files] == ['lib/python.dll', 'walle-backend.exe']
    assert spec.manifest_sha256 == hashlib.sha256(_bytes(manifest())).hexdigest()


@pytest.mark.parametrize(
    'changed',
    [
        {'policy_version': 'OTHER'},
        {'entry': 'python.exe'},
        {'entry': 'PYTHON/WALLE-BACKEND.EXE'},
        {'files': []},
        {'entry': 'missing/walle-backend.exe'},
        {'files': [{'path': 'backend-program.v1.json', 'byte_count': 0, 'sha256': 'b' * 64}]},
        {'files': [{'path': '../walle-backend.exe', 'byte_count': 0, 'sha256': 'b' * 64}]},
        {'files': [{'path': 'walle-backend.exe', 'byte_count': True, 'sha256': 'b' * 64}]},
        {
            'files': [
                {
                    'path': 'walle-backend.exe',
                    'byte_count': program_manifest.MAX_FILE_BYTES + 1,
                    'sha256': 'b' * 64,
                }
            ]
        },
        {'files': [{'path': 'walle-backend.exe', 'byte_count': 1, 'sha256': 'not pinned'}]},
        {'files': list(reversed(manifest()['files']))},
        {'extra': 'wire override'},
    ],
)
def test_incomplete_ambiguous_or_unregistered_manifest_never_admits_a_program(changed):
    with pytest.raises((RuntimeError, ValueError)):
        decode(manifest(**changed))


def test_manifest_rejects_case_aliases_and_file_directory_collisions():
    rows = manifest()['files']
    for extra in [
        {'path': 'LIB/other.dll', 'byte_count': 1, 'sha256': 'c' * 64},
        {'path': 'lib', 'byte_count': 1, 'sha256': 'c' * 64},
        dict(rows[0]),
    ]:
        with pytest.raises(ValueError):
            decode(
                manifest(files=sorted([*rows, extra], key=lambda row: row['path'].encode('utf-8')))
            )


def test_manifest_capacity_and_trusted_digest_are_independent(monkeypatch):
    raw = _bytes(manifest())
    with pytest.raises(program.BackendProgramError, match='DIGEST_DIFFERS'):
        program.decode_backend_program_manifest(raw, expected_sha256='c' * 64)
    monkeypatch.setattr(program_manifest, 'MAX_TOTAL_BYTES', 19)
    with pytest.raises(program.BackendProgramError, match='TOTAL_SIZE'):
        decode(manifest())
    monkeypatch.setattr(program_manifest, 'MAX_MEMBERS', 1)
    with pytest.raises(program.BackendProgramError, match='MEMBER_LIMIT'):
        decode(manifest())


@pytest.mark.parametrize('value', [None, {}, {'pid': 1}, 7])
def test_untrusted_peer_object_fails_before_any_package_or_token_access(value):
    with patch.object(
        program, 'ControllerPrimaryToken', side_effect=AssertionError('No token API')
    ):
        with pytest.raises(program.BackendProgramError, match='ACTUAL_ORIGINAL_BACKEND_PEER'):
            program.ProtectedBackendProgram(
                value,
                r'C:\untrusted',
                expected_manifest_sha256='a' * 64,
                timeout_ms=3000,
                cancelled=lambda: False,
            )


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_actual_client_cannot_admit_user_writable_package_or_ancestors(connection, tmp_path):
    package = tmp_path / 'unprotected-backend'
    package.mkdir()
    raw = _bytes(manifest())
    with (package / program.MANIFEST_NAME).open('xb') as stream:
        stream.write(raw)
    before = sorted(path.name for path in package.iterdir())
    with peer(connection) as actual:
        with pytest.raises(NativeAccessError, match='CAN_MUTATE'):
            program.ProtectedBackendProgram(
                actual,
                package,
                expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                timeout_ms=5000,
                cancelled=lambda: False,
            )
        assert actual._users == 0
        assert actual.verify() == connection.process.identity
    assert sorted(path.name for path in package.iterdir()) == before


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
@pytest.mark.parametrize(
    'timeout,cancelled', [(0, False), (True, False), (300001, False), (3000, True)]
)
def test_bad_or_cancelled_query_does_not_borrow_original_peer(
    connection, tmp_path, timeout, cancelled
):
    with peer(connection) as actual:
        with pytest.raises(program.BackendProgramError):
            program.ProtectedBackendProgram(
                actual,
                tmp_path,
                expected_manifest_sha256='a' * 64,
                timeout_ms=timeout,
                cancelled=lambda: cancelled,
            )
        assert actual._users == 0


def inventory_port(root, monkeypatch):
    # Only the enumeration algorithm uses a port. Real rights/identity/token
    # primitives and writable-package refusal are tested independently above.
    instance = object.__new__(program.ProtectedBackendProgram)
    instance._root = root
    instance._spec = decode(manifest())
    monkeypatch.setattr(instance, '_hold_path', lambda *args: None)
    return instance


def test_fixed_program_member_lease_accepts_binary_and_streams_original_digest(
    tmp_path, monkeypatch
):
    member = tmp_path / 'walle-backend.exe'
    content = b'MZ\x00\xfffixed program fixture'
    member.write_bytes(content)

    owner = object.__new__(program.ProtectedBackendProgram)
    owner._sources = {}
    owner._orphans = []
    with LocalPathGuard(member, directory=False) as path_guard:
        monkeypatch.setattr(owner, '_hold_path', lambda *args: path_guard)
        try:
            snapshot = owner._hold_file(member, len(content), None, None)
            assert snapshot.byte_count == len(content)
            assert snapshot.sha256 == hashlib.sha256(content).hexdigest()
            assert snapshot.raw == b''
            assert owner._sources[member].verify() == snapshot
        finally:
            for held in owner._sources.values():
                held.close()


def test_inventory_port_covers_complete_files_extra_empty_directory_and_missing_members(
    tmp_path, monkeypatch
):
    (tmp_path / 'lib').mkdir()
    for name in ['lib/python.dll', 'walle-backend.exe', program.MANIFEST_NAME]:
        with (tmp_path / name).open('xb') as stream:
            stream.write(b'port fixture')
    instance = inventory_port(tmp_path, monkeypatch)
    from time import monotonic

    assert instance._inventory(monotonic() + 3, lambda: False) == {
        'lib/python.dll',
        'walle-backend.exe',
        program.MANIFEST_NAME,
    }
    (tmp_path / 'extra-empty').mkdir()
    with pytest.raises(program.BackendProgramError, match='MEMBERS_DIFFER'):
        instance._inventory(monotonic() + 3, lambda: False)
    (tmp_path / 'extra-empty').rmdir()
    with (tmp_path / 'unlisted.dll').open('xb') as stream:
        stream.write(b'extra')
    with pytest.raises(program.BackendProgramError, match='MEMBERS_DIFFER'):
        instance._inventory(monotonic() + 3, lambda: False)


def verification_port(monkeypatch):
    # This explicit port cannot produce a real ProtectedBackendProgram
    # constructor success or production admission. It checks revalidation.
    instance = object.__new__(program.ProtectedBackendProgram)
    instance._owner_thread = get_ident()
    instance._closing = False
    instance._users = 0
    instance._root = Path(r'C:\PortBackend')
    instance._spec = decode(manifest())
    instance._admission = None
    identity = FileIdentity(r'C:\PortBackend\walle-backend.exe', '1' * 16, '2' * 32, False, 'NTFS')
    facts = ControllerAccess(identity, 'S-1-5-21-1', 'S-1-5-18', '3' * 64, 0x1200A9)
    guard = SimpleNamespace(verify=lambda: identity)
    instance._guards = {instance._root / 'walle-backend.exe': guard}
    instance._roles = {instance._root / 'walle-backend.exe': 'FILE'}
    instance._facts = {instance._root / 'walle-backend.exe': facts}
    instance._access = SimpleNamespace(query=lambda _: facts)
    snapshot = SimpleNamespace(raw=b'port', sha256='4' * 64)
    source = SimpleNamespace(snapshot=snapshot, verify=lambda: snapshot)
    instance._sources = {instance._root / 'walle-backend.exe': source}
    instance._peer = SimpleNamespace(
        verify=lambda: None,
        _expected=identity,
        _program=SimpleNamespace(verify=lambda: identity),
    )
    monkeypatch.setattr(
        instance,
        '_inventory',
        lambda *args: {'lib/python.dll', 'walle-backend.exe', program.MANIFEST_NAME},
    )
    instance._admission = instance._bound_admission()
    return instance, facts


def test_verification_port_rejects_changed_descriptor_bytes_and_inventory_before_any_new_admission(
    monkeypatch,
):
    instance, facts = verification_port(monkeypatch)
    assert instance.verify(timeout_ms=3000, cancelled=lambda: False) == instance._admission
    instance._access.query = lambda _: replace(facts, descriptor_sha256='5' * 64)
    with pytest.raises(program.BackendProgramError, match='DESCRIPTOR_DIFFERS'):
        instance.verify(timeout_ms=3000, cancelled=lambda: False)
    instance._access.query = lambda _: facts
    source = next(iter(instance._sources.values()))
    source.verify = lambda: object()
    with pytest.raises(program.BackendProgramError, match='BYTES_DIFFER'):
        instance.verify(timeout_ms=3000, cancelled=lambda: False)
    source.verify = lambda: source.snapshot
    monkeypatch.setattr(instance, '_inventory', lambda *args: {program.MANIFEST_NAME})
    with pytest.raises(program.BackendProgramError, match='MEMBERS_DIFFER'):
        instance.verify(timeout_ms=3000, cancelled=lambda: False)


def test_admission_port_holds_original_owner_and_rejects_expiry_during_use(monkeypatch):
    instance, _ = verification_port(monkeypatch)
    with instance.admission(timeout_ms=3000, cancelled=lambda: False) as admission:
        assert admission.policy_version == program.POLICY_VERSION
        with pytest.raises(program.BackendProgramError, match='IN_USE'):
            instance.close()
    assert instance._users == 0
    state = {'cancelled': False}
    with pytest.raises(program.BackendProgramError, match='CANCELLED'):
        with instance.admission(timeout_ms=3000, cancelled=lambda: state['cancelled']):
            state['cancelled'] = True
    assert instance._users == 0


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_failed_program_cleanup_retains_original_process_and_token_until_same_owner_retry(
    connection, tmp_path
):
    from backend.app.infrastructure.windows_access_check import ControllerAccessQuery

    package = tmp_path / 'unprotected-backend-cleanup'
    package.mkdir()
    closed = ControllerAccessQuery.close
    failures = []

    def fail_once(owner):
        if not failures:
            failures.append(owner)
            raise NativeAccessError('INJECTED_ORIGINAL_QUERY_CLOSE_UNVERIFIED')
        return closed(owner)

    with peer(connection) as actual:
        with patch.object(ControllerAccessQuery, 'close', fail_once):
            with pytest.raises(NativeAccessError, match='INJECTED') as caught:
                program.ProtectedBackendProgram(
                    actual,
                    package,
                    expected_manifest_sha256='a' * 64,
                    timeout_ms=5000,
                    cancelled=lambda: False,
                )
        retained = caught.value.retained_owner
        assert type(retained) is program.ProtectedBackendProgram
        assert retained._token._handle is not None
        assert retained._controller_process is not actual._process
        assert retained._controller_process.identity == actual.verify()
        assert actual._users == 0
        retained.close()
        assert retained._token is None and retained._access is None
        assert retained._controller_process is None
        assert actual.verify() == connection.process.identity


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_peer_exit_during_program_verification_does_not_retain_closed_resources(
    connection, tmp_path, monkeypatch
):
    with peer(connection) as actual:

        def disconnect_before_next_access(owner, *_):
            connection.job.terminate_owned(0)
            process = connection.process
            assert process._kernel.WaitForSingleObject(process._handle, 8000) == 0
            owner.peer.verify()

        monkeypatch.setattr(
            program.ProtectedBackendProgram, '_hold_path', disconnect_before_next_access
        )
        with pytest.raises(PipePeerError) as caught:
            program.ProtectedBackendProgram(
                actual,
                tmp_path,
                expected_manifest_sha256='a' * 64,
                timeout_ms=10000,
                cancelled=lambda: False,
            )
        assert getattr(caught.value, 'retained_owner', None) is None


def test_existing_path_permissions_cannot_silently_refresh_original_descriptor_port(monkeypatch):
    instance, original = verification_port(monkeypatch)
    from time import monotonic

    path = instance._root / 'walle-backend.exe'
    assert instance._hold_path(path, 'FILE', monotonic() + 3, lambda: False)
    instance._access.query = lambda _: replace(original, descriptor_sha256='f' * 64)
    with pytest.raises(program.BackendProgramError, match='DESCRIPTOR_DIFFERS'):
        instance._hold_path(path, 'FILE', monotonic() + 3, lambda: False)
    assert instance._facts[path] == original


def test_registered_entry_pin_uses_installed_manifest_bytes(tmp_path):
    image_path = tmp_path / 'walle-backend.exe'
    image_bytes = Path(sys.executable).read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()
    with image_path.open('xb') as output:
        output.write(image_bytes)
    value = manifest(
        files=[
            {'path': image_path.name, 'byte_count': len(image_bytes), 'sha256': image_sha256},
        ]
    )
    raw = _bytes(value)
    with (tmp_path / program.MANIFEST_NAME).open('xb') as output:
        output.write(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with program.open_registered_backend_image(tmp_path, manifest_sha256=digest) as image:
        assert image.path == image_path
        assert image.verify().sha256 == image_sha256
    with pytest.raises(program.BackendProgramError, match='DIGEST_DIFFERS'):
        program.open_registered_backend_image(tmp_path, manifest_sha256='0' * 64)
    with image_path.open('r+b') as output:
        output.write(b'ZZ')
    with pytest.raises(ExecutablePinError):
        program.open_registered_backend_image(tmp_path, manifest_sha256=digest)
