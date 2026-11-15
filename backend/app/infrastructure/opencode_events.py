"""Bounded original-instance OpenCode SSE observations."""

from backend.app.shared.validation import strict_json_object

from .opencode_task_launch import TaskExecutionError

MAX_EVENT_BYTES = 4 * 1024 * 1024 + 16 * 1024
MAX_STREAM_BYTES = 2 * MAX_EVENT_BYTES
MAX_EVENTS = 256


class OpenCodeEvents:
    def __init__(self, receive):
        self._receive = receive
        self._buffer = bytearray()
        self._bytes = 0
        self._count = 0

    def _line(self):
        while True:
            position = self._buffer.find(b'\n')
            if position >= 0:
                line = bytes(self._buffer[:position]).removesuffix(b'\r')
                del self._buffer[: position + 1]
                return line
            chunk = self._receive()
            self._bytes += len(chunk)
            if (
                not chunk
                or self._bytes > MAX_STREAM_BYTES
                or len(self._buffer) + len(chunk) > MAX_EVENT_BYTES
            ):
                raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_STREAM_INCOMPLETE')
            self._buffer.extend(chunk)

    def next(self):
        data = []
        size = 0
        while True:
            line = self._line()
            size += len(line) + 1
            if size > MAX_EVENT_BYTES:
                raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_TOO_LARGE')
            if not line:
                if data:
                    break
                continue
            if line.startswith(b'data:'):
                data.append(line[5:].removeprefix(b' '))
            elif not line.startswith(b':') and not (
                line.startswith(b'event:') and line[6:].removeprefix(b' ') == b'message'
            ):
                raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_FRAME_INVALID')
        self._count += 1
        if self._count > MAX_EVENTS:
            raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_LIMIT_REACHED')
        try:
            event = strict_json_object(b'\n'.join(data))
        except ValueError as error:
            raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_FRAME_INVALID') from error
        if (
            set(event) != {'id', 'type', 'properties'}
            or type(event['id']) is not str
            or not event['id']
            or len(event['id']) > 256
            or type(event['type']) is not str
            or type(event['properties']) is not dict
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_FRAME_INVALID')
        if event['type'] == 'server.instance.disposed':
            raise TaskExecutionError('ORIGINAL_OPENCODE_EVENT_OWNER_DISPOSED')
        return event
