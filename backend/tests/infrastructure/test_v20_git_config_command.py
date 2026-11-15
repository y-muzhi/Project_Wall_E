"""Fixed config parsing through real ordinary AsUser/Journal/Registry ownership."""

from dataclasses import asdict
from contextlib import ExitStack
import json
import os
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.app.infrastructure.git_config_command import ConfigCommandError, ConfigParseCommand
from backend.app.infrastructure.git_local_config import validate_local_config_output
from backend.app.infrastructure.runtime_control_git import ControlGitRegistry
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_config_copy import ConfigCopyError, PrivateConfigCopy
from backend.app.infrastructure.windows_config_source import ConfigReadError, LockedConfigSource
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_native_process import (
    NativeLaunchError,
    _command,
    control_git_input_sha256,
)
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_stdio import GuardStandardIO
from backend.tests.infrastructure.test_v20_windows_stdio import peer, publish, wait_file
from backend.tests.infrastructure.test_v20_windows_native_process import scope
from backend.tests.requirements.test_v15_foundation import tmp_path


RAW = b'[core]\n repositoryformatversion=0\n bare=false\n[user]\n name=PRIVATE_COMMAND_VALUE\n'
SCOPE = scope()


@pytest.fixture
def command_resources(tmp_path, request):
    parameter = getattr(request, 'param', 'sha1')
    format, extra_bytes = parameter if type(parameter) is tuple else (parameter, 0)
    raw = (
        RAW
        if format == 'sha1'
        else RAW.replace(b'formatversion=0', b'formatversion=1')
        + b'[extensions]\n objectformat=sha256\n'
    )
    if extra_bytes:
        raw = raw.replace(b'PRIVATE_COMMAND_VALUE', b'X' * extra_bytes)
    original = tmp_path / 'original.config'
    with original.open('xb') as stream:
        stream.write(raw)
    package = create_private_package(tmp_path / 'parse-private')
    empty = package / 'global.empty'
    empty.open('xb').close()
    with (
        PrivatePackageGuard(package) as private,
        LockedConfigSource(original, max_file_bytes=max(4096, len(raw))) as source,
        LockedConfigSource(empty, max_file_bytes=4096) as global_config,
        PrivateConfigCopy(source, private) as copied,
        LocalPathGuard(package, directory=True) as directory,
    ):
        command = ConfigParseCommand(copied, global_config)
        try:
            yield SimpleNamespace(
                raw=raw,
                object_format=format,
                command=command,
                copied=copied,
                source=source,
                empty=global_config,
                directory=directory,
                package=private,
                root=tmp_path,
            )
        finally:
            command.close()


@pytest.mark.parametrize('copied,empty', [(None, None), ({}, {}), ('file', 'file')])
def test_command_requires_actual_original_private_resource_types(copied, empty):
    with pytest.raises(ConfigCommandError, match='ORIGINAL_PRIVATE_CONFIG'):
        ConfigParseCommand(copied, empty)


def test_exact_private_arguments_nonsecret_facts_and_fresh_environment(command_resources):
    value = command_resources
    command = value.command
    assert command.arguments() == (
        'config',
        '--file',
        str(value.copied._path),
        '--no-includes',
        '--null',
        '--list',
    )
    facts = command.facts(value.directory)
    assert 'PRIVATE_COMMAND_VALUE' not in json.dumps(facts)
    assert facts['source']['sha256'] == facts['copy']['sha256']
    with patch.dict(
        os.environ,
        {
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'alias.evil',
            'GIT_CONFIG_VALUE_0': '!cmd',
            'HTTPS_PROXY': 'PRIVATE_PROXY',
            'OPENAI_API_KEY': 'PRIVATE_API_KEY',
            'PATH': 'PERSONAL_PATH',
        },
    ):
        env = command.environment(r'C:\Windows')
    assert set(env).isdisjoint(
        {
            'GIT_CONFIG_COUNT',
            'GIT_CONFIG_KEY_0',
            'GIT_CONFIG_VALUE_0',
            'HTTPS_PROXY',
            'OPENAI_API_KEY',
        }
    )
    assert env['GIT_CONFIG_GLOBAL'] == str(value.empty._path)
    assert env['GIT_CEILING_DIRECTORIES'] == str(value.package.path.parent)
    assert env['PATH'] == str(BUNDLE_PARENT / 'win-x64/cmd')
    assert env['GIT_NO_LAZY_FETCH'] == env['GIT_LITERAL_PATHSPECS'] == '1'
    env['HOME'] = 'changed'
    assert command.environment(r'C:\Windows')['HOME'] == str(value.package.path)


