"""Install or observe exact owned WFP filters in a local native transaction."""

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from uuid import UUID

from .windows_private_package import _api as security_api
from .windows_private_package import _sid_text
from .windows_wfp import (
    _PACKAGE_SID,
    _REDIRECT_LAYERS,
    _REQUIRED_LAYERS,
    WfpObservationError,
    _Display,
    _Guid,
    _require_success,
    _WfpSession,
)

UINT8, UINT16, UINT32, UINT64 = 1, 2, 3, 4
ADDRESS_V6, SID = 11, 13
PERSISTENT, CLEAR_ACTION_RIGHT = 1, 8
BLOCK, PERMIT = 0x1001, 0x1002
_CONTINUE = 0x2006
_BOOTTIME, _DISABLED = 0x2, 0x20
EQUAL = 0
_FILTER_NOT_FOUND = 0x80320003


@dataclass(frozen=True)
class WfpRule:
    key: UUID
    layer: UUID
    action: int
    flags: int
    weight: int
    conditions: tuple


class _Data(ctypes.Union):
    _fields_ = [
        ('uint8', ctypes.c_uint8),
        ('uint16', ctypes.c_uint16),
        ('uint32', ctypes.c_uint32),
        ('uint64', ctypes.POINTER(ctypes.c_uint64)),
        ('address_v6', ctypes.POINTER(ctypes.c_ubyte * 16)),
        ('sid', wintypes.LPVOID),
    ]


class _Value(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_int), ('data', _Data)]


class _Condition(ctypes.Structure):
    _fields_ = [('field', _Guid), ('match', ctypes.c_int), ('value', _Value)]


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', wintypes.LPVOID)]


class _Action(ctypes.Structure):
    _fields_ = [('kind', wintypes.DWORD), ('unused', _Guid)]


class _Context(ctypes.Union):
    _fields_ = [('raw', ctypes.c_uint64), ('provider_key', _Guid)]


class _Filter(ctypes.Structure):
    _fields_ = [
        ('key', _Guid),
        ('display', _Display),
        ('flags', wintypes.DWORD),
        ('provider', ctypes.POINTER(_Guid)),
        ('provider_data', _Blob),
        ('layer', _Guid),
        ('sublayer', _Guid),
        ('weight', _Value),
        ('count', wintypes.DWORD),
        ('conditions', ctypes.POINTER(_Condition)),
        ('action', _Action),
        ('context', _Context),
        ('reserved', ctypes.POINTER(_Guid)),
        ('id', ctypes.c_uint64),
        ('effective_weight', _Value),
    ]


def _weight(value):
    if value.kind != UINT64 or not value.data.uint64:
        raise WfpObservationError('WFP_ORIGINAL_RULE_WEIGHT_UNVERIFIED')
    return value.data.uint64.contents.value


def _value(condition, sid_text):
    kind, data = condition.kind, condition.data
    if kind == UINT8:
        return data.uint8
    if kind == UINT16:
        return data.uint16
    if kind == UINT32:
        return data.uint32
    if kind == ADDRESS_V6 and data.address_v6:
        return bytes(data.address_v6.contents)
    if kind == SID and data.sid:
        return sid_text(data.sid)
    raise WfpObservationError('WFP_ORIGINAL_RULE_VALUE_UNVERIFIED')


def _verify_filter(actual, expected, provider, sublayer, marker, sid_text):
    if (
        bytes(actual.key) != expected.key.bytes_le
        or not actual.provider
        or bytes(actual.provider.contents) != provider.bytes_le
        or bytes(actual.layer) != expected.layer.bytes_le
        or bytes(actual.sublayer) != sublayer.bytes_le
        or actual.flags != expected.flags
        or actual.action.kind != expected.action
        or actual.provider_data.size != len(marker)
        or not actual.provider_data.data
        or ctypes.string_at(actual.provider_data.data, len(marker)) != marker
        or bytes(actual.context) != bytes(16)
        or actual.reserved
        or actual.id == 0
        or actual.count != len(expected.conditions)
        or not actual.conditions
    ):
        raise WfpObservationError('WFP_ORIGINAL_RULE_DIFFERS')
    if (
        _weight(actual.weight) != expected.weight
        or _weight(actual.effective_weight) != expected.weight
    ):
        raise WfpObservationError('WFP_ORIGINAL_RULE_WEIGHT_DIFFERS')
    actual_conditions = set()
    for index in range(actual.count):
        condition = actual.conditions[index]
        if condition.match != EQUAL:
            raise WfpObservationError('WFP_ORIGINAL_RULE_MATCH_DIFFERS')
        actual_conditions.add(
            (bytes(condition.field), condition.value.kind, _value(condition.value, sid_text))
        )
    required = {(key.bytes_le, kind, value) for key, kind, value in expected.conditions}
    if actual_conditions != required:
        raise WfpObservationError('WFP_ORIGINAL_RULE_CONDITIONS_DIFFER')
    return actual.id


