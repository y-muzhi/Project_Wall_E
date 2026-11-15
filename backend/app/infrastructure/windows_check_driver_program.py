"""Materialize only the registered browser driver and its runtime into CHECK_DRIVER."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from backend.app.shared.validation import strict_integer

from .browser_driver_lpac_policy import runner_lpac_capability_names
from .check_runner_bundle import CheckResourceError, RegisteredCheckRunner, hold_check_runner_bundle
from .content_paths import relative_content_path
from .windows_config_source import LockedFileSource
from .windows_job import MAX_JOB_PROCESSES
from .windows_local_paths import FileIdentity, LocalPathGuard
from .windows_native_process import ExecutablePin
from .windows_project_check_command import _NativeCheckPlan
from .windows_task_directories import TaskLpacDirectories, _policy, _TaskDirectory
from .windows_task_workspace_tree import _scan_task_workspace_tree, workspace_tree_sha256


def browser_inspection_checkpoint(checkpoint, *, deadline, cancelled):
    next_check = 0.0

    def inspect():
        nonlocal next_check
        now = monotonic()
        if cancelled() or now >= deadline:
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_PREPARATION_INTERRUPTED')
        if now >= next_check:
            checkpoint()
            next_check = monotonic() + 0.1

    return inspect


@dataclass(frozen=True)
class RegisteredBrowserDriver:
    runner: RegisteredCheckRunner
    bootstrap_ref: str
    chromium_ref: str

    def __post_init__(self):
        if type(self.runner) is not RegisteredCheckRunner:
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_RUNNER_REQUIRED')
        for value in (self.bootstrap_ref, self.chromium_ref):
            relative_content_path(value)
        if not self.bootstrap_ref.endswith('.py') or not self.chromium_ref.lower().endswith('.exe'):
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_ENTRY_DIFFERS')

    def verify_closure(self, closure):
        files = {file.path: file for file in closure.manifest.file_entries}
        entry = closure.manifest.entry_ref
        if (
            closure.registration != self.runner
            or not {'BROWSER', 'CONTENT_INTEGRITY'}.issubset(closure.manifest.capabilities)
            or not entry.lower().endswith('.exe')
            or len({entry, self.bootstrap_ref, self.chromium_ref}) != 3
            or any(
                name not in files or not files[name].byte_count
                for name in (self.bootstrap_ref, self.chromium_ref, entry)
            )
        ):
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_CLOSURE_DIFFERS')
        return files


@dataclass(frozen=True)
class BrowserDriverFiles:
    directory: FileIdentity = field(repr=False)
    members: tuple[FileIdentity, ...] = field(repr=False)
    tree_identity_sha256: str
    lpac_capability_names: tuple[str, ...]


class BrowserDriverProgram:
    """One native immutable bundle copy, one job resource, no product code."""

    def __init__(self, directories, driver, *, processes, memory, case_pack_sha256):
        if (
            type(directories) is not TaskLpacDirectories
            or not directories.is_browser_driver
            or type(driver) is not RegisteredBrowserDriver
        ):
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_SCOPE_REQUIRED')
        self._dirs = directories
        self.driver = driver
        runtime = directories.root / 'runtime'
        arguments = (
            '-I',
            '-B',
            str(runtime / driver.bootstrap_ref),
            '--browser',
            str(runtime / driver.chromium_ref),
            '--case-pack-sha256',
            case_pack_sha256,
        )
        self.plan = _NativeCheckPlan(
            arguments,
            strict_integer(processes, 'active_process_limit', maximum=MAX_JOB_PROCESSES),
            strict_integer(memory, 'job_memory_limit_bytes'),
        )
        self._image = self._facts = self._layout = None
        self._children = {}
        self._started = False

    def _copy_directories(self, destination, path):
        owner = self._dirs
        aces, label = _policy('runtime', owner._operator, owner._user, owner.package_sid)
        parent = path.split('/')[:-1]
        for count in range(1, len(parent) + 1):
            name = '/'.join(parent[:count])
            if name in self._children:
                continue
            directory = _TaskDirectory(
                destination / name, 'browser-runtime', owner._operator, aces, label
            )
            try:
                directory.create()
                self._children[name] = directory.verify().file
            finally:
                directory.close()

    def _copy_member(self, source, target, identity, member, checkpoint):
        self._copy_directories(target, member.path)
        original = LockedFileSource(
            source / member.path,
            max_file_bytes=max(1, member.byte_count),
            expected_file=identity,
            checkpoint=checkpoint,
            capture_raw=False,
        )
        try:
            observed = original.snapshot
            if (observed.byte_count, observed.sha256) != (member.byte_count, member.sha256):
                raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_MEMBER_DIFFERS')
            with (target / member.path).open('xb') as stream:
                original.consume_verified(stream.write)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            original.close()
        with LocalPathGuard(target / member.path, directory=False) as pin:
            return pin.verify(), member.byte_count, member.sha256

    def prepare(self, *, deadline, cancelled):
        if self._started:
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_ALREADY_RESERVED')
        self._started = True

        def interrupted():
            return cancelled() or monotonic() >= deadline

        checkpoint = browser_inspection_checkpoint(
            lambda: self._dirs._require_open(interrupted), deadline=deadline, cancelled=cancelled
        )

        checkpoint()
        runtime = self._dirs._directories['runtime']
        directory = runtime.verify().file
        if any(runtime.path.iterdir()):
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_RUNTIME_NOT_EMPTY')
        try:
            with hold_check_runner_bundle(
                self.driver.runner, deadline=deadline, cancelled=cancelled
            ) as closure:
                files = self.driver.verify_closure(closure)
                capability_names = runner_lpac_capability_names(closure, checkpoint)
                source_root = Path(self.driver.runner.directory.canonical_path)
                copies = {}
                for name, identity in closure.members:
                    member = files.get(name)
                    if member is not None:
                        checkpoint()
                        copies[name] = self._copy_member(
                            source_root, runtime.path, identity, member, checkpoint
                        )
                entry = files[closure.manifest.entry_ref]
                self._image = ExecutablePin(
                    runtime.path / entry.path,
                    expected_byte_count=entry.byte_count,
                    expected_sha256=entry.sha256,
                )
                self._image.__enter__()
            self._layout = (copies, dict(self._children))
            self._facts = BrowserDriverFiles(
                directory,
                tuple(self._children[name] for name in sorted(self._children))
                + tuple(copies[name][0] for name in sorted(copies)),
                workspace_tree_sha256(*self._layout),
                capability_names,
            )
            self.verify(checkpoint)
            return self._facts
        except BaseException as error:
            error.retained_owner = self
            raise

    def verify(self, checkpoint):
        checkpoint()
        if self._facts is None or self._image is None:
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_NOT_PREPARED')
        runtime = self._dirs._directories['runtime']
        original = runtime.verify().file
        files, directories, _, _ = _scan_task_workspace_tree(runtime.path, original, checkpoint)
        if original != self._facts.directory or (files, directories) != self._layout:
            raise CheckResourceError('INPUT_CHANGED')
        return self._image.verify(), self._facts

    def close(self):
        if self._image is not None:
            self._image.close()
            self._image = None
