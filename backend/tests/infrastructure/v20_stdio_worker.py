"""Owned backend STDIO peer; fixture body bytes never pass through Guard code."""

from dataclasses import asdict
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
from time import monotonic, sleep

from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.runtime_launch_journal import LaunchFence, LaunchScope
from backend.app.infrastructure.windows_stdio import BackendStandardIO, GuardStdioBinding
from backend.app.infrastructure.windows_pipe_capture import BoundedOutputCapture
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess


def publish(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def wait(path):
    deadline = monotonic() + 40
    while not path.exists() and monotonic() < deadline:
        sleep(0.01)
    if not path.exists():
        raise TimeoutError('Owned STDIO fixture control not received')


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    nonce = sys.argv[2]
    if root != Path.cwd().resolve() or (root / '.stdio-owner').read_text(encoding='ascii') != nonce:
        raise ValueError('Exact owned STDIO fixture required')
    configured_scope = root / 'stdio-scope.json'
    scope = (
        LaunchScope(**json.loads(configured_scope.read_bytes()))
        if configured_scope.exists()
        else LaunchScope('a' * 64, 1, 1, 'stdio-original-nonce-0001')
    )
    configured_epoch = root / 'bound-controller-epoch'
    if configured_epoch.exists():
        with ObservedProcess(os.getpid()) as controller:
            binding = GuardControllerBinding(
                'a' * 64, configured_epoch.read_text(encoding='ascii'), controller.identity
            )
        scope = binding.scope(scope.operation_id, scope.step_no, scope.nonce)
    with (root / 'owned-input.bin').open('xb+') as ordinary_file:
        import msvcrt

        with BackendStandardIO(scope) as streams:
            kernel = streams._kernel
            kernel.WriteFile.argtypes = [
                wintypes.HANDLE,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPVOID,
            ]
            kernel.WriteFile.restype = wintypes.BOOL
            kernel.ReadFile.argtypes = kernel.WriteFile.argtypes
            kernel.ReadFile.restype = wintypes.BOOL
            with streams.parent_endpoint('STDIN') as handle:
                data = ctypes.create_string_buffer(b'inp')
                written = wintypes.DWORD()
                if (
                    not kernel.WriteFile(handle, data, 3, ctypes.byref(written), None)
                    or written.value != 3
                ):
                    raise OSError('Owned fixture input write failed')
            descriptor = streams.begin_handoff()
            publish(
                root / 'stdio-ready.json',
                {
                    'nonce': nonce,
                    'pid': os.getpid(),
                    'descriptor': asdict(descriptor),
                    'file_handle': f'{msvcrt.get_osfhandle(ordinary_file.fileno()):016x}',
                },
            )
            wait(root / 'copy-ack.json')
            row = json.loads((root / 'copy-ack.json').read_bytes())
            binding = GuardStdioBinding(
                NativeProcessIdentity(**row['owner']),
                LaunchScope(**row['scope']),
                row['io_nonce'],
                row['guard_io_ref'],
            )
            streams.acknowledge_copy(binding)
            streams.release_child_copies()
            publish(root / 'copy-released.json', {'nonce': nonce})
            wait(root / 'run-reader')
            if (root / 'parse-output-request').exists():
                request = json.loads((root / 'parse-output-request').read_bytes())
                with BoundedOutputCapture(
                    streams, scope=scope, max_output_bytes=request['max_output_bytes']
                ) as capture:
                    publish(root / 'capture-ready.json', {'nonce': nonce})
                    deadline = monotonic() + 12
                    while True:
                        progress = capture.poll()
                        if progress.complete or progress.limit_exceeded:
                            break
                        if monotonic() >= deadline:
                            raise TimeoutError('Owned output fixture did not complete')
                        sleep(0.002)
                    captured = capture.snapshot()
                    output = {
                        'STDOUT': captured.stdout.hex(),
                        'STDERR': captured.stderr.hex(),
                        'progress': asdict(captured.progress),
                    }
            else:
                output = {}
                for stream in ('STDOUT', 'STDERR'):
                    with streams.parent_endpoint(stream) as handle:
                        data = ctypes.create_string_buffer(3)
                        read = wintypes.DWORD()
                        if (
                            not kernel.ReadFile(handle, data, 3, ctypes.byref(read), None)
                            or read.value != 3
                        ):
                            raise OSError('Owned fixture output read failed')
                        output[stream] = data.raw.decode('ascii')
            publish(root / 'stdio-result.json', output)
            wait(root / 'stop')
            streams.acknowledge_closed_scope(
                LaunchFence(
                    1, scope, None, 'NONE', 'NONE', None, True, 1, '2026-11-05T00:00:00.000Z'
                )
            )


if __name__ == '__main__':
    main()
