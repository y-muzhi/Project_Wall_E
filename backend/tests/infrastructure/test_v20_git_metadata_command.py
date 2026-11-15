"""Real fixed Native/Registry metadata commands and original backend pipe capture."""

import ctypes
import json
import os
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure.git_bundle import BUNDLE_PARENT, verify_bundle_bytes
from backend.app.infrastructure.git_config_command import ConfigCommandError, ConfigParseCommand
from backend.app.infrastructure.git_metadata_command import (
    MetadataCommandError,
    RepositoryMetadataCommand,
)
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.git_repository_metadata import (
    MetadataTreeError,
    RepositoryMetadataLease,
)
from backend.app.infrastructure.git_worktrees import validate_worktree_links
from backend.app.infrastructure.runtime_control_git import ControlGitRegistry
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_empty_directory import (
    ReadOnlyEmptyDirectory,
    create_readonly_empty_directory,
)
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_native_process import NativeLaunchError, _command
from backend.app.infrastructure.windows_pipe_capture import (
    CapturedOutput,
    OutputCaptureError,
    OutputProgress,
)
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.windows_stdio import GuardStandardIO
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease
from backend.tests.infrastructure.test_v20_git_config_command import (
    read_peer_output,
    start_peer_capture,
    wait_empty,
)
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.infrastructure.test_v20_windows_stdio import (
    peer as peer_fixture,
)
from backend.tests.infrastructure.test_v20_windows_stdio import (
    publish,
    wait_file,
)
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


def run_native(
    command,
    directory,
    root,
    number,
    after_output=None,
    *,
    max_output_bytes=1024 * 1024,
    wait_seconds=8,
):
    peer_root = root / ('operation-' + str(number))
    peer_root.mkdir()
    scope = LaunchScope('a' * 64, number, 1, 'metadata-' + str(uuid4()))
    with (peer_root / 'stdio-scope.json').open('x', encoding='utf-8') as stream:
        json.dump(asdict(scope), stream)
    inventory = json.loads((BUNDLE_PARENT / 'win-x64/manifest.json').read_bytes())
    member = next(row for row in inventory['members'] if row['path'] == 'cmd/git.exe')
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    guard = None
    try:
        with contextmanager(peer_fixture.__wrapped__)(peer_root) as peer, ExitStack() as stack:
            controller, descriptor, _, _ = peer
            token = stack.enter_context(
                ControllerPrimaryToken(controller, expected=controller.identity)
            )
            image = stack.enter_context(
                ExecutablePin(
                    BUNDLE_PARENT / 'win-x64/cmd/git.exe',
                    expected_byte_count=member['byte_count'],
                    expected_sha256=member['sha256'],
                )
            )
            streams = stack.enter_context(GuardStandardIO(token, descriptor, scope=scope))
            publish(peer_root / 'copy-ack.json', asdict(streams.binding))
            wait_file(peer_root / 'copy-released.json')
            journal = stack.enter_context(
                LaunchJournal(create_private_package(peer_root / 'journal'))
            )
            guard = ControlGitRegistry(journal, token, controller_ref=scope.controller_ref)
            guard.register(scope, image, job, streams, directory, arguments=command)
            try:
                guard.create(scope)
                child = guard._entry(scope).root
                start_peer_capture(peer_root, maximum=max_output_bytes)
                guard.resume(scope)
                assert (
                    child._kernel.WaitForSingleObject(
                        child._info.process, max(1, min(8000, int(wait_seconds * 1000)))
                    )
                    == 0
                )
                exit_code = child.observe().exit_code
                wait_empty(job)
                output = read_peer_output(peer_root, maximum=max_output_bytes)
                progress = dict(output['progress'])
                progress['scope'] = LaunchScope(**progress['scope'])
                captured = CapturedOutput(
                    OutputProgress(**progress), output['STDOUT'], output['STDERR']
                )
                if after_output is not None:
                    after_output()
                return captured, scope, descriptor.io_nonce, exit_code
            finally:
                guard.stop(scope)
                wait_empty(job)
                try:
                    guard.release_native_handles(scope)
                except MetadataTreeError:
                    assert after_output is not None
                    assert guard._entry(scope).root._argument_context is None
                    guard.release_native_handles(scope)
                guard.close_watch()
    finally:
        job.terminate_owned(1)
        wait_empty(job)
        job.close()


