"""Registered Windows driver entry point helpers, with no candidate imports."""

import os
from contextlib import contextmanager
from typing import BinaryIO

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object

from .check_case_evidence import CheckEvidenceUnknown
from .windows_stdio import _api, _handle, _verify_pipe

_MAX_FRAME_BYTES = 128 * 1024
BROWSER_REQUEST_BODY_MAX_BYTES = 1024 * 1024
BROWSER_RESPONSE_BODY_MAX_BYTES = 4 * 1024 * 1024
CONTROL_FRAME_MAX_BYTES = 8 * 1024 * 1024


@contextmanager
def original_result_writer(handle_hex):
    """Remove the inherited flag before loading the browser runtime or making children."""
    import msvcrt

    handle = _handle(handle_hex)
    kernel, _, native = _api()
    adopted = False
    try:
        _verify_pipe(kernel, native, handle, 'DRIVER_RESULT_WRITE', inheritable=True)
        if not kernel.SetHandleInformation(handle, 1, 0):
            raise CheckEvidenceUnknown('DRIVER_RESULT_WRITER_INHERITANCE_UNVERIFIED')
        _verify_pipe(kernel, native, handle, 'DRIVER_RESULT_WRITE', inheritable=False)
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT)
        adopted = True
        try:
            writer = os.fdopen(fd, 'wb', buffering=0)
        except BaseException:
            os.close(fd)
            raise
        with writer:
            if os.get_inheritable(fd):
                raise CheckEvidenceUnknown('DRIVER_RESULT_WRITER_INHERITANCE_UNVERIFIED')
            yield writer
    finally:
        if not adopted:
            kernel.CloseHandle(handle)


def control_frame(value, *, maximum=CONTROL_FRAME_MAX_BYTES):
    raw = canonical_input(value).encode('utf-8')
    if not 1 <= len(raw) <= maximum:
        raise CheckEvidenceUnknown('DRIVER_FRAME_CAPACITY_EXCEEDED')
    return len(raw).to_bytes(4, 'big') + raw


def read_control_frame(reader):
    header = reader.read(4)
    size = int.from_bytes(header, 'big')
    if len(header) != 4 or not 1 <= size <= CONTROL_FRAME_MAX_BYTES:
        raise CheckEvidenceUnknown('DRIVER_CONTROL_FRAME_REQUIRED')
    raw = reader.read(size)
    if len(raw) != size:
        raise CheckEvidenceUnknown('DRIVER_CONTROL_FRAME_TRUNCATED')
    return strict_json_object(raw)


def write_frame(writer: BinaryIO, value: dict, *, maximum=CONTROL_FRAME_MAX_BYTES):
    data = memoryview(control_frame(value, maximum=maximum))
    while data:
        count = writer.write(data)
        if type(count) is not int or not 1 <= count <= len(data):
            raise CheckEvidenceUnknown('DRIVER_RESULT_FRAME_WRITE_UNVERIFIED')
        data = data[count:]


def write_result_frame(writer: BinaryIO, value: dict) -> None:
    write_frame(writer, value, maximum=_MAX_FRAME_BYTES)