def test_borrow_denies_premature_command_copy_and_empty_config_close(command_resources):
    value = command_resources
    with value.command.hold(value.directory):
        with pytest.raises(ConfigCommandError, match='IN_USE'):
            value.command.close()
        with pytest.raises(ConfigCopyError, match='IN_USE'):
            value.copied.close()
        with pytest.raises(ConfigReadError, match='IN_USE'):
            value.empty.close()
    assert value.copied._uses == value.empty._borrows == 0
    value.command.close()
    with pytest.raises(ConfigCommandError, match='CLOSED'):
        value.command.arguments()


def test_foreign_working_directory_cannot_reuse_command(command_resources):
    value = command_resources
    with LocalPathGuard(value.root, directory=True) as foreign:
        with pytest.raises(ConfigCommandError, match='ORIGINAL_PRIVATE_NONREPOSITORY'):
            value.command.facts(foreign)


def test_nonempty_or_foreign_empty_global_rejected(command_resources):
    value = command_resources
    other = value.root / 'empty-outside'
    other.open('xb').close()
    with LockedConfigSource(other, max_file_bytes=4096) as outside:
        with pytest.raises(ConfigCommandError, match='PRIVATE_EMPTY_GLOBAL'):
            ConfigParseCommand(value.copied, outside)
    with pytest.raises(ConfigCommandError, match='PRIVATE_EMPTY_GLOBAL'):
        ConfigParseCommand(value.copied, value.source)


def test_unexpected_local_git_metadata_prevents_nonrepository_parse(command_resources):
    value = command_resources
    (value.package.path / '.git').mkdir()
    try:
        with pytest.raises(ConfigCommandError, match='PRIVATE_NONREPOSITORY'):
            value.command.facts(value.directory)
    finally:
        (value.package.path / '.git').rmdir()


def test_extracted_config_argv_is_not_a_registered_native_command(command_resources):
    image = object.__new__(ExecutablePin)
    image._path = BUNDLE_PARENT / 'win-x64/cmd/git.exe'
    with pytest.raises(NativeLaunchError, match='NOT_REGISTERED'):
        _command(image, command_resources.command.arguments())


@pytest.fixture
def native_resources(command_resources, peer):
    value = command_resources
    controller, descriptor, _, peer_directory = peer
    bundle = BUNDLE_PARENT / 'win-x64'
    inventory = json.loads((bundle / 'manifest.json').read_bytes())
    member = next(row for row in inventory['members'] if row['path'] == 'cmd/git.exe')
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    guard = None
    try:
        with ExitStack() as stack:
            token = stack.enter_context(
                ControllerPrimaryToken(controller, expected=controller.identity)
            )
            image = stack.enter_context(
                ExecutablePin(
                    bundle / 'cmd/git.exe',
                    expected_byte_count=member['byte_count'],
                    expected_sha256=member['sha256'],
                )
            )
            streams = stack.enter_context(GuardStandardIO(token, descriptor, scope=SCOPE))
            publish(peer_directory / 'copy-ack.json', asdict(streams.binding))
            wait_file(peer_directory / 'copy-released.json')
            journal = stack.enter_context(
                LaunchJournal(create_private_package(value.root / 'journal'))
            )
            guard = ControlGitRegistry(journal, token, controller_ref=SCOPE.controller_ref)
            try:
                guard.register(SCOPE, image, job, streams, value.directory, arguments=value.command)
                yield SimpleNamespace(
                    guard=guard,
                    value=value,
                    peer_directory=peer_directory,
                    job=job,
                    image=image,
                    streams=streams,
                    token=token,
                    journal=journal,
                )
            finally:
                guard.stop(SCOPE)
                entry = guard._entry(SCOPE)
                if entry.root is not None and not entry.released:
                    assert (
                        entry.root._kernel.WaitForSingleObject(entry.root._info.process, 8000) == 0
                    )
                deadline = monotonic() + 8
                while job.observe_members().process_ids and monotonic() < deadline:
                    sleep(0.01)
                guard.release_native_handles(SCOPE)
                guard.close_watch()
    finally:
        job.terminate_owned(1)
        deadline = monotonic() + 8
        while job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert job.observe_members().complete and not job.observe_members().process_ids
        job.close()


