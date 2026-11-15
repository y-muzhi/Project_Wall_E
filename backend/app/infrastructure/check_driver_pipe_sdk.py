"""Synchronous fixed-SDK pipe adapter: no asyncio, sockets or result-frame forwarding."""

import base64
import json
import os
import queue
import struct
import subprocess
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from backend.app.shared.validation import strict_json_object

from .check_case_evidence import CheckEvidenceUnknown
from .check_driver_bootstrap import CONTROL_FRAME_MAX_BYTES

MAX_FRAME_BYTES = CONTROL_FRAME_MAX_BYTES
ENVIRONMENT_NAMES = frozenset(
    {
        'SystemRoot',
        'SystemDrive',
        'WINDIR',
        'PATH',
        'TEMP',
        'TMP',
        'HOME',
        'USERPROFILE',
        'APPDATA',
        'LOCALAPPDATA',
        'XDG_CONFIG_HOME',
        'XDG_DATA_HOME',
        'XDG_CACHE_HOME',
        'XDG_STATE_HOME',
    }
)


class PipeChromium:
    """The original root owns the only SDK stdin/stdout ends and compares all facts."""

    def __init__(self, runtime, *, private_temp=None):
        self._runtime = Path(runtime)
        self._private_temp = private_temp
        self._browser = None
        self._browser_id = None
        self._browser_epoch = None
        self._environment = None
        self._last_browser_stderr = b''
        self._process = None
        self._incoming = queue.Queue(maxsize=64)
        self._responses = {}
        self._waiting = set()
        self._last_error = None
        self._sequence = 0
        self._context = None
        self._closed = False
        self._failed = False
        self._diagnostic = bytearray()
        self._threads = []
        self._outgoing = queue.Queue(maxsize=16)

    def __enter__(self):
        if self._closed or self._process is not None:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_ALREADY_USED')
        allowed = {name.upper() for name in ENVIRONMENT_NAMES}
        values = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        temp = Path(os.environ['TEMP']) if self._private_temp is None else Path(self._private_temp)
        if not temp.is_absolute() or not temp.is_dir():
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_SCRATCH_REQUIRED')
        values['WALLE_SDK_TEMP'] = str(temp)
        self._environment = {**values, 'TEMP': str(temp), 'TMP': str(temp)}
        self._environment.pop('WALLE_SDK_TEMP')
        self._process = subprocess.Popen(
            [
                str(self._runtime / 'vendor/playwright/driver/node.exe'),
                '--preserve-symlinks',
                '--preserve-symlinks-main',
                str(self._runtime / 'pipe-worker.cjs'),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            env=values,
            cwd=self._runtime,
            creationflags=subprocess.CREATE_NO_WINDOW,
            bufsize=0,
        )
        try:
            for target in (self._read_frames, self._read_errors, self._write_frames):
                thread = Thread(target=target, daemon=True)
                self._threads.append(thread)
                thread.start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _publish(self, value):
        while not self._closed:
            try:
                self._incoming.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            part = self._process.stdout.read(size - len(result))
            if not part:
                raise CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_CLOSED')
            result.extend(part)
        return bytes(result)

    def _read_frames(self):
        try:
            while not self._closed:
                size = struct.unpack('<I', self._read_exact(4))[0]
                if not 1 <= size <= MAX_FRAME_BYTES:
                    raise CheckEvidenceUnknown('ORIGINAL_SDK_FRAME_LIMIT')
                self._publish(strict_json_object(self._read_exact(size)))
        except (OSError, ValueError, TypeError, CheckEvidenceUnknown, struct.error):
            self._publish(CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_UNVERIFIED'))

    def _read_errors(self):
        try:
            while part := self._process.stderr.read(1024):
                remaining = 4096 - len(self._diagnostic)
                if remaining > 0:
                    self._diagnostic.extend(part[:remaining])
        except (OSError, ValueError):
            pass

    def _write_frames(self):
        while not self._closed:
            try:
                raw, completed, errors = self._outgoing.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                offset = 0
                while offset < len(raw) and not self._closed:
                    count = self._process.stdin.write(raw[offset:])
                    if count is None or count <= 0:
                        raise OSError('Original SDK pipe write did not progress')
                    offset += count
                self._process.stdin.flush()
            except (OSError, ValueError):
                errors.append(CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_UNVERIFIED'))
            finally:
                completed.set()

    def rpc(self, op, value, *, timeout=30000):
        if self._closed or self._process is None:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_CLOSED')
        cleanup = op in ('CLOSE', 'WEBSOCKET_CLOSE') or (
            op == 'ROUTE_REPLY' and value.get('action') == 'abort'
        )
        if self._failed and not cleanup:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_OPERATION_REQUIRES_STOP')
        if type(timeout) is not int or not 1 <= timeout <= 3600 * 1000:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_REQUIRED')
        self._sequence += 1
        identity = self._sequence
        raw = json.dumps(
            {'id': identity, 'op': op, 'value': value},
            ensure_ascii=False,
            separators=(',', ':'),
            allow_nan=False,
        ).encode()
        if not 1 <= len(raw) <= MAX_FRAME_BYTES:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_FRAME_LIMIT')
        self._waiting.add(identity)
        deadline = monotonic() + timeout / 1000
        completed = Event()
        errors = []
        try:
            self._outgoing.put(
                (struct.pack('<I', len(raw)) + raw, completed, errors),
                timeout=max(0, deadline - monotonic()),
            )
        except queue.Full as error:
            self._waiting.discard(identity)
            self._failed = True
            raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_EXPIRED') from error
        if not completed.wait(max(0, deadline - monotonic())):
            self._failed = True
            raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_EXPIRED')
        if errors:
            raise errors[0]
        while True:
            response = self._responses.pop(identity, None)
            if response is not None:
                self._waiting.discard(identity)
                if set(response) == {'id', 'error'}:
                    error = response['error']
                    if type(error) is dict and set(error) == {'code', 'message'}:
                        self._last_error = {key: str(value)[:1000] for key, value in error.items()}
                    raise CheckEvidenceUnknown('ORIGINAL_SDK_OPERATION_FAILED')
                if set(response) != {'id', 'result'}:
                    raise CheckEvidenceUnknown('ORIGINAL_SDK_RESPONSE_UNVERIFIED')
                return response['result']
            if self._browser is not None:
                self._browser.poll()
            remaining = deadline - monotonic()
            if remaining <= 0:
                self._failed = True
                raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_EXPIRED')
            try:
                response = self._incoming.get(timeout=min(remaining, 0.01))
            except queue.Empty:
                continue
            if isinstance(response, BaseException):
                raise response
            if 'event' in response:
                self._event(response)
                continue
            response_id = response.get('id')
            if (
                type(response_id) is not int
                or not 1 <= response_id <= self._sequence
                or response_id not in self._waiting
                or response_id in self._responses
                or len(self._responses) >= 64
            ):
                raise CheckEvidenceUnknown('ORIGINAL_SDK_RESPONSE_UNVERIFIED')
            self._responses[response_id] = response

    def _transport(self, op, value):
        value = {**value, 'browser': self._browser_id, 'epoch': self._browser_epoch}
        raw = json.dumps(
            {'transport': op, 'value': value}, separators=(',', ':'), allow_nan=False
        ).encode()
        if len(raw) > MAX_FRAME_BYTES:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_FRAME_LIMIT')
        completed = Event()
        errors = []
        deadline = monotonic() + 1
        try:
            self._outgoing.put((struct.pack('<I', len(raw)) + raw, completed, errors), timeout=1)
        except queue.Full as error:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_EXPIRED') from error
        if not completed.wait(max(0, deadline - monotonic())):
            raise CheckEvidenceUnknown('ORIGINAL_SDK_DEADLINE_EXPIRED')
        if errors:
            raise errors[0]

    def _browser_event(self, event):
        from .check_driver_browser_process import BrowserPipeProcess

        identity = event.get('browser')
        if type(identity) is not int or identity < 1:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROCESS_REQUIRED')
        kind = event['event']
        if kind == 'BROWSER_START':
            if (
                set(event) != {'event', 'epoch', 'browser', 'command', 'args'}
                or self._browser is not None
            ):
                raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROCESS_REQUIRED')
            self._browser_id = identity
            self._browser_epoch = event['epoch']
            self._browser = BrowserPipeProcess(
                self._runtime, self._context._profile, self._environment, self._transport
            )
            pid = self._browser.start(event['command'], event['args'])
            self._transport('BROWSER_STARTED', {'pid': pid})
        elif self._browser is None or identity != self._browser_id:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROCESS_REQUIRED')
        elif kind == 'BROWSER_WRITE' and set(event) == {
            'event',
            'epoch',
            'browser',
            'write',
            'data',
        }:
            self._browser.write(event['data'], sequence=event['write'])
        elif kind == 'BROWSER_STOP' and set(event) == {'event', 'epoch', 'browser'}:
            self._browser.stop()
        else:
            raise CheckEvidenceUnknown('ORIGINAL_BROWSER_PROCESS_EVENT_REQUIRED')

    def _event(self, event):
        context = self._context
        if (
            context is None
            or type(event.get('epoch')) is not int
            or event['epoch'] != context._generation
        ):
            raise CheckEvidenceUnknown('ORIGINAL_SDK_CONTEXT_REQUIRED')
        if event.get('event') in ('BROWSER_START', 'BROWSER_WRITE', 'BROWSER_STOP'):
            self._browser_event(event)
        elif event.get('event') == 'ROUTE' and set(event) == {'event', 'epoch', 'route', 'request'}:
            route = _Route(self, event['route'], event['request'])
            if context._route is None or self._failed:
                route.abort('blockedbyclient')
            else:
                context._route(route)
        elif event.get('event') == 'WEBSOCKET' and set(event) == {'event', 'epoch', 'socket'}:
            socket = _WebSocket(self, event['socket'])
            if context._websocket is None:
                socket.close(code=1008)
            else:
                context._websocket(socket)
        else:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_EVENT_UNVERIFIED')

    def profile_can_remove(self):
        return self._browser is None

    def _close_browser(self):
        browser = self._browser
        if browser is not None:
            self._last_browser_stderr = bytes(browser.stderr)
            browser.close()
            self._browser = None

    def launch_persistent_context(
        self,
        profile,
        *,
        executable_path,
        chromium_sandbox,
        headless,
        service_workers,
        accept_downloads,
        args,
        timeout,
    ):
        if self._context is not None or not headless:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_CONTEXT_ALREADY_OPEN')
        context = _Context(self)
        self._context = context
        context._generation = self._sequence + 1
        context._profile = Path(profile)
        try:
            result = self.rpc(
                'LAUNCH',
                {
                    'generation': context._generation,
                    'profile': str(profile),
                    'executable': str(executable_path),
                    'sandbox': chromium_sandbox,
                    'serviceWorkers': service_workers,
                    'acceptDownloads': accept_downloads,
                    'args': args,
                    'timeout': timeout,
                },
                timeout=timeout,
            )
            context._pages = [_Page(self, identity) for identity in result['pages']]
            return context
        except BaseException:
            try:
                self._close_browser()
            finally:
                self._context = None
            raise

    def __exit__(self, *unused):
        self._closed = True
        errors = []
        try:
            self._close_browser()
        except BaseException as error:  # noqa: BLE001 -- Stop the SDK even when browser cleanup fails.
            errors.append(error)
        process = self._process
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(error)
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError as error:
                    errors.append(error)
            for thread in self._threads:
                if thread.ident is not None:
                    thread.join(timeout=2)
                    if thread.is_alive():
                        errors.append(CheckEvidenceUnknown('ORIGINAL_SDK_PIPE_CLOSE_UNVERIFIED'))
            self._process = None
        if errors:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_CLEANUP_REQUIRED') from errors[0]


class _Context:
    def __init__(self, pipe):
        self._pipe = pipe
        self._route = self._websocket = None
        self._pages = []
        self._generation = None

    @property
    def pages(self):
        return tuple(self._pages)

    def new_page(self):
        value = self._pipe.rpc('NEW_PAGE', {})
        page = _Page(self._pipe, value['page'])
        self._pages.append(page)
        return page

    def route(self, pattern, callback):
        if pattern != '**/*' or self._route is not None:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_ROUTE_REQUIRED')
        self._route = callback

    def route_web_socket(self, pattern, callback):
        if pattern != '**/*' or self._websocket is not None:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_WEBSOCKET_REQUIRED')
        self._websocket = callback

    def close(self):
        try:
            self._pipe.rpc('CLOSE', {})
        finally:
            try:
                self._pipe._close_browser()
            finally:
                self._pipe._context = None


class _Page:
    def __init__(self, pipe, identity):
        if type(identity) is not int or identity < 1:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_PAGE_REQUIRED')
        self._pipe, self._identity = pipe, identity

    def goto(self, url, *, wait_until, timeout):
        if wait_until != 'domcontentloaded':
            raise CheckEvidenceUnknown('ORIGINAL_SDK_NAVIGATION_REQUIRED')
        return self._pipe.rpc(
            'GOTO', {'page': self._identity, 'url': url, 'timeout': timeout}, timeout=timeout
        )

    def get_by_test_id(self, name):
        return _Locator(self, {'kind': 'TEST_ID', 'value': name})

    def get_by_role(self, role, *, name, exact):
        if exact is not True:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_LOCATOR_REQUIRED')
        return _Locator(self, {'kind': 'ROLE', 'value': role, 'name': name})


class _Locator:
    def __init__(self, page, value):
        self._page, self._value = page, value

    def _call(self, method, value=None, timeout=30000):
        page = self._page
        return page._pipe.rpc(
            'LOCATOR',
            {
                'page': page._identity,
                'locator': self._value,
                'method': method,
                'value': value,
                'timeout': timeout,
            },
            timeout=timeout,
        )

    def click(self, *, timeout):
        return self._call('click', timeout=timeout)

    def fill(self, value, *, timeout):
        return self._call('fill', value, timeout)

    def select_option(self, *, value, timeout):
        return self._call('select_option', value, timeout)

    def press(self, value, *, timeout):
        return self._call('press', value, timeout)

    def is_visible(self):
        return self._call('is_visible')

    def inner_text(self, *, timeout):
        return self._call('inner_text', timeout=timeout)

    def count(self):
        return self._call('count')


class _Request:
    def __init__(self, value):
        if type(value) is not dict or set(value) != {'url', 'method', 'headers', 'body'}:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_REQUEST_REQUIRED')
        self.url, self.method = value['url'], value['method']
        self._headers = value['headers']
        try:
            self.post_data_buffer = base64.b64decode(value['body'], validate=True)
        except (ValueError, TypeError) as error:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_REQUEST_REQUIRED') from error
        if len(self.post_data_buffer) > 1024 * 1024:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_BODY_LIMIT')

    def all_headers(self):
        return self._headers


class _Route:
    def __init__(self, pipe, identity, request):
        self._pipe, self._identity = pipe, identity
        self.request = _Request(request)

    def fulfill(self, *, status, headers=None, body=b'', content_type=None):
        if type(body) is str:
            body = body.encode()
        values = {} if headers is None else dict(headers)
        if content_type is not None:
            values['content-type'] = content_type
        return self._pipe.rpc(
            'ROUTE_REPLY',
            {
                'route': self._identity,
                'action': 'fulfill',
                'status': status,
                'headers': values,
                'body': base64.b64encode(body).decode('ascii'),
            },
        )

    def abort(self, *unused):
        return self._pipe.rpc('ROUTE_REPLY', {'route': self._identity, 'action': 'abort'})


class _WebSocket:
    def __init__(self, pipe, identity):
        self._pipe, self._identity = pipe, identity

    def close(self, *, code):
        if code != 1008:
            raise CheckEvidenceUnknown('ORIGINAL_SDK_WEBSOCKET_REQUIRED')
        return self._pipe.rpc('WEBSOCKET_CLOSE', {'socket': self._identity, 'code': code})
