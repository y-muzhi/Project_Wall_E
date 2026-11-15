"""Own a local Windows Filtering Platform transaction and observe fixed ALE layers."""

import ctypes
import os
from ctypes import wintypes
from uuid import UUID

RPC_C_AUTHN_WINNT = 10
FWPM_TXN_READ_ONLY = 1
FWPM_LAYER_BUILTIN_KERNEL = 3

_PACKAGE_SID = UUID('71bc78fa-f17c-4997-a602-6abb261f351c')
_LOCAL_ADDRESS = UUID('d9ee00de-c1ef-4617-bfe3-ffd8f5a08957')
_REMOTE_ADDRESS = UUID('b235ae9a-1d64-49b8-a44c-5ff3d9095045')
_PROTOCOL = UUID('3971ef2b-623e-4f9a-8cb1-6e79b806b9a7')
_LOCAL_PORT = UUID('0c1ba1af-5765-453f-af22-a8f791ac775b')
_REMOTE_PORT = UUID('c35a604d-d22b-4e1a-91b4-68f674ee674b')
_LISTEN_FIELDS = frozenset((_PACKAGE_SID, _LOCAL_ADDRESS, _LOCAL_PORT))
_CONNECT_FIELDS = frozenset(
    (_PACKAGE_SID, _LOCAL_ADDRESS, _REMOTE_ADDRESS, _REMOTE_PORT, _PROTOCOL)
)
_RECEIVE_FIELDS = _LISTEN_FIELDS | {_REMOTE_ADDRESS, _PROTOCOL}

_REQUIRED_LAYERS = (
    (UUID('c38d57d1-05a7-4c33-904f-7fbceee60e82'), _CONNECT_FIELDS),
    (UUID('4a72393b-319f-44bc-84c3-ba54dcb3b6b4'), _CONNECT_FIELDS),
    (UUID('88bb5dad-76d7-4227-9c71-df0a3ed7be7e'), _LISTEN_FIELDS),
    (UUID('7ac9de24-17dd-4814-b4bd-a9fbc95a321b'), _LISTEN_FIELDS),
    (UUID('e1cd9fe7-f4b5-4273-96c0-592e487b8650'), _RECEIVE_FIELDS),
    (UUID('a3b42c97-9f04-4672-b87e-cee9c483257f'), _RECEIVE_FIELDS),
)


_REDIRECT_LAYERS = (
    UUID('c6e63c8c-b784-4562-aa7d-0a67cfcaf9a3'),
    UUID('587e54a7-8046-42ba-a0aa-b716250fc7fd'),
    UUID('66978cad-c704-42ac-86ac-7c1a231bd253'),
    UUID('bef02c9c-606b-4536-8c26-1c2fc7b631d4'),
)


class WfpObservationError(RuntimeError):
    def __init__(self, code, native_error=None):
        super().__init__(code)
        self.native_error = native_error


class _Guid(ctypes.Structure):
    _fields_ = [
        ('first', ctypes.c_uint32),
        ('second', ctypes.c_uint16),
        ('third', ctypes.c_uint16),
        ('last', ctypes.c_ubyte * 8),
    ]


class _Display(ctypes.Structure):
    _fields_ = [('name', wintypes.LPWSTR), ('description', wintypes.LPWSTR)]


class _Session(ctypes.Structure):
    _fields_ = [
        ('key', _Guid),
        ('display', _Display),
        ('flags', wintypes.DWORD),
        ('transaction_wait_ms', wintypes.DWORD),
        ('pid', wintypes.DWORD),
        ('sid', wintypes.LPVOID),
        ('username', wintypes.LPWSTR),
        ('kernel_mode', wintypes.BOOL),
    ]


class _Field(ctypes.Structure):
    _fields_ = [('key', ctypes.POINTER(_Guid)), ('kind', ctypes.c_int), ('data_type', ctypes.c_int)]


class _Layer(ctypes.Structure):
    _fields_ = [
        ('key', _Guid),
        ('display', _Display),
        ('flags', wintypes.DWORD),
        ('field_count', wintypes.DWORD),
        ('fields', ctypes.POINTER(_Field)),
        ('default_sublayer', _Guid),
        ('id', ctypes.c_uint16),
    ]


