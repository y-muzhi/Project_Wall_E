"""Bounded deterministic UTF8-object frames over the original Guard pipe IO.

Parsing a frame grants no authority. Action, peer, owner_epoch and original
operation/step/nonce validation belong to the registered Guard protocol handler.
"""

import json
import math
from threading import RLock
from time import monotonic

from backend.app.shared.validation import MAX_SAFE_INTEGER, InvalidInput, strict_json_object

from .windows_guard_pipe_io import CHUNK_LIMIT, GuardPipeIO, _deadline

HEADER_BYTES = 4
PAYLOAD_LIMIT = CHUNK_LIMIT - HEADER_BYTES
MAX_DEPTH = 32
MAX_NODES = 32768


class GuardFrameError(RuntimeError):
    pass


def _facts(value):
    stack = [(value, 1)]
    nodes = text_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise GuardFrameError('GUARD_FRAME_STRUCTURE_CAPACITY_EXCEEDED')
        kind = type(item)
        if item is None or kind is bool:
            continue
        if kind is int:
            if abs(item) > MAX_SAFE_INTEGER:
                raise GuardFrameError('GUARD_FRAME_INTEGER_OUT_OF_RANGE')
        elif kind is float:
            if not math.isfinite(item):
                raise GuardFrameError('GUARD_FRAME_NONFINITE_NUMBER')
        elif kind is str:
            if len(item) > PAYLOAD_LIMIT:
                raise GuardFrameError('GUARD_FRAME_TEXT_CAPACITY_EXCEEDED')
            text_bytes += len(item.encode('utf-8', errors='strict'))
            if text_bytes > PAYLOAD_LIMIT:
                raise GuardFrameError('GUARD_FRAME_TEXT_CAPACITY_EXCEEDED')
        elif kind is list:
            if nodes + len(stack) + len(item) > MAX_NODES:
                raise GuardFrameError('GUARD_FRAME_STRUCTURE_CAPACITY_EXCEEDED')
            stack.extend((child, depth + 1) for child in item)
        elif kind is dict:
            if nodes + len(stack) + 2 * len(item) > MAX_NODES:
                raise GuardFrameError('GUARD_FRAME_STRUCTURE_CAPACITY_EXCEEDED')
            if any(type(key) is not str for key in item):
                raise GuardFrameError('GUARD_FRAME_TEXT_KEYS_REQUIRED')
            stack.extend((child, depth + 1) for child in item.values())
            stack.extend((key, depth + 1) for key in item)
        else:
            raise GuardFrameError('GUARD_FRAME_JSON_FACTS_REQUIRED')
        if nodes + len(stack) > MAX_NODES:
            raise GuardFrameError('GUARD_FRAME_STRUCTURE_CAPACITY_EXCEEDED')


def encode_guard_frame(value):
    if type(value) is not dict:
        raise GuardFrameError('GUARD_FRAME_OBJECT_REQUIRED')
    try:
        _facts(value)
        raw = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')
        ).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise GuardFrameError('INVALID_GUARD_FRAME_FACTS') from error
    if not 1 <= len(raw) <= PAYLOAD_LIMIT:
        raise GuardFrameError('GUARD_FRAME_PAYLOAD_CAPACITY_EXCEEDED')
    return len(raw).to_bytes(HEADER_BYTES, 'big') + raw


def decode_guard_payload(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= PAYLOAD_LIMIT:
        raise GuardFrameError('GUARD_FRAME_PAYLOAD_CAPACITY_EXCEEDED')
    try:
        result = strict_json_object(raw)
        _facts(result)
        return result
    except (InvalidInput, TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise GuardFrameError('INVALID_GUARD_FRAME_JSON') from error


def _remaining(deadline):
    milliseconds = int((deadline - monotonic()) * 1000)
    if milliseconds < 1:
        raise GuardFrameError('GUARD_FRAME_DEADLINE_EXPIRED')
    return milliseconds


class GuardPipeFrames:
    """One parser for this connection; invalid input poisons the original stream."""

    def __init__(self, io):
        if type(io) is not GuardPipeIO:
            raise TypeError('Original Guard pipe IO required')
        io._check_thread()
        self._io = io
        self._gate = RLock()
        self._failed = False
        with io._gate:
            io._check()
            if io._framing_owner is not None:
                raise GuardFrameError('ORIGINAL_GUARD_STREAM_ALREADY_HAS_FRAME_OWNER')
            io._framing_owner = self

    def _check(self):
        if self._failed:
            raise GuardFrameError('ORIGINAL_GUARD_FRAME_STREAM_UNAVAILABLE')
        self._io._check()

    def read(self, *, timeout_ms, cancelled):
        self._io._check_thread()
        deadline = _deadline(timeout_ms)
        with self._gate, self._io._gate:
            self._check()
            try:
                header = self._io.read_exact(
                    HEADER_BYTES, timeout_ms=_remaining(deadline), cancelled=cancelled
                )
                size = int.from_bytes(header, 'big')
                if not 1 <= size <= PAYLOAD_LIMIT:
                    raise GuardFrameError('GUARD_FRAME_PAYLOAD_CAPACITY_EXCEEDED')
                raw = self._io.read_exact(
                    size, timeout_ms=_remaining(deadline), cancelled=cancelled
                )
                return decode_guard_payload(raw)
            except BaseException:
                self._failed = True
                self._io._failed = True
                raise

    def write(self, value, *, timeout_ms, cancelled):
        self._io._check_thread()
        deadline = _deadline(timeout_ms)
        raw = encode_guard_frame(value)
        with self._gate, self._io._gate:
            self._check()
            try:
                self._io.write_all(raw, timeout_ms=_remaining(deadline), cancelled=cancelled)
            except BaseException:
                self._failed = True
                self._io._failed = True
                raise

    def invalidate(self):
        self._io._check_thread()
        with self._gate, self._io._gate:
            self._failed = True
            self._io._failed = True

    def close(self):
        self._io._check_thread()
        with self._gate:
            self._failed = True
            self._io.close()

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