def _verify_filter_layout():
    if (
        ctypes.sizeof(_Filter),
        ctypes.sizeof(_Condition),
        _Filter.conditions.offset,
        _Filter.context.offset,
        _Filter.id.offset,
    ) != (200, 40, 120, 152, 176):
        raise WfpObservationError('WFP_FILTER_NATIVE_LAYOUT_UNSUPPORTED')


def _read_original_filter_ids(
    session, rules, provider, sublayer, marker, sid_text, *, allow_missing
):
    fetch = session._api.FwpmFilterGetByKey0
    fetch.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(ctypes.POINTER(_Filter)),
    ]
    fetch.restype = wintypes.DWORD
    ids = set()
    for expected in rules:
        actual = ctypes.POINTER(_Filter)()
        status = fetch(session._engine, ctypes.byref(_guid(expected.key)), ctypes.byref(actual))
        if allow_missing and status == _FILTER_NOT_FOUND and not actual:
            continue
        _require_success(status, 'WFP_ORIGINAL_RULE_UNAVAILABLE')
        if not actual:
            raise WfpObservationError('WFP_ORIGINAL_RULE_UNAVAILABLE')
        try:
            identity = _verify_filter(
                actual.contents, expected, provider, sublayer, marker, sid_text
            )
            if identity in ids:
                raise WfpObservationError('WFP_ORIGINAL_RULE_ID_REUSED')
            ids.add(identity)
        finally:
            allocation = ctypes.cast(actual, wintypes.LPVOID)
            session._api.FwpmFreeMemory0(ctypes.byref(allocation))
    return ids


def read_owned_filters(rules, provider, sublayer, marker, *, check_external=False, checkpoint=None):
    """Report only matching filter IDs. Caller still needs runtime traffic evidence."""
    _verify_filter_layout()
    kernel, advapi = security_api()
    with _WfpSession() as session:

        def sid_text(sid):
            return _sid_text(kernel, advapi, sid)

        ids = _read_original_filter_ids(
            session, rules, provider, sublayer, marker, sid_text, allow_missing=False
        )
        if check_external:
            _registered_sublayer(session, provider, sublayer)
        _verify_sublayer_inventory(
            session, rules, sublayer, sid_text, check_external=check_external, checkpoint=checkpoint
        )
        if check_external:
            for layer in _REDIRECT_LAYERS:
                if checkpoint is not None:
                    checkpoint()
                session.read_layer(layer, frozenset())
                _layer_filter_inventory(
                    session,
                    layer,
                    None,
                    set(),
                    rules[0].conditions[0][2],
                    sid_text,
                    check_external=True,
                    checkpoint=checkpoint,
                )
        return len(ids)


def _release_owned_filters(rules, provider, sublayer, marker, *, cancelled):
    """Delete an exact complete original rule group, inside the validation transaction."""
    _verify_filter_layout()
    kernel, advapi = security_api()

    def sid_text(sid):
        return _sid_text(kernel, advapi, sid)

    if cancelled():
        raise WfpObservationError('WFP_ORIGINAL_RELEASE_INTERRUPTED')
    with _WfpSession(read_only=False) as session:
        _registered_sublayer(session, provider, sublayer)
        ids = _read_original_filter_ids(
            session, rules, provider, sublayer, marker, sid_text, allow_missing=True
        )
        if ids and len(ids) != len(rules):
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_RULE_GROUP_INCOMPLETE')
        _verify_sublayer_inventory(session, rules, sublayer, sid_text, expect_absent=not ids)
        if not ids:
            return
        delete = session._api.FwpmFilterDeleteByKey0
        delete.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid)]
        delete.restype = wintypes.DWORD
        for rule in rules:
            if cancelled():
                raise WfpObservationError('WFP_ORIGINAL_RELEASE_INTERRUPTED')
            _require_success(
                delete(session._engine, ctypes.byref(_guid(rule.key))),
                'WFP_ORIGINAL_RULE_DELETE_UNVERIFIED',
            )
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_INTERRUPTED')
        session.commit()