def setup_repository(root, format, *, workspace=False, negative=False):
    nonce = uuid4().hex
    with (root / '.metadata-owner').open('x') as stream:
        stream.write(nonce)
    worker = ROOT / 'backend/tests/infrastructure/v20_metadata_setup_worker.py'
    code = '\n'.join(
        [
            'import runpy,sys',
            'sys.path.insert(0,' + repr(str(ROOT)) + ')',
            'sys.argv='
            + repr(
                [str(worker), str(root), nonce, format]
                + (['workspace'] if workspace else [])
                + (['negative'] if negative else [])
            ),
            'runpy.run_path(' + repr(str(worker)) + ',run_name="__main__")',
        ]
    )
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    process = None
    try:
        process = TestSuspendedRoot(job, root, code)
        process.resume()
        with ObservedProcess(process.pid) as observed:
            deadline = monotonic() + 45
            while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.01)
            assert observed.observe().state == 'EXITED'
            result = json.loads((root / 'setup-result.json').read_bytes())
            assert (
                observed.observe().exit_code == 0
                and result['nonce'] == nonce
                and result['completed']
            )
    finally:
        job.terminate_owned(1)
        if process is not None:
            assert job._kernel.WaitForSingleObject(process.info.process, 8000) == 0
            process.close()
        wait_empty(job)
        job.close()


@pytest.fixture
def resources(tmp_path, request):
    format = getattr(request, 'param', 'sha1')
    assert verify_bundle_bytes()[0] == 375
    setup_repository(tmp_path, format)
    private = create_private_package(tmp_path / 'private')
    empty = private / 'empty'
    empty.open('xb').close()
    with ExitStack() as stack:
        package = stack.enter_context(PrivatePackageGuard(private))
        directory = stack.enter_context(LocalPathGuard(private, directory=True))
        global_config = stack.enter_context(LockedConfigSource(empty, max_file_bytes=4096))
        hooks = stack.enter_context(
            ReadOnlyEmptyDirectory(create_readonly_empty_directory(package, 'hooks'))
        )
        location = stack.enter_context(
            RepositoryLocationLease(
                tmp_path / 'repository',
                private_roots=(private,),
                max_file_bytes=65536,
                max_open_handles=4096,
                max_metadata_entries=4096,
            )
        )
        copied = stack.enter_context(PrivateConfigCopy(location.config_source, package))
        parser = ConfigParseCommand(copied, global_config)
        stack.callback(parser.close)
        captured, scope, nonce, code = run_native(parser, directory, tmp_path, 1)
        parser.accept_output(
            captured,
            location,
            scope=scope,
            io_nonce=nonce,
            exit_code=code,
            max_output_bytes=65536,
            max_entries=100,
        )
        metadata = stack.enter_context(
            RepositoryMetadataLease(
                location,
                format=format,
                max_entries=1000,
                max_open_handles=20000,
                max_file_bytes=65536,
                max_metadata_bytes=1024 * 1024,
            )
        )
        yield SimpleNamespace(
            root=tmp_path,
            directory=directory,
            parser=parser,
            metadata=metadata,
            hooks=hooks,
            location=location,
            config_capture=captured,
            config_scope=scope,
            config_nonce=nonce,
        )


