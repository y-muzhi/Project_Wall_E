"""Read-only diagnosis of a fixed installed Guard before any service start.

The existing file-verification algorithm runs through a metadata-only port.
No administrator identity is simulated; no write, ACL or SCM control API exists
on this port. Success is file evidence, never SYSTEM or service admission.
"""

import argparse
import ctypes
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY, GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_private_package import _api, create_private_package
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.v20_backend_guard_probe_worker import finish, launch, read_ready
from tools.windows_guard_inspection import GuardBootstrapSources
from tools.windows_guard_install_contract import ADMINISTRATORS, program_rights
from tools.windows_guard_install_files import NativeDescriptor, ProtectedInstallationWriter
from tools.windows_guard_installation import ProbeChannel


class ReadOnlyMetadataPort:
    def __init__(self, root, sid):
        self.root = root
        self._kernel, _ = _api()
        self._deadline = monotonic() + 240
        self._retained = []
        self._owners = []
        self._close_failed = False
        self._closed = False
        try:
            self._program_directory = NativeDescriptor(
                ADMINISTRATORS, program_rights(sid), directory=True
            )
            self._owners.append(self._program_directory)
            self._program_file = NativeDescriptor(
                ADMINISTRATORS, program_rights(sid), directory=False
            )
            self._owners.append(self._program_file)
        except BaseException as original:
            retained = getattr(original, 'retained_owner', None)
            if retained is not None:
                self._retained.append(retained)
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _checkpoint(self):
        if self._closed or self._close_failed or self._retained or monotonic() >= self._deadline:
            raise RuntimeError('Read-only metadata diagnosis unavailable')

    def _open(self, path, access, *, directory=False):
        self._checkpoint()
        if access != 0x20080:
            raise RuntimeError('Only READ_CONTROL and FILE_READ_ATTRIBUTES permitted')
        handle = self._kernel.CreateFileW(
            '\\\\?\\' + str(path),
            access,
            3,
            None,
            3,
            0x00200000 | (0x02000000 if directory else 0),
            None,
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise RuntimeError(
                'Original read-only metadata handle unavailable', ctypes.get_last_error()
            )
        return handle

    def _close_handle(self, handle):
        if not self._kernel.CloseHandle(handle):
            self._retained.append(handle)
            error = RuntimeError('Original read-only metadata handle closure unknown')
            error.retained_owner = self
            raise error

    def close(self):
        if self._close_failed:
            error = RuntimeError('Read-only metadata closure previously unverified')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in reversed(self._owners):
            try:
                owner.close()
            except BaseException as error:  # noqa: BLE001 -- Close known owners once.
                failures.append(error)
        if failures or self._retained:
            self._close_failed = True
            error = RuntimeError('Original read-only metadata ownership retained')
            error.retained_owner = self
            raise error from (failures[0] if failures else None)
        self._closed = True


def exercise(prepared, plan_sha):
    with (
        TemporaryDirectory(prefix='we-installed-read-') as temporary,
        GuardBootstrapSources(
            prepared, plan_sha, allow_existing_target=True, timeout_ms=300000
        ) as inputs,
    ):
        # The original plan and complete fixed backend package are held BEFORE
        # launching any EXE. Never select an executable from an unverified header.
        backend = inputs.backend.root
        reader_process = launch(
            backend,
            [
                '--hold-installation-reader',
                '--program-sha256',
                inputs.backend.spec.manifest_sha256,
            ],
            temporary,
        )
        try:
            _, pid, created = read_ready(reader_process)
            with ObservedProcess(pid) as reader:
                assert reader.identity.creation_time_hex == created
                root = Path(inputs.plan['installation_root'])
                inputs.verify_parent_access(reader)
                print('READ_ONLY_INSTALLED_ORIGINAL_SOURCES_AND_PARENTS_BOUND', flush=True)
                with (
                    ProgramPackageLease(
                        root / 'guard',
                        expected_sha256=inputs.guard.spec.manifest_sha256,
                        policy=GUARD_PROGRAM_POLICY,
                    ),
                    ProgramPackageLease(
                        root / 'backend',
                        expected_sha256=inputs.backend.spec.manifest_sha256,
                        policy=BACKEND_PROGRAM_POLICY,
                    ),
                    ControllerPrimaryToken(reader, expected=reader.identity) as token,
                ):
                    print('READ_ONLY_INSTALLED_COMPLETE_TARGET_BYTES_BOUND', flush=True)
                    port = ReadOnlyMetadataPort(root, inputs.plan['backend_sid'])
                    try:
                        ProtectedInstallationWriter.verify_program_access(
                            port,
                            token,
                            {'guard': inputs.guard, 'backend': inputs.backend},
                            include_receipt=True,
                        )
                    finally:
                        port.close()
                    print(
                        'READ_ONLY_INSTALLED_EXACT_DACL_AND_ORIGINAL_READER_RIGHTS_VERIFIED',
                        flush=True,
                    )
                channel = create_private_package(Path(temporary) / 'channel')
                from backend.app.infrastructure.runtime_launch_journal import _bytes
                from tools.windows_program_package import write_new_verified_file

                write_new_verified_file(
                    channel / 'channel.v1.json',
                    _bytes(
                        {
                            'request_sha256': 'a' * 64,
                            'reader_pid': pid,
                            'reader_created_at': created,
                            'channel_ref': 'b' * 64,
                        }
                    ),
                )
                with ProbeChannel(channel, 'a' * 64, reader) as probe:
                    assert not probe.stopped()
                print(
                    'READ_ONLY_PRIVATE_CHANNEL_CONSTRUCTOR_VERIFIED_ORDINARY_OPERATOR', flush=True
                )
                reader_process.stdin.write(b'STOP\n')
                reader_process.stdin.flush()
                reader_process.stdin.close()
                reader_process.stdin = None
                output, _ = reader_process.communicate(timeout=30)
                assert reader_process.returncode == 0 and reader.observe().state == 'EXITED', (
                    output[-1000:]
                )
        finally:
            finish(reader_process)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    values = parser.parse_args()
    exercise(values.prepared.resolve(strict=True), values.plan_sha256)
