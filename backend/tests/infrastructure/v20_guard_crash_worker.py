"""Owned crash-only Guard host for real last-Job-handle evidence, never a service."""

from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
from time import monotonic, sleep

from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.app.infrastructure.runtime_control_git import ControlGitRegistry
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_process import ObservedProcess, NativeProcessIdentity
from backend.app.infrastructure.windows_stdio import ChildStdioDescriptor, GuardStandardIO
from backend.tests.infrastructure.v20_stdio_worker import publish, wait


def main(directory, nonce):
    root = Path(directory).resolve(strict=True)
    if (
        root != Path.cwd().resolve()
        or (root / '.guard-proof-owner').read_text(encoding='ascii') != nonce
    ):
        raise ValueError('Exact owned Guard crash fixture required')
    packet = json.loads((root / 'stdio-ready.json').read_bytes())
    if (root / '.stdio-owner').read_text(encoding='ascii') != packet['nonce']:
        raise ValueError('Original owned backend fixture required')
    raw = packet['descriptor']
    scope = LaunchScope(**raw['scope'])
    descriptor = ChildStdioDescriptor(
        NativeProcessIdentity(**raw['owner']),
        scope,
        raw['io_nonce'],
        raw['stdin_handle'],
        raw['stdout_handle'],
        raw['stderr_handle'],
    )
    bundle = BUNDLE_PARENT / 'win-x64'
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    member = next(row for row in manifest['members'] if row['path'] == 'cmd/git.exe')
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    registry = None
    try:
        with ExitStack() as held:
            source = held.enter_context(
                ObservedProcess(descriptor.owner.pid, expected=descriptor.owner)
            )
            token = held.enter_context(ControllerPrimaryToken(source, expected=descriptor.owner))
            image = held.enter_context(
                ExecutablePin(
                    bundle / 'cmd/git.exe',
                    expected_byte_count=member['byte_count'],
                    expected_sha256=member['sha256'],
                )
            )
            cwd = held.enter_context(LocalPathGuard(root, directory=True))
            streams = held.enter_context(GuardStandardIO(token, descriptor, scope=scope))
            publish(root / 'copy-ack.json', asdict(streams.binding))
            wait(root / 'copy-released.json')
            package = create_private_package(root / 'crash-guard-journal')
            journal = held.enter_context(LaunchJournal(package))
            registry = ControlGitRegistry(journal, token, controller_ref=scope.controller_ref)
            try:
                registry.register(scope, image, job, streams, cwd)
                facts = registry.create(scope)
                registry.start_controller_watch()
                with ObservedProcess(os.getpid()) as guard:
                    guard_identity = asdict(guard.identity)
                publish(
                    root / 'guard-held-root.json',
                    {
                        'nonce': nonce,
                        'guard_identity': guard_identity,
                        'root_identity': facts['original_process_identity'],
                        'input_sha256': facts['input_sha256'],
                        'scope': asdict(scope),
                        'resource_ref': facts['resource_ref'],
                    },
                )
                # Parent deliberately kills this ORIGINAL worker without finally.
                # Keep a timeout/normal cleanup path for any failed test parent.
                deadline = monotonic() + 45
                while not (root / 'normal-guard-stop').exists() and monotonic() < deadline:
                    sleep(0.05)
            finally:
                if registry is not None:
                    registry.stop(scope)
                    entry = registry._entry(scope)
                    if entry.root is not None:
                        if job._kernel.WaitForSingleObject(entry.root._info.process, 8000) != 0:
                            raise RuntimeError('Original native root still active')
                    deadline = monotonic() + 8
                    while job.observe_members().process_ids and monotonic() < deadline:
                        sleep(0.01)
                    registry.release_native_handles(scope)
                    registry.close_watch()
    finally:
        job.terminate_owned(1)
        job.close()