def start_peer_capture(directory, *, maximum=4096):
    publish(directory / 'parse-output-request', {'max_output_bytes': maximum})
    (directory / 'run-reader').open('x').close()
    wait_file(directory / 'capture-ready.json')


def read_peer_output(directory, *, maximum=4096):
    wait_file(directory / 'stdio-result.json')
    result = json.loads((directory / 'stdio-result.json').read_bytes())
    assert set(result) == {'STDOUT', 'STDERR', 'progress'}
    decoded = {key: bytes.fromhex(result[key]) for key in ('STDOUT', 'STDERR')}
    assert sum(len(raw) for raw in decoded.values()) <= maximum
    decoded['progress'] = result['progress']
    return decoded


def wait_empty(job):
    deadline = monotonic() + 8
    while job.observe_members().process_ids and monotonic() < deadline:
        sleep(0.01)
    assert job.observe_members().complete and not job.observe_members().process_ids


@pytest.mark.parametrize('command_resources', ['sha1', 'sha256'], indirect=True)
def test_actual_registered_asuser_config_parse_returns_real_original_bytes(native_resources):
    data = native_resources
    guard, value = data.guard, data.value
    facts = guard.create(SCOPE)
    entry = guard._entry(SCOPE)
    root = entry.root
    assert facts['fence']['create_state'] == 'RESOURCE_RECORDED'
    assert root._argument_context is not None and value.command._uses == 1
    with pytest.raises(ConfigCommandError, match='IN_USE'):
        value.command.close()
    with pytest.raises(ConfigCopyError, match='IN_USE'):
        value.copied.close()
    start_peer_capture(data.peer_directory)
    guard.resume(SCOPE)
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert root.observe().exit_code == 0
    wait_empty(data.job)
    output = read_peer_output(data.peer_directory)
    raw = output['STDOUT']
    expected = (
        b'core.repositoryformatversion\n0\0core.bare\nfalse\0user.name\nPRIVATE_COMMAND_VALUE\0'
    )
    if value.object_format == 'sha256':
        expected = (
            expected.replace(b'formatversion\n0', b'formatversion\n1')
            + b'extensions.objectformat\nsha256\0'
        )
    assert raw == expected
    assert output['STDERR'] == b''
    assert output['progress']['stdout_eof'] and output['progress']['stderr_eof']
    assert not output['progress']['limit_exceeded']
    assert guard._entry(SCOPE).creation_stdio_closed
    parsed = validate_local_config_output(
        raw,
        expected_object_format=value.object_format,
        expected_bare=False,
        max_output_bytes=4096,
        max_entries=100,
    )
    assert not parsed.bare and parsed.object_format == value.object_format
    assert value.command._uses == 1, 'Git exit alone must not drop original resource borrows'
    guard.stop(SCOPE)
    guard.release_native_handles(SCOPE)
    assert root._argument_context is None and value.command._uses == 0
    saved = guard.read_receipt(SCOPE, entry.receipt)
    assert 'PRIVATE_COMMAND_VALUE' not in json.dumps(saved)
    assert saved['native_handles_released']
    assert value.source.verify().raw == value.raw and value.copied.verify().raw == value.raw


def test_config_input_digest_and_registration_bind_all_originals(native_resources):
    data = native_resources
    value = data.value
    first = control_git_input_sha256(
        data.token, data.image, data.job, data.streams, value.directory, SCOPE, value.command
    )
    assert first == data.guard._entry(SCOPE).digest
    assert first != control_git_input_sha256(
        data.token, data.image, data.job, data.streams, value.directory, SCOPE, ('--version',)
    )
    other = ConfigParseCommand(value.copied, value.empty)
    try:
        # Even matching bytes cannot switch the original resource-owner object.
        with pytest.raises(Exception, match='BINDING_CONFLICT'):
            data.guard.register(
                SCOPE, data.image, data.job, data.streams, value.directory, arguments=other
            )
    finally:
        other.close()


