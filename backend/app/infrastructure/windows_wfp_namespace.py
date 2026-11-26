"""Register only the WFP objects of one admitted SYSTEM TASK deployment."""

import ctypes
import hashlib
from contextlib import contextmanager
from ctypes import wintypes
from uuid import UUID

from .windows_private_package import AclHeader, AllowedAce, _sid_text, current_operator_sid
from .windows_private_package import _api as security_api
from .windows_wfp import (
    _REQUIRED_LAYERS,
    WfpObservationError,
    _Display,
    _Guid,
    _require_success,
    _WfpSession,
)
from .windows_wfp_filters import PERSISTENT, _Blob, _guard_filter_descriptor, _guid, _SubLayer

_SYSTEM = 'S-1-5-18'
_PROVIDER_NOT_FOUND = 0x80320005
_SUBLAYER_NOT_FOUND = 0x80320007
_OWNER_AND_DACL = 0x5
_DACL_PROTECTED = 0x1000
_SUBLAYER_WEIGHT = 0x100
_DISPLAY_NAME = 'WALL-E managed TASK network'


class _Provider(ctypes.Structure):
    _fields_ = [
        ('key', _Guid),
        ('display', _Display),
        ('flags', wintypes.DWORD),
        ('provider_data', _Blob),
        ('service_name', wintypes.LPWSTR),
    ]


def _marker(installation_ref, provider, sublayer):
    if (
        type(installation_ref) is not str
        or len(installation_ref) != 64
        or any(letter not in '0123456789abcdef' for letter in installation_ref)
        or type(provider) is not UUID
        or type(sublayer) is not UUID
        or provider.int == 0
        or sublayer.int == 0
        or provider == sublayer
    ):
        raise WfpObservationError('WFP_NAMESPACE_IDENTITY_INVALID')
    if (ctypes.sizeof(_Provider), ctypes.sizeof(_SubLayer)) != (64, 72):
        raise WfpObservationError('WFP_NAMESPACE_NATIVE_LAYOUT_UNSUPPORTED')
    return hashlib.sha256(
        b'WALL-E TASK WFP namespace v1'
        + bytes.fromhex(installation_ref)
        + provider.bytes
        + sublayer.bytes
    ).digest()


def _signature(session, name, arguments):
    function = getattr(session._api, name)
    function.argtypes = [wintypes.HANDLE, *arguments]
    function.restype = wintypes.DWORD
    return function


@contextmanager
def _object(session, kind, key, layout, not_found):
    lookup = _signature(
        session,
        f'Fwpm{kind}GetByKey0',
        [ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.POINTER(layout))],
    )
    result = ctypes.POINTER(layout)()
    native = lookup(session._engine, ctypes.byref(_guid(key)), ctypes.byref(result))
    if native == not_found and not result:
        yield None
        return
    _require_success(native, 'WFP_NAMESPACE_LOOKUP_UNVERIFIED')
    if not result:
        raise WfpObservationError('WFP_NAMESPACE_LOOKUP_UNVERIFIED')
    try:
        yield result.contents
    finally:
        memory = ctypes.cast(result, wintypes.LPVOID)
        session._api.FwpmFreeMemory0(ctypes.byref(memory))


def _require_system_security(session, kind, key):
    pointer = ctypes.POINTER(wintypes.LPVOID)
    get = _signature(
        session,
        f'Fwpm{kind}GetSecurityInfoByKey0',
        [ctypes.POINTER(_Guid), wintypes.DWORD, pointer, pointer, pointer, pointer, pointer],
    )
    owner, dacl, descriptor = (wintypes.LPVOID() for _ in range(3))
    _require_success(
        get(
            session._engine,
            ctypes.byref(_guid(key)),
            _OWNER_AND_DACL,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        ),
        'WFP_NAMESPACE_SECURITY_UNVERIFIED',
    )
    try:
        kernel, security = security_api()
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if (
            not owner
            or not dacl
            or not descriptor
            or _sid_text(kernel, security, owner) != _SYSTEM
            or not security.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            )
            or not control.value & _DACL_PROTECTED
            or AclHeader.from_address(dacl.value).count != 1
        ):
            raise WfpObservationError('WFP_NAMESPACE_SECURITY_DIFFERS')
        ace_pointer = wintypes.LPVOID()
        if not security.GetAce(dacl, 0, ctypes.byref(ace_pointer)) or not ace_pointer:
            raise WfpObservationError('WFP_NAMESPACE_SECURITY_DIFFERS')
        ace = AllowedAce.from_address(ace_pointer.value)
        if (
            ace.kind != 0
            or ace.flags != 0
            or ace.size < ctypes.sizeof(AllowedAce) + 12
            or not ace.mask
            or _sid_text(kernel, security, ace_pointer.value + ctypes.sizeof(AllowedAce)) != _SYSTEM
        ):
            raise WfpObservationError('WFP_NAMESPACE_SECURITY_DIFFERS')
    finally:
        if descriptor:
            session._api.FwpmFreeMemory0(ctypes.byref(descriptor))


