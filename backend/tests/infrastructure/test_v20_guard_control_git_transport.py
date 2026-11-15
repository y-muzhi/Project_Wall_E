"""Actual request/receipt round trips. The protected program check is a test port."""

import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_control_git_host as host_module
from backend.app.infrastructure import guard_control_git_transport as transport
from backend.app.infrastructure import guard_controller_owner as owners
from backend.app.infrastructure import guard_controller_records as records
from backend.app.infrastructure import guard_recovery as recovery_module
from backend.app.infrastructure.guard_backend_program import POLICY_VERSION, BackendProgramAdmission
from backend.app.infrastructure.guard_control_git_reply import (
    GuardReplyError,
    guard_control_git_reply,
    parse_guard_control_git_reply,
)
from backend.app.infrastructure.guard_git_config_source import (
    ConfigReadDescriptor,
    copy_original_config_source,
)
from backend.app.infrastructure.guard_pipe_frames import GuardPipeFrames
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.runtime_launch_journal import (
    LaunchJournal,
    LaunchOutcomeUnknown,
    LaunchScope,
)
from backend.app.infrastructure.windows_config_source import ConfigReadError, LockedConfigSource
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_guard_pipe import GuardPipeError, GuardPipeServer
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO, PipeIOError
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    current_operator_sid,
)
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.tests.infrastructure import test_v20_guard_control_git_version as version_tests
from backend.tests.infrastructure import test_v20_opencode_binary as binary_tests
from backend.tests.infrastructure import test_v20_opencode_runtime_bundle as bundle_tests
from backend.tests.infrastructure.test_v20_guard_control_git_version import wire
from backend.tests.infrastructure.test_v20_windows_guard_pipe_io import client_owner
from backend.tests.infrastructure.test_v20_windows_stdio import wait_file
from backend.tests.requirements import test_v15_foundation as foundation_tests

sample = version_tests.sample
binary_installation = binary_tests.binary_installation
runtime_bundle = bundle_tests.runtime_bundle
tmp_path = foundation_tests.tmp_path

ROOT = Path(__file__).resolve().parents[3]


def test_unknown_reply_is_bound_to_original_step_input_and_epoch(sample):
    binding, _, _ = sample
    request = _parse(wire(binding, 'STOP', {}), binding)
    original = guard_control_git_reply(request, None)
    assert parse_guard_control_git_reply(request, original).status == 'UNKNOWN'
    for different in (
        replace(request, scope=binding.scope(3, 1, request.scope.nonce)),
        replace(request, binding_ref='resource-binding1'),
        replace(request, owner_epoch=str(uuid4())),
    ):
        with pytest.raises(GuardReplyError, match='REQUEST_DIFFERS'):
            parse_guard_control_git_reply(different, original)
    with pytest.raises(GuardReplyError):
        parse_guard_control_git_reply(request, {**original, 'result': {'completed': True}})


@pytest.fixture
def program_port(monkeypatch):
    admission = BackendProgramAdmission(
        POLICY_VERSION, 'TEST-CONTROL-GIT-PACKAGE', 'a' * 64, 'b' * 64
    )

    class ProgramPort:
        def __init__(self, peer, root, **boundary):
            self.peer = peer

        @contextmanager
        def admission(self, **boundary):
            self.peer.verify()
            yield admission
            self.peer.verify()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    for module in (transport, owners, records, recovery_module):
        monkeypatch.setattr(module, 'ProtectedBackendProgram', ProgramPort)


def backend_worker_script(reference, sid, mode):
    worker = ROOT / 'backend/tests/infrastructure/v20_guard_control_git_pipe_worker.py'
    return '\n'.join(
        (
            'import runpy,sys,traceback',
            'from pathlib import Path',
            'sys.path.insert(0,' + repr(str(ROOT)) + ')',
            'sys.argv=' + repr([str(worker), reference, sid, str(os.getpid()), mode]),
            'try:',
            '    runpy.run_path(' + repr(str(worker)) + ',run_name="__main__")',
            'except BaseException:',
            '    with Path("owned-guard-worker-error.txt").open("x", encoding="utf-8") as report:',
            '        report.write(traceback.format_exc())',
            '    raise',
        )
    )


@contextmanager
def connected(directory, mode):
    reference = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    script = backend_worker_script(reference, sid, mode)
    with (
        GuardPipeServer(reference, backend_sid=sid) as server,
        client_owner(directory, server, 'SILENT', script=script) as client,
        GuardPipeIO(server) as io,
    ):
        client.start()
        failure = directory / 'owned-guard-worker-error.txt'
        try:
            timeout = (
                30000
                if mode
                in (
                    'PROJECT_CHECK_DURABLE',
                    'PROJECT_CHECK_RESTART',
                    'PROJECT_CHECK_MULTI',
                    'PROJECT_CHECK_HANDOFF',
                )
                else 15000
            )
            if mode in ('TESTING_VALIDATION_GROUP', 'TESTING_VALIDATION_RECOVERY'):
                timeout = 90000
            io.connect(timeout_ms=timeout, cancelled=failure.exists)
        except RuntimeError:
            if failure.exists():
                pytest.fail(failure.read_text(encoding='utf-8'))
            raise
        backend = client.ready()
        if backend.identity.is_elevated or backend.identity.is_appcontainer:
            pytest.skip('Actual Control Git requires an ordinary original backend')
        yield GuardPipeFrames(io), backend, reference


def close_test_actor(actor):
    actor.stop_owned(timeout_ms=15000)
    actor.close()


