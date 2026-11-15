"""Real private-file creation descriptors and original journal ownership faults."""

import ctypes
from ctypes import wintypes

import pytest

from backend.app.infrastructure import runtime_launch_journal as launch
from backend.app.infrastructure import windows_config_copy as copying
from backend.app.infrastructure import windows_private_package as packages
from backend.app.infrastructure import windows_private_record as records
from backend.app.infrastructure.process_lock import ProcessAlreadyRunning
from backend.tests.infrastructure import test_v20_windows_config_copy as copy_tests
from backend.tests.infrastructure import test_v20_windows_private_record as record_tests
from backend.tests.requirements import test_v15_foundation as foundation

tmp_path = foundation.tmp_path
package = record_tests.package
setup = copy_tests.setup


def assert_explicit_descriptor(pointer, expected_sid):
    assert pointer is not None
    attributes = ctypes.cast(pointer, ctypes.POINTER(packages.SecurityAttributes)).contents
    assert attributes.length == ctypes.sizeof(packages.SecurityAttributes)
    assert not attributes.inherit_handle and attributes.descriptor
    kernel, api = packages._api()
    api.GetSecurityDescriptorOwner.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.BOOL),
    ]
    api.GetSecurityDescriptorOwner.restype = wintypes.BOOL
    owner, defaulted = wintypes.LPVOID(), wintypes.BOOL()
    assert api.GetSecurityDescriptorOwner(
        attributes.descriptor, ctypes.byref(owner), ctypes.byref(defaulted)
    )
    assert packages._sid_text(kernel, api, owner) == expected_sid
    control, revision = wintypes.WORD(), wintypes.DWORD()
    assert api.GetSecurityDescriptorControl(
        attributes.descriptor, ctypes.byref(control), ctypes.byref(revision)
    )
    assert control.value & 0x1000


@pytest.mark.parametrize('kind', ['record', 'config'])
def test_create_new_receives_explicit_owner_protected_descriptor_and_no_inheritance_handle(
    request, monkeypatch, kind
):
    calls = []
    if kind == 'record':
        held = request.getfixturevalue('package')
        kernel = records.record_api()
    else:
        source, held, _, raw = request.getfixturevalue('setup')
        kernel = copying._api()

    def create(path, access, sharing, attributes, disposition, flags, template):
        if disposition == 1:
            assert_explicit_descriptor(attributes, held.operator_sid)
            calls.append(path)
        else:
            # Owned config cleanup reopens the same original file with OPEN_EXISTING.
            assert disposition == 3 and attributes is None
        return kernel.CreateFileW(path, access, sharing, attributes, disposition, flags, template)

    proxy = record_tests.Proxy(kernel, CreateFileW=create)
    if kind == 'record':
        monkeypatch.setattr(records, 'record_api', lambda: proxy)
        with records.PrivateRecordAppend(
            held, 'a' * 32 + '.git.json', b'fixed', max_record_bytes=100
        ) as owner:
            reference = owner.publish()
        assert held.verify_member(reference.filename, directory=False) == reference.file
    else:
        monkeypatch.setattr(copying, '_api', lambda: proxy)
        with copying.PrivateConfigCopy(source, held) as owner:
            assert owner.verify().raw == raw
    assert len(calls) == 1


@pytest.mark.parametrize(
    'name',
    ['runtime-guard.lock', '.launch-' + 'a' * 32 + '.tmp', '.guard-action-' + 'b' * 32 + '.tmp'],
)
def test_journal_file_roles_use_existing_no_replace_original_handle_publisher(package, name):
    reference = package.publish_new_file(name, b'\0', max_file_bytes=1)
    assert reference.byte_count == 1
    assert package.verify_member(name, directory=False) == reference.file
    with pytest.raises(records.PrivateRecordError, match='RENAME_UNVERIFIED'):
        package.publish_new_file(name, b'X', max_file_bytes=1)
    assert (package.path / name).read_bytes() == b'\0'


@pytest.mark.parametrize(
    'name',
    [
        'runtime-guard.lock:stream',
        '../runtime-guard.lock',
        '.launch-not-a-nonce.tmp',
        'arbitrary.txt',
    ],
)
def test_private_publication_does_not_add_arbitrary_filename_authority(package, monkeypatch, name):
    def forbidden():
        raise AssertionError('Invalid role must not create a file')

    monkeypatch.setattr(records, 'record_api', forbidden)
    with pytest.raises(records.PrivateRecordError, match='NAME_INVALID'):
        package.publish_new_file(name, b'X', max_file_bytes=1)
    assert not list(package.path.iterdir())


