"""One isolated per-user native LPAC profile and its original cleanup."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin
from backend.app.infrastructure.windows_lpac_profile import TaskLpacProfile, TaskLpacProfileError
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_task_directories import TaskLpacDirectories, TaskRuntimeRoot
from backend.tests.infrastructure.test_v20_guard_action_journal import packet
from backend.tests.infrastructure.test_v20_opencode_binary import binary_installation
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    controller,
    ordinary_controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def lpac_scope(tmp_path, ordinary_controller, request):
    process, _ = ordinary_controller
    binding = GuardControllerBinding(uuid4().hex + uuid4().hex, str(uuid4()), process.identity)
    with (
        ControllerPrimaryToken(process, expected=binding.controller) as token,
        LaunchJournal(create_private_package(tmp_path / 'guard')) as journal,
        LocalDirectoryPin(tmp_path) as base,
        TaskRuntimeRoot.create(base, binding.controller.user_sid) as runtime_root,
        OwnedJob(
            active_process_limit=64 if getattr(request, 'param', None) == 'headless-runtime' else 2,
            job_memory_limit_bytes=(
                2048 if getattr(request, 'param', None) == 'headless-runtime' else 128
            )
            * 1024
            * 1024,
        ) as job,
    ):
        actions = GuardActionJournal(journal)
        action_input = {'run_kind': 'TASK'}
        if getattr(request, 'param', None) == 'check-project':
            candidate, _, _ = make_check_candidate(tmp_path)
            action_input.update(
                execution_purpose='CHECK',
                project_command={
                    'command_id': check_definition().command_id,
                    'definition_sha256': check_definition().definition_sha256,
                    'active_process_limit': 2,
                    'job_memory_limit_bytes': 128 * 1024 * 1024,
                },
                network={role: [] for role in ('model', 'forward', 'control', 'application')},
                check_input={
                    'owner_kind': 'CODING',
                    'owner_id': 9,
                    'control_generation': 2,
                    'verification_id': 13,
                    'item_id': 14,
                    'candidate_id': candidate.seal.binding.candidate_id,
                    'manifest_sha256': candidate.seal.manifest_sha256,
                },
            )
        request_header = packet(binding, action_input=action_input)
        prepare = _parse({**request_header.wire, 'step_no': 4}, binding)
        directories = TaskLpacDirectories(
            runtime_root, actions, actions.begin(prepare), prepare, binding, token
        )
        try:
            directories.allocate(cancelled=lambda: False)
            if directories.is_project_check:
                from backend.app.infrastructure.windows_task_check_input import TaskCheckWorkspace

                publication = TaskCheckWorkspace(directories, candidate)
                limits, git_limits = check_limits()
                publication.publish(limits=limits, git_limits=git_limits, cancelled=lambda: False)
            yield directories, job, journal
        finally:
            directories.close()


def test_per_user_profile_is_created_once_and_deleted_only_after_stop(lpac_scope):
    directories, job, journal = lpac_scope
    profile = TaskLpacProfile(directories, job)
    try:
        identity = profile.prepare(lambda: False)
        assert profile.verify(lambda: False) == identity
        assert identity.is_directory and Path(identity.canonical_path).is_dir()
        with pytest.raises(TaskLpacProfileError, match='ALREADY_DISPATCHED'):
            TaskLpacProfile(directories, job).prepare(lambda: False)
        with pytest.raises(TaskLpacProfileError, match='RELEASE_UNVERIFIED'):
            profile.release()
        assert Path(identity.canonical_path).exists()
    finally:
        journal.close_nonce(directories.scope)
        if profile._created:
            profile.release()
    assert not Path(identity.canonical_path).exists()
    assert profile._released
    profile.release()


@pytest.fixture
def suspended_lpac(lpac_scope, request, monkeypatch):
    import ctypes
    import hashlib
    import os
    from contextlib import ExitStack
    import shutil
    import subprocess
    import sys

    from backend.app.infrastructure.windows_executable_pin import ExecutablePin
    from backend.app.infrastructure.windows_job import (
        ALL_APPLICATION_PACKAGES_POLICY_ATTRIBUTE,
        JobMembers,
    )
    from backend.app.infrastructure.windows_native_process import ProcessInfo, StartupInfoEx, _api

    directories, job, journal = lpac_scope
    profile = TaskLpacProfile(directories, job)
    info = ProcessInfo()
    kernel, security = _api()
    if getattr(request, 'param', None) == 'ordinary_appcontainer':
        update = job._kernel.UpdateProcThreadAttribute

        def without_opt_out(*args):
            if args[2] == ALL_APPLICATION_PACKAGES_POLICY_ATTRIBUTE:
                return True
            return update(*args)

        monkeypatch.setattr(job._kernel, 'UpdateProcThreadAttribute', without_opt_out)
    diagnostic_mode = getattr(request, 'param', None)
    diagnostic_runtime = diagnostic_mode in (
        'base_runtime_debug',
        'base_runtime_registry_read_debug',
    )
    if diagnostic_mode == 'base_runtime_registry_read_debug':
        from backend.app.infrastructure import windows_job
        from backend.tests.infrastructure.v20_owned_debug_events import (
            diagnostic_registry_read_capability,
        )

        original_capabilities = windows_job._lpac_security_capabilities
        monkeypatch.setattr(
            windows_job,
            '_lpac_security_capabilities',
            lambda name: diagnostic_registry_read_capability(original_capabilities, name),
        )
    if diagnostic_runtime:
        from backend.tests.infrastructure.v20_browser_driver_native_worker import make_runner

        runtime = directories.root / 'runtime'
        make_runner(runtime, Path(os.environ['SystemRoot']) / 'System32' / 'findstr.exe')
        image = runtime / 'python.exe'
    else:
        image = directories.root / 'runtime' / 'probe.exe'
        shutil.copyfile(sys.executable, image)
    raw = image.read_bytes()
    created = False
    try:
        profile.prepare(lambda: False)
        with (
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            ExitStack() as diagnostic_resources,
        ):
            stdio = ()
            if diagnostic_runtime:
                from backend.tests.infrastructure.v20_owned_debug_events import DiagnosticStdio

                streams = diagnostic_resources.enter_context(DiagnosticStdio())
                stdio = tuple(streams.child)
                info._diagnostic_streams = streams
            with (
                directories._controller.creation_handle() as token,
                pin.creation_path() as application,
                job.process_creation_attributes(
                    lpac_profile=directories.profile, stdio_handles=stdio
                ) as attributes,
            ):
                startup = StartupInfoEx()
                startup.startup.cb = ctypes.sizeof(startup)
                startup.attributes = attributes
                if stdio:
                    startup.startup.flags = 0x100
                    startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdio
                system_root = Path(os.environ['SystemRoot'])
                scratch = directories.root / 'scratch'
                locations = {
                    'USERPROFILE': 'home',
                    'APPDATA': 'appdata',
                    'LOCALAPPDATA': 'localappdata',
                    'TEMP': 'temp',
                }
                for folder in locations.values():
                    (scratch / folder).mkdir()
                values = {
                    'SystemRoot': str(system_root),
                    'SystemDrive': system_root.drive,
                    **{key: str(scratch / folder) for key, folder in locations.items()},
                }
                values['TMP'] = values['TEMP']
                block = '\0'.join(f'{key}={values[key]}' for key in sorted(values, key=str.upper))
                environment = ctypes.create_unicode_buffer(block + '\0\0')
                command = ctypes.create_unicode_buffer(
                    subprocess.list2cmdline([application, '-I', '-B', '-c', 'raise SystemExit(91)'])
                )
                flags = 0x4 | 0x80000 | 0x400 | 0x08000000
                if diagnostic_runtime:
                    flags |= 0x2  # DEBUG_ONLY_THIS_PROCESS, owned diagnostic child only.
                if not security.CreateProcessAsUserW(
                    token,
                    application,
                    command,
                    None,
                    None,
                    bool(stdio),
                    flags,
                    environment,
                    str(directories.root / 'workspace'),
                    ctypes.byref(startup),
                    ctypes.byref(info),
                ):
                    pytest.fail(f'Native CreateProcessAsUserW failed: {ctypes.get_last_error()}')
                created = True
                if diagnostic_runtime:
                    streams.close_child_ends()
            assert job.observe_members() == JobMembers((info.pid,), 1, True)
            yield directories, job, profile, info, pin
    finally:
        if created:
            job.terminate_owned(0)
            if diagnostic_runtime and kernel.WaitForSingleObject(info.process, 0) != 0:
                from backend.tests.infrastructure.v20_owned_debug_events import (
                    drain_owned_debug_exit,
                )

                drain_owned_debug_exit(info)
            assert kernel.WaitForSingleObject(info.process, 8000) == 0
            assert kernel.CloseHandle(info.thread)
            assert kernel.CloseHandle(info.process)
        journal.close_nonce(directories.scope)
        if profile._created:
            profile.release()


def test_actual_suspended_root_token_is_original_lpac(suspended_lpac):
    from backend.app.infrastructure.windows_lpac_token import LpacProcessToken

    directories, job, profile, info, pin = suspended_lpac
    token = LpacProcessToken(info, job, profile, pin)
    try:
        identity = token.verify()
        assert identity.process.pid == info.pid
        assert identity.process.appcontainer_sid == directories.package_sid
        assert identity.lpac_evidence in ('TOKEN_FLAG', 'EFFECTIVE_OPT_OUT')
        assert identity.process.is_lpac is not False
        assert identity.integrity_sid == 'S-1-16-4096'
        assert (
            identity.authentication_id_hex == directories._controller.identity.authentication_id_hex
        )
    finally:
        token.close()


@pytest.mark.parametrize('suspended_lpac', ['ordinary_appcontainer'], indirect=True)
def test_actual_ordinary_appcontainer_does_not_pass_lpac_verification(suspended_lpac):
    from backend.app.infrastructure.windows_lpac_token import LpacProcessToken, LpacTokenError

    _, job, profile, info, pin = suspended_lpac
    with pytest.raises(LpacTokenError, match='TOKEN_(FLAG_FALSE|OPT_OUT_UNVERIFIED)'):
        LpacProcessToken(info, job, profile, pin)


def test_actual_lpac_effective_task_role_and_protected_access(suspended_lpac, tmp_path):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_lpac_access import verify_lpac_task_access
    from backend.app.infrastructure.windows_lpac_token import LpacProcessToken, LpacTokenError

    directories, job, profile, info, pin = suspended_lpac
    source = create_private_package(tmp_path / 'protected-source')
    members = {'runtime': (pin.verify().file,)}
    for role in ('basis', 'config'):
        target = directories.root / role / 'read-only.txt'
        target.write_bytes(b'isolated fixture')
        with LocalPathGuard(target, directory=False) as held:
            members[role] = (held.verify(),)
    token = LpacProcessToken(info, job, profile, pin)
    try:
        with LocalPathGuard(source, directory=True) as source_guard:
            evidence = verify_lpac_task_access(
                token, directories, members, (source_guard.verify(),), lambda: None
            )
            profile._journal.close_nonce(directories.scope)
            with pytest.raises(LpacTokenError, match='ACCESS_SCOPE_FENCED'):
                verify_lpac_task_access(
                    token, directories, members, (source_guard.verify(),), lambda: None
                )
        assert evidence.object_count == 11
    finally:
        token.close()


@pytest.mark.parametrize('outcome', ['resume', 'lost_receipt', 'stop_first', 'stop_before_create'])
def test_native_task_launch_uses_original_job_and_durable_fence(
    lpac_scope, binary_installation, tmp_path, outcome, monkeypatch
):
    import json
    from dataclasses import replace
    from time import monotonic
    from types import SimpleNamespace

    from backend.app.infrastructure import windows_task_runtime_environment as runtime_environment
    from backend.app.infrastructure.opencode_binary import VERSION
    from backend.app.infrastructure.opencode_control import OpenCodeControlCredential
    from backend.app.infrastructure.opencode_managed_config import _source_is_absent
    from backend.app.infrastructure.opencode_runtime_bundle import REF_PREFIX
    from backend.app.infrastructure.opencode_task_launch import TaskExecutionPlan, TaskProgramOwner
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
    from backend.app.infrastructure.windows_job import JobMembers
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure import windows_task_native_launch as native_launch
    from backend.app.infrastructure.windows_task_workspace_tree import observe_task_workspace_tree

    directories, job, journal = lpac_scope
    profile = TaskLpacProfile(directories, job)
    binary, _ = binary_installation
    image = directories.root / 'runtime' / binary.image.name
    image.write_bytes(binary.image.read_bytes())
    source = replace(binary, image=image, runtime_bundle_ref=REF_PREFIX + 'a' * 64)
    plan = TaskExecutionPlan.parse(
        {
            'version': VERSION,
            'binary_ref': source.binary_ref,
            'active_process_limit': 2,
            'job_memory_limit_bytes': 128 * 1024 * 1024,
        },
        {
            'model': [{'address': '127.0.0.1', 'port': 41001}],
            'control': [{'address': '127.0.0.1', 'port': 41002}],
            'forward': [],
            'application': [],
        },
        source.runtime_bundle_ref,
    )
    program = TaskProgramOwner(source, plan)
    native = None
    created_folder = environment = credential = None

    def checkpoint():
        pass

    try:
        created_folder = profile.prepare(lambda: False)
        program.prepare(deadline=monotonic() + 8, cancelled=lambda: False)
        native = native_launch.TaskNativeLaunch(directories, job, profile, program)
        managed = tmp_path / 'managed-fixture'
        managed.mkdir()
        monkeypatch.setattr(
            runtime_environment, 'opencode_managed_source_clear', lambda: _source_is_absent(managed)
        )
        configuration = directories.root / 'runtime' / 'opencode.json'
        configuration.write_bytes(b'{}')
        environment = runtime_environment.TaskRuntimeEnvironment(
            directories, SimpleNamespace(configuration_path=configuration)
        )
        environment.prepare(checkpoint)
        credential = OpenCodeControlCredential.issue(directories.scope, plan)
        protected = create_private_package(tmp_path / 'native-protected')
        destination = directories.workspace_destination().directory
        workspace = Path(destination.canonical_path)
        (workspace / 'fixture.txt').write_bytes(b'keep this workspace original')
        tree = observe_task_workspace_tree(workspace, destination, checkpoint)
        with LocalPathGuard(protected, directory=True) as source_guard:

            def create():
                return native.create(
                    'b' * 64,
                    environment,
                    credential,
                    {'basis': (), 'config': (), 'runtime': (program._image.verify().file,)},
                    (source_guard.verify(),),
                    checkpoint,
                    workspace_tree_sha256=tree,
                )

            if outcome == 'stop_before_create':
                stopped = native.stop(checkpoint, deadline=monotonic() + 3)
                assert stopped['process_state'] == 'NOT_CREATED'
                with pytest.raises(LaunchOutcomeUnknown, match='LAUNCH_CLOSED'):
                    create()
                assert not native._created
                return

            if outcome == 'lost_receipt':
                publish = native_launch._publish_original

                def lose_receipt(*args):
                    publish(*args)
                    raise OSError('fixture lost original receipt confirmation')

                with monkeypatch.context() as patch:
                    patch.setattr(native_launch, '_publish_original', lose_receipt)
                    with pytest.raises(OSError, match='lost original receipt') as failure:
                        create()
                    assert failure.value.retained_owner is native
                suspended = native.observe()
            else:
                suspended = create()
            assert suspended['process_state'] == 'SUSPENDED'
            assert suspended['job'] == JobMembers((native._info.pid,), 1, True)
            assert suspended['fence'].create_state == 'RESOURCE_RECORDED'
            unrelated = native_launch.TaskNativeLaunch(directories, job, profile, program)
            assert unrelated.observe()['process_state'] == 'UNKNOWN'
            assert unrelated.observe()['resource_ref'] is None
            facts = json.loads((journal.root / native._record_name).read_bytes())
            assert facts['resource_ref'] == suspended['resource_ref']
            assert facts['pid'] == native._info.pid
            assert len(facts['token_sha256']) == len(facts['access_sha256']) == 64
            with pytest.raises(LaunchOutcomeUnknown, match='CREATE_REQUIRES_OBSERVATION'):
                create()
            with pytest.raises(LaunchOutcomeUnknown, match='RESUME_RECEIPT_REQUIRED'):
                native.resume('0' * 64, checkpoint)
            assert journal.inspect(directories.scope).resume_state == 'NONE'
            if outcome in ('resume', 'lost_receipt'):
                running = native.resume(suspended['receipt_sha256'], checkpoint)
                assert running['fence'].resume_state == 'ACKNOWLEDGED'
                assert running['process_state'] in ('RUNNING', 'EXITED')
                with pytest.raises(LaunchOutcomeUnknown, match='RESUME_RECEIPT_REQUIRED'):
                    native.resume(suspended['receipt_sha256'], checkpoint)
            stopped = native.stop(checkpoint, deadline=monotonic() + 4)
            assert stopped['process_state'] == 'EXITED' and stopped['job'] == JobMembers(
                (), 0, True
            )
            assert stopped['fence'].stop_closed
            assert native.stop(checkpoint, deadline=monotonic() + 4) == stopped
            stop_record = json.loads((journal.root / native._stop_name).read_bytes())
            assert (
                stop_record['root_state'] == 'EXITED'
                and stop_record['resource_ref'] == suspended['resource_ref']
            )
            with pytest.raises(LaunchOutcomeUnknown, match='LAUNCH_CLOSED'):
                native.resume(suspended['receipt_sha256'], checkpoint)
    finally:
        journal.close_nonce(directories.scope)
        if native is not None and native._created:
            if job.observe_members() != JobMembers((), 0, True):
                job.terminate_owned(1)
            assert native._kernel.WaitForSingleObject(native._info.process, 8000) == 0
            native.close()
        if created_folder is not None:
            assert job.observe_members() == JobMembers((), 0, True)
            assert profile.verify_identity() == created_folder
            # The test alone allocated this random profile. Product cleanup still
            # needs the original network and dispatched RELEASE pipeline.
            assert (
                profile._call(lambda: profile._api.DeleteAppContainerProfile(directories.profile))
                == 0
            )
            assert not Path(created_folder.canonical_path).exists()
        if credential is not None:
            credential.close()
        if environment is not None:
            environment.close()
        program.close()


def check_limits():
    from backend.app.infrastructure.content_manifest import ContentLimits
    from backend.app.infrastructure.git_commit_closure import ClosureLimits

    return ContentLimits(1024, 4096, 10, 4096), ClosureLimits(20, 20, 4096, 4096, 10)


def make_check_candidate(tmp_path):
    from hashlib import sha1
    from zlib import compress

    from backend.app.infrastructure.content_manifest import (
        ContentEntry,
        _canonical,
        build_manifest,
        encode_manifest,
        manifest_sha256,
    )
    from backend.app.infrastructure.content_package import CandidatePackageBinding, SealedCandidate
    from backend.app.infrastructure.content_package_publish import PublishedCandidate
    from backend.app.infrastructure.git_content_command import content_config_bytes
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

    def loose(kind, data):
        raw = kind + b' ' + str(len(data)).encode() + b'\0' + data
        return sha1(raw, usedforsecurity=False).hexdigest(), compress(raw)

    file_bytes = b'WALLE\xff\0\r\n'
    blob, blob_bytes = loose(b'blob', file_bytes)
    child, child_bytes = loose(b'tree', b'100644 input.bin\0' + bytes.fromhex(blob))
    tree, tree_bytes = loose(b'tree', b'40000 src\0' + bytes.fromhex(child))
    import hashlib

    limits, _ = check_limits()
    binding = CandidatePackageBinding(5, 6, 2, '1' * 32, 3, 'sha1')
    manifest = build_manifest(
        (
            ContentEntry(
                'src/input.bin',
                '100644',
                blob,
                len(file_bytes),
                hashlib.sha256(file_bytes).hexdigest(),
            ),
        ),
        content_profile_version_id=3,
        format='sha1',
        content_tree_oid=tree,
        limits=limits,
    )
    raw_manifest = encode_manifest(manifest, limits)
    seal = SealedCandidate(
        binding, manifest, manifest_sha256(raw_manifest), '2026-11-09T15:00:00.000Z'
    )
    store = create_private_package(tmp_path / 'check-packages')
    root = create_private_package(store / binding.package_name(staged=False))
    repo = root / 'repo.git'
    for name in ('objects/info', 'objects/pack', 'refs/heads', 'refs/tags', 'refs/walle'):
        (repo / name).mkdir(parents=True)
    for oid, raw in ((blob, blob_bytes), (child, child_bytes), (tree, tree_bytes)):
        parent = repo / 'objects' / oid[:2]
        parent.mkdir(exist_ok=True)
        (parent / oid[2:]).write_bytes(raw)
    (repo / 'HEAD').write_bytes(b'ref: refs/heads/walle-content\n')
    (repo / 'config').write_bytes(content_config_bytes('sha1'))
    (repo / 'refs/walle/content').write_bytes(tree.encode() + b'\n')
    (root / 'manifest.json').write_bytes(raw_manifest)
    (root / 'seal.json').write_bytes(
        _canonical(binding.seal(manifest, seal.manifest_sha256, seal.captured_at))
    )
    with PrivatePackageGuard(root) as package:
        candidate = PublishedCandidate(seal, package.verify())
    return candidate, store, file_bytes


@pytest.mark.parametrize('lpac_scope', ['check-project'], indirect=True)
def test_actual_lpac_project_check_reads_fixed_candidate_and_only_writes_scratch(suspended_lpac):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_lpac_access import verify_lpac_task_access
    from backend.app.infrastructure.windows_lpac_token import LpacProcessToken
    from backend.app.infrastructure.windows_private_package import PackageSecurityError
    from backend.app.infrastructure.windows_task_check_input import (
        CheckInputError,
        TaskCheckWorkspace,
    )

    directories, job, profile, info, pin = suspended_lpac
    publication = directories._check_publication
    facts = publication.verify(lambda: None)
    members = {
        'runtime': (pin.verify().file,),
        'basis': (),
        'config': (),
        'workspace': facts.members,
    }
    candidate = publication._candidate
    workspace = directories.root / 'workspace'
    scratch = directories.root / 'scratch'
    with pytest.raises(PackageSecurityError, match='WRITER_NOT_ALLOWED'):
        directories.workspace_destination()
    another = TaskCheckWorkspace(directories, candidate)
    limits, git_limits = check_limits()
    with pytest.raises(CheckInputError, match='ALREADY_RESERVED'):
        another.publish(limits=limits, git_limits=git_limits, cancelled=lambda: False)
    with LocalPathGuard(candidate.directory.canonical_path, directory=True) as source:
        token = LpacProcessToken(info, job, profile, pin)
        try:
            evidence = verify_lpac_task_access(
                token, directories, members, (source.verify(),), lambda: None
            )

            def attempt():
                assert (workspace / 'src/input.bin').read_bytes() == b'WALLE\xff\0\r\n'
                for target in (
                    workspace / 'src/input.bin',
                    workspace / 'src/new.bin',
                    workspace / 'new.bin',
                ):
                    with pytest.raises(PermissionError), target.open('ab'):
                        raise AssertionError('The LPAC must not be able to write into inputs')
                with pytest.raises(PermissionError):
                    (workspace / 'src/input.bin').unlink()
                (scratch / 'result.tmp').write_bytes(b'output')

            token.with_restricted_token(attempt)
        finally:
            token.close()
    assert evidence.object_count == 11
    assert (scratch / 'result.tmp').read_bytes() == b'output'
    assert publication.verify(lambda: None) == facts
    (workspace / 'src/input.bin').write_bytes(b'changed')
    with pytest.raises(CheckInputError, match='INPUT_CHANGED'):
        publication.verify(lambda: None)


@pytest.mark.parametrize('lpac_scope', ['check-project'], indirect=True)
def test_check_environment_has_only_original_scratch_and_never_inherits_credentials(
    lpac_scope, monkeypatch
):
    from backend.app.infrastructure.windows_task_runtime_environment import TaskRuntimeEnvironment
    from backend.app.infrastructure.windows_task_runtime_bundle import TaskRuntimeFilesError

    directories, _, _ = lpac_scope
    for name in (
        'NODE_OPTIONS',
        'PYTHONPATH',
        'HTTPS_PROXY',
        'OPENCODE_CONFIG',
        'NPM_CONFIG_USERCONFIG',
    ):
        monkeypatch.setenv(name, 'untrusted-parent-value')
    environment = TaskRuntimeEnvironment(directories, None)
    try:
        evidence = environment.prepare(lambda: None)
        assert environment.verify(lambda: None) == evidence
        values = environment.values(lambda: None)
        assert set(values).isdisjoint(
            {
                'NODE_OPTIONS',
                'PYTHONPATH',
                'HTTPS_PROXY',
                'OPENCODE_CONFIG',
                'NPM_CONFIG_USERCONFIG',
            }
        )
        output = Path(values['WALLE_CHECK_OUTPUT'])
        assert output.is_dir()
        assert output == directories.root / 'scratch' / 'output'
        assert Path(values['TEMP']).is_relative_to(directories.root / 'scratch')
        assert not list((directories.root / 'config').iterdir())
        with pytest.raises(TaskRuntimeFilesError, match='CREDENTIAL_REQUIRED'):
            environment.launch_values(None, None, lambda: None)
    finally:
        environment.close()


def check_definition(*, timeout_seconds=15, missing=False, stdin=False, fixture=False):
    from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand

    return ProjectCheckCommand.decode(
        {
            'command_id': 'match-stdin'
            if stdin
            else 'find-absent-text'
            if missing
            else 'find-original-text',
            'executable_ref': 'fixture:findstr',
            'argument_template': ['/L', 'WALLE']
            if stdin
            else ['/L', 'WALLE', '{CHECK_FIXTURE}/data/sample.txt']
            if fixture
            else ['/L', 'ABSENT' if missing else 'WALLE', 'src\\\\input.bin'],
            'working_directory': '.',
            'purpose': 'CHECK',
            'timeout_seconds': timeout_seconds,
            'network_scope_ref': None,
        }
    )


FIXED_FIXTURE_BYTES = b'WALLE fixture\r\n'


def make_fixed_check_fixture(root):
    from hashlib import sha256

    from backend.app.infrastructure.check_fixture import RegisteredCheckFixture
    from backend.app.infrastructure.runtime_launch_journal import _bytes
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

    fixture = create_private_package(root / 'fixed-testing-input')
    (fixture / 'data').mkdir()
    (fixture / 'data' / 'sample.txt').write_bytes(FIXED_FIXTURE_BYTES)
    raw = _bytes(
        {
            'schema_version': 1,
            'target': {'fixture_ref': 'fixture:testing-input'},
            'file_entries': [
                {
                    'path': 'data/sample.txt',
                    'byte_count': len(FIXED_FIXTURE_BYTES),
                    'sha256': sha256(FIXED_FIXTURE_BYTES).hexdigest(),
                }
            ],
        }
    )
    (fixture / 'manifest.json').write_bytes(raw)
    with PrivatePackageGuard(fixture) as package:
        return RegisteredCheckFixture(
            'fixture:testing-input', sha256(raw).hexdigest(), package.verify()
        )


@pytest.mark.parametrize('lpac_scope', ['check-project'], indirect=True)
def test_original_offline_project_job_starts_and_reports_actual_exit(
    lpac_scope, tmp_path, monkeypatch
):
    from hashlib import sha256
    from time import monotonic, sleep

    from backend.app.infrastructure import guard_task_network as network
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_project_check_command import (
        ProjectCheckNetwork,
        ProjectCheckProgram,
        RegisteredCheckExecutable,
    )
    from backend.app.infrastructure.windows_task_native_launch import TaskNativeLaunch
    from backend.app.infrastructure.windows_task_runtime_environment import (
        TaskRuntimeEnvironment,
        _windows_system_paths,
    )

    directories, job, journal = lpac_scope
    profile = TaskLpacProfile(directories, job)
    _, system = _windows_system_paths()
    raw = (Path(system.canonical_path) / 'findstr.exe').read_bytes()
    path = create_private_package(tmp_path / 'registered-check') / 'findstr.exe'
    path.write_bytes(raw)
    with LocalPathGuard(path, directory=False) as source:
        executable = RegisteredCheckExecutable(
            'fixture:findstr', source.verify(), sha256(raw).hexdigest(), len(raw)
        )
    environment = TaskRuntimeEnvironment(directories, None)
    program = ProjectCheckProgram(directories, check_definition(), executable)
    provider, sublayer = uuid4(), uuid4()
    policy = ProjectCheckNetwork(directories, provider, sublayer)
    readbacks = []
    native = None
    try:
        environment.prepare(lambda: None)
        program.prepare(deadline=monotonic() + 15, cancelled=lambda: False)
        profile.prepare(lambda: False)
        native = TaskNativeLaunch(directories, job, profile, program)
        with pytest.raises(LaunchOutcomeUnknown, match='MODEL_SOURCE_DENIED'):
            native.verify_model_root(lambda: None)
        actions = directories._actions
        protected = (directories._check_publication._candidate.directory,)
        marker = network.seal_original_task_network(
            actions, directories._prepare_request, provider=provider, sublayer=sublayer
        )
        with pytest.raises(network.WfpObservationError, match='INSTALL_DISPATCH_REQUIRED'):
            native.project_launch_input(environment, policy, protected, lambda: None)
        assert not job.observe_members().process_ids
        sealed = network._sealed_bytes(actions, directories.scope)
        network._publish_once(
            actions,
            directories._original,
            network._INSTALL_DISPATCH,
            network._install_dispatch(sealed, bytes.fromhex(marker)),
        )

        def read(
            rules, actual_provider, actual_sublayer, actual_marker, *, check_external, checkpoint
        ):
            assert (actual_provider, actual_sublayer, actual_marker.hex()) == (
                provider,
                sublayer,
                marker,
            )
            assert check_external and len(rules) == 6
            checkpoint()
            readbacks.append(rules)
            return len(rules)

        monkeypatch.setattr(network, 'read_owned_filters', read)
        digest = native.project_launch_input(environment, policy, protected, lambda: None)
        result = native.create_project_check(digest, environment, policy, protected, lambda: None)
        assert result['process_state'] == 'SUSPENDED'
        assert result['process_identity'].appcontainer_sid == directories.package_sid
        assert result['job'].process_ids == (result['process_identity'].pid,)
        native.resume(result['receipt_sha256'], lambda: None)
        deadline = monotonic() + 10
        while monotonic() < deadline and native.observe()['process_state'] != 'EXITED':
            sleep(0.005)
        assert native.observe()['process_state'] == 'EXITED'
        assert not native.stop(lambda: None, deadline=deadline)['job'].process_ids
        outcome = native.project_exit()
        assert outcome.scope == directories.scope and outcome.binding_ref == directories.binding_ref
        assert outcome.exit_code == 0
        assert not outcome.terminated and len(readbacks) == 3
        assert directories._check_publication.verify(lambda: None).check == directories.check_input
    finally:
        try:
            if native is not None:
                try:
                    native.stop(lambda: None, deadline=monotonic() + 8)
                    if profile._created:
                        profile.release_after_native_stop(native)
                finally:
                    native.close()
            else:
                journal.close_nonce(directories.scope)
                if profile._created:
                    profile.release()
        finally:
            program.close()
            environment.close()