def _verify_owned_filters_absent(rules, provider, sublayer, marker):
    _verify_filter_layout()
    kernel, advapi = security_api()

    def sid_text(sid):
        return _sid_text(kernel, advapi, sid)

    with _WfpSession() as session:
        _registered_sublayer(session, provider, sublayer)
        if _read_original_filter_ids(
            session, rules, provider, sublayer, marker, sid_text, allow_missing=True
        ):
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_RULES_STILL_PRESENT')
        _verify_sublayer_inventory(session, rules, sublayer, sid_text, expect_absent=True)


class _SubLayer(ctypes.Structure):
    _fields_ = [
        ('key', _Guid),
        ('display', _Display),
        ('flags', wintypes.DWORD),
        ('provider', ctypes.POINTER(_Guid)),
        ('provider_data', _Blob),
        ('weight', ctypes.c_uint16),
    ]


def _guid(value):
    return _Guid.from_buffer_copy(value.bytes_le)


def _registered_sublayer(session, provider, sublayer):
    if ctypes.sizeof(_SubLayer) != 72:
        raise WfpObservationError('WFP_SUBLAYER_NATIVE_LAYOUT_UNSUPPORTED')
    get = session._api.FwpmSubLayerGetByKey0
    get.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(ctypes.POINTER(_SubLayer)),
    ]
    get.restype = wintypes.DWORD
    result = ctypes.POINTER(_SubLayer)()
    _require_success(
        get(session._engine, ctypes.byref(_guid(sublayer)), ctypes.byref(result)),
        'WFP_REGISTERED_SUBLAYER_UNAVAILABLE',
    )
    if not result:
        raise WfpObservationError('WFP_REGISTERED_SUBLAYER_UNAVAILABLE')
    try:
        row = result.contents
        if (
            bytes(row.key) != sublayer.bytes_le
            or row.flags != PERSISTENT
            or not row.provider
            or bytes(row.provider.contents) != provider.bytes_le
        ):
            raise WfpObservationError('WFP_REGISTERED_SUBLAYER_DIFFERS')
    finally:
        memory = ctypes.cast(result, wintypes.LPVOID)
        session._api.FwpmFreeMemory0(ctypes.byref(memory))


@contextmanager
def _guard_filter_descriptor(kernel, security):
    descriptor = wintypes.LPVOID()
    size = wintypes.DWORD()
    if (
        not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            'O:SYG:SYD:P(A;;GA;;;SY)', 1, ctypes.byref(descriptor), ctypes.byref(size)
        )
        or not descriptor.value
    ):
        raise WfpObservationError(
            'WFP_GUARD_FILTER_DESCRIPTOR_UNAVAILABLE', ctypes.get_last_error()
        )
    try:
        yield descriptor
    finally:
        if kernel.LocalFree(descriptor):
            raise WfpObservationError('WFP_GUARD_FILTER_DESCRIPTOR_RELEASE_UNVERIFIED')


def _condition_value(kind, value, sid_pointer, sid_text):
    data = _Data()
    if kind == SID and value == sid_text and sid_pointer:
        data.sid = sid_pointer
    elif kind == UINT8 and type(value) is int and 0 <= value <= 255:
        data.uint8 = value
    elif kind == UINT16 and type(value) is int and 0 <= value <= 65535:
        data.uint16 = value
    elif kind == UINT32 and type(value) is int and 0 <= value <= 0xFFFFFFFF:
        data.uint32 = value
    elif kind == ADDRESS_V6 and type(value) is bytes and len(value) == 16:
        data.address_v6 = ctypes.pointer((ctypes.c_ubyte * 16).from_buffer_copy(value))
    else:
        raise WfpObservationError('WFP_ORIGINAL_RULE_VALUE_UNVERIFIED')
    return _Value(kind, data)


