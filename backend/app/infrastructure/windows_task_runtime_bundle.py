"""Publish the fixed OpenCode bundle into the original protected runtime role."""

import hashlib
import os
from ctypes import byref, wintypes
from dataclasses import asdict, dataclass
from time import monotonic

from .opencode_runtime_bundle import (
    CONFIG,
    _verify_control_files,
    _verify_tree,
    hold_opencode_runtime_bundle,
)
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_empty_directory import OWNER_RIGHTS, READ_EXECUTE
from .windows_local_paths import LocalPathGuard
from .windows_private_package import OPERATOR_ACCESS, _sid_text
from .windows_task_directories import _LABEL_TYPE, _MEDIUM, _policy, _read_aces, _TaskDirectory


class TaskRuntimeFilesError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class TaskRuntimeBundleEvidence:
    runtime_bundle_ref: str
    member_count: int
    tree_identity_sha256: str


class TaskRuntimeBundlePublication:
    def __init__(self, directories, source, runtime_bundle_ref):
        self._dirs, self._source, self._ref = directories, source, runtime_bundle_ref
        self._role = directories._directories['runtime']
        self._directory = self._role.verify().file
        self._files = self._directories = None
        self._members = {}
        self._evidence = None
        self._descriptor = None
        self._started = False

    @property
    def configuration_path(self):
        if self._evidence is None:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_BUNDLE_UNVERIFIED')
        return self._role.path / CONFIG

    def close(self):
        if self._descriptor and self._role._kernel.LocalFree(self._descriptor):
            error = TaskRuntimeFilesError('ORIGINAL_RUNTIME_DESCRIPTOR_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error
        self._descriptor = None

    def _verify_file_policy(self, path):
        if self._descriptor is not None:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_DESCRIPTOR_CLOSE_UNVERIFIED')
        kernel, security = self._role._kernel, self._role._security
        owner, dacl, sacl, descriptor = (wintypes.LPVOID() for _ in range(4))
        status = security.GetNamedSecurityInfoW(
            str(path), 1, 0x15, byref(owner), None, byref(dacl), byref(sacl), byref(descriptor)
        )
        if status or not descriptor:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_POLICY_UNAVAILABLE')
        self._descriptor = descriptor
        try:
            operator = self._dirs._operator
            expected = {operator: OPERATOR_ACCESS}
            for sid in {self._dirs._user, self._dirs.package_sid, OWNER_RIGHTS} - {operator}:
                expected[sid] = READ_EXECUTE
            rows = _read_aces(kernel, security, dacl)
            labels = _read_aces(kernel, security, sacl)
            if (
                _sid_text(kernel, security, owner) != operator
                or len(rows) != len(expected)
                or any(kind != 0 or flags not in (0, 16) for kind, flags, _, _ in rows)
                or {sid: mask for _, _, mask, sid in rows} != expected
                or len(labels) != 1
                or labels[0][1] not in (0, 16)
                or (labels[0][0], *labels[0][2:]) != (_LABEL_TYPE, 1, _MEDIUM)
            ):
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_POLICY_DIFFERS')
        finally:
            self.close()

    def _child(self, name):
        dirs = self._dirs
        aces, label = _policy('runtime', dirs._operator, dirs._user, dirs.package_sid)
        return _TaskDirectory(self._role.path / name, 'runtime', dirs._operator, aces, label)

    def _copy(self, name, file, raw):
        target = self._role.path / name
        if file.is_directory:
            child = self._child(name)
            try:
                child.create()
                self._members[name] = child.verify().file
            finally:
                child.close()
            return
        with target.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            with LocalPathGuard(target, directory=False) as pin:
                self._members[name] = pin.verify()
                self._verify_file_policy(target)

    def _inspect(self, checkpoint, *, original):
        def policy(name, file, _):
            if file.is_directory:
                self._child(name)._verify_security()
            else:
                self._verify_file_policy(self._role.path / name)

        if self._role.verify().file != self._directory:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_DIRECTORY_DIFFERS')
        controls, members = _verify_tree(
            self._role.path,
            self._directory,
            self._files,
            self._directories,
            checkpoint,
            original=original,
            consume=policy,
        )
        _verify_control_files(controls, self._files)
        checkpoint()
        digest = hashlib.sha256()
        for name in sorted(members):
            digest.update(_bytes({'name': name, 'file': asdict(members[name])}))
        return TaskRuntimeBundleEvidence(self._ref, len(self._files), digest.hexdigest())

    def publish(self, *, deadline, cancelled):
        if self._started:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_BUNDLE_ALREADY_DISPATCHED')
        self._started = True

        def checkpoint():
            self._dirs._require_open(lambda: cancelled() or monotonic() >= deadline)

        checkpoint()
        with hold_opencode_runtime_bundle(
            self._source, self._ref, deadline=deadline, cancelled=cancelled
        ) as bundle:
            target = self._role.path
            source = bundle.source.root
            if (
                source.is_relative_to(self._dirs.root)
                or self._dirs.root.is_relative_to(source)
                or bundle.source.manifest.is_relative_to(self._dirs.root)
                or any(target.iterdir())
            ):
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_DESTINATION_NOT_EMPTY_OR_DISJOINT')
            self._files, self._directories = bundle.files, bundle.directories

            def consume(name, file, raw):
                checkpoint()
                self._copy(name, file, raw)

            bundle.visit(consume)
        self._evidence = self._inspect(checkpoint, original=self._members)
        return self._evidence

    def verify(self, checkpoint):
        if self._evidence is None:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_BUNDLE_UNVERIFIED')
        observed = self._inspect(checkpoint, original=self._members)
        if observed != self._evidence:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_BUNDLE_EVIDENCE_DIFFERS')
        return observed