def test_root_does_not_release_config_borrows_when_job_observation_unknown(native_resources):
    data = native_resources
    data.guard.create(SCOPE)
    data.guard.resume(SCOPE)
    root = data.guard._entry(SCOPE).root
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert root.observe().state == 'EXITED'
    wait_empty(data.job)
    original = data.job.observe_members()
    from dataclasses import replace

    with patch.object(data.job, 'observe_members', return_value=replace(original, complete=False)):
        with pytest.raises(NativeLaunchError, match='COMMAND_JOB_STILL_ACTIVE_OR_UNKNOWN'):
            root.close()
        assert root._argument_context is not None and data.value.command._uses == 1
    assert root._info.process and root._info.thread


def test_created_but_unverified_root_keeps_original_config_borrows(native_resources):
    from backend.app.infrastructure import windows_native_process as native
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown

    data = native_resources
    with patch.object(
        native.SuspendedControlGit,
        '_verify_created',
        side_effect=NativeLaunchError('TEST_CREATED_IDENTITY_UNKNOWN'),
    ):
        with pytest.raises(LaunchOutcomeUnknown, match='CREATE_OUTCOME_UNVERIFIED'):
            data.guard.create(SCOPE)
    root = data.guard._entry(SCOPE).root
    assert root is not None and root._argument_context is not None
    assert data.value.command._uses == data.value.copied._uses == data.value.empty._borrows == 1
    with pytest.raises(ConfigCopyError, match='IN_USE'):
        data.value.copied.close()
    with patch.object(native, 'SuspendedControlGit', side_effect=AssertionError('No replacement')):
        with pytest.raises(LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
            data.guard.create(SCOPE)


def test_unknown_resume_ack_keeps_config_and_original_dispatch_closed(native_resources):
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown

    data = native_resources
    data.guard.create(SCOPE)
    root = data.guard._entry(SCOPE).root
    original = root._kernel

    class Proxy:
        def __getattr__(self, name):
            if name == 'ResumeThread':
                return lambda handle: 0
            return getattr(original, name)

    try:
        root._kernel = Proxy()
        with pytest.raises(LaunchOutcomeUnknown, match='RESUME_OUTCOME_UNVERIFIED'):
            data.guard.resume(SCOPE)
        assert root._argument_context is not None and data.value.command._uses == 1
        with pytest.raises(LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
            data.guard.resume(SCOPE)
    finally:
        root._kernel = original


@pytest.mark.parametrize(
    'command_resources', [('sha1', 512 * 1024), ('sha256', 512 * 1024)], indirect=True
)
def test_large_actual_config_drains_while_original_git_is_running(native_resources):
    data = native_resources
    guard, value = data.guard, data.value
    guard.create(SCOPE)
    root = guard._entry(SCOPE).root
    start_peer_capture(data.peer_directory, maximum=1024 * 1024)
    guard.resume(SCOPE)
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert root.observe().exit_code == 0
    wait_empty(data.job)
    output = read_peer_output(data.peer_directory, maximum=1024 * 1024)
    raw = output['STDOUT']
    assert len(raw) > 512 * 1024 and b'X' * (512 * 1024) in raw
    assert output['STDERR'] == b''
    assert output['progress']['stdout_bytes'] == len(raw)
    assert output['progress']['stdout_eof'] and output['progress']['stderr_eof']
    assert not output['progress']['limit_exceeded']
    parsed = validate_local_config_output(
        raw,
        expected_object_format=value.object_format,
        expected_bare=False,
        max_output_bytes=1024 * 1024,
        max_entries=100,
    )
    assert parsed.object_format == value.object_format
    assert value.command._uses == 1
    assert guard.read_receipt(SCOPE, guard._entry(SCOPE).receipt)['creation_stdio_closed']


@pytest.mark.parametrize('command_resources', [('sha1', 512 * 1024)], indirect=True)
def test_real_output_limit_is_not_success_and_original_job_is_stopped(native_resources):
    data = native_resources
    data.guard.create(SCOPE)
    root = data.guard._entry(SCOPE).root
    start_peer_capture(data.peer_directory, maximum=4096)
    data.guard.resume(SCOPE)
    output = read_peer_output(data.peer_directory, maximum=4096)
    assert output['progress']['limit_exceeded']
    assert len(output['STDOUT']) + len(output['STDERR']) == 4096
    assert not (output['progress']['stdout_eof'] and output['progress']['stderr_eof'])
    data.guard.stop(SCOPE)
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    wait_empty(data.job)
    assert data.guard._entry(SCOPE).stop_requested