def _native_filter(rule, provider, sublayer, marker, sid_pointer, sid_text):
    row = _Filter()
    row.key = _guid(rule.key)
    row.display.name = 'WALL-E V2 task network'
    row.flags = rule.flags
    row.provider = ctypes.pointer(_guid(provider))
    payload = ctypes.create_string_buffer(marker)
    row.provider_data = _Blob(len(marker), ctypes.cast(payload, wintypes.LPVOID))
    row.layer = _guid(rule.layer)
    row.sublayer = _guid(sublayer)
    row.action.kind = rule.action
    weight = ctypes.pointer(ctypes.c_uint64(rule.weight))
    row.weight = _Value(UINT64, _Data(uint64=weight))
    conditions = (_Condition * len(rule.conditions))(
        *(
            _Condition(_guid(key), EQUAL, _condition_value(kind, value, sid_pointer, sid_text))
            for key, kind, value in rule.conditions
        )
    )
    row.count = len(conditions)
    row.conditions = conditions
    return row


def _install_owned_filters(rules, provider, sublayer, marker, *, sid_pointer, cancelled):
    # Called only with the same derived LPAC SID and the Guard's durable dispatch.
    _verify_filter_layout()
    if cancelled():
        raise WfpObservationError('WFP_ORIGINAL_INSTALL_INTERRUPTED')
    kernel, security = security_api()
    sid = _sid_text(kernel, security, sid_pointer)
    with _WfpSession(read_only=False) as session, _guard_filter_descriptor(kernel, security) as sd:
        _registered_sublayer(session, provider, sublayer)
        layer_ids = {session.read_layer(key, fields) for key, fields in _REQUIRED_LAYERS}
        if len(layer_ids) != len(_REQUIRED_LAYERS):
            raise WfpObservationError('WFP_REQUIRED_ALE_LAYERS_DIFFER')
        add = session._api.FwpmFilterAdd0
        add.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Filter),
            wintypes.LPVOID,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        add.restype = wintypes.DWORD
        allocated = set()
        for rule in rules:
            if cancelled():
                raise WfpObservationError('WFP_ORIGINAL_INSTALL_INTERRUPTED')
            row = _native_filter(rule, provider, sublayer, marker, sid_pointer, sid)
            identity = ctypes.c_uint64()
            _require_success(
                add(session._engine, ctypes.byref(row), sd, ctypes.byref(identity)),
                'WFP_ORIGINAL_RULE_ADD_UNVERIFIED',
            )
            if not identity.value or identity.value in allocated:
                raise WfpObservationError('WFP_ORIGINAL_RULE_ID_UNVERIFIED')
            allocated.add(identity.value)
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_INSTALL_INTERRUPTED')
        session.commit()


class _FilterEnumTemplate(ctypes.Structure):
    _fields_ = [
        ('provider', ctypes.POINTER(_Guid)),
        ('layer', _Guid),
        ('enum_type', ctypes.c_int),
        ('flags', wintypes.DWORD),
        ('provider_context', wintypes.LPVOID),
        ('count', wintypes.DWORD),
        ('conditions', ctypes.POINTER(_Condition)),
        ('action_mask', wintypes.DWORD),
        ('callout', ctypes.POINTER(_Guid)),
    ]


def _restricts_different_package(row, original_sid, sid_text):
    if not 1 <= row.count <= 64 or not row.conditions:
        return False
    package_key = _PACKAGE_SID.bytes_le
    matches = [
        row.conditions[index]
        for index in range(row.count)
        if bytes(row.conditions[index].field) == package_key
    ]
    if len(matches) != 1:
        return False
    selector = matches[0]
    return (
        selector.match == EQUAL
        and selector.value.kind == SID
        and bool(selector.value.data.sid)
        and sid_text(selector.value.data.sid) != original_sid
    )


def _check_external_filter(row, original_sid, sid_text):
    if row.flags & (_BOOTTIME | _DISABLED):
        return
    action = row.action.kind
    if action in (BLOCK, _CONTINUE) or (action == PERMIT and not row.flags & CLEAR_ACTION_RIGHT):
        return
    if not _restricts_different_package(row, original_sid, sid_text):
        raise WfpObservationError('WFP_EXTERNAL_ARBITRATION_UNVERIFIED')


