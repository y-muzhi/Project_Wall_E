"""Original CHECK_DRIVER-owned Chromium process and bounded anonymous DevTools I/O."""

import base64
import ctypes
import msvcrt
import os
import queue
import subprocess
from pathlib import Path
from threading import Thread

from .check_case_evidence import CheckEvidenceUnknown
from .windows_pipe_capture import _read_api, read_available_pipe

CHUNK_BYTES = 32768


def browser_arguments(runtime, profile, command, args):
    executable = Path(runtime) / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe'
    if (
        type(command) is not str
        or Path(command) != executable
        or type(args) is not list
        or not 1 <= len(args) <= 256
        or any(type(value) is not str or len(value) > 8192 or '\0' in value for value in args)
        or '--remote-debugging-pipe' not in args
        or sum(value.startswith('--user-data-dir=') for value in args) != 1
        or '--user-data-dir=' + str(profile) not in args
        or any(
            value.split('=', 1)[0] == '--no-sandbox'
            or value.startswith(
                (
                    '--remote-debugging-port',
                    '--remote-debugging-io-pipes',
                    '--disable-setuid-sandbox',
                    '--disable-gpu-sandbox',
                    '--renderer-cmd-prefix',
                    '--browser-subprocess-path',
                )
            )
            for value in args
        )
    ):
        raise CheckEvidenceUnknown('ORIGINAL_BROWSER_LAUNCH_ARGUMENTS_REQUIRED')
    return executable, tuple(args)


class BrowserPipeProcess:
    """All process/pipe handles originate in this root; no candidate code is imported."""

    def __init__(self, runtime, profile, environment, send):
        self.runtime = Path(runtime)
        self.profile = Path(profile)
        self.environment = environment
        self.send = send
        self.process = None
        self._read_fd = self._write_fd = None
        self._streams = {}
        self._eof = set()
        self._exited = False
        self._remaining = 64 * 1024 * 1024
        self._closed = False
        self._released = False
        self._pending = queue.Queue(maxsize=64)
        self._acks = queue.Queue(maxsize=64)
        self._write_sequence = 0
        self._write_error = None
        self._writer = None
        self.stderr = bytearray()
        self._kernel = _read_api(ctypes.WinDLL('kernel32', use_last_error=True))

    def start(self, command, args):
        if self.process is not None or self._closed:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_ALREADY_STARTED')
        executable, arguments = browser_arguments(self.runtime, self.profile, command, args)
        child_read = child_write = None
        try:
            child_read, self._write_fd = os.pipe()
            self._read_fd, child_write = os.pipe()
            for descriptor in (child_read, child_write):
                os.set_inheritable(descriptor, True)
            handles = [msvcrt.get_osfhandle(value) for value in (child_read, child_write)]
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {'handle_list': handles}
            io_arg = '--remote-debugging-io-pipes=' + ','.join(str(value) for value in handles)
            self.process = subprocess.Popen(
                [str(executable), *arguments, io_arg],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=self.environment,
                cwd=self.runtime,
                bufsize=0,
            )
        finally:
            for descriptor in (child_read, child_write):
                if descriptor is not None:
                    os.close(descriptor)
        from .windows_process import ObservedProcess

        with ObservedProcess(os.getpid()) as root, ObservedProcess(self.process.pid) as browser:
            fields = ('user_sid', 'appcontainer_sid', 'is_appcontainer', 'is_lpac', 'is_elevated')
            if (
                any(getattr(root.identity, key) != getattr(browser.identity, key) for key in fields)
                or Path(browser.identity.image_path) != executable
            ):
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_INHERITED_IDENTITY_DIFFERS')
        self._streams = {
            'stdout': msvcrt.get_osfhandle(self.process.stdout.fileno()),
            'stderr': msvcrt.get_osfhandle(self.process.stderr.fileno()),
            'cdp': msvcrt.get_osfhandle(self._read_fd),
        }
        self._writer = Thread(target=self._write, daemon=True)
        self._writer.start()
        return self.process.pid

    def _write(self):
        while not self._closed:
            try:
                sequence, data = self._pending.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                offset = 0
                while offset < len(data) and not self._closed:
                    count = os.write(self._write_fd, data[offset:])
                    if count <= 0:
                        raise OSError('Original browser pipe write did not progress')
                    offset += count
                if offset != len(data) or self._closed:
                    return
                self._acks.put_nowait(sequence)
            except (OSError, queue.Full):
                if not self._closed:
                    self._write_error = CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_WRITE_FAILED')
                return

    def write(self, encoded, *, sequence):
        if (
            type(sequence) is not int
            or sequence != self._write_sequence + 1
            or sequence > 2**53 - 1
        ):
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_WRITE_SEQUENCE_REQUIRED')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as error:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_DATA_REQUIRED') from error
        if not 1 <= len(raw) <= CHUNK_BYTES:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CHUNK_LIMIT')
        if self._closed or self.process is None or self.process.poll() is not None:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CLOSED')
        try:
            self._pending.put_nowait((sequence, raw))
            self._write_sequence = sequence
        except queue.Full as error:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CAPACITY') from error

    def poll(self):
        if self._closed or self.process is None:
            return
        if self._write_error is not None:
            raise self._write_error
        for _ in range(64):
            try:
                sequence = self._acks.get_nowait()
            except queue.Empty:
                break
            self.send('BROWSER_WRITTEN', {'write': sequence})
        for name, handle in self._streams.items():
            if name in self._eof:
                continue
            raw = read_available_pipe(self._kernel, handle, CHUNK_BYTES)
            if raw is None:
                self._eof.add(name)
                self.send('BROWSER_DATA', {'stream': name, 'data': None})
            elif raw:
                self._remaining -= len(raw)
                if self._remaining < 0:
                    raise CheckEvidenceUnknown('ORIGINAL_BROWSER_TRANSPORT_LIMIT')
                if name == 'stderr':
                    self.stderr.extend(raw)
                    del self.stderr[:-4096]
                self.send(
                    'BROWSER_DATA', {'stream': name, 'data': base64.b64encode(raw).decode('ascii')}
                )
        code = self.process.poll()
        if code is not None and not self._exited:
            self._exited = True
            self.send('BROWSER_EXIT', {'code': code})

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def close(self):
        if self._released:
            return
        if self._closed:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CLOSE_UNVERIFIED')
        self._closed = True
        errors = []
        try:
            self.stop()
            if self.process is not None:
                self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(error)
        cancel = self._kernel.CancelIoEx
        cancel.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cancel.restype = ctypes.c_int
        if self._write_fd is not None:
            cancel(msvcrt.get_osfhandle(self._write_fd), None)
        writer = self._writer
        if writer is not None and writer.ident is not None:
            writer.join(timeout=2)
            if writer.is_alive():
                errors.append(CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CLOSE_UNVERIFIED'))
        # A blocked raw-fd writer must finish before its descriptor could be reused.
        for name in ('_read_fd', '_write_fd'):
            descriptor = getattr(self, name)
            if descriptor is None or (
                name == '_write_fd' and writer is not None and writer.is_alive()
            ):
                continue
            try:
                os.close(descriptor)
                setattr(self, name, None)
            except OSError as error:
                errors.append(error)
        if self.process is not None:
            for stream in (self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except OSError as error:
                    errors.append(error)
        if errors:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PIPE_CLOSE_UNVERIFIED') from errors[0]
        self.process = None
        self._released = True