@pytest.mark.parametrize('resources', ['sha1', 'sha256'], indirect=True)
def test_fixed_metadata_commands_use_real_asuser_job_capture_and_original_ref_cohort(resources):
    data = resources
    commands = []
    try:
        for kind in ('LOCAL_BRANCHES', 'WORKTREES'):
            command = RepositoryMetadataCommand(data.metadata, data.parser, data.hooks, kind=kind)
            commands.append(command)
        branches_output = run_native(commands[0], data.directory, data.root, 2)
        branches = commands[0].decode_output(
            branches_output[0],
            scope=branches_output[1],
            io_nonce=branches_output[2],
            exit_code=branches_output[3],
            max_output_bytes=1024 * 1024,
        )
        trees_output = run_native(commands[1], data.directory, data.root, 3)
        trees = commands[1].decode_output(
            trees_output[0],
            scope=trees_output[1],
            io_nonce=trees_output[2],
            exit_code=trees_output[3],
            max_output_bytes=1024 * 1024,
        )
        validate_worktree_links(trees, branches)
        with WorktreeHeadLease(
            trees,
            branches,
            common_directory=data.location._common.path,
            private_roots=(data.directory.path,),
            max_file_bytes=65536,
            max_open_handles=20000,
        ) as originals:
            assert len(originals.verify()) == 2
            from backend.app.code_tasks.repository_observation_publish import (
                capture_repository_observation,
            )
            from backend.app.code_tasks.repository_registration import (
                capture_repository_registration,
            )

            registered = capture_repository_registration(data.metadata)
            assert registered.canonical_root == data.metadata.location.verify().root.canonical_path
            assert registered.object_format == data.metadata.verify().object_format
            assert registered.metadata_sha256 == data.metadata.verify().fingerprint_sha256
            captured = capture_repository_observation(data.metadata, originals)
            observed = json.loads(captured.payload_json)
            assert observed['head_commit'] == dict(data.metadata.verify().heads)['refs/heads/main']
            assert len(observed['worktrees']) == 2 and len(observed['local_branches']) == 3
            assert observed['status'] == 'READABLE'
            assert captured.object_format == data.metadata.verify().object_format

        assert {row.full_ref for row in branches} == {
            'refs/heads/main',
            'refs/heads/idle',
            'refs/heads/loose',
        }
        assert len(trees.entries) == 2
        assert commands[0]._uses == data.metadata._users == 0
        image = object.__new__(ExecutablePin)
        image._path = BUNDLE_PARENT / 'win-x64/cmd/git.exe'
        with pytest.raises(NativeLaunchError, match='NOT_REGISTERED'):
            _command(image, commands[0].arguments())
        assert 'safe.directory=*' not in commands[0].arguments()
        with patch.dict(
            os.environ, {'GIT_DIR': 'evil', 'GIT_CONFIG_COUNT': '1', 'HTTPS_PROXY': 'private'}
        ):
            assert set(commands[0].environment(r'C:\Windows')).isdisjoint(
                {'GIT_DIR', 'GIT_CONFIG_COUNT', 'HTTPS_PROXY'}
            )
    finally:
        for command in commands:
            command.close()


def test_incomplete_foreign_or_nonzero_config_result_never_becomes_metadata_admission(resources):
    data = resources
    for capture, nonce, code in [
        (
            replace(
                data.config_capture,
                progress=replace(data.config_capture.progress, stdout_eof=False),
            ),
            data.config_nonce,
            0,
        ),
        (data.config_capture, 'foreign', 0),
        (data.config_capture, data.config_nonce, True),
        (data.config_capture, data.config_nonce, 1),
    ]:
        with pytest.raises(OutputCaptureError):
            data.parser.accept_output(
                capture,
                data.location,
                scope=data.config_scope,
                io_nonce=nonce,
                exit_code=code,
                max_output_bytes=65536,
                max_entries=100,
            )


def test_source_change_after_read_releases_original_argument_borrows_without_replaying(resources):
    data = resources
    command = RepositoryMetadataCommand(
        data.metadata, data.parser, data.hooks, kind='LOCAL_BRANCHES'
    )
    try:

        def change():
            with (data.root / 'repository/.git/new-metadata').open('xb') as stream:
                stream.write(b'owned mutation')

        output = run_native(command, data.directory, data.root, 4, after_output=change)
        assert command._uses == data.metadata._users == data.parser._uses == data.hooks._uses == 0
        with pytest.raises(MetadataTreeError, match='LIST_CHANGED'):
            command.decode_output(
                output[0],
                scope=output[1],
                io_nonce=output[2],
                exit_code=output[3],
                max_output_bytes=65536,
            )
    finally:
        command.close()