def _api():
    if os.name != 'nt' or (
        ctypes.sizeof(_Session),
        ctypes.sizeof(_Layer),
        ctypes.sizeof(_Field),
    ) != (72, 72, 16):
        raise WfpObservationError('WFP_NATIVE_LAYOUT_UNSUPPORTED')
    api = ctypes.WinDLL('fwpuclnt', use_last_error=True)
    signatures = {
        'FwpmEngineOpen0': [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(_Session),
            ctypes.POINTER(wintypes.HANDLE),
        ],
        'FwpmEngineClose0': [wintypes.HANDLE],
        'FwpmTransactionBegin0': [wintypes.HANDLE, wintypes.DWORD],
        'FwpmTransactionAbort0': [wintypes.HANDLE],
        'FwpmLayerGetByKey0': [
            wintypes.HANDLE,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.POINTER(_Layer)),
        ],
    }
    for name, args in signatures.items():
        function = getattr(api, name)
        function.argtypes = args
        function.restype = wintypes.DWORD
    api.FwpmFreeMemory0.argtypes = [ctypes.POINTER(wintypes.LPVOID)]
    api.FwpmFreeMemory0.restype = None
    return api


def _require_success(result, code):
    if result:
        raise WfpObservationError(code, result)


class _WfpSession:
    def __init__(self, *, read_only=True):
        self._api = _api()
        self._engine = wintypes.HANDLE()
        self._read_only = read_only
        self._commit_may = False
        session = _Session()
        session.transaction_wait_ms = 2000
        _require_success(
            self._api.FwpmEngineOpen0(
                None, RPC_C_AUTHN_WINNT, None, ctypes.byref(session), ctypes.byref(self._engine)
            ),
            'WFP_LOCAL_ENGINE_UNAVAILABLE',
        )
        if not self._engine:
            raise WfpObservationError('WFP_ENGINE_HANDLE_UNAVAILABLE')
        try:
            _require_success(
                self._api.FwpmTransactionBegin0(
                    self._engine, FWPM_TXN_READ_ONLY if read_only else 0
                ),
                'WFP_READ_TRANSACTION_UNAVAILABLE'
                if read_only
                else 'WFP_WRITE_TRANSACTION_UNAVAILABLE',
            )
        except BaseException:
            self.close()
            raise

    def read_layer(self, key, required_fields):
        layer = ctypes.POINTER(_Layer)()
        _require_success(
            self._api.FwpmLayerGetByKey0(
                self._engine,
                ctypes.byref(_Guid.from_buffer_copy(key.bytes_le)),
                ctypes.byref(layer),
            ),
            'WFP_ALE_LAYER_UNAVAILABLE',
        )
        if not layer:
            raise WfpObservationError('WFP_ALE_LAYER_UNAVAILABLE')
        try:
            row = layer.contents
            if (
                bytes(row.key) != key.bytes_le
                or row.flags & FWPM_LAYER_BUILTIN_KERNEL != FWPM_LAYER_BUILTIN_KERNEL
                or not 1 <= row.field_count <= 256
                or not row.fields
            ):
                raise WfpObservationError('WFP_ALE_LAYER_DIFFERS')
            fields = set()
            for index in range(row.field_count):
                field = row.fields[index]
                if not field.key:
                    raise WfpObservationError('WFP_ALE_FIELD_UNVERIFIED')
                fields.add(UUID(bytes_le=bytes(field.key.contents)))
            if not required_fields <= fields:
                raise WfpObservationError('WFP_ALE_FIELDS_UNAVAILABLE')
            return row.id
        finally:
            allocation = ctypes.cast(layer, wintypes.LPVOID)
            self._api.FwpmFreeMemory0(ctypes.byref(allocation))

    def close(self):
        if self._engine:
            code = self._api.FwpmEngineClose0(self._engine)
            if code:
                error = WfpObservationError('WFP_ENGINE_CLOSE_UNVERIFIED', code)
                error.retained_owner = self
                raise error
            self._engine = wintypes.HANDLE()

    def commit(self):
        if self._read_only or self._commit_may or not self._engine:
            raise WfpObservationError('WFP_ORIGINAL_WRITE_TRANSACTION_REQUIRED')
        submit = self._api.FwpmTransactionCommit0
        submit.argtypes = [wintypes.HANDLE]
        submit.restype = wintypes.DWORD
        self._commit_may = True
        _require_success(submit(self._engine), 'WFP_ORIGINAL_COMMIT_RESULT_UNKNOWN')

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            if self._engine and not self._commit_may:
                _require_success(
                    self._api.FwpmTransactionAbort0(self._engine),
                    'WFP_READ_TRANSACTION_END_UNVERIFIED'
                    if self._read_only
                    else 'WFP_WRITE_ABORT_UNVERIFIED',
                )
        finally:
            self.close()


def probe_wfp_ale_layers():
    """Read the six fixed ALE layers, without adding a provider, rule or sublayer."""
    try:
        with _WfpSession() as read:
            layer_ids = {read.read_layer(key, required) for key, required in _REQUIRED_LAYERS}
            return len(layer_ids) == len(_REQUIRED_LAYERS)
    except (WfpObservationError, OSError, AttributeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        return False