@pytest.mark.parametrize(
    'mode', ['VERSION', 'CONFIG_PARSE', 'REGISTER', 'REGISTER_THREAD', 'OBSERVE_THREAD']
)
def test_real_original_endpoints_run_fixed_commands_with_durable_replies(
    tmp_path, program_port, mode
):
    if mode == 'OBSERVE_THREAD':
        from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository

        setup_repository(tmp_path, 'sha1')
        (tmp_path / 'private').mkdir()
    elif mode != 'VERSION':
        make_source(tmp_path)
    with connected(tmp_path, mode) as (frames, backend, reference):
        image_path = Path(backend.identity.image_path)
        raw = image_path.read_bytes()
        package = create_private_package(tmp_path / 'guard-original-action-state')
        with (
            ExecutablePin(
                image_path,
                expected_byte_count=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            ) as pin,
            LaunchJournal(package) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
            )
            try:
                actions = ['PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'OBSERVE', 'STOP', 'RELEASE']
                if mode.startswith('REGISTER') or mode == 'OBSERVE_THREAD':
                    actions.insert(-1, 'OBSERVE')
                else:
                    actions.append('RELEASE')
                for action in actions * (3 if mode == 'OBSERVE_THREAD' else 1):
                    try:
                        actor.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=lambda: False,
                        )
                    except BaseException:
                        backend._kernel.WaitForSingleObject(backend._handle, 2000)
                        diagnostic = tmp_path / 'control-git-pipe-failure.json'
                        if diagnostic.exists():
                            pytest.fail(json.loads(diagnostic.read_bytes())['traceback'])
                        raise
                    (owner,) = actor._owners.values()
                    if action == 'PREPARE':
                        with pytest.raises(LaunchOutcomeUnknown, match='SCOPE_RELEASE_REQUIRED'):
                            actor.close()
                    if action in ('RESUME', 'STOP'):
                        entry = tuple(owner.registry._entries.values())[-1]
                        root = entry.root
                        assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
                result = tmp_path / 'control-git-pipe-result.json'
                wait_file(result)
                reported = json.loads(result.read_bytes())
                if mode == 'OBSERVE_THREAD':
                    expected = json.loads((tmp_path / 'setup-result.json').read_bytes())['oid']
                    assert reported == {
                        'observation_id': 1,
                        'operation_status': 'SUCCEEDED',
                        'head_commit': expected,
                    }
                    assert len(owner.registry._preparations) == 3
                    assert all(
                        item.handles_released for item in owner.registry._preparations.values()
                    )
                    assert not list(package.glob('control-git-*'))
                    (tmp_path / 'stop').touch(exist_ok=False)
                    assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                    assert backend.observe().exit_code == 0
                    return
                (entry,) = owner.registry._entries.values()
                if mode == 'VERSION':
                    assert reported == {'stdout': 'git version 2.56.0.windows.4', 'stderr': ''}
                    assert entry.directory.path.is_dir()
                else:
                    expected = {'object_format': 'sha1', 'bare': True, 'stderr': ''}
                    if mode.startswith('REGISTER'):
                        expected['repository_id'] = 1
                        expected['operation_status'] = 'SUCCEEDED'
                    assert reported == expected
                    assert not entry.directory.path.exists()
                    assert (tmp_path / 'source.git/config').read_bytes() == SOURCE_CONFIG
                    assert all(
                        b'PRIVATE_EXPORT_VALUE' not in path.read_bytes()
                        for path in package.glob('*.json')
                    )
                (preparation,) = owner.registry._preparations.values()
                assert preparation.handles_released
                assert len(actor._owners) == 1
            finally:
                close_test_actor(actor)


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_guard_pipe_fixed_metadata_after_original_config_and_cleanup(
    tmp_path, program_port, format
):
    from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository

    setup_repository(tmp_path, format)
    (tmp_path / 'private').mkdir()
    with connected(tmp_path, 'METADATA_' + format.upper()) as (frames, backend, reference):
        image_path = Path(backend.identity.image_path)
        raw = image_path.read_bytes()
        package = create_private_package(tmp_path / 'guard-metadata-action-state')
        with (
            ExecutablePin(
                image_path,
                expected_byte_count=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            ) as pin,
            LaunchJournal(package) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
            )
            try:
                # The direct proof checks, followed by the real queue's three original commands.
                for _ in range(41):
                    try:
                        actor.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=lambda: False,
                        )
                    except BaseException:
                        backend._kernel.WaitForSingleObject(backend._handle, 2000)
                        diagnostic = tmp_path / 'control-git-pipe-failure.json'
                        if diagnostic.exists():
                            pytest.fail(json.loads(diagnostic.read_bytes())['traceback'])
                        raise
                result = tmp_path / 'control-git-pipe-result.json'
                wait_file(result)
                expected_head = json.loads((tmp_path / 'setup-result.json').read_bytes())['oid']
                assert json.loads(result.read_bytes()) == {
                    'format': format,
                    'original_operation': 1,
                    'observation_id': 1,
                    'queued_observation_id': 2,
                    'head_commit': expected_head,
                    'worktrees': 2,
                    'branches': ['refs/heads/idle', 'refs/heads/loose', 'refs/heads/main'],
                }
                (owner,) = actor._owners.values()
                assert len(owner.registry._preparations) == 6
                assert all(item.handles_released for item in owner.registry._preparations.values())
                assert not list(package.glob('control-git-*'))
                (tmp_path / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
            finally:
                close_test_actor(actor)


@pytest.mark.parametrize(
    ('format', 'mode_prefix'),
    [
        ('sha1', 'BASELINE_'),
        ('sha256', 'BASELINE_'),
        ('sha1', 'BASELINE_MISSING_'),
        ('sha1', 'BASELINE_MALFORMED_REF_'),
        ('sha1', 'BASELINE_PIN_'),
        ('sha256', 'BASELINE_PIN_'),
        ('sha1', 'BASELINE_PIN_CONFLICT_'),
        ('sha1', 'BASELINE_PIN_UNKNOWN_'),
        ('sha1', 'BASELINE_SAVE_'),
        ('sha256', 'BASELINE_SAVE_'),
        ('sha1', 'BASELINE_SAVE_TAMPERED_'),
        ('sha1', 'BASELINE_RECOVERY_'),
        ('sha1', 'BASELINE_RECOVERY_PACKED_'),
        ('sha1', 'BASELINE_HTTP_'),
        ('sha1', 'BASELINE_QUERY_'),
        ('sha1', 'BASELINE_QUERY_RESTORE_'),
        ('sha256', 'BASELINE_QUERY_RESTORE_'),
    ],
)
def test_c05_fixed_batch_uses_original_objects_and_releases_guard(
    tmp_path, program_port, format, mode_prefix
):
    from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository

    restore = mode_prefix == 'BASELINE_QUERY_RESTORE_'
    setup_repository(tmp_path, format, workspace=restore)
    (tmp_path / 'private').mkdir()
    repository = tmp_path / 'repository'
    (repository / 'fixture.txt').write_bytes(b'uncommitted fixture change')

    def git_state():
        return {
            path.relative_to(repository): path.read_bytes()
            for path in (repository / '.git').rglob('*')
            if path.is_file()
        }

    expected_commit = json.loads((tmp_path / 'setup-result.json').read_bytes())['oid']
    conflict = mode_prefix == 'BASELINE_PIN_CONFLICT_'
    uncertain = mode_prefix == 'BASELINE_PIN_UNKNOWN_'
    target = Path('.git/refs/walle/baselines/1')
    if conflict:
        (repository / target).parent.mkdir(parents=True)
        (repository / target).write_bytes(expected_commit.encode('ascii') + b'\n')
    malformed_ref = mode_prefix == 'BASELINE_MALFORMED_REF_'
    if malformed_ref:
        (repository / '.git/refs/heads/invalid').write_bytes(b'invalid oid\n')
    original_git = git_state()
    missing = mode_prefix == 'BASELINE_MISSING_'
    via_http = mode_prefix == 'BASELINE_HTTP_'
    query = mode_prefix == 'BASELINE_QUERY_' or restore
    publish = query or via_http or mode_prefix.startswith(('BASELINE_SAVE_', 'BASELINE_RECOVERY_'))
    tampered = mode_prefix == 'BASELINE_SAVE_TAMPERED_'
    pin_ref = publish or mode_prefix.startswith('BASELINE_PIN_')
    mode = mode_prefix + format.upper()
    with connected(tmp_path, mode) as (frames, backend, reference):
        image_path = Path(backend.identity.image_path)
        raw = image_path.read_bytes()
        package = create_private_package(tmp_path / 'guard-baseline-actions')
        with (
            ExecutablePin(
                image_path,
                expected_byte_count=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            ) as pin,
            LaunchJournal(package) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
            )
            try:
                # OBSERVE can repeat while a stopped job is still exiting.
                scopes = (
                    1
                    if malformed_ref
                    else (
                        8
                        if query
                        else 5
                        if tampered
                        else 6
                        if publish
                        else 3
                        if conflict
                        else 4
                        if pin_ref
                        else 2
                    )
                )
                for _ in range(80 if query else 64):
                    try:
                        actor.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=lambda: False,
                        )
                    except BaseException:
                        backend._kernel.WaitForSingleObject(backend._handle, 2000)
                        diagnostic = tmp_path / 'owned-guard-worker-error.txt'
                        if diagnostic.exists():
                            pytest.fail(diagnostic.read_text(encoding='utf-8'))
                        raise
                    if actor._owners:
                        (owner,) = actor._owners.values()
                        preparations = owner.registry._preparations.values()
                        if len(preparations) == scopes and all(
                            item.handles_released for item in preparations
                        ):
                            break
                else:
                    pytest.fail('Original Git scopes did not release')
                result = tmp_path / 'control-git-pipe-result.json'
                try:
                    wait_file(result)
                except AssertionError:
                    diagnostic = tmp_path / 'owned-guard-worker-error.txt'
                    if diagnostic.exists():
                        pytest.fail(diagnostic.read_text(encoding='utf-8'))
                    raise
                data = json.loads(result.read_bytes())
                if via_http:
                    assert data == {'snapshot_id': 1, 'operation_status': 'SUCCEEDED'}
                elif missing or malformed_ref:
                    assert data == {
                        'validation_status': 'FAILED',
                        'proof': None,
                        'pin_status': 'PENDING',
                        'snapshot_id': None,
                    }
                else:
                    from backend.app.infrastructure.idempotency import canonical_input

                    def oid(kind, body):
                        header = f'{kind} {len(body)}'.encode('ascii') + b'\0'
                        return hashlib.new(format, header + body).hexdigest()

                    def item(path, mode, raw):
                        return {
                            'path': path,
                            'mode': mode,
                            'blob_oid': oid('blob', raw),
                            'byte_count': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest(),
                        }

                    source = item('fixture.txt', '100644', b'owned fixed source\n')
                    entries = [source]
                    tree = b'100644 fixture.txt\0' + bytes.fromhex(source['blob_oid'])
                    if restore:
                        empty = item('empty', '100644', b'')
                        binary = item('sub/run.bin', '100755', b'\xef\xbb\xbfraw\r\n\x00\xff')
                        entries = [empty, source, binary]
                        subtree = b'100755 run.bin\0' + bytes.fromhex(binary['blob_oid'])
                        tree = (
                            b'100644 empty\0'
                            + bytes.fromhex(empty['blob_oid'])
                            + tree
                            + b'40000 sub\0'
                            + bytes.fromhex(oid('tree', subtree))
                        )
                    tree_oid = oid('tree', tree)
                    expected_content = hashlib.sha256(
                        canonical_input({'entries': entries}).encode('utf-8')
                    ).hexdigest()
                    assert data['validation_status'] == 'SUCCEEDED'
                    expected_pin = 'PENDING'
                    if conflict:
                        expected_pin = 'FAILED'
                    elif uncertain:
                        expected_pin = 'UNKNOWN'
                    elif pin_ref:
                        expected_pin = 'SUCCEEDED'
                    assert data['pin_status'] == expected_pin
                    assert data['snapshot_id'] == (1 if publish and not tampered else None)
                    assert data['proof']['commit_oid'] == expected_commit
                    assert data['proof']['tree_oid'] == tree_oid
                    assert data['proof']['content_sha256'] == expected_content
                (owner,) = actor._owners.values()
                assert len(owner.registry._preparations) == scopes
                assert all(item.handles_released for item in owner.registry._preparations.values())
                assert not list(package.glob('control-git-*'))
                (tmp_path / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
            finally:
                close_test_actor(actor)
    if mode_prefix == 'BASELINE_RECOVERY_PACKED_':
        original_git[Path('.git/packed-refs')] += (
            expected_commit.encode('ascii') + b' refs/walle/baselines/1\n'
        )
    elif pin_ref and not conflict:
        oid = 'e' * len(expected_commit) if tampered else expected_commit
        original_git[target] = oid.encode('ascii') + b'\n'
    assert git_state() == original_git
    assert (repository / 'fixture.txt').read_bytes() == b'uncommitted fixture change'


def test_real_original_pipe_rejects_unrelated_reply_and_preserves_uncertain_scope(tmp_path):
    with connected(tmp_path, 'MISMATCH') as (frames, _, _):
        request = frames.read(timeout_ms=15000, cancelled=lambda: False)
        assert request['action'] == 'STOP'
        frames.write(
            {
                'protocol_version': request['protocol_version'],
                'request_sha256': '0' * 64,
                'status': 'UNKNOWN',
                'result': None,
            },
            timeout_ms=10000,
            cancelled=lambda: False,
        )
        result = tmp_path / 'control-git-pipe-result.json'
        wait_file(result)
        outcome = json.loads(result.read_bytes())
        assert outcome['unknown'] is True
        assert len(outcome['original_scope']) == 64


def test_real_pipe_loss_does_not_retry_the_unacknowledged_original(tmp_path):
    with connected(tmp_path, 'NO_REPLY') as (frames, _, _):
        request = frames.read(timeout_ms=15000, cancelled=lambda: False)
        assert request['action'] == 'STOP'
        # The server endpoint remains owned; the backend must use its one deadline.
        result = tmp_path / 'control-git-pipe-result.json'
        wait_file(result)
        outcome = json.loads(result.read_bytes())
        assert outcome['unknown'] is True
        assert len(outcome['original_scope']) == 64


SOURCE_CONFIG = (
    b'[core]\n repositoryformatversion=0\n bare=true\n[user]\n name=PRIVATE_EXPORT_VALUE\n'
)


def make_source(tmp_path):
    root = tmp_path / 'source.git'
    root.mkdir()
    (tmp_path / 'private').mkdir()
    (root / 'objects').mkdir()
    (root / 'refs').mkdir()
    with (root / 'config').open('xb') as stream:
        stream.write(SOURCE_CONFIG)
    with (root / 'HEAD').open('xb') as stream:
        stream.write(b'ref: refs/heads/main\n')


def test_original_config_export_is_copied_without_opening_a_supplied_path(tmp_path, monkeypatch):
    make_source(tmp_path)
    with connected(tmp_path, 'CONFIG_EXPORT') as (_, backend, _):
        packet = tmp_path / 'config-export.json'
        wait_file(packet)
        data = json.loads(packet.read_bytes())
        descriptor = ConfigReadDescriptor(
            NativeProcessIdentity(**data['owner']),
            LaunchScope(**data['scope']),
            FileIdentity(**data['file']),
            data['sha256'],
            data['byte_count'],
            data['handle'],
        )
        assert descriptor.owner == backend.identity
        with ControllerPrimaryToken(backend, expected=backend.identity) as token:

            def refuse_path_open(*args, **kwargs):
                raise AssertionError('Guard must use the original export handle')

            with monkeypatch.context() as isolated:
                isolated.setattr(LockedConfigSource, '__init__', refuse_path_open)
                with pytest.raises(ConfigReadError, match='EXPORT_REQUIRED'):
                    copy_original_config_source(
                        token,
                        descriptor,
                        scope=replace(descriptor.scope, step_no=3),
                        max_file_bytes=4096,
                    )
                with pytest.raises(ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
                    copy_original_config_source(
                        token,
                        replace(descriptor, file=replace(descriptor.file, file_id='f' * 32)),
                        scope=descriptor.scope,
                        max_file_bytes=4096,
                    )
                with pytest.raises(ConfigReadError, match='SOURCE_CHANGED'):
                    copy_original_config_source(
                        token,
                        replace(descriptor, sha256='f' * 64),
                        scope=descriptor.scope,
                        max_file_bytes=4096,
                    )
                with copy_original_config_source(
                    token, descriptor, scope=descriptor.scope, max_file_bytes=4096
                ) as copied:
                    assert copied.verify().raw == SOURCE_CONFIG
                    (tmp_path / 'config-copied').touch(exist_ok=False)
                    verified = tmp_path / 'original-config-verified.json'
                    wait_file(verified)
                    assert json.loads(verified.read_bytes()) == {'sha256': descriptor.sha256}
                    assert copied.verify().file == descriptor.file


def test_metadata_directories_duplicate_the_original_cohort_without_opening_paths(
    tmp_path, monkeypatch
):
    from backend.app.infrastructure.guard_git_metadata_source import (
        DirectoryHandle,
        GuardMetadataDirectories,
        MetadataDirectoryError,
        MetadataDirectoryExport,
    )
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard

    source = tmp_path / 'source.git'
    source.mkdir()
    (tmp_path / 'private').mkdir()
    git = source / '.git'
    git.mkdir()
    (git / 'objects').mkdir()
    (git / 'refs').mkdir()
    with (git / 'config').open('xb') as stream:
        stream.write(SOURCE_CONFIG.replace(b'bare = true', b'bare = false'))
    with (git / 'HEAD').open('xb') as stream:
        stream.write(b'ref: refs/heads/main\n')
    with connected(tmp_path, 'DIRECTORY_EXPORT') as (_, backend, _):
        packet = tmp_path / 'metadata-directory-export.json'
        wait_file(packet)
        data = json.loads(packet.read_bytes())
        scope = LaunchScope(**data['scope'])
        descriptor = MetadataDirectoryExport(
            NativeProcessIdentity(**data['owner']),
            scope,
            *(
                DirectoryHandle(FileIdentity(**data[role]['file']), data[role]['handle'])
                for role in ('root', 'git_directory', 'common_directory')
            ),
            data['expected_bare'],
            data['linked'],
            data['location_sha256'],
        )
        assert not descriptor.expected_bare and not descriptor.linked
        assert descriptor.root.file != descriptor.git_directory.file
        assert descriptor.git_directory.file == descriptor.common_directory.file

        def refuse_path_open(*args, **kwargs):
            raise AssertionError('Guard must duplicate original directory handles')

        with (
            ControllerPrimaryToken(backend, expected=backend.identity) as token,
            monkeypatch.context() as isolated,
        ):
            isolated.setattr(LocalPathGuard, '__enter__', refuse_path_open)
            with pytest.raises(MetadataDirectoryError, match='SCOPE_DIFFERS'):
                GuardMetadataDirectories(token, descriptor, scope=replace(scope, step_no=3))
            bad = replace(descriptor.root, file=replace(descriptor.root.file, file_id='f' * 32))
            with pytest.raises(MetadataDirectoryError, match='DIRECTORY_DIFFERS'):
                GuardMetadataDirectories(token, replace(descriptor, root=bad), scope=scope)
            broad = replace(descriptor.root, handle=data['list_handle'])
            with pytest.raises(MetadataDirectoryError, match='READ_ATTRIBUTES_REQUIRED'):
                GuardMetadataDirectories(token, replace(descriptor, root=broad), scope=scope)
            with GuardMetadataDirectories(token, descriptor, scope=scope) as bound:
                assert bound.verify() == descriptor
                with monkeypatch.context() as close_failure:
                    close_failure.setattr(bound._kernel, 'CloseHandle', lambda _handle: False)
                    with pytest.raises(MetadataDirectoryError, match='CLOSE_UNVERIFIED') as error:
                        bound.close()
                    assert error.value.retained_owner is bound
                    with pytest.raises(MetadataDirectoryError, match='COHORT_CLOSED'):
                        bound.verify()
            assert not bound._handles
            (tmp_path / 'metadata-directories-copied').touch(exist_ok=False)
            wait_file(tmp_path / 'metadata-directories-verified.json')
            assert json.loads((tmp_path / 'metadata-directories-verified.json').read_bytes()) == {
                'location_sha256': descriptor.location_sha256
            }


@pytest.mark.parametrize('service_shutdown', [False, True])
def test_actual_runner_retains_original_suspended_process_after_create_reply_loss(
    tmp_path, program_port, monkeypatch, service_shutdown
):
    make_source(tmp_path)
    with connected(tmp_path, 'REGISTER_LOST') as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        package = create_private_package(tmp_path / 'guard-original-fault-state')
        with (
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(package) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
            )
            boundary = {
                'expected_backend': backend.identity,
                'backend_image': pin,
                'timeout_ms': 30000,
                'cancelled': lambda: False,
            }
            try:
                actor.serve(frames, **boundary)

                def lost_reply(*args, **kwargs):
                    raise OSError('test-owned original CREATE reply lost')

                with monkeypatch.context() as isolated:
                    isolated.setattr(frames, 'write', lost_reply)
                    with pytest.raises(OSError, match='CREATE reply lost'):
                        actor.serve(frames, **boundary)
                (tmp_path / 'cancel-owned-control-request').touch(exist_ok=False)
                result = tmp_path / 'control-git-pipe-result.json'
                wait_file(result)
                assert json.loads(result.read_bytes()) == {
                    'unknown': True,
                    'retained': True,
                    'status': 'UNKNOWN',
                }
                (owner,) = actor._owners.values()
                (entry,) = owner.registry._entries.values()
                assert entry.root.observe().state == 'RUNNING'
                assert entry.root.resume_state == 'NONE'
                assert not entry.stop_requested and not entry.released
                if service_shutdown:
                    native_release = owner.registry.release_native_handles
                    released = []

                    def release_original(original):
                        assert original == entry.scope
                        assert entry.root.observe().state == 'EXITED'
                        members = entry.job.observe_members()
                        assert members.complete and not members.process_ids
                        assert members.assigned_count == 0
                        released.append(original)
                        return native_release(original)

                    with monkeypatch.context() as shutdown_port:
                        shutdown_port.setattr(
                            owner.registry, 'release_native_handles', release_original
                        )
                        actor.stop_owned(timeout_ms=15000)
                    assert released == [entry.scope]
                    assert entry.released and entry.preparation.handles_released
                    assert journal.inspect(entry.scope).stop_closed
                    seal = original_records.read_seal(
                        owner.binding.controller_ref, owner.binding.owner_epoch
                    )
                    assert seal.controller_ref == owner.binding.controller_ref
                    assert seal.owner_epoch == owner.binding.owner_epoch
                    actor.close()
                    return
                wait_file(tmp_path / 'old-control-connection-closed')
                endpoint = frames._io._endpoint
                original_handle = endpoint._handle
                with pytest.raises(GuardPipeError, match='GUARD_PIPE_IN_USE'):
                    endpoint.disconnect_closed_peer()
                frames.close()
                endpoint.disconnect_closed_peer()
                assert endpoint._handle == original_handle
                with GuardPipeIO(endpoint) as recovered_io:
                    (tmp_path / 'guard-reconnect-ready').touch(exist_ok=False)
                    recovered_io.connect(timeout_ms=10000, cancelled=lambda: False)
                    recovered_frames = GuardPipeFrames(recovered_io)
                    for action in ('STOP', 'OBSERVE', 'RELEASE'):
                        actor.serve(recovered_frames, **boundary)
                        if action == 'STOP':
                            assert (
                                entry.root._kernel.WaitForSingleObject(
                                    entry.root._info.process, 8000
                                )
                                == 0
                            )
                    cleaned = tmp_path / 'control-git-cleanup-result.json'
                    wait_file(cleaned)
                    assert json.loads(cleaned.read_bytes()) == {
                        'retained': False,
                        'status': 'UNKNOWN',
                        'released': True,
                    }
                    assert entry.released and entry.preparation.handles_released
            finally:
                if not actor._closed:
                    close_test_actor(actor)


def test_restarted_repository_actor_cleans_only_the_original_scope(
    tmp_path, program_port, monkeypatch
):
    crashed, restarted = (tmp_path / name for name in ('crashed', 'restarted'))
    crashed.mkdir()
    restarted.mkdir()
    make_source(crashed)
    reference = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    package = create_private_package(tmp_path / 'restart-guard-actions')
    with ObservedProcess(os.getpid()) as process:
        if process.identity.is_elevated or process.identity.is_appcontainer:
            pytest.skip('The two owned backends require an ordinary token')
        image = Path(process.identity.image_path)
    image_bytes = image.read_bytes()
    with (
        GuardPipeServer(reference, backend_sid=sid) as endpoint,
        ExecutablePin(
            image,
            expected_byte_count=len(image_bytes),
            expected_sha256=hashlib.sha256(image_bytes).hexdigest(),
        ) as pin,
        LaunchJournal(package) as journal,
        records.GuardControllerRecords(journal) as original_records,
    ):
        guard = transport.GuardControlGitServer(
            original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
        )
        try:
            with (
                client_owner(
                    crashed,
                    endpoint,
                    'SILENT',
                    script=backend_worker_script(reference, sid, 'REGISTER_CRASH'),
                ) as client,
                GuardPipeIO(endpoint) as io,
            ):
                client.start()
                failure = crashed / 'owned-guard-worker-error.txt'
                try:
                    io.connect(timeout_ms=15000, cancelled=failure.exists)
                except RuntimeError:
                    if failure.exists():
                        pytest.fail(failure.read_text(encoding='utf-8'))
                    raise
                backend = client.ready()
                frames = GuardPipeFrames(io)
                boundary = {
                    'expected_backend': backend.identity,
                    'backend_image': pin,
                    'timeout_ms': 30000,
                    'cancelled': lambda: False,
                }
                guard.serve(frames, **boundary)

                def lost_reply(*args, **kwargs):
                    raise OSError('test original CREATE reply loss before backend exit')

                with monkeypatch.context() as isolated:
                    isolated.setattr(frames, 'write', lost_reply)
                    with pytest.raises(OSError, match='original CREATE reply loss'):
                        guard.serve(frames, **boundary)
                (crashed / 'cancel-owned-control-request').touch(exist_ok=False)
                wait_file(crashed / 'control-git-pipe-result.json')
                (original_owner,) = guard._owners.values()
                (entry,) = original_owner.registry._entries.values()
                assert entry.root.observe().state == 'RUNNING'
                assert entry.root.resume_state == 'NONE'
                (crashed / 'exit-original-backend').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
                deadline = monotonic() + 10
                while not entry.watch_settled and monotonic() < deadline:
                    sleep(0.01)
                assert entry.watch_settled and not entry.released
                frames.close()
                endpoint.disconnect_closed_peer()

            with (
                client_owner(
                    restarted,
                    endpoint,
                    'SILENT',
                    script=backend_worker_script(reference, sid, 'RECOVER_REGISTRATION'),
                ) as client,
                GuardPipeIO(endpoint) as io,
            ):
                client.start()
                failure = restarted / 'owned-guard-worker-error.txt'
                try:
                    io.connect(timeout_ms=15000, cancelled=failure.exists)
                except RuntimeError:
                    if failure.exists():
                        pytest.fail(failure.read_text(encoding='utf-8'))
                    raise
                backend = client.ready()
                frames = GuardPipeFrames(io)
                boundary['expected_backend'] = backend.identity
                requests = []
                read = frames.read

                def capture_request(**kwargs):
                    request = read(**kwargs)
                    requests.append(request)
                    return request

                monkeypatch.setattr(frames, 'read', capture_request)
                recovery_failures = []
                run_action = transport.run_guard_control_git_action

                def record_failure(*args, **kwargs):
                    try:
                        return run_action(*args, **kwargs)
                    except LaunchOutcomeUnknown as error:
                        recovery_failures.append(str(error))
                        raise

                with monkeypatch.context() as isolated:
                    isolated.setattr(transport, 'run_guard_control_git_action', record_failure)
                    for _ in range(4):
                        try:
                            guard.serve(frames, **boundary)
                        except BaseException:
                            backend._kernel.WaitForSingleObject(backend._handle, 2000)
                            diagnostic = restarted / 'owned-guard-worker-error.txt'
                            if diagnostic.exists():
                                pytest.fail(
                                    f'{recovery_failures}\n{diagnostic.read_text(encoding="utf-8")}'
                                )
                            raise
                result = restarted / 'control-git-pipe-result.json'
                wait_file(result)
                outcome = json.loads(result.read_bytes())
                assert outcome['operation_status'] == 'UNKNOWN'
                assert outcome['controller_ref'] != original_owner.binding.controller_ref
                assert [request['action'] for request in requests] == [
                    'OBSERVE',
                    'STOP',
                    'OBSERVE',
                    'RELEASE',
                ]
                for request in requests:
                    assert request['controller_ref'] == outcome['controller_ref']
                    assert request['input']['recovery'] == {
                        'controller_ref': original_owner.binding.controller_ref,
                        'owner_epoch': original_owner.binding.owner_epoch,
                    }
                    assert (request['operation_id'], request['step_no'], request['nonce']) == (
                        entry.scope.operation_id,
                        entry.scope.step_no,
                        entry.scope.nonce,
                    )
                assert entry.released and entry.preparation.handles_released
                assert not guard._owners[outcome['controller_ref']].registry._preparations
                (restarted / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
                frames.close()
        finally:
            close_test_actor(guard)


@pytest.mark.parametrize('discovered', [False, True])
def test_host_owns_actual_sessions_and_keeps_first_endpoint(
    tmp_path, program_port, monkeypatch, discovered
):
    with ObservedProcess(os.getpid()) as process:
        if process.identity.is_elevated or process.identity.is_appcontainer:
            pytest.skip('This isolated client fixture requires an ordinary user')
        image_path = Path(process.identity.image_path)
    image_bytes = image_path.read_bytes()
    image_digest = hashlib.sha256(image_bytes).hexdigest()

    def pin_fixture(root, *, manifest_sha256):
        assert root == tmp_path and manifest_sha256 == 'a' * 64
        return ExecutablePin(
            image_path, expected_byte_count=len(image_bytes), expected_sha256=image_digest
        )

    monkeypatch.setattr(host_module, 'open_registered_backend_image', pin_fixture)
    reference = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    package = create_private_package(tmp_path / 'host-owned-actions')
    with (
        LaunchJournal(package) as journal,
        records.GuardControllerRecords(journal) as original_records,
    ):
        host = host_module.GuardControlGitHost(
            original_records,
            reference,
            backend_sid=sid,
            package_root=tmp_path,
            manifest_sha256='a' * 64,
        )
        original_handle = host._endpoint._handle
        try:
            with pytest.raises(TypeError, match='original backend process'):
                host.accept({'pid': os.getpid()}, timeout_ms=1000, cancelled=lambda: False)
            for number in (1, 2):
                directory = tmp_path / f'host-session-{number}'
                directory.mkdir()
                script = """
import os, time
from pathlib import Path
with Path('registered-process.tmp').open('x', encoding='ascii') as registration:
    registration.write(str(os.getpid()))
os.replace('registered-process.tmp', 'registered-process')
deadline = time.monotonic() + 15
while not Path('connect-original').exists():
    assert time.monotonic() < deadline
    time.sleep(0.01)
""" + backend_worker_script(reference, sid, 'VERSION')
                with client_owner(directory, host, 'SILENT', script=script) as client:
                    client.start()
                    marker = directory / 'registered-process'
                    wait_file(marker)
                    with ObservedProcess(int(marker.read_text(encoding='ascii'))) as backend:
                        assert client.job.contains_process(backend)
                        if number == 1:
                            with pytest.raises(
                                PipeIOError, match='CANCELLED_OR_TIMED_OUT'
                            ) as error:
                                if discovered:
                                    host.accept_registered(timeout_ms=500, cancelled=lambda: False)
                                else:
                                    host.accept(backend, timeout_ms=500, cancelled=lambda: False)
                            assert error.value.native_error == 995
                            assert host._session == 'ABORTED'
                            host.retire_session()
                            assert host._endpoint._handle == original_handle
                        (directory / 'connect-original').touch(exist_ok=False)
                        if discovered:
                            host.accept_registered(timeout_ms=15000, cancelled=lambda: False)
                        else:
                            host.accept(backend, timeout_ms=15000, cancelled=lambda: False)
                        assert (
                            host._backend is not backend
                            and host._backend.identity == backend.identity
                        )
                        with pytest.raises(LaunchOutcomeUnknown, match='RETIREMENT_REQUIRED'):
                            host.accept(backend, timeout_ms=1000, cancelled=lambda: False)
                        for _ in range(7):
                            host.serve(timeout_ms=30000, cancelled=lambda: False)
                        result = directory / 'control-git-pipe-result.json'
                        wait_file(result)
                        assert (
                            json.loads(result.read_bytes())['stdout']
                            == 'git version 2.56.0.windows.4'
                        )
                        with pytest.raises(GuardPipeError, match='PEER_CLOSURE_REQUIRED'):
                            host.retire_session()
                        (directory / 'stop').touch(exist_ok=False)
                        assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                        host.retire_session()
                        assert host._endpoint._handle == original_handle
                        assert host._backend is None and host._frames is None
            assert len(host._server._owners) == 2
        finally:
            close_test_actor(host._server)
            host.close()


@pytest.mark.parametrize('snapshot_query', [False, True])
def test_restarted_baseline_observes_original_ref_without_reissuing_write(
    tmp_path,
    program_port,
    snapshot_query,
):
    from backend.app.infrastructure.guard_control_git_input import (
        CONFIG_COMMAND_REF,
        OBJECT_BATCH_COMMAND_REF,
    )
    from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository

    original, restarted = (tmp_path / name for name in ('crashed', 'restarted'))
    original.mkdir()
    restarted.mkdir()
    setup_repository(original, 'sha1')
    (original / 'private').mkdir()
    marker = original / 'owned-baseline-original-unknown'
    oid = json.loads((original / 'setup-result.json').read_bytes())['oid']
    target = original / 'repository/.git/refs/walle/baselines/1'
    mode = 'BASELINE_QUERY' if snapshot_query else 'BASELINE'
    step_no = 3 if snapshot_query else 2
    reference = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    package = create_private_package(tmp_path / 'restart-baseline-guard')
    with ObservedProcess(os.getpid()) as process:
        if process.identity.is_elevated or process.identity.is_appcontainer:
            pytest.skip('The two owned backends require an ordinary token')
        image = Path(process.identity.image_path)
    raw = image.read_bytes()
    with (
        GuardPipeServer(reference, backend_sid=sid) as endpoint,
        ExecutablePin(
            image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        ) as pin,
        LaunchJournal(package) as journal,
        records.GuardControllerRecords(journal) as original_records,
    ):
        guard = transport.GuardControlGitServer(
            original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
        )
        try:
            with (
                client_owner(
                    original,
                    endpoint,
                    'SILENT',
                    script=backend_worker_script(reference, sid, mode + '_CRASH_SHA1'),
                ) as client,
                GuardPipeIO(endpoint) as io,
            ):
                client.start()
                io.connect(timeout_ms=15000, cancelled=lambda: False)
                backend = client.ready()
                frames = GuardPipeFrames(io)
                for _ in range(80):
                    if marker.exists():
                        break
                    try:
                        guard.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=marker.exists,
                        )
                    except RuntimeError:
                        if marker.exists():
                            break
                        diagnostic = original / 'owned-guard-worker-error.txt'
                        if diagnostic.exists():
                            pytest.fail(diagnostic.read_text(encoding='utf-8'))
                        raise
                else:
                    pytest.fail('Original PIN_COMMIT scope did not reach the loss boundary')
                assert target.read_bytes() == oid.encode('ascii') + b'\n'
                (old_owner,) = guard._owners.values()
                (entry,) = [
                    entry for entry in old_owner.registry._entries.values() if not entry.released
                ]
                assert entry.scope.step_no == step_no
                (original / 'exit-original-backend').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
                deadline = monotonic() + 10
                while not entry.watch_settled and monotonic() < deadline:
                    sleep(0.01)
                assert entry.watch_settled and not entry.released
                frames.close()
                endpoint.disconnect_closed_peer()

            with (
                client_owner(
                    restarted,
                    endpoint,
                    'SILENT',
                    script=backend_worker_script(reference, sid, mode + '_RESTART_SHA1'),
                ) as client,
                GuardPipeIO(endpoint) as io,
            ):
                client.start()
                io.connect(timeout_ms=15000, cancelled=lambda: False)
                backend = client.ready()
                frames = GuardPipeFrames(io)
                requests = []
                read = frames.read

                def capture_request(**kwargs):
                    request = read(**kwargs)
                    requests.append(request)
                    return request

                frames.read = capture_request
                for _ in range(48):
                    try:
                        guard.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=lambda: False,
                        )
                    except BaseException:
                        diagnostic = restarted / 'owned-guard-worker-error.txt'
                        if diagnostic.exists():
                            pytest.fail(diagnostic.read_text(encoding='utf-8'))
                        raise
                    if snapshot_query and entry.released:
                        break
                    if not snapshot_query and len(guard._owners) == 2:
                        new_owner = next(
                            owner for owner in guard._owners.values() if owner is not old_owner
                        )
                        preparations = new_owner.registry._preparations.values()
                        if len(preparations) == 2 and all(
                            item.handles_released for item in preparations
                        ):
                            break
                else:
                    pytest.fail('Reopened baseline did not release its read scopes')
                result = restarted / 'control-git-pipe-result.json'
                try:
                    wait_file(result)
                except AssertionError:
                    diagnostic = restarted / 'owned-guard-worker-error.txt'
                    if diagnostic.exists():
                        pytest.fail(diagnostic.read_text(encoding='utf-8'))
                    raise
                outcome = json.loads(result.read_bytes())
                assert outcome['operation_id'] == outcome['snapshot_id'] == 1
                assert outcome['controller_ref'] != old_owner.binding.controller_ref
                old_requests = [request for request in requests if 'recovery' in request['input']]
                assert [request['action'] for request in old_requests] == [
                    'OBSERVE',
                    'STOP',
                    'OBSERVE',
                    'RELEASE',
                ]
                assert {request['nonce'] for request in old_requests} == {entry.scope.nonce}
                assert {request['step_no'] for request in old_requests} == {step_no}
                assert [
                    request['input']['command_ref']
                    for request in requests
                    if request['action'] == 'PREPARE'
                ] == ([] if snapshot_query else [CONFIG_COMMAND_REF, OBJECT_BATCH_COMMAND_REF])
                assert entry.released and target.read_bytes() == oid.encode('ascii') + b'\n'
                (restarted / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
        finally:
            close_test_actor(guard)


@pytest.mark.parametrize('workspace_start', [False, True], ids=['stop', 'start'])
def test_fixed_baseline_http_reads_and_creates_one_task_in_private_guard_scopes(
    tmp_path, program_port, workspace_start
):
    from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository

    setup_repository(tmp_path, 'sha1')
    (tmp_path / 'private').mkdir()
    fixture = tmp_path / 'repository/fixture.txt'
    fixture.write_bytes(b'uncommitted fixture change')
    reference = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    package = create_private_package(tmp_path / 'snapshot-read-guard')
    with ObservedProcess(os.getpid()) as process:
        if process.identity.is_elevated or process.identity.is_appcontainer:
            pytest.skip('Actual snapshot read requires an ordinary backend')
        image = Path(process.identity.image_path)
    raw = image.read_bytes()
    with (
        GuardPipeServer(reference, backend_sid=sid) as endpoint,
        ExecutablePin(
            image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        ) as pin,
        LaunchJournal(package) as journal,
        records.GuardControllerRecords(journal) as original_records,
        client_owner(
            tmp_path,
            endpoint,
            'SILENT',
            script=backend_worker_script(
                reference,
                sid,
                'BASELINE_QUERY_HTTP_START_SHA1' if workspace_start else 'BASELINE_QUERY_HTTP_SHA1',
            ),
        ) as client,
    ):
        guard = transport.GuardControlGitServer(
            original_records, reference, package_root=tmp_path, manifest_sha256='a' * 64
        )
        diagnostic = tmp_path / 'owned-guard-worker-error.txt'
        try:
            client.start()
            scope_counts = (6, 8, 10, 12, 12, 12, 14, 16, 16) + ((18,) if workspace_start else ())
            for index, scopes in enumerate(scope_counts, 1):
                with GuardPipeIO(endpoint) as io:
                    try:
                        io.connect(timeout_ms=15000, cancelled=diagnostic.exists)
                        backend = client.ready()
                        frames = GuardPipeFrames(io)
                        if index <= 4 or index in (7, 8, 10):
                            for _ in range(64):
                                guard.serve(
                                    frames,
                                    expected_backend=backend.identity,
                                    backend_image=pin,
                                    timeout_ms=30000,
                                    cancelled=diagnostic.exists,
                                )
                                (owner,) = guard._owners.values()
                                preparations = owner.registry._preparations.values()
                                if len(preparations) == scopes and all(
                                    item.handles_released for item in preparations
                                ):
                                    break
                            else:
                                pytest.fail('Snapshot read scope did not release')
                        wait_file(tmp_path / f'owned-connection-{index}-closed')
                        frames.close()
                    except BaseException:
                        if diagnostic.exists():
                            pytest.fail(diagnostic.read_text(encoding='utf-8'))
                        raise
                if index < len(scope_counts):
                    endpoint.disconnect_closed_peer()
            result = tmp_path / 'control-git-pipe-result.json'
            try:
                wait_file(result)
            except AssertionError:
                if diagnostic.exists():
                    pytest.fail(diagnostic.read_text(encoding='utf-8'))
                raise
            expected = {
                'snapshot_id': 1,
                'operation_status': 'SUCCEEDED',
                'snapshot_reads': True,
                'task_id': 1,
            }
            if workspace_start:
                expected['workspace_start'] = True
            assert json.loads(result.read_bytes()) == expected
            assert len(owner.registry._preparations) == scope_counts[-1]
            assert fixture.read_bytes() == b'uncommitted fixture change'
            (tmp_path / 'stop').touch(exist_ok=False)
            assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
            assert backend.observe().exit_code == 0
        finally:
            close_test_actor(guard)


@pytest.mark.parametrize('deployed,create_uncertain', [(True, False), (False, False), (True, True)])
def test_authenticated_pipe_routes_only_original_sealed_task_controls(
    tmp_path, program_port, monkeypatch, deployed, create_uncertain
):
    from backend.app.infrastructure import guard_task_actions as task_actions
    from backend.app.infrastructure import guard_task_network as network
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
    from backend.tests.infrastructure.v20_stdio_worker import publish

    deployment = task_actions.TaskNetworkDeployment(uuid4(), uuid4())
    installed_rules = []
    deletes = []

    def install(rules, provider, sublayer, marker, **kwargs):
        assert (provider, sublayer) == (deployment.provider, deployment.sublayer)
        assert not installed_rules
        installed_rules.extend(rules)

    def read(rules, provider, sublayer, marker):
        assert (provider, sublayer) == (deployment.provider, deployment.sublayer)
        assert installed_rules == list(rules)
        return len(rules)

    def delete(rules, provider, sublayer, marker, **kwargs):
        read(rules, provider, sublayer, marker)
        installed_rules.clear()
        deletes.append(marker)

    def absent(rules, provider, sublayer, marker):
        assert (provider, sublayer) == (deployment.provider, deployment.sublayer)
        assert not installed_rules and deletes == [marker]

    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(network, '_install_owned_filters', install)
    monkeypatch.setattr(network, 'read_owned_filters', read)
    monkeypatch.setattr(network, '_release_owned_filters', delete)
    monkeypatch.setattr(network, '_verify_owned_filters_absent', absent)
    monkeypatch.setattr(task_actions, 'read_owned_filters', read)
    monkeypatch.setattr(task_actions, '_verify_owned_filters_absent', absent)

    with connected(tmp_path, 'TASK_NETWORK_CONTROL') as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        private = create_private_package(tmp_path / 'original-task-scope')
        with (
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(private) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            source = tmp_path / 'task-network-prepare.json'
            wait_file(source)
            wire = json.loads(source.read_bytes())
            binding = GuardControllerBinding(reference, wire['owner_epoch'], backend.identity)
            request = _parse(wire, binding)
            actions = GuardActionJournal(journal)
            original = actions.begin(request).record
            network.seal_original_task_network(
                actions, request, provider=deployment.provider, sublayer=deployment.sublayer
            )
            network.install_original_task_network(
                actions,
                request,
                provider=deployment.provider,
                sublayer=deployment.sublayer,
                cancelled=lambda: False,
            )
            original_create = None
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_network=deployment if deployed else None,
            )
            publish(
                tmp_path / 'task-network-binding.json',
                {
                    'binding_ref': original.allocated_binding_ref if deployed else None,
                    'create_uncertain': create_uncertain,
                },
            )
            try:
                exchange_count = 7 if create_uncertain else 11 if deployed else 4
                for index in range(exchange_count):
                    actor.serve(
                        frames,
                        expected_backend=backend.identity,
                        backend_image=pin,
                        timeout_ms=30000,
                        cancelled=lambda: False,
                    )
                    if create_uncertain and index == 3:
                        original = actions.acknowledge(
                            original, {'binding_ref': original.allocated_binding_ref}
                        )
                        journal.prepare(request.scope, original.input_sha256)
                        create = _parse(
                            {
                                **wire,
                                'action': 'CREATE_SUSPENDED',
                                'input': {},
                                'binding_ref': original.allocated_binding_ref,
                            },
                            binding,
                        )
                        original_create = actions.begin(create).record
                        (tmp_path / 'task-network-create-intent-ready').touch()
                reply = tmp_path / 'control-git-pipe-result.json'
                wait_file(reply)
                assert json.loads(reply.read_bytes()) == {'verified': True}
                assert actions.find(request.scope, 'PREPARE') == original
                assert actions.find(request.scope, 'CREATE_SUSPENDED') == original_create
                unsealed = binding.scope(
                    request.scope.operation_id,
                    request.scope.step_no,
                    request.scope.nonce + '-unsealed',
                )
                assert actions.find(unsealed, 'PREPARE') is None
                if create_uncertain:
                    assert journal.inspect(request.scope).stop_closed
                    assert actions.find(request.scope, 'STOP').phase == 'MAY_HAVE_BEEN_SENT'
                    assert actions.find(request.scope, 'RELEASE') is None
                    assert not deletes
                elif deployed:
                    (owner,) = actor._owners.values()
                    assert not owner.registry._entries
                    assert not owner.registry._preparations
                    assert actions.find(request.scope, 'STOP').phase == 'ACKNOWLEDGED'
                    assert actions.find(request.scope, 'RELEASE').phase == 'MAY_HAVE_BEEN_SENT'
                    assert journal.inspect(request.scope).stop_closed
                    assert len(deletes) == 1
                else:
                    assert not actor._owners
                    assert actions.find(request.scope, 'STOP') is None
                    assert actions.find(request.scope, 'RELEASE') is None
                    assert not deletes
            finally:
                (tmp_path / 'stop').touch()
                close_test_actor(actor)


def test_task_source_handoff_verifies_exact_original_ntfs_objects(
    tmp_path, program_port, monkeypatch
):
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_task_sources import TaskSourceError
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot

    parent_path = tmp_path / 'task-source'
    parent_path.mkdir()
    nonce = '1' * 32
    (parent_path / ('working-' + nonce)).mkdir()
    (parent_path / (nonce + '.workspace-tree.json')).write_bytes(b'workspace metadata')
    (parent_path / (nonce + '.basis-seal.json')).write_bytes(b'basis metadata')
    outcomes = []
    verify = transport.verify_guard_task_source_request

    def observe(*args, **kwargs):
        try:
            verify(*args, **kwargs)
        except TaskSourceError as error:
            outcomes.append(str(error))
            raise
        else:
            outcomes.append('VERIFIED')

    monkeypatch.setattr(transport, 'verify_guard_task_source_request', observe)
    with connected(tmp_path, 'TASK_SOURCE_HANDOFF') as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        private = create_private_package(tmp_path / 'task-source-journal')
        with (
            LocalPathGuard(parent_path, directory=True) as parent,
            LocalDirectoryPin(tmp_path) as runtime_base,
            TaskRuntimeRoot.create(runtime_base, backend.identity.user_sid) as runtime_root,
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(private) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=parent.verify(),
                task_runtime_root=runtime_root,
            )
            try:
                for _ in range(7):
                    actor.serve(
                        frames,
                        expected_backend=backend.identity,
                        backend_image=pin,
                        timeout_ms=30000,
                        cancelled=lambda: False,
                    )
                reply = tmp_path / 'control-git-pipe-result.json'
                wait_file(reply)
                assert json.loads(reply.read_bytes()) == {'verified': True}
                assert outcomes == [
                    'VERIFIED',
                    'ORIGINAL_BASIS_GROUP_PLAN_DIGEST_REQUIRED',
                    'ORIGINAL_TASK_SOURCE_DIFFERS',
                    'ORIGINAL_TASK_SOURCE_READ_ATTRIBUTES_REQUIRED',
                    'ORIGINAL_TASK_SOURCE_NONCE_INVALID',
                    'ORIGINAL_TASK_SOURCE_SCOPE_FENCED',
                ]
                (owner,) = actor._owners.values()
                assert not owner.registry._preparations and not owner.registry._entries
                scope = owner.binding.scope(17, 2, 'guard-pipe-control-git-test')
                assert GuardActionJournal(journal).find(scope, 'PREPARE') is None
                assert journal.inspect(scope).stop_closed
            finally:
                (tmp_path / 'stop').touch()
                close_test_actor(actor)


@pytest.mark.parametrize('outcome', ['held', 'partial', 'no_receipt', 'lost_reply'])
def test_authenticated_task_file_reservation_keeps_one_original_owner(
    tmp_path, program_port, monkeypatch, outcome
):
    from backend.app.infrastructure import guard_task_files as task_files
    from backend.app.infrastructure import windows_task_directories as task_dirs
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_task_files import find_task_file_reservation
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_private_package import PackageSecurityError

    parent_path = tmp_path / 'task-source'
    parent_path.mkdir()
    nonce = '1' * 32
    (parent_path / ('working-' + nonce)).mkdir()
    (parent_path / (nonce + '.workspace-tree.json')).write_bytes(b'workspace metadata')
    (parent_path / (nonce + '.basis-seal.json')).write_bytes(b'basis metadata')

    if outcome == 'partial':
        create = task_dirs._TaskDirectory.create

        def interrupt(directory):
            if directory.role == 'basis':
                raise PackageSecurityError(
                    'fixture interrupted after the original directory create'
                )
            return create(directory)

        monkeypatch.setattr(task_dirs._TaskDirectory, 'create', interrupt)

    if outcome in ('no_receipt', 'lost_reply'):
        publish = task_files._publish_original

        def interrupt_receipt(package, name, raw, limit):
            if not name.endswith(task_files._HELD_SUFFIX):
                return publish(package, name, raw, limit)
            if outcome == 'lost_reply':
                publish(package, name, raw, limit)
            raise OSError('fixture interrupted during held receipt publication')

        monkeypatch.setattr(task_files, '_publish_original', interrupt_receipt)

    mode = {
        'partial': 'TASK_FILE_PARTIAL',
        'no_receipt': 'TASK_FILE_NO_RECEIPT',
    }.get(outcome, 'TASK_FILE_RESERVATION')
    with connected(tmp_path, mode) as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        private = create_private_package(tmp_path / 'task-files-journal')
        with (
            LocalPathGuard(parent_path, directory=True) as parent,
            LocalDirectoryPin(tmp_path) as runtime_base,
            task_dirs.TaskRuntimeRoot.create(
                runtime_base, backend.identity.user_sid
            ) as runtime_root,
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(private) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=parent.verify(),
                task_runtime_root=runtime_root,
            )

            def serve():
                actor.serve(
                    frames,
                    expected_backend=backend.identity,
                    backend_image=pin,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )

            try:
                serve()  # Malformed plan digest creates no task-file intent.
                serve()  # Original PREPARE retains the exact native owner.
                (owner,) = actor._owners.values()
                scope = owner.binding.scope(23, 4, 'guard-pipe-control-git-test-files')
                actions = GuardActionJournal(journal)
                original, digest = find_task_file_reservation(actions, scope)
                assert digest == 'a' * 64
                assert original.phase == 'MAY_HAVE_BEEN_SENT'
                (directories,) = owner._task_directories.values()
                identity = directories._directories['root'].verify().file
                assert list(runtime_root.path.iterdir()) == [directories.root]
                if outcome != 'partial':
                    assert directories.verify()[0].file == identity
                    assert not list((directories.root / 'basis').iterdir())
                held = journal.root / (scope.key + task_files._HELD_SUFFIX)
                if outcome in ('held', 'lost_reply'):
                    assert (
                        json.loads(held.read_bytes())['directories'][0]['file']['file_id']
                        == identity.file_id
                    )
                else:
                    assert not held.exists()
                for _ in range(13):
                    serve()
                reply = tmp_path / 'control-git-pipe-result.json'
                wait_file(reply)
                assert json.loads(reply.read_bytes()) == {'verified': True}
                assert find_task_file_reservation(actions, scope) == (original, digest)
                assert not owner._task_directories
                assert list(runtime_root.path.iterdir()) == [directories.root]
                with LocalPathGuard(directories.root, directory=True) as retained:
                    assert retained.verify() == identity
                assert not directories._directories
                assert journal.inspect(scope).stop_closed
                assert actions.find(scope, 'CREATE_SUSPENDED') is None
                assert actions.find(scope, 'RELEASE') is None
                for number, suffix in ((24, 'stop-first'), (25, 'bad-files')):
                    other = owner.binding.scope(number, 4, 'guard-pipe-control-git-test-' + suffix)
                    assert actions.find(other, 'PREPARE') is None
                    assert find_task_file_reservation(actions, other) is None
            finally:
                (tmp_path / 'stop').touch()
                close_test_actor(actor)


@pytest.mark.parametrize('outcome', ['success', 'finish_unknown', 'stop_writer', 'lost_offer'])
def test_authenticated_task_basis_transfer(tmp_path, program_port, monkeypatch, outcome):
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_task_files import find_task_file_reservation
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
    from backend.app.infrastructure.windows_task_basis import TaskBasisTransferError
    from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot

    parent_path = create_private_package(tmp_path / 'task-basis-source')
    nonce = '1' * 32
    (parent_path / ('working-' + nonce)).mkdir()
    (parent_path / (nonce + '.workspace-tree.json')).write_bytes(b'original workspace metadata')

    if outcome == 'finish_unknown':
        publish = PrivateRecordAppend.publish

        def interrupt_after_basis_seal(pending):
            result = publish(pending)
            if result.filename.endswith('.task-basis-complete.json'):
                raise OSError('fixture lost completion after the durable append')
            return result

        monkeypatch.setattr(PrivateRecordAppend, 'publish', interrupt_after_basis_seal)

    with connected(tmp_path, 'TASK_BASIS_' + outcome.upper()) as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        private = create_private_package(tmp_path / 'basis-transfer-journal')
        with (
            LocalPathGuard(parent_path, directory=True) as parent,
            LocalDirectoryPin(tmp_path) as runtime_base,
            TaskRuntimeRoot.create(runtime_base, backend.identity.user_sid) as runtime_root,
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(private) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=parent.verify(),
                task_runtime_root=runtime_root,
            )

            def serve():
                actor.serve(
                    frames,
                    expected_backend=backend.identity,
                    backend_image=pin,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )

            try:
                if outcome == 'lost_offer':
                    for _ in range(7):
                        serve()
                    write = GuardPipeFrames.write

                    def lose_offer(stream, value, **options):
                        if value.get('status') == 'BASIS_STAGE' and 'writer' in value['result']:
                            raise OSError('fixture disconnected before delivering the writer')
                        return write(stream, value, **options)

                    with monkeypatch.context() as patch:
                        patch.setattr(GuardPipeFrames, 'write', lose_offer)
                        with pytest.raises(OSError, match='disconnected before delivering'):
                            serve()
                    endpoint = frames._io._endpoint
                    frames.close()
                    endpoint.close()
                    reply = tmp_path / 'control-git-pipe-result.json'
                    wait_file(reply)
                    assert json.loads(reply.read_bytes()) == {'offer_disconnected': True}
                    assert backend.observe().state == 'RUNNING'
                    (owner,) = actor._owners.values()
                    (directories,) = owner._task_directories.values()
                    group = directories._basis_group
                    assert tuple(group._slots) == (1,)
                    with pytest.raises(TaskBasisTransferError) as pending:
                        group.pin_written(1)
                    assert pending.value.native_error == 32
                    assert not (
                        journal.root / (directories.scope.key + '.task-basis-complete.json')
                    ).exists()
                    return
                for _ in range(16):
                    serve()
                reply = tmp_path / 'control-git-pipe-result.json'
                wait_file(reply)
                assert json.loads(reply.read_bytes()) == {'verified': True}
                (owner,) = actor._owners.values()
                scope = owner.binding.scope(27, 4, 'guard-pipe-control-git-test-basis')
                actions = GuardActionJournal(journal)
                original, digest = find_task_file_reservation(actions, scope)
                assert original.phase == 'MAY_HAVE_BEEN_SENT'
                assert not owner._task_directories
                assert journal.inspect(scope).stop_closed
                assert actions.find(scope, 'CREATE_SUSPENDED') is None
                basis_files = runtime_root.path / ('task-' + original.directory_nonce) / 'basis'
                seal = journal.root / (scope.key + '.task-basis-complete.json')
                if outcome == 'stop_writer':
                    assert not seal.exists()
                    assert {file.name for file in basis_files.iterdir()} == {'b1.md'}
                    assert (basis_files / 'b1.md').read_bytes() == b''
                else:
                    closed = json.loads(seal.read_bytes())
                    assert closed['evidence']['plan_sha256'] == digest
                    assert closed['evidence']['document_count'] == 2
                    assert (basis_files / 'b1.md').read_bytes() == '设计\r\n'.encode()
                    assert (basis_files / 'b2.md').read_bytes() == b''
            finally:
                if outcome == 'lost_offer':
                    endpoint = frames._io._endpoint
                    frames.close()
                    endpoint.close()
                (tmp_path / 'stop').touch()
                if outcome == 'lost_offer':
                    assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                close_test_actor(actor)


@pytest.mark.parametrize(
    'outcome',
    [
        'success',
        'finish_unknown',
        'stop_writer',
        'lost_offer',
        'cohort',
        'runtime_success',
        'runtime_unknown',
        'runtime_unregistered',
        'execution_success',
        'execution_active',
        'execution_profile',
        'execution_profile_network',
        'execution_pipe_launch',
        'execution_pipe_watch',
        'execution_pipe_recover',
        'execution_busy',
        'execution_unregistered',
    ],
)
def test_authenticated_task_workspace_publication(
    tmp_path, program_port, monkeypatch, outcome, runtime_bundle, request
):
    from backend.app.infrastructure import (
        guard_task_actions,
        guard_task_deployment,
        guard_task_launch,
        guard_task_network,
    )
    from backend.app.infrastructure import windows_task_runtime_environment as runtime_environment
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_task_actions import TaskNetworkDeployment
    from backend.app.infrastructure.guard_task_files import find_task_file_reservation
    from backend.app.infrastructure.opencode_binary import VERSION
    from backend.app.infrastructure.opencode_managed_config import _source_is_absent
    from backend.app.infrastructure.opencode_runtime_bundle import (
        REF_PREFIX,
        TaskRuntimeBundleDeployment,
    )
    from backend.app.infrastructure.runtime_launch_journal import _bytes
    from backend.app.infrastructure.windows_job import JobMembers
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
    from backend.app.infrastructure.windows_runtime_host_identity import (
        windows_runtime_host_identity,
    )
    from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot
    from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
    from backend.tests.code_tasks.test_task_runtime_workspace import PAYLOADS
    from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot

    parent_path = create_private_package(tmp_path / 'task-workspace-source')
    execution_case = outcome.startswith('execution_')
    recover_case = outcome == 'execution_pipe_recover'
    watch_case = outcome in ('execution_pipe_watch', 'execution_pipe_recover')
    launch_case = outcome == 'execution_pipe_launch' or watch_case
    network_case = outcome == 'execution_profile_network' or launch_case
    profile_case = outcome == 'execution_profile' or network_case
    network_events = []
    if network_case:
        installed = None

        def install(rules, provider, sublayer, marker, *, sid_pointer, cancelled):
            nonlocal installed
            assert installed is None and sid_pointer and not cancelled()
            installed = rules, provider, sublayer, marker
            network_events.append('INSTALL')

        def read(rules, provider, sublayer, marker, *, check_external=False, checkpoint=None):
            if check_external:
                checkpoint()
                network_events.append('POLICY')
            if installed != (rules, provider, sublayer, marker):
                raise guard_task_network.WfpObservationError('FIXTURE_RULES_UNAVAILABLE')
            return len(rules)

        def delete(rules, provider, sublayer, marker, *, cancelled):
            nonlocal installed
            assert not cancelled() and installed == (rules, provider, sublayer, marker)
            installed = None
            network_events.append('DELETE')

        def verify_absent(*_):
            assert installed is None
            network_events.append('VERIFY_ABSENT')
            if network_events.count('VERIFY_ABSENT') == 1:
                raise guard_task_network.WfpObservationError('FIXTURE_RELEASE_READBACK_UNKNOWN')

        monkeypatch.setattr(guard_task_network, 'current_operator_sid', lambda: 'S-1-5-18')
        monkeypatch.setattr(guard_task_network, '_install_owned_filters', install)
        monkeypatch.setattr(guard_task_network, 'read_owned_filters', read)
        monkeypatch.setattr(guard_task_network, '_release_owned_filters', delete)
        monkeypatch.setattr(guard_task_network, '_verify_owned_filters_absent', verify_absent)
        monkeypatch.setattr(guard_task_actions, 'read_owned_filters', read)
        monkeypatch.setattr(guard_task_actions, '_verify_owned_filters_absent', verify_absent)
        monkeypatch.setattr(guard_task_launch, '_verify_owned_filters_absent', verify_absent)
    runtime_case = outcome.startswith('runtime_') or execution_case
    installed_bundle = installed_program = network = None
    if runtime_case:
        source, installed_ref = runtime_bundle()
        installed_bundle = TaskRuntimeBundleDeployment(source, installed_ref)
        runtime_ref = REF_PREFIX + 'c' * 64 if outcome == 'runtime_unregistered' else installed_ref
        (tmp_path / 'runtime-bundle-ref').write_text(runtime_ref, encoding='ascii')
        if execution_case:
            program_source, _ = request.getfixturevalue('binary_installation')
            installed_program = replace(program_source, runtime_bundle_ref=installed_ref)
            if launch_case:
                subprocess.run(
                    ['icacls.exe', str(installed_program.image), '/grant', '*S-1-15-2-2:(RX)'],
                    check=True,
                    capture_output=True,
                )
        managed = tmp_path / 'system-managed'
        managed.mkdir()
        monkeypatch.setattr(
            runtime_environment, 'opencode_managed_source_clear', lambda: _source_is_absent(managed)
        )
    if outcome in ('finish_unknown', 'runtime_unknown'):
        publish = PrivateRecordAppend.publish
        suffix = '.task-runtime-files.json' if runtime_case else '.task-workspace-published.json'

        def interrupt_after_workspace_receipt(pending):
            result = publish(pending)
            if result.filename.endswith(suffix):
                raise OSError('fixture lost workspace completion after the durable append')
            return result

        monkeypatch.setattr(PrivateRecordAppend, 'publish', interrupt_after_workspace_receipt)

    with connected(tmp_path, 'TASK_WORKSPACE_' + outcome.upper()) as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        if execution_case:
            listener = tmp_path / 'registered-task-listener.json'
            wait_file(listener)
            port = json.loads(listener.read_bytes())['model_port']
            if outcome == 'execution_unregistered':
                port = 1 if port != 1 else 2
            provider, sublayer = uuid4(), uuid4()
            admission = None
            if network_case:
                admission_path = create_private_package(tmp_path / 'task-deployment-admission')
                evidence = _bytes(
                    {
                        'schema_version': 1,
                        'deployment': {
                            'installation_ref': reference,
                            'backend_program_ref': 'TEST-CONTROL-GIT-PACKAGE',
                            'runtime_bundle_ref': installed_ref,
                            'binary_ref': installed_program.binary_ref,
                            'program_sha256': hashlib.sha256(
                                installed_program.image.read_bytes()
                            ).hexdigest(),
                            'opencode_version': VERSION,
                            'host': windows_runtime_host_identity(),
                            'wfp_provider': str(provider),
                            'wfp_sublayer': str(sublayer),
                            'model_listener': ['127.0.0.1', port],
                            'forward_listeners': [],
                        },
                        'checks': {
                            name: hashlib.sha256(name.encode()).hexdigest()
                            for name in guard_task_deployment._REQUIRED_CHECKS
                        },
                    }
                )
                (admission_path / guard_task_deployment._EVIDENCE_NAME).write_bytes(evidence)
                with PrivatePackageGuard(admission_path) as package:
                    monkeypatch.setattr(guard_task_deployment, '_SYSTEM', package.operator_sid)
                    admission = guard_task_deployment.TaskRuntimeAdmission(
                        package.verify(), hashlib.sha256(evidence).hexdigest()
                    )
            network = TaskNetworkDeployment(
                provider, sublayer, model_listener=('127.0.0.1', port), admission=admission
            )
        with (
            LocalPathGuard(parent_path, directory=True) as parent,
            LocalDirectoryPin(tmp_path) as runtime_base,
            TaskRuntimeRoot.create(runtime_base, backend.identity.user_sid) as runtime_root,
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(
                create_private_package(tmp_path / 'workspace-transfer-journal')
            ) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=parent.verify(),
                task_runtime_root=runtime_root,
                task_runtime_bundle=installed_bundle,
                task_program=installed_program,
                task_network=network,
            )

            def serve():
                actor.serve(
                    frames,
                    expected_backend=backend.identity,
                    backend_image=pin,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )

            probe = probe_job = prepared = None
            replacement_io = None
            try:
                if outcome == 'lost_offer':
                    for _ in range(3):
                        serve()
                    write = GuardPipeFrames.write

                    def lose_offer(stream, value, **options):
                        if value.get('status') == 'WORKSPACE_STAGE' and 'writer' in value['result']:
                            raise OSError('fixture disconnected before workspace writer reply')
                        return write(stream, value, **options)

                    with monkeypatch.context() as patch:
                        patch.setattr(GuardPipeFrames, 'write', lose_offer)
                        with pytest.raises(OSError, match='before workspace writer reply'):
                            serve()
                    frames.close()
                    frames._io._endpoint.close()
                    reply = tmp_path / 'control-git-pipe-result.json'
                    wait_file(reply)
                    assert json.loads(reply.read_bytes()) == {'offer_disconnected': True}
                    assert backend.observe().state == 'RUNNING'
                    (owner,) = actor._owners.values()
                    (directories,) = owner._task_directories.values()
                    with pytest.raises(WorkspaceWriteError, match='STILL_ACTIVE'):
                        directories._workspace_publication._lease.verify_closed()
                    assert not list((directories.root / 'workspace').iterdir())
                    assert not list(journal.root.glob('*.task-workspace-published.json'))
                    return
                exchanges = {
                    'execution_success': 36,
                    'execution_active': 31,
                    'execution_profile': 43,
                    'execution_profile_network': 47,
                    'execution_pipe_launch': 50,
                    'execution_pipe_watch': 38,
                    'execution_pipe_recover': 38,
                    'execution_busy': 23,
                    'execution_unregistered': 23,
                    'cohort': 16,
                }.get(outcome, 22 if runtime_case else 9)
                execution_owner = None
                for index in range(exchanges):
                    try:
                        serve()
                    except RuntimeError as error:
                        failure = tmp_path / 'owned-guard-worker-error.txt'
                        until = monotonic() + 1
                        while not failure.exists() and monotonic() < until:
                            sleep(0.025)
                        if failure.exists():
                            pytest.fail(failure.read_text(encoding='utf-8'))
                        error.add_note(f'Original TASK pipe exchange {index + 1} of {exchanges}')
                        raise
                    if launch_case and not watch_case and index == 36:
                        wait_file(tmp_path / 'old-task-connection-closed')
                        endpoint = frames._io._endpoint
                        frames.close()
                        endpoint.disconnect_closed_peer()
                        (tmp_path / 'task-reconnect-ready').touch(exist_ok=False)
                        replacement_io = GuardPipeIO(endpoint)
                        replacement_io.connect(timeout_ms=15000, cancelled=lambda: False)
                        frames = GuardPipeFrames(replacement_io)
                        assert execution_owner is not None
                        assert tuple(actor._owners.values()) == (execution_owner,)
                    if (
                        outcome in ('execution_success', 'execution_active') or profile_case
                    ) and index == 19:
                        (execution_owner,) = actor._owners.values()
                        (held,) = execution_owner._task_directories.values()
                        prepared = held._execution_preparation
                        assert prepared._job.verify_limits()
                        assert prepared._job.observe_members() == JobMembers((), 0, True)
                        assert prepared._program.verify()
                    if outcome == 'execution_success' and index == 25:
                        payload = prepared._credential.pipe_payload(
                            prepared._dirs.scope, prepared._plan
                        )
                        evidence = (journal.root / prepared._credential_name).read_bytes()
                        assert payload['password'].encode() not in evidence
                        assert set(json.loads(evidence)) == {
                            'schema_version',
                            'scope',
                            'prepare_input_sha256',
                            'binding_ref',
                            'job_ref',
                            'credential_ref',
                            'credential_sha256',
                        }
                        environment = prepared._dirs._runtime_preparation._environment
                        values = environment.launch_values(
                            prepared._credential, prepared._plan, lambda: None
                        )
                        assert values['OPENCODE_SERVER_PASSWORD'] == payload['password']
                    if outcome == 'execution_success' and index in (27, 28):
                        workspace_file = held.root / 'workspace' / 'README.md'
                        workspace_file.write_bytes(b'X' if index == 27 else PAYLOADS['README.md'])
                    if outcome == 'execution_success' and index == 31:
                        assert prepared._credential._password is None
                    active_start = (35 if network_case else 31) if profile_case else 24
                    if (
                        outcome == 'execution_active' or profile_case and not launch_case
                    ) and index == active_start:
                        probe_job = prepared._job
                        probe = TestSuspendedRoot(probe_job, tmp_path, 'pass')
                        assert probe_job.observe_members() == JobMembers((probe.pid,), 1, True)
                    if (
                        outcome == 'execution_active' or profile_case and not launch_case
                    ) and index == active_start + 1:
                        assert prepared._job is probe_job
                        probe_job.terminate_owned(0)
                        assert probe.kernel.WaitForSingleObject(probe.info.process, 8000) == 0
                        probe.close()
                        probe = None
                    retained_indices = (38, 43, 44) if network_case else (34, 39)
                    if profile_case and not launch_case and index in retained_indices:
                        assert not execution_owner._task_directories
                        assert tuple(execution_owner._task_profiles.values()) == (prepared,)
                        assert prepared._job is probe_job
                        assert prepared._profile.verify_identity().canonical_path
                    completed_index = 45 if network_case else 40
                    if profile_case and not launch_case and index == completed_index:
                        assert not execution_owner._task_profiles
                        assert prepared._job is None
                        assert prepared._profile._released
                reply = tmp_path / 'control-git-pipe-result.json'
                wait_file(reply)
                assert json.loads(reply.read_bytes()) == {'verified': True}
                (owner,) = actor._owners.values()
                nonce = 'd' * 32 if recover_case else 'guard-pipe-control-git-test-workspace'
                scope = owner.binding.scope(17, 4, nonce)
                original, _ = find_task_file_reservation(GuardActionJournal(journal), scope)
                assert original.phase == ('ACKNOWLEDGED' if launch_case else 'MAY_HAVE_BEEN_SENT')
                if watch_case:
                    assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                    wait_file(journal.root / prepared._native._stop_name)
                    assert prepared._native.stopped_evidence()
                    assert prepared._native.observe()['job'] == JobMembers((), 0, True)
                    assert prepared._credential._password is None
                    assert GuardActionJournal(journal).find(scope, 'STOP') is None
                    assert 'DELETE' not in network_events
                    if recover_case:
                        endpoint = frames._io._endpoint
                        frames.close()
                        endpoint.disconnect_closed_peer()
                        restarted = tmp_path / 'task-recovered-backend'
                        restarted.mkdir()
                        failure = restarted / 'owned-guard-worker-error.txt'
                        with (
                            client_owner(
                                restarted,
                                endpoint,
                                'SILENT',
                                script=backend_worker_script(
                                    reference, backend.identity.user_sid, 'TASK_RECOVER_CONTROLLER'
                                ),
                            ) as current_client,
                            GuardPipeIO(endpoint) as recovery_io,
                        ):
                            current_client.start()
                            try:
                                recovery_io.connect(timeout_ms=15000, cancelled=failure.exists)
                                current_backend = current_client.ready()
                                recovery_frames = GuardPipeFrames(recovery_io)
                                for _ in range(8):
                                    actor.serve(
                                        recovery_frames,
                                        expected_backend=current_backend.identity,
                                        backend_image=pin,
                                        timeout_ms=30000,
                                        cancelled=failure.exists,
                                    )
                            except RuntimeError:
                                if failure.exists():
                                    pytest.fail(failure.read_text(encoding='utf-8'))
                                raise
                            recovered = restarted / 'control-git-pipe-result.json'
                            wait_file(recovered)
                            assert json.loads(recovered.read_bytes()) == {'recovered': True}
                        assert len(actor._owners) == 2
                        assert not prepared._dirs.root.exists()
                        assert parent_path.exists()
                        assert network_events.count('DELETE') == 1
                        assert (
                            GuardActionJournal(journal).find(scope, 'STOP').owner_epoch
                            == owner.binding.owner_epoch
                        )
                    return
                assert journal.inspect(scope).stop_closed
                if launch_case:
                    assert prepared._native.observe()['process_state'] == 'EXITED'
                    actions = GuardActionJournal(journal)
                    for action in ('CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE'):
                        assert actions.find(scope, action).phase == 'ACKNOWLEDGED'
                    assert prepared._credential._password is None
                    assert prepared._profile.release_evidence()
                    assert network_events.count('DELETE') == 1
                    assert not prepared._dirs.root.exists()
                    assert (
                        prepared._directory_release.verify()
                        == actions.find(scope, 'RELEASE').result['cleanup_ref']
                    )
                    assert parent_path.exists()
                    return
                assert not owner._task_directories
                workspace = runtime_root.path / ('task-' + original.directory_nonce) / 'workspace'
                files = {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in workspace.rglob('*')
                    if path.is_file()
                }
                assert (journal.root / (scope.key + '.task-workspace-write.json')).exists()
                published = journal.root / (scope.key + '.task-workspace-published.json')
                if outcome == 'stop_writer':
                    assert len(files) == 1 and files.items() <= PAYLOADS.items()
                    assert not published.exists()
                else:
                    assert files == PAYLOADS
                    record = json.loads(published.read_bytes())
                    assert record['intent']['target']['directory']['canonical_path'] == str(
                        workspace
                    )
                if outcome == 'cohort' or runtime_case:
                    basis = journal.root / (scope.key + '.task-basis-complete.json')
                    assert (
                        json.loads(basis.read_bytes())['prepare_input_sha256']
                        == original.input_sha256
                    )
                    assert (
                        workspace.parent / 'basis' / 'b1.md'
                    ).read_bytes() == '共同设计\r\n'.encode()
                if outcome == 'runtime_unregistered':
                    assert not list(journal.root.glob('*.task-runtime-*.json'))
                    assert not list((workspace.parent / 'runtime').iterdir())
                    assert not list((workspace.parent / 'config').iterdir())
                elif runtime_case:
                    evidence = journal.root / (scope.key + '.task-runtime-files.json')
                    record = json.loads(evidence.read_bytes())
                    assert record['intent']['prepare_input_sha256'] == original.input_sha256
                    assert record['evidence']['runtime_bundle_ref'] == runtime_ref
                    assert (workspace.parent / 'runtime' / 'opencode.json').read_bytes() == (
                        installed_bundle.source.root / 'opencode.json'
                    ).read_bytes()
                    assert (workspace.parent / 'config' / 'opencode').is_dir()
                    assert (workspace.parent / 'scratch' / 'home').is_dir()
                    assert GuardActionJournal(journal).find(scope, 'CREATE_SUSPENDED') is None
                if outcome in ('execution_success', 'execution_active') or profile_case:
                    execution = journal.root / (scope.key + '.task-execution-prepared.json')
                    record = json.loads(execution.read_bytes())
                    assert record['prepare_input_sha256'] == original.input_sha256
                    assert record['lpac_sid'].startswith('S-1-15-2-')
                    assert (journal.root / (scope.key + '.task-network.json')).exists()
                    assert (
                        bool(list(journal.root.glob('*.task-network-install.json'))) == network_case
                    )
                    if network_case:
                        assert network_events == [
                            'INSTALL',
                            'POLICY',
                            'POLICY',
                            'POLICY',
                            'DELETE',
                            'VERIFY_ABSENT',
                            'VERIFY_ABSENT',
                            'VERIFY_ABSENT',
                        ]
                    if profile_case:
                        assert (
                            journal.root / (scope.key + '.task-lpac-profile-released.json')
                        ).exists()
                        assert not Path(prepared._profile._folder.canonical_path).exists()
                elif outcome in ('execution_busy', 'execution_unregistered'):
                    assert not list(journal.root.glob('*.task-execution-prepared.json'))
                    assert not list(journal.root.glob('*.task-network.json'))
            finally:
                if probe is not None:
                    probe_job.terminate_owned(1)
                    assert probe.kernel.WaitForSingleObject(probe.info.process, 8000) == 0
                    probe.close()
                if outcome == 'lost_offer':
                    frames.close()
                    frames._io._endpoint.close()
                try:
                    if profile_case and prepared is not None:
                        profile = prepared._profile
                        if profile is not None and profile._created and not profile._released:
                            journal.close_nonce(profile._dirs.scope)
                            if (
                                launch_case
                                and prepared._native is not None
                                and prepared._native._created
                            ):
                                prepared.stop_native(lambda: None, monotonic() + 5)
                                if backend.observe().state != 'RUNNING':
                                    folder = profile._folder
                                    assert current_operator_sid() == profile._intent['user_sid']
                                    with LocalPathGuard(
                                        folder.canonical_path, directory=True
                                    ) as held_profile:
                                        assert held_profile.verify() == folder
                                    assert (
                                        profile._api.DeleteAppContainerProfile(
                                            profile._dirs.profile
                                        )
                                        == 0
                                    )
                                    assert not Path(folder.canonical_path).exists()
                                else:
                                    profile.release_after_native_stop(prepared._native)
                            else:
                                profile.release()
                finally:
                    if replacement_io is not None:
                        replacement_io.close()
                    (tmp_path / 'stop').touch()
                    if outcome == 'lost_offer':
                        assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                    close_test_actor(actor)


@pytest.mark.parametrize(
    'mode', ['CANDIDATE_PACKAGE', 'CANDIDATE_DURABLE', 'CANDIDATE_RELEASED_LOST_RESULT']
)
def test_authenticated_guard_builds_exact_private_candidate(tmp_path, program_port, mode):
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

    parent = create_private_package(tmp_path / 'task-source')
    package = create_private_package(tmp_path / 'guard-state')
    with PrivatePackageGuard(parent) as source:
        identity = source.verify()
    with connected(tmp_path, mode) as (frames, backend, reference):
        image_path = Path(backend.identity.image_path)
        raw = image_path.read_bytes()
        with (
            ExecutablePin(
                image_path,
                expected_byte_count=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            ) as pin,
            LaunchJournal(package) as journal,
            records.GuardControllerRecords(journal) as original_records,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=identity,
            )
            try:
                failure = tmp_path / 'owned-guard-worker-error.txt'
                result = tmp_path / 'control-git-pipe-result.json'
                deadline = monotonic() + 135
                while not result.exists() and monotonic() < deadline:
                    try:
                        actor.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=30000,
                            cancelled=lambda: failure.exists() or result.exists(),
                        )
                    except BaseException:
                        if result.exists():
                            break
                        backend._kernel.WaitForSingleObject(backend._handle, 2000)
                        if failure.exists():
                            pytest.fail(failure.read_text(encoding='utf-8'))
                        raise
                wait_file(result)
                report = json.loads(result.read_bytes())
                assert report == {
                    'commands': 7
                    if mode == 'CANDIDATE_DURABLE'
                    else 1
                    if mode == 'CANDIDATE_RELEASED_LOST_RESULT'
                    else [
                        'INIT',
                        'WRITE_BLOB',
                        'WRITE_TREE',
                        'CREATE_REF',
                        'READ_REF',
                        'READ_TREE',
                        'READ_BLOB',
                    ],
                    'sha256': hashlib.sha256(bytes(range(256)) * 40).hexdigest(),
                }
                (owner,) = actor._owners.values()
                expected_count = 1 if mode == 'CANDIDATE_RELEASED_LOST_RESULT' else 7
                assert len(owner.registry._preparations) == expected_count
                assert all(item.handles_released for item in owner.registry._preparations.values())
                assert not list(package.glob('control-git-*'))
                (tmp_path / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
            finally:
                close_test_actor(actor)


@pytest.mark.parametrize(
    'mode',
    [
        'PROJECT_CHECK',
        'TESTING_PROJECT_CHECK',
        'TESTING_SNAPSHOT_CHECK',
        'TESTING_STDIN_CHECK',
        'TESTING_VALIDATION_GROUP',
        'TESTING_VALIDATION_RECOVERY',
        'TESTING_HTTP_CHECK',
        'TESTING_FIXTURE_CHECK',
        'PROJECT_CHECK_REJECT',
        'PROJECT_CHECK_DURABLE',
        'PROJECT_CHECK_MULTI',
        'PROJECT_CHECK_HANDOFF',
        'PROJECT_CHECK_RESTART',
        'PROJECT_CHECK_CONTROLLER_LOST',
    ],
)
def test_authenticated_project_check_transfers_input_runs_and_releases_original_job(
    tmp_path, program_port, monkeypatch, mode
):
    from backend.app.infrastructure import guard_task_launch, guard_task_network
    from backend.app.infrastructure.check_runner_bundle import (
        RegisteredCheckRunner,
        hold_check_runner_bundle,
    )
    from backend.app.infrastructure.guard_project_check_deployment import (
        GuardProjectCheckDeployment,
    )
    from backend.app.infrastructure.idempotency import canonical_input
    from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin, LocalPathGuard
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.infrastructure.windows_project_check_command import RegisteredCheckExecutable
    from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot
    from backend.app.infrastructure.windows_task_runtime_environment import _windows_system_paths
    from backend.tests.infrastructure.test_v20_check_runner_bundle import document
    from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
        check_definition,
        check_limits,
        make_fixed_check_fixture,
    )

    recovery = mode == 'TESTING_VALIDATION_RECOVERY'
    full_testing = recovery or mode == 'TESTING_VALIDATION_GROUP'
    http = mode == 'TESTING_HTTP_CHECK'
    fixture = make_fixed_check_fixture(tmp_path) if mode == 'TESTING_FIXTURE_CHECK' else None
    native_failures = []
    if full_testing:
        from backend.app.infrastructure.content_manifest import ContentLimits
        from backend.app.infrastructure.guard_project_check import _ProjectCheckExecution

        def observe(action, native):
            def observed(*args, **kwargs):
                try:
                    return native(*args, **kwargs)
                except Exception as error:
                    native_failures.append((action, type(error).__name__, str(error)))
                    raise

            return observed

        for action in (
            'prepare',
            'create_native',
            'resume_native',
            'stop_native',
            'release_check_inputs',
        ):
            original = getattr(_ProjectCheckExecution, action)
            monkeypatch.setattr(_ProjectCheckExecution, action, observe(action, original))
        from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository
        from backend.tests.infrastructure.v20_testing_validation_worker import command_definition

        for kind in ('positive', 'negative'):
            repository_fixture = tmp_path / kind
            repository_fixture.mkdir()
            setup_repository(repository_fixture, 'sha1', negative=kind == 'negative')

    source = create_private_package(tmp_path / 'task-source')
    runner_path = create_private_package(tmp_path / 'registered-runner')
    (runner_path / 'bin').mkdir()
    (runner_path / 'bin/entry').write_bytes(b'runner')
    (runner_path / 'zero').write_bytes(b'')
    manifest = canonical_input(
        document(capabilities=['CONTENT_INTEGRITY', 'HTTP']) if http else document()
    ).encode('utf-8')
    (runner_path / 'manifest.json').write_bytes(manifest)
    admission = create_private_package(tmp_path / 'registered-admission')
    program_root = create_private_package(tmp_path / 'registered-program')
    if http:
        from backend.tests.infrastructure.v20_testing_http_worker import (
            build_service,
            service_definition,
        )

        executable_path = build_service(program_root)
        raw = executable_path.read_bytes()
        fixed_command = service_definition()
    else:
        executable_path = program_root / 'findstr.exe'
        _, system = _windows_system_paths()
        raw = (Path(system.canonical_path) / 'findstr.exe').read_bytes()
        executable_path.write_bytes(raw)
        fixed_command = (
            command_definition()
            if full_testing
            else check_definition(
                timeout_seconds=30
                if mode
                in (
                    'PROJECT_CHECK_DURABLE',
                    'PROJECT_CHECK_RESTART',
                    'PROJECT_CHECK_MULTI',
                    'PROJECT_CHECK_HANDOFF',
                )
                else 15,
                stdin=mode == 'TESTING_STDIN_CHECK',
                fixture=fixture is not None,
            )
        )
    limits, _ = check_limits()
    if full_testing:
        limits = ContentLimits(1024 * 1024, 4 * 1024 * 1024, 4096, 1024 * 1024)
    provider, sublayer = uuid4(), uuid4()
    with (
        PrivatePackageGuard(source) as input_root,
        PrivatePackageGuard(runner_path) as runner_root,
        PrivatePackageGuard(admission) as admission_root,
        LocalPathGuard(executable_path, directory=False) as program_file,
    ):
        deployment = GuardProjectCheckDeployment(
            'runner:cli' if full_testing else 'fixture:project-runner',
            RegisteredCheckRunner(
                runner_root.verify(),
                hashlib.sha256(manifest).hexdigest(),
                'native-check-runner',
                '1.0.0',
            ),
            fixed_command,
            RegisteredCheckExecutable(
                fixed_command.executable_ref,
                program_file.verify(),
                hashlib.sha256(raw).hexdigest(),
                len(raw),
            ),
            provider,
            sublayer,
            limits,
            admission_root.verify(),
            'a' * 64,
            owner_kind='TESTING' if mode.startswith('TESTING_') else 'CODING',
            fixture=fixture,
        )
        deployments = (deployment,)
        if mode == 'PROJECT_CHECK_MULTI':
            from dataclasses import replace

            deployments += (
                replace(deployment, command=check_definition(timeout_seconds=30, missing=True)),
            )
        source_identity = input_root.verify()

    def admission_fixture(self, installation, program, *, deadline, cancelled):
        assert self in deployments and len(installation) == 64 and program
        with hold_check_runner_bundle(self.runner, deadline=deadline, cancelled=cancelled):
            return self.admission_sha256

    live = {}

    def install(rules, actual_provider, actual_sublayer, marker, *, sid_pointer, cancelled):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert not cancelled() and sid_pointer and len(rules) == (8 if http else 6)
        assert sum(rule.action == guard_task_network.BLOCK for rule in rules) == 6
        assert not live
        live[marker] = rules

    def read(rules, actual_provider, actual_sublayer, marker, **options):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert live[marker] == rules
        return len(rules)

    def release(rules, actual_provider, actual_sublayer, marker, *, cancelled):
        assert (actual_provider, actual_sublayer) == (provider, sublayer) and not cancelled()
        assert live.pop(marker) == rules

    def absent(rules, actual_provider, actual_sublayer, marker):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert len(rules) == (8 if http else 6) and marker not in live

    monkeypatch.setattr(GuardProjectCheckDeployment, 'verify', admission_fixture)
    monkeypatch.setattr(guard_task_network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(guard_task_network, '_install_owned_filters', install)
    monkeypatch.setattr(guard_task_network, 'read_owned_filters', read)
    monkeypatch.setattr(guard_task_network, '_release_owned_filters', release)
    monkeypatch.setattr(guard_task_network, '_verify_owned_filters_absent', absent)
    monkeypatch.setattr(guard_task_launch, '_verify_owned_filters_absent', absent)

    from backend.tests.infrastructure.v20_validation_probe import watch_validation_phase

    with (
        watch_validation_phase(tmp_path, enabled=full_testing),
        connected(tmp_path, mode) as (frames, backend, reference),
    ):
        image = Path(backend.identity.image_path)
        image_raw = image.read_bytes()
        with (
            ExecutablePin(
                image,
                expected_byte_count=len(image_raw),
                expected_sha256=hashlib.sha256(image_raw).hexdigest(),
            ) as pin,
            LaunchJournal(create_private_package(tmp_path / 'check-state')) as journal,
            records.GuardControllerRecords(journal) as original_records,
            LocalDirectoryPin(tmp_path) as base,
            TaskRuntimeRoot.create(base, backend.identity.user_sid) as runtime,
        ):
            actor = transport.GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=source_identity,
                task_runtime_root=runtime,
                project_checks=deployments,
            )
            from collections import deque

            original_dispatch = actor._dispatch
            timings = deque(maxlen=64)
            diagnostic_count = 0

            def measured_dispatch(request, *args, **kwargs):
                nonlocal diagnostic_count
                started = monotonic()
                if full_testing and request.action == 'CREATE_SUSPENDED' and diagnostic_count < 64:
                    print('TESTING_GUARD_CREATE_START', request.target_scope.step_no, flush=True)
                    diagnostic_count += 1
                try:
                    return original_dispatch(request, *args, **kwargs)
                finally:
                    elapsed = round(monotonic() - started, 2)
                    timings.append((request.action, request.target_scope.step_no, elapsed))
                    if full_testing and elapsed >= 2 and diagnostic_count < 64:
                        print(
                            'TESTING_GUARD_SLOW',
                            request.action,
                            request.target_scope.step_no,
                            elapsed,
                            flush=True,
                        )
                        diagnostic_count += 1

            actor._dispatch = measured_dispatch
            try:
                failure = tmp_path / 'owned-guard-worker-error.txt'
                result = tmp_path / 'control-git-pipe-result.json'
                if mode == 'PROJECT_CHECK_CONTROLLER_LOST':
                    _recover_project_check_controller(
                        tmp_path, actor, frames, backend, reference, pin, journal
                    )
                    assert not live and not list(runtime.path.iterdir())
                    assert not list(source.glob('check-input-*.bin'))
                    return
                # Revoke/restore each add an explicit configuration and project
                # check to this chain; command deadlines remain unchanged.
                if mode == 'PROJECT_CHECK_HANDOFF':
                    budget = 1800
                elif full_testing:
                    budget = 1200
                else:
                    budget = 240
                deadline = monotonic() + budget
                while not result.exists() and monotonic() < deadline:
                    try:
                        actor.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=90000
                            if full_testing
                            or mode
                            in (
                                'PROJECT_CHECK_DURABLE',
                                'PROJECT_CHECK_MULTI',
                                'PROJECT_CHECK_RESTART',
                                'PROJECT_CHECK_HANDOFF',
                            )
                            else 30000,
                            cancelled=lambda: failure.exists() or result.exists(),
                        )
                    except BaseException as error:
                        if result.exists():
                            break
                        backend._kernel.WaitForSingleObject(backend._handle, 2000)
                        if failure.exists():
                            pytest.fail(failure.read_text(encoding='utf-8') + repr(native_failures))
                        raise AssertionError(
                            (repr(error), list(timings)[-12:], native_failures)
                        ) from error
                wait_file(result)
                if recovery:
                    assert json.loads(result.read_bytes()) == {'result': 'recovered', 'cases': 2}
                elif full_testing:
                    assert json.loads(result.read_bytes()) == {
                        'result': 'published',
                        'validation_id': 1,
                        'children': 4,
                        'cases': 8,
                    }
                elif http:
                    actual = json.loads(result.read_bytes())
                    assert set(actual) == {'result', 'candidate_sha256'}
                    assert (
                        actual['candidate_sha256'] == hashlib.sha256(b'WALLE\xff\0\r\n').hexdigest()
                    )
                    assert actual['result'] in ('verified', 'endpoint_unavailable')
                    print('ACTUAL_LPAC_HTTP_SERVICE_RESULT', actual['result'], flush=True)
                else:
                    assert json.loads(result.read_bytes()) == {
                        'result': {
                            'PROJECT_CHECK': 'verified',
                            'TESTING_PROJECT_CHECK': 'verified',
                            'TESTING_SNAPSHOT_CHECK': 'verified',
                            'TESTING_STDIN_CHECK': 'verified',
                            'TESTING_FIXTURE_CHECK': 'verified',
                            'PROJECT_CHECK_REJECT': 'rejected',
                            'PROJECT_CHECK_DURABLE': 'durable',
                            'PROJECT_CHECK_MULTI': 'durable',
                            'PROJECT_CHECK_HANDOFF': 'durable',
                            'PROJECT_CHECK_RESTART': 'durable',
                        }[mode],
                        'candidate_sha256': hashlib.sha256(b'WALLE\xff\0\r\n').hexdigest(),
                    }
                assert not live
                assert not list(runtime.path.iterdir())
                assert len(list(source.glob('check-input-*.bin'))) == int(
                    mode == 'PROJECT_CHECK_REJECT'
                )
                (tmp_path / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                assert backend.observe().exit_code == 0
            finally:
                close_test_actor(actor)


def _recover_project_check_controller(root, actor, frames, backend, reference, pin, journal):
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal

    started = root / 'check-owner-exit.json'
    failure = root / 'owned-guard-worker-error.txt'
    while not started.exists():
        try:
            actor.serve(
                frames,
                expected_backend=backend.identity,
                backend_image=pin,
                timeout_ms=30000,
                cancelled=lambda: started.exists() or failure.exists(),
            )
        except RuntimeError:
            if failure.exists():
                pytest.fail(failure.read_text(encoding='utf-8'))
            if not started.exists():
                raise
    assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
    assert backend.observe().exit_code == 0
    old = json.loads(started.read_bytes())
    scope = LaunchScope(**old['scope'])
    actions = GuardActionJournal(journal)
    assert actions.find(scope, 'RESUME').phase == 'ACKNOWLEDGED'
    assert actions.find(scope, 'RELEASE') is None
    endpoint = frames._io._endpoint
    frames.close()
    endpoint.disconnect_closed_peer()
    restarted = root / 'restarted'
    restarted.mkdir()
    failed = restarted / 'owned-guard-worker-error.txt'
    done = restarted / 'control-git-pipe-result.json'
    with (
        client_owner(
            restarted,
            endpoint,
            'SILENT',
            script=backend_worker_script(
                reference, backend.identity.user_sid, 'PROJECT_CHECK_RECOVER_CONTROLLER'
            ),
        ) as client,
        GuardPipeIO(endpoint) as io,
    ):
        client.start()
        io.connect(timeout_ms=15000, cancelled=failed.exists)
        current = client.ready()
        recovery_frames = GuardPipeFrames(io)
        while not done.exists():
            try:
                actor.serve(
                    recovery_frames,
                    expected_backend=current.identity,
                    backend_image=pin,
                    timeout_ms=30000,
                    cancelled=lambda: failed.exists() or done.exists(),
                )
            except RuntimeError:
                if failed.exists():
                    pytest.fail(failed.read_text(encoding='utf-8'))
                if not done.exists():
                    raise
        assert json.loads(done.read_bytes()) == {'recovered': True}
        (restarted / 'stop').touch(exist_ok=False)
        assert current._kernel.WaitForSingleObject(current._handle, 8000) == 0
        assert current.observe().exit_code == 0
    for action in ('STOP', 'RELEASE'):
        record = actions.find(scope, action)
        assert record.phase == 'ACKNOWLEDGED'
        assert record.owner_epoch == old['owner_epoch']
        assert record.requested_by_controller_ref != scope.controller_ref
    assert len(actor._owners) == 2