def _layer_filter_inventory(
    session, layer, sublayer, expected, original_sid, sid_text, *, check_external, checkpoint
):
    if ctypes.sizeof(_FilterEnumTemplate) != 72:
        raise WfpObservationError('WFP_FILTER_ENUM_NATIVE_LAYOUT_UNSUPPORTED')
    api = session._api
    create = api.FwpmFilterCreateEnumHandle0
    create.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FilterEnumTemplate),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    create.restype = wintypes.DWORD
    filter_list = ctypes.POINTER(ctypes.POINTER(_Filter))
    read_page = api.FwpmFilterEnum0
    read_page.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(filter_list),
        ctypes.POINTER(wintypes.DWORD),
    ]
    read_page.restype = wintypes.DWORD
    destroy = api.FwpmFilterDestroyEnumHandle0
    destroy.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    destroy.restype = wintypes.DWORD
    query = _FilterEnumTemplate()
    query.layer = _guid(layer)
    query.flags = 0x8 | 0x10  # Include boot-time and disabled filters.
    query.action_mask = 0xFFFFFFFF
    cursor = wintypes.HANDLE()
    _require_success(
        create(session._engine, ctypes.byref(query), ctypes.byref(cursor)),
        'WFP_ORIGINAL_INVENTORY_UNAVAILABLE',
    )
    if not cursor:
        raise WfpObservationError('WFP_ORIGINAL_INVENTORY_UNAVAILABLE')
    page_size = 64
    seen = set()
    try:
        for _ in range(64):
            if checkpoint is not None:
                checkpoint()
            page = filter_list()
            count = wintypes.DWORD()
            _require_success(
                read_page(
                    session._engine, cursor, page_size, ctypes.byref(page), ctypes.byref(count)
                ),
                'WFP_ORIGINAL_INVENTORY_UNAVAILABLE',
            )
            try:
                if count.value > page_size or (count.value and not page):
                    raise WfpObservationError('WFP_ORIGINAL_INVENTORY_UNAVAILABLE')
                for index in range(count.value):
                    if not page[index]:
                        raise WfpObservationError('WFP_ORIGINAL_INVENTORY_UNAVAILABLE')
                    row = page[index].contents
                    if bytes(row.layer) != layer.bytes_le:
                        raise WfpObservationError('WFP_ORIGINAL_INVENTORY_LAYER_DIFFERS')
                    if sublayer is None or bytes(row.sublayer) != sublayer.bytes_le:
                        if check_external:
                            _check_external_filter(row, original_sid, sid_text)
                        continue
                    key = bytes(row.key)
                    if key not in expected:
                        if not _restricts_different_package(row, original_sid, sid_text):
                            raise WfpObservationError('WFP_ORIGINAL_INVENTORY_HAS_EXTRA_RULE')
                    elif key in seen:
                        raise WfpObservationError('WFP_ORIGINAL_INVENTORY_REPEATED_RULE')
                    else:
                        seen.add(key)
            finally:
                if page:
                    memory = ctypes.cast(page, wintypes.LPVOID)
                    api.FwpmFreeMemory0(ctypes.byref(memory))
            if count.value < page_size:
                if seen != expected:
                    raise WfpObservationError('WFP_ORIGINAL_INVENTORY_INCOMPLETE')
                return
        raise WfpObservationError('WFP_ORIGINAL_INVENTORY_LIMIT_EXCEEDED')
    finally:
        _require_success(
            destroy(session._engine, cursor),
            'WFP_ORIGINAL_INVENTORY_CLOSE_UNVERIFIED',
        )


def _verify_sublayer_inventory(
    session,
    rules,
    sublayer,
    sid_text,
    *,
    expect_absent=False,
    check_external=False,
    checkpoint=None,
):
    original_sid = rules[0].conditions[0][2]
    for layer, _ in _REQUIRED_LAYERS:
        expected = {rule.key.bytes_le for rule in rules if rule.layer == layer}
        if not expected:
            raise WfpObservationError('WFP_ORIGINAL_INVENTORY_INCOMPLETE')
        if expect_absent:
            expected.clear()
        _layer_filter_inventory(
            session,
            layer,
            sublayer,
            expected,
            original_sid,
            sid_text,
            check_external=check_external,
            checkpoint=checkpoint,
        )
