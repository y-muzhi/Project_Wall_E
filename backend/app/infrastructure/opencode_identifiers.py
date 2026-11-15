"""Preallocate the original native message/part identities with fixed OpenCode encoding."""

from secrets import token_bytes
from threading import Lock
from time import time_ns

from .opencode_task_launch import TaskExecutionError

_BASE62 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
_MASK = (1 << 48) - 1


class OpenCodeMessageIds:
    def __init__(self):
        self._gate = Lock()
        self._timestamp = None
        self._counter = 0

    def allocate(self, kind):
        if kind not in ('msg', 'prt'):
            raise TaskExecutionError('ORIGINAL_OPENCODE_ID_KIND_INVALID')
        with self._gate:
            timestamp = time_ns() // 1_000_000
            if self._timestamp != timestamp:
                self._timestamp, self._counter = timestamp, 0
            self._counter += 1
            raw = ((timestamp << 12) + self._counter) & _MASK
            suffix = ''.join(_BASE62[value % 62] for value in token_bytes(14))
            return f'{kind}_{raw:012x}{suffix}'