def test_failed_native_flush_preserves_original_state_and_cleans_only_unpublished_stage(
    package, monkeypatch
):
    kernel = records.record_api()
    monkeypatch.setattr(
        records,
        'record_api',
        lambda: record_tests.Proxy(kernel, FlushFileBuffers=lambda handle: False),
    )
    with pytest.raises(records.PrivateRecordError, match='FLUSH_UNVERIFIED'):
        package.publish_new_file('runtime-guard.lock', b'\0', max_file_bytes=1)
    assert not list(package.path.iterdir())


@pytest.mark.parametrize('failure', ['lock', 'directory'])
def test_journal_unknown_close_retains_original_components_without_retry_or_reopen(
    tmp_path, monkeypatch, failure
):
    root = packages.create_private_package(tmp_path / 'original-journal')
    journal = launch.LaunchJournal(root)
    journal.__enter__()
    original_lock, original_package = journal._owner, journal._package
    calls = []
    owner = original_lock if failure == 'lock' else original_package
    attribute = 'release' if failure == 'lock' else 'close'
    original = getattr(owner, attribute)

    def unknown():
        calls.append('before-native-port')
        raise RuntimeError('private original close failure')

    monkeypatch.setattr(owner, attribute, unknown)
    try:
        with pytest.raises(RuntimeError) as first:
            journal.close()
        assert first.value.retained_owner is journal
        assert journal._owner is original_lock and journal._package is original_package
        assert journal._stack is not None and journal._close_error is first.value
        with pytest.raises(launch.LaunchOutcomeUnknown, match='CLOSURE_REQUIRES_OBSERVATION'):
            journal.close()
        with pytest.raises(launch.LaunchOutcomeUnknown, match='CLOSURE_REQUIRES_OBSERVATION'):
            journal.__enter__()
        assert calls == ['before-native-port']
        if failure == 'lock':
            with pytest.raises(ProcessAlreadyRunning), launch.LaunchJournal(root):
                pytest.fail('The original OS lock remains owned')
    finally:
        # This port failed before its native call. Reconcile this test's known
        # original owner explicitly; product code never resets the failure latch.
        monkeypatch.setattr(owner, attribute, original)
        original()
    with launch.LaunchJournal(root) as recovered:
        recovered._verify()


def test_descriptor_rejection_is_known_undispatched_and_releases_original_source(
    setup, monkeypatch
):
    source, held, _, _ = setup

    class RejectedDescriptor:
        def __enter__(self):
            raise packages.PackageSecurityError('PACKAGE_SECURITY_CREATION_FAILED')

        def __exit__(self, *_):
            raise AssertionError('A rejected entry has no exit')

    monkeypatch.setattr(held, 'file_creation_attributes', RejectedDescriptor)
    owner = copying.PrivateConfigCopy.__new__(copying.PrivateConfigCopy)
    with pytest.raises(packages.PackageSecurityError) as failure:
        owner._initialize(source, held)
    assert not owner._creation_unknown and not owner._created and owner._writer is None
    assert getattr(failure.value, 'retained_owner', None) is None
    assert source._borrows == 0 and not list(held.path.iterdir())


@pytest.mark.parametrize('kind', ['launch', 'action'])
def test_private_native_flush_error_preserves_original_journal_contract_and_bytes(
    tmp_path, monkeypatch, kind
):
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_action_records import GuardActionError
    from backend.tests.infrastructure.test_v20_guard_action_journal import packet

    root = packages.create_private_package(tmp_path / 'flush-contract')
    with launch.LaunchJournal(root) as journal:
        if kind == 'launch':
            scope = launch.LaunchScope('a' * 64, 1, 1, 'original-flush-contract-nonce-001')
            journal.prepare(scope, 'b' * 64)
            path = journal._path(scope)
            operation = lambda: journal.close_nonce(scope)
            expected = launch.LaunchOutcomeUnknown
        else:
            store = GuardActionJournal(journal)
            request = packet()
            first = store.begin(request)
            path = store._path(request.scope, request.action)
            operation = lambda: store.acknowledge(
                first.record, {'binding_ref': first.record.allocated_binding_ref}
            )
            expected = GuardActionError
        original = path.read_bytes()
        kernel = records.record_api()
        monkeypatch.setattr(
            records,
            'record_api',
            lambda: record_tests.Proxy(kernel, FlushFileBuffers=lambda handle: False),
        )
        with pytest.raises(expected, match='SAVE_UNVERIFIED') as failure:
            operation()
        assert isinstance(failure.value.__cause__, records.PrivateRecordError)
        assert path.read_bytes() == original
        assert not list(root.glob('.record-*.tmp'))
        assert not list(root.glob('.launch-*.tmp'))
        assert not list(root.glob('.guard-action-*.tmp'))
