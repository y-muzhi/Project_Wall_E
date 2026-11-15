"""One bounded driver control stream over private original stdio."""

from backend.app.shared.validation import strict_json_object

from .check_case_evidence import CheckEvidenceUnknown
from .check_driver_bootstrap import CONTROL_FRAME_MAX_BYTES, control_frame
from .windows_check_stdin import MAX_STDIN_BYTES
from .windows_pipe_capture import _read_api, read_available_pipe

_HEADER = 4


def send_control(writer, value, *, deadline, cancelled):
    wire = control_frame(value)
    for offset in range(0, len(wire), MAX_STDIN_BYTES):
        writer.send(wire[offset : offset + MAX_STDIN_BYTES], deadline=deadline, cancelled=cancelled)


class DriverControlReader:
    def __init__(self, streams, *, maximum):
        self._kernel = _read_api(streams._kernel)
        self._lease = streams.output_endpoints()
        self._out, self._error = self._lease.__enter__()
        self._limit = maximum
        self._seen = 0
        self._buffer = bytearray()
        self._closed = False
        self._eof = set()

    def poll(self):
        if self._closed:
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_CONTROL_CLOSED')
        records = []
        for handle in (self._out, self._error):
            if handle in self._eof:
                continue
            chunk = read_available_pipe(self._kernel, handle, self._limit - self._seen + 1)
            if chunk is None:
                self._eof.add(handle)
                if handle == self._out and self._buffer:
                    raise CheckEvidenceUnknown('ORIGINAL_DRIVER_CONTROL_TRUNCATED')
                continue
            self._seen += len(chunk)
            if self._seen > self._limit:
                raise CheckEvidenceUnknown('ORIGINAL_DRIVER_CONTROL_LIMIT')
            if handle == self._out:
                self._buffer.extend(chunk)
                self._consume(records)
        return records

    def _consume(self, records):
        while len(self._buffer) >= _HEADER:
            size = int.from_bytes(self._buffer[:_HEADER], 'big')
            if not 1 <= size <= CONTROL_FRAME_MAX_BYTES or size + _HEADER > self._limit:
                raise CheckEvidenceUnknown('ORIGINAL_DRIVER_CONTROL_SIZE_INVALID')
            end = _HEADER + size
            if len(self._buffer) < end:
                return
            records.append(strict_json_object(bytes(self._buffer[_HEADER:end])))
            del self._buffer[:end]

    @property
    def complete(self):
        return self._eof == {self._out, self._error}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self._closed:
            self._lease.__exit__(None, None, None)
            self._closed = True
            self._buffer.clear()
