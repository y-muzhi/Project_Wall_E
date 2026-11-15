"""Read the original NTFS handle's stream inventory, without opening another path."""

import ctypes
from struct import unpack_from

_FILE_STREAM_INFO = 7
_ERROR_HANDLE_EOF = 38
_STREAM_HEADER_SIZE = 24
_DEFAULT_STREAM = '::$DATA'.encode('utf-16-le')


class FileStreamError(RuntimeError):
    pass


def require_default_data_stream(kernel, handle, *, directory):
    buffer = ctypes.create_string_buffer(1024)
    if not kernel.GetFileInformationByHandleEx(handle, _FILE_STREAM_INFO, buffer, len(buffer)):
        if directory and ctypes.get_last_error() == _ERROR_HANDLE_EOF:
            return
        raise FileStreamError('STREAMS_UNVERIFIED')
    next_entry, name_bytes = unpack_from('<II', buffer)
    if (
        next_entry != 0
        or name_bytes != len(_DEFAULT_STREAM)
        or buffer[_STREAM_HEADER_SIZE : _STREAM_HEADER_SIZE + name_bytes] != _DEFAULT_STREAM
    ):
        raise FileStreamError('ALTERNATE_STREAM_UNSUPPORTED')