def _matches(row, key, marker):
    return (
        bytes(row.key) == key.bytes_le
        and row.flags == PERSISTENT
        and row.display.name == _DISPLAY_NAME
        and row.provider_data.size == len(marker)
        and bool(row.provider_data.data)
        and ctypes.string_at(row.provider_data.data, len(marker)) == marker
    )


def _observe(session, provider, sublayer, marker, *, verify_security):
    with (
        _object(session, 'Provider', provider, _Provider, _PROVIDER_NOT_FOUND) as root,
        _object(session, 'SubLayer', sublayer, _SubLayer, _SUBLAYER_NOT_FOUND) as layer,
    ):
        if root is None and layer is None:
            return False
        if (
            root is None
            or layer is None
            or not _matches(root, provider, marker)
            or root.service_name is not None
            or not _matches(layer, sublayer, marker)
            or not layer.provider
            or bytes(layer.provider.contents) != provider.bytes_le
            or layer.weight != _SUBLAYER_WEIGHT
        ):
            raise WfpObservationError('WFP_NAMESPACE_BINDING_DIFFERS')
        if verify_security:
            _require_system_security(session, 'Provider', provider)
            _require_system_security(session, 'SubLayer', sublayer)
        return True


def _add(session, provider, sublayer, marker, descriptor):
    data = (ctypes.c_ubyte * len(marker)).from_buffer_copy(marker)
    blob = _Blob(len(marker), ctypes.cast(data, wintypes.LPVOID))
    provider_key = _guid(provider)
    display = _Display(_DISPLAY_NAME, None)
    root = _Provider(provider_key, display, PERSISTENT, blob, None)
    layer = _SubLayer(
        _guid(sublayer), display, PERSISTENT, ctypes.pointer(provider_key), blob, _SUBLAYER_WEIGHT
    )
    for kind, row in (('Provider', root), ('SubLayer', layer)):
        add = _signature(session, f'Fwpm{kind}Add0', [ctypes.POINTER(type(row)), wintypes.LPVOID])
        _require_success(
            add(session._engine, ctypes.byref(row), descriptor),
            'WFP_NAMESPACE_ADD_UNVERIFIED',
        )


def ensure_admitted_task_wfp_namespace(installation_ref, provider, sublayer, checkpoint):
    """Create or verify the two SYSTEM objects only after original TASK admission."""
    checkpoint()
    if current_operator_sid() != _SYSTEM:
        raise WfpObservationError('WFP_NAMESPACE_SYSTEM_REQUIRED')
    marker = _marker(installation_ref, provider, sublayer)
    with _WfpSession(read_only=False) as session:
        layer_ids = {session.read_layer(key, fields) for key, fields in _REQUIRED_LAYERS}
        if len(layer_ids) != len(_REQUIRED_LAYERS):
            raise WfpObservationError('WFP_REQUIRED_ALE_LAYERS_DIFFER')
        if not _observe(session, provider, sublayer, marker, verify_security=True):
            with _guard_filter_descriptor(*security_api()) as descriptor:
                _add(session, provider, sublayer, marker, descriptor)
            checkpoint()
            if not _observe(session, provider, sublayer, marker, verify_security=True):
                raise WfpObservationError('WFP_NAMESPACE_CREATION_UNVERIFIED')
            session.commit()
    checkpoint()
    with _WfpSession() as session:
        if not _observe(session, provider, sublayer, marker, verify_security=True):
            raise WfpObservationError('WFP_NAMESPACE_PERSISTENCE_UNVERIFIED')