@pytest.mark.parametrize('resources', ['sha1', 'sha256'], indirect=True)
def test_raw_commit_tree_blob_and_tag_conversion_use_original_native_chain(resources):
    import hashlib

    from backend.app.infrastructure.git_object_read import (
        GitObjectReadError,
        RepositoryObjectCommand,
    )
    from backend.app.infrastructure.git_ref_metadata import decode_packed_refs

    data = resources
    format = data.metadata.verify().object_format
    commit_oid = dict(data.metadata.verify().heads)['refs/heads/main']

    def read(kind, oid, number, maximum=65536, wait_seconds=8):
        command = RepositoryObjectCommand(
            data.metadata, data.parser, data.hooks, object_type=kind, oid=oid
        )
        try:
            output = run_native(
                command,
                data.directory,
                data.root,
                number,
                max_output_bytes=maximum,
                wait_seconds=wait_seconds,
            )
            result = command.decode_output(
                output[0],
                scope=output[1],
                io_nonce=output[2],
                exit_code=output[3],
                max_output_bytes=maximum,
            )
            assert (
                command._uses == data.metadata._users == data.parser._uses == data.hooks._uses == 0
            )
            image = object.__new__(ExecutablePin)
            image._path = BUNDLE_PARENT / 'win-x64/cmd/git.exe'
            with pytest.raises(NativeLaunchError, match='NOT_REGISTERED'):
                _command(image, command.arguments())
            if kind == 'blob':
                damaged = b'changed'
                capture = replace(
                    output[0],
                    stdout=damaged,
                    progress=replace(output[0].progress, stdout_bytes=len(damaged)),
                )
                with pytest.raises(GitObjectReadError, match='TYPE_OR_OID'):
                    command.decode_output(
                        capture,
                        scope=output[1],
                        io_nonce=output[2],
                        exit_code=output[3],
                        max_output_bytes=65536,
                    )
            return result
        finally:
            command.close()

    from backend.app.infrastructure.git_commit_closure import ClosureLimits, inspect_commit_closure

    captured = {}
    numbers = iter(range(10, 100))

    def original_read(request):
        value = read(
            request.object_type,
            request.object_oid,
            next(numbers),
            request.max_output_bytes,
            request.remaining_seconds,
        )
        captured[value.object_type] = value
        return value

    source = data.metadata.verify().fingerprint_sha256
    closure = inspect_commit_closure(
        (commit_oid,),
        format=format,
        read_object=original_read,
        source_fingerprint=source,
        verify_source=lambda: data.metadata.verify().fingerprint_sha256,
        check_active=lambda: None,
        limits=ClosureLimits(100, 100, 65536, 1024 * 1024, 300),
        started_at=monotonic(),
    )
    assert len(closure.objects) == 3 and closure.edge_count == 3
    from backend.app.infrastructure.content_manifest import ContentLimits
    from backend.app.infrastructure.content_secret_policy import (
        REFERENCE,
        inspect_registered_fixed_tree,
    )

    fixed = inspect_registered_fixed_tree(
        commit_oid,
        format=format,
        read_object=original_read,
        source_fingerprint=source,
        verify_source=lambda: data.metadata.verify().fingerprint_sha256,
        check_active=lambda: None,
        read_limits=ClosureLimits(100, 100, 65536, 1024 * 1024, 300),
        content_limits=ContentLimits(65536, 1024 * 1024, 100, 1),
        materialization_root=data.directory.path / 'prospective-workspace',
        secret_policy_ref=REFERENCE,
        started_at=monotonic(),
    )
    assert len(fixed.entries) == 1 and fixed.entries[0].path == 'fixture.txt'
    assert fixed.byte_count == len(b'owned fixed source\n')
    commit = captured['commit']
    from backend.app.infrastructure.git_object_graph import decode_commit_edges, decode_tree_edges

    edges = decode_commit_edges(commit, max_object_bytes=65536, max_headers=100)
    assert edges.parent_oids == ()
    tree_oid = edges.tree_oid
    tree = captured['tree']
    assert tree.object_oid == tree_oid
    binary_length = 20 if format == 'sha1' else 32
    assert (
        tree.raw.startswith(b'100644 fixture.txt\0')
        and len(tree.raw.split(b'\0', 1)[1]) == binary_length
    )
    children = decode_tree_edges(tree, max_object_bytes=65536, max_entries=100)
    assert len(children) == 1 and children[0].name == 'fixture.txt' and children[0].mode == '100644'
    blob_oid = children[0].object_oid
    assert blob_oid == tree.raw[-binary_length:].hex()
    blob = captured['blob']
    assert blob.object_oid == blob_oid
    assert blob.raw == b'owned fixed source\n'
    assert blob.sha256 == hashlib.sha256(blob.raw).hexdigest()

    source = next(
        value for key, value in data.metadata._sources.items() if key.endswith('packed-refs')
    )
    packed = decode_packed_refs(
        source.snapshot.raw, format=format, max_output_bytes=65536, max_refs=100
    )
    tag_oid = next(row.object_oid for row in packed if row.name == 'refs/tags/v1')
    # Real Git successfully returns a commit for a tag when asked for type commit.
    # Exact original type/OID integrity must nevertheless refuse that conversion.
    with pytest.raises(GitObjectReadError, match='TYPE_OR_OID'):
        read('commit', tag_oid, 99)
